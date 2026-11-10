"""AWS Lab operator tools. Run in CloudShell with its existing temporary role."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.config import Config

REGION = "us-east-1"
STACK = "cloudsense-http-ingest-test"
FUNCTIONS = ["cloudsense-http-ingest-test", "cloudsense-process-alerts", "cloudsense-query-readings"]
HOME = Path(__file__).resolve().parent
EVIDENCE = HOME / "cloud_evidence"
EVIDENCE.mkdir(exist_ok=True)


def client(service):
    return boto3.client(service, region_name=REGION, config=Config(retries={"max_attempts": 3}, connect_timeout=10, read_timeout=30))


def save(name, data):
    (EVIDENCE / name).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def resources():
    stack = client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]
    return {entry["OutputKey"]: entry["OutputValue"] for entry in stack["Outputs"]}


def queue_state(url):
    names = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible", "ApproximateNumberOfMessagesDelayed"]
    return {key: int(value) for key, value in client("sqs").get_queue_attributes(QueueUrl=url, AttributeNames=names)["Attributes"].items()}


def snapshot():
    outputs = resources()
    result = {"at": datetime.now(timezone.utc).isoformat(), "region": REGION, "functions": {}, "main_queue": queue_state(outputs["QueueUrl"]), "dlq": queue_state(outputs["DeadLetterQueueUrl"])}
    for name in FUNCTIONS:
        config = client("lambda").get_function_configuration(FunctionName=name)
        result["functions"][name] = {key: config.get(key) for key in ["State", "LastUpdateStatus", "Runtime", "Timeout", "MemorySize", "CodeSha256"]}
    result["mappings"] = [{key: item.get(key) for key in ["UUID", "State", "BatchSize", "FunctionResponseTypes"]} for item in client("lambda").list_event_source_mappings(FunctionName=FUNCTIONS[1])["EventSourceMappings"]]
    save("environment.json", result)
    print(json.dumps(result, indent=2))


def deploy():
    service = client("lambda")
    backup = HOME / "backups"
    backup.mkdir(exist_ok=True)
    package = (HOME / "lambda_sources.zip").read_bytes()
    digest = base64.b64encode(hashlib.sha256(package).digest()).decode()
    deployed = []
    for name in FUNCTIONS:
        existing = service.get_function(FunctionName=name)
        destination = backup / (name + ".zip")
        if not destination.exists():
            with urllib.request.urlopen(existing["Code"]["Location"], timeout=30) as response:
                destination.write_bytes(response.read())
        service.update_function_code(FunctionName=name, ZipFile=package, RevisionId=existing["Configuration"]["RevisionId"])
        service.get_waiter("function_updated_v2").wait(FunctionName=name)
        config = service.get_function_configuration(FunctionName=name)
        if config["CodeSha256"] != digest:
            raise RuntimeError("Deployed code hash does not match local package")
        deployed.append({"name": name, "code_sha256": digest, "status": config["LastUpdateStatus"]})
        print("Deployed", name, config["LastUpdateStatus"], flush=True)
    mappings = service.list_event_source_mappings(FunctionName=FUNCTIONS[1])["EventSourceMappings"]
    outputs = resources()
    queue_arn = client("sqs").get_queue_attributes(QueueUrl=outputs["QueueUrl"], AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    mapping = next(item for item in mappings if item["EventSourceArn"] == queue_arn)
    if mapping["State"] == "Disabled":
        service.update_event_source_mapping(UUID=mapping["UUID"], Enabled=True)
        for attempt in range(30):
            if service.get_event_source_mapping(UUID=mapping["UUID"])["State"] == "Enabled":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Main trigger did not become Enabled")
    save("deployment.json", {"deployed_at": datetime.now(timezone.utc).isoformat(), "functions": deployed, "main_trigger": "Enabled", "backup_location": "CloudShell evaluation/backups"})
    snapshot()


def read_item(table, reading_id):
    result = client("dynamodb").get_item(TableName=table, Key={"PK": {"S": "READING#" + reading_id}, "SK": {"S": "DATA"}}, ConsistentRead=True)
    item = result.get("Item")
    return {"exists": bool(item), "status": item.get("processing_status", {}).get("S")} if item else {"exists": False}


def wait_item(table, reading_id, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read_item(table, reading_id)
        if result.get("status") in ("COMPLETE", "LATE"):
            return result
        time.sleep(2)
    raise RuntimeError("Reading did not reach final state")


def fault_test():
    from run_low_load import normal_reading, request_json

    service, sqs = client("lambda"), client("sqs")
    outputs = resources()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run_id = "fault-" + suffix
    function = "cloudsense-evaluation-" + suffix
    result = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "scope": "Dedicated queues and Lambda using production processor code and existing LabRole; synthetic records in existing table; topic has no subscribers.", "timeline": [], "checks": {}}
    queues = {}
    mapping_uuid = None

    def record(stage, **extra):
        result["timeline"].append({"at": datetime.now(timezone.utc).isoformat(), "stage": stage, **extra})
        save("faults.json", result)
        print(stage, json.dumps(extra), flush=True)

    def send(reading):
        return sqs.send_message(QueueUrl=queues["main"], MessageBody=json.dumps(reading))["MessageId"]

    try:
        dlq = sqs.create_queue(QueueName="cloudsense-eval-dlq-" + suffix)["QueueUrl"]
        queues["dlq"] = dlq
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        main = sqs.create_queue(QueueName="cloudsense-eval-main-" + suffix, Attributes={"VisibilityTimeout": "60", "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 3})})["QueueUrl"]
        queues["main"] = main
        main_arn = sqs.get_queue_attributes(QueueUrl=main, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        topic = client("sns").create_topic(Name="cloudsense-eval-" + suffix)["TopicArn"]
        original = service.get_function_configuration(FunctionName=FUNCTIONS[1])
        environment = dict(original["Environment"]["Variables"])
        environment["ALERTS_TOPIC_ARN"] = topic
        service.create_function(FunctionName=function, Runtime="python3.13", Role=original["Role"], Handler="process.app.lambda_handler", Code={"ZipFile": (HOME / "lambda_sources.zip").read_bytes()}, Timeout=10, MemorySize=256, Environment={"Variables": environment})
        service.get_waiter("function_active_v2").wait(FunctionName=function)
        mapping = service.create_event_source_mapping(FunctionName=function, EventSourceArn=main_arn, Enabled=False, BatchSize=1, FunctionResponseTypes=["ReportBatchItemFailures"])
        mapping_uuid = mapping["UUID"]
        for attempt in range(40):
            state = service.get_event_source_mapping(UUID=mapping_uuid)["State"]
            if state == "Disabled":
                break
            time.sleep(2)
        else:
            raise RuntimeError("Test trigger did not become Disabled")
        record("isolated_test_ready", mapping_state=state, visibility_seconds=60, max_receive_count=3)

        invalid_status, _ = request_json(outputs["ApiEndpoint"], {"reading_id": run_id + "-invalid"})
        result["checks"]["invalid_input_rejected"] = invalid_status == 400
        record("invalid_input", http_status=invalid_status, stored=read_item(outputs["AlertStateTableName"], run_id + "-invalid"))

        readings = [normal_reading(run_id + "-pause-" + str(number), run_id + "-pause-" + str(number)) for number in range(5)]
        for reading in readings:
            send(reading)
        time.sleep(5)
        absent = [read_item(outputs["AlertStateTableName"], reading["reading_id"]) for reading in readings]
        record("consumer_paused", sent=5, not_stored=sum(not item["exists"] for item in absent), queue=queue_state(main))
        result["checks"]["paused_messages_retained"] = all(not item["exists"] for item in absent)
        restored_at = time.monotonic()
        service.update_event_source_mapping(UUID=mapping_uuid, Enabled=True)
        completed = [wait_item(outputs["AlertStateTableName"], reading["reading_id"]) for reading in readings]
        result["checks"]["resume_completed_all"] = all(item["status"] == "COMPLETE" for item in completed)
        record("consumer_resumed", completed=len(completed), recovery_seconds=round(time.monotonic() - restored_at, 2))

        duplicate = readings[0]
        before = client("dynamodb").get_item(TableName=outputs["AlertStateTableName"], Key={"PK": {"S": "READING#" + duplicate["reading_id"]}, "SK": {"S": "DATA"}}, ConsistentRead=True)["Item"]
        send(duplicate)
        send(duplicate)
        time.sleep(15)
        after = client("dynamodb").get_item(TableName=outputs["AlertStateTableName"], Key={"PK": {"S": "READING#" + duplicate["reading_id"]}, "SK": {"S": "DATA"}}, ConsistentRead=True)["Item"]
        result["checks"]["duplicate_did_not_rewrite_data"] = before == after
        record("duplicate_replayed", identical_data=before == after)

        poison_id = run_id + "-poison"
        poison = {"device_id": run_id + "-repair", "reading_id": poison_id}
        send(poison)
        record("failure_injected", reading_id=poison_id)
        deadline = time.monotonic() + 360
        poison_message = None
        while time.monotonic() < deadline:
            messages = sqs.receive_message(QueueUrl=dlq, MaxNumberOfMessages=1, WaitTimeSeconds=10, VisibilityTimeout=30, MessageSystemAttributeNames=["All"]).get("Messages", [])
            if messages:
                poison_message = messages[0]
                break
            record("waiting_for_dlq", main=queue_state(main), dlq=queue_state(dlq))
        if poison_message is None:
            raise RuntimeError("Poison message did not arrive in DLQ within 360 seconds")
        result["checks"]["failed_message_reached_dlq"] = json.loads(poison_message["Body"])["reading_id"] == poison_id
        record("dlq_received", reading_id=poison_id, original_payload_missing_timestamp=True)
        repaired = normal_reading(poison["device_id"], poison_id)
        send(repaired)
        repaired_state = wait_item(outputs["AlertStateTableName"], poison_id)
        result["checks"]["repaired_replay_completed"] = repaired_state["status"] == "COMPLETE"
        sqs.delete_message(QueueUrl=dlq, ReceiptHandle=poison_message["ReceiptHandle"])
        record("repaired_and_replayed", reading_id=poison_id, stored_status=repaired_state["status"])
        result["result"] = "PASS" if all(result["checks"].values()) else "FAIL"
    except Exception as error:
        result["result"] = "FAIL"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        raise
    finally:
        if mapping_uuid:
            service.update_event_source_mapping(UUID=mapping_uuid, Enabled=False)
            for attempt in range(30):
                if service.get_event_source_mapping(UUID=mapping_uuid)["State"] == "Disabled":
                    break
                time.sleep(2)
        result["test_trigger_final_state"] = service.get_event_source_mapping(UUID=mapping_uuid)["State"] if mapping_uuid else "not_created"
        result["test_function"] = function
        result["ended_at"] = datetime.now(timezone.utc).isoformat()
        result["resources_retained"] = "Dedicated test resources retained with trigger disabled; no production queue purged."
        save("faults.json", result)
        print("FAULT_REPORT", json.dumps(result), flush=True)


def collect(start, end):
    outputs = resources()
    beginning = datetime.fromisoformat(start.replace("Z", "+00:00"))
    finish = datetime.fromisoformat(end.replace("Z", "+00:00"))
    window_start = beginning.replace(second=0, microsecond=0)
    window_end = finish.replace(second=0, microsecond=0) + timedelta(minutes=1)
    metrics = []
    definitions = []
    for function in FUNCTIONS:
        for metric, stats in [("Invocations", ["Sum"]), ("Errors", ["Sum"]), ("Throttles", ["Sum"]), ("Duration", ["Average", "Maximum"]), ("ConcurrentExecutions", ["Maximum"])]:
            definitions.append(("AWS/Lambda", metric, [{"Name": "FunctionName", "Value": function}], stats, function))
    for key in ["QueueUrl", "DeadLetterQueueUrl"]:
        for metric in ["ApproximateNumberOfMessagesVisible", "ApproximateNumberOfMessagesNotVisible", "ApproximateAgeOfOldestMessage"]:
            definitions.append(("AWS/SQS", metric, [{"Name": "QueueName", "Value": outputs[key].rsplit("/", 1)[-1]}], ["Maximum"], key))
        for metric in ["NumberOfMessagesSent", "NumberOfMessagesReceived", "NumberOfMessagesDeleted", "NumberOfEmptyReceives"]:
            definitions.append(("AWS/SQS", metric, [{"Name": "QueueName", "Value": outputs[key].rsplit("/", 1)[-1]}], ["Sum"], key))
    for metric in ["ConsumedReadCapacityUnits", "ConsumedWriteCapacityUnits", "ReadThrottleEvents", "WriteThrottleEvents"]:
        definitions.append(("AWS/DynamoDB", metric, [{"Name": "TableName", "Value": outputs["AlertStateTableName"]}], ["Sum"], "table"))
    for metric in ["ConsumedReadCapacityUnits", "ConsumedWriteCapacityUnits"]:
        definitions.append(("AWS/DynamoDB", metric, [{"Name": "TableName", "Value": outputs["AlertStateTableName"]}, {"Name": "GlobalSecondaryIndexName", "Value": "DeviceTimeIndex"}], ["Sum"], "DeviceTimeIndex"))
    api_id = outputs["ApiEndpoint"].split("//", 1)[1].split(".", 1)[0]
    for metric, stats in [("Count", ["Sum"]), ("4xx", ["Sum"]), ("5xx", ["Sum"]), ("Latency", ["Average", "Maximum"]), ("IntegrationLatency", ["Average", "Maximum"])]:
        definitions.append(("AWS/ApiGateway", metric, [{"Name": "ApiId", "Value": api_id}], stats, "HTTP API"))
    for namespace, metric, dimensions, stats, label in definitions:
        result = client("cloudwatch").get_metric_statistics(Namespace=namespace, MetricName=metric, Dimensions=dimensions, StartTime=window_start, EndTime=window_end, Period=60, Statistics=stats)
        points = sorted(result["Datapoints"], key=lambda point: point["Timestamp"])
        metrics.append({"namespace": namespace, "resource": label, "metric": metric, "points": points})
    save("metrics.json", {"requested_start": start, "requested_end": end, "actual_window_start": window_start, "actual_window_end": window_end, "note": "One minute shared-resource context; not attributed solely to the test. Missing points are not zero.", "metrics": metrics})
    events = []
    groups = FUNCTIONS[:]
    fault_path = EVIDENCE / "faults.json"
    if fault_path.exists():
        groups.append(json.loads(fault_path.read_text())["test_function"])
    for function in groups:
        try:
            pages = client("logs").get_paginator("filter_log_events").paginate(logGroupName="/aws/lambda/" + function, startTime=int(beginning.timestamp() * 1000), endTime=int(finish.timestamp() * 1000))
            for page in pages:
                for event in page["events"]:
                    text = event["message"].strip()
                    if "eval-" in text or "fault-" in text or "REPORT RequestId:" in text:
                        events.append({"function": function, "timestamp": event["timestamp"], "message": text})
        except Exception as error:
            events.append({"function": function, "collection_error": type(error).__name__})
    save("logs.json", events)
    print("COLLECTED", len(metrics), "metric series and", len(events), "log events")


def pricing():
    """Save current public AWS Price List rates, no account billing credentials."""
    services = ["AWSLambda", "AmazonApiGateway", "AWSQueueService", "AmazonDynamoDB", "AmazonCloudWatch", "AmazonSNS"]
    result = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "region": REGION, "services": {}}
    for service in services:
        url = f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{service}/current/{REGION}/index.json"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = json.load(response)
        rows = []
        for sku, product in data["products"].items():
            attrs = product["attributes"]
            for offer in data.get("terms", {}).get("OnDemand", {}).get(sku, {}).values():
                for dimension in offer["priceDimensions"].values():
                    rows.append({"sku": sku, "family": product.get("productFamily"), "attributes": attrs, "unit": dimension["unit"], "usd": dimension["pricePerUnit"].get("USD"), "begin": dimension["beginRange"], "end": dimension["endRange"], "description": dimension["description"]})
        result["services"][service] = {"source": url, "publication_date": data.get("publicationDate"), "rates": rows}
        save("pricing.json", result)
        print("PRICE_LIST", service, len(rows), flush=True)


def billing():
    now = datetime.now(timezone.utc)
    start = now.replace(day=1).strftime("%Y-%m-%d")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        response = client("ce").get_cost_and_usage(TimePeriod={"Start": start, "End": end}, Granularity="DAILY", Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])
        response.pop("ResponseMetadata", None)
        save("billing.json", {"scope": "Account-wide month-to-date; delayed, not isolated experiment billing", "queried_at": now.isoformat(), "data": response})
        print("BILLING_COLLECTED", len(response.get("ResultsByTime", [])), "daily periods")
    except Exception as error:
        save("billing.json", {"status": "unavailable", "error_type": type(error).__name__, "error_code": getattr(error, "response", {}).get("Error", {}).get("Code")})
        print("Billing unavailable:", type(error).__name__)


def bundle():
    archive = HOME / "cloud_evidence.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(EVIDENCE.glob("*.json")):
            output.write(path, "cloud_evidence/" + path.name)
    print("DOWNLOAD", archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "deploy", "faults", "collect", "billing", "pricing", "bundle"])
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    if args.action == "collect":
        if not args.start or not args.end:
            parser.error("collect requires --start and --end")
        collect(args.start, args.end)
    else:
        {"snapshot": snapshot, "deploy": deploy, "faults": fault_test, "collect": collect, "billing": billing, "pricing": pricing, "bundle": bundle}[args.action]()


if __name__ == "__main__":
    main()
