"""Read-only CloudShell evidence. No writes to AWS resources or test messages."""

import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("view", choices=["deployment", "queries", "upstream"])
    parser.add_argument("--stack", default="cloudsense-http-ingest-test")
    args = parser.parse_args()
    stack = boto3.client("cloudformation").describe_stacks(StackName=args.stack)["Stacks"][0]
    outputs = {x["OutputKey"]: x["OutputValue"] for x in stack["Outputs"]}
    lam = boto3.client("lambda")
    print("CloudSense Lambda3 /", args.view)
    if args.view == "deployment":
        fn = lam.get_function_configuration(FunctionName=outputs["QueryFunctionName"])
        for label, value in [
            ("Stack", args.stack), ("StackStatus", stack["StackStatus"]),
            ("Function", fn["FunctionName"]), ("State", fn["State"]),
            ("LastUpdateStatus", fn["LastUpdateStatus"]),
            ("Handler", fn["Handler"]), ("Runtime", fn["Runtime"]),
            ("Memory / Timeout", f'{fn["MemorySize"]} MB / {fn["Timeout"]} seconds'),
        ]:
            print(f"{label}: {value}")
        resources = boto3.client("cloudformation").list_stack_resources(StackName=args.stack)
        print("Deployed query resources:")
        for row in resources["StackResourceSummaries"]:
            if row["LogicalResourceId"].startswith("QueryFunction") or row["LogicalResourceId"] == "ReadingsHttpApi":
                print(" ", row["LogicalResourceId"], row["ResourceStatus"])
    elif args.view == "queries":
        prefix = outputs["QueryApiBaseUrl"] + "/devices/email-critical-001/"
        params = urlencode({"from": "2026-10-01T00:00:00Z", "to": "2026-11-07T00:00:00Z", "limit": 1})
        for view in ("latest", "history", "alerts"):
            with urlopen(prefix + view + ("?" + params if view != "latest" else ""), timeout=20) as res:
                body = json.load(res)
                print("GET", view, "HTTP", res.status)
            if view == "latest":
                data = body["data"]
                print(" device_id:", body["device_id"])
                print(" reading:", json.dumps(data["reading"], ensure_ascii=False))
                print(" overall_status:", data["overall_status"])
                print(" is_stale:", body["is_stale"])
                for alert in data["alerts"]:
                    print(" alert:", json.dumps(alert, ensure_ascii=False))
            else:
                print(" count:", body["count"], "has_next_page:", bool(body["next_token"]))
                for item in body["items"]:
                    print(" reading_id:", item["reading"]["reading_id"], "status:", item["overall_status"])
    else:
        device = "query-demo-20261106"
        reading_id = "2ad07287-b2e0-4cf3-9c79-180139d8fc89"
        item = boto3.resource("dynamodb").Table(outputs["AlertStateTableName"]).get_item(
            Key={"PK": "READING#" + reading_id, "SK": "DATA"}
        ).get("Item")
        print("Fresh synthetic device:", device)
        print("Reading ID:", reading_id)
        print("Reading exists in DynamoDB:", bool(item))
        for mapping in lam.list_event_source_mappings(FunctionName="cloudsense-process-alerts")["EventSourceMappings"]:
            print("Lambda2 event source state:", mapping["State"])
            print("LastProcessingResult:", mapping.get("LastProcessingResult"))
        sqs = boto3.client("sqs")
        for key in ("QueueUrl", "DeadLetterQueueUrl"):
            counts = sqs.get_queue_attributes(
                QueueUrl=outputs[key],
                AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
            )["Attributes"]
            print(key + ":", json.dumps(counts))
        try:
            with urlopen(outputs["QueryApiBaseUrl"] + "/devices/" + device + "/latest", timeout=20) as res:
                print("Fresh latest HTTP:", res.status)
        except HTTPError as exc:
            print("Fresh latest HTTP:", exc.code)
            print("Response:", exc.read().decode())
        print("New-data pipeline check is blocked upstream; historic query check is separate.")


if __name__ == "__main__":
    main()
