"""Recalculate a transparent USD estimate from saved AWS experiment evidence."""

import csv
import html
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "cloud_evidence"


def read(name):
    return json.loads((EVIDENCE / (name + ".json")).read_text(encoding="utf-8"))


def calculate():
    prices = read("pricing")
    metrics = read("metrics")
    usage = read("usage_details")
    if usage["table"]["BillingModeSummary"]["BillingMode"] != "PAY_PER_REQUEST":
        raise ValueError("This calculation requires an on-demand DynamoDB table")
    selected = {}

    def rate(label, service, sku, begin="0"):
        matches = [row for row in prices["services"][service]["rates"]
                   if row["sku"] == sku and row["begin"] == begin]
        if len(matches) != 1:
            raise ValueError("Ambiguous or missing official rate: " + label)
        selected[label] = dict(matches[0], source=prices["services"][service]["source"])
        return Decimal(matches[0]["usd"])

    def metric(resource, name):
        rows = [row for row in metrics["metrics"] if row["resource"] == resource and row["metric"] == name]
        if len(rows) != 1 or not rows[0]["points"]:
            raise ValueError("Missing metric: " + resource + " " + name)
        return sum(Decimal(str(point["Sum"])) for point in rows[0]["points"])

    request_rate = rate("lambda_request", "AWSLambda", "GU2ZS9HVP6QTQ7KE")
    compute_rate = rate("lambda_x86_gb_second", "AWSLambda", "TG3M4CAGBA3NYQBH")
    api_rate = rate("http_api_request", "AmazonApiGateway", "FC2TWT2UEPTBKVBX")
    sqs_rate = rate("standard_sqs_request", "AWSQueueService", "8RN6B8U4MERHRXP3")
    write_rate = rate("dynamodb_write", "AmazonDynamoDB", "FGXVD96DKJMUASY3")
    read_rate = rate("dynamodb_read", "AmazonDynamoDB", "4W4ZMC46EHE8XTTZ")
    logs_rate = rate("standard_log_ingestion_gb", "AmazonCloudWatch", "96K55R2PV3ZZZ3AM")
    rate("dynamodb_storage_gb_month", "AmazonDynamoDB", "F3E2EDSYC6ZNW7XP", "25")
    rate("logs_storage_gb_month", "AmazonCloudWatch", "JRHJQ2UMPUB5K73A")
    reports = defaultdict(lambda: {"invocations": 0, "billed_ms": Decimal(0), "gb_seconds": Decimal(0)})
    pattern = re.compile(r"Billed Duration:\s*([\d.]+)\s*ms\s+Memory Size:\s*(\d+)\s*MB")
    seen = set()
    for event in read("logs"):
        message = event.get("message", "")
        if not message.startswith("REPORT RequestId:"):
            continue
        key = (event["function"], message.split()[2])
        if key in seen:
            continue
        seen.add(key)
        match = pattern.search(message)
        if not match:
            raise ValueError("Unrecognized Lambda REPORT")
        billed_ms, memory_mb = map(Decimal, match.groups())
        row = reports[event["function"]]
        row["invocations"] += 1
        row["billed_ms"] += billed_ms
        row["gb_seconds"] += billed_ms / 1000 * memory_mb / 1024
    count = sum(row["invocations"] for row in reports.values())
    if not count:
        raise ValueError("No Lambda billing reports collected")
    gb_seconds = sum(row["gb_seconds"] for row in reports.values())
    log_bytes = sum(Decimal(str(point["Sum"])) for row in usage["log_incoming_bytes"] for point in row["points"])
    if not log_bytes:
        raise ValueError("No log ingestion measurements")
    items = []

    def item(service, quantity, unit, price, basis):
        items.append({"service": service, "quantity": float(quantity), "unit": unit,
                      "usd_per_unit": float(price), "estimated_usd": float(quantity * price), "basis": basis})

    item("Lambda requests", Decimal(count), "requests", request_rate, "Distinct REPORT lines including isolated fault function")
    item("Lambda compute", gb_seconds, "GB seconds", compute_rate, "REPORT billed duration multiplied by configured memory; x86 first tier")
    item("HTTP API", metric("HTTP API", "Count"), "requests", api_rate, "Shared aligned CloudWatch window; includes history queries and one invalid request")
    item("DynamoDB writes", metric("table", "ConsumedWriteCapacityUnits") + metric("DeviceTimeIndex", "ConsumedWriteCapacityUnits"), "write units", write_rate, "On-demand table plus GSI; shared window, not isolated reading attribution")
    item("DynamoDB reads", metric("table", "ConsumedReadCapacityUnits") + metric("DeviceTimeIndex", "ConsumedReadCapacityUnits"), "read units", read_rate, "On-demand table plus GSI; shared window")
    item("CloudWatch log ingestion", log_bytes / (1024 ** 3), "GB", logs_rate, "IncomingBytes for three main functions and isolated fault function")
    sqs_requests = sum(metric("QueueUrl", name) for name in ["NumberOfMessagesSent", "NumberOfMessagesReceived", "NumberOfMessagesDeleted", "NumberOfEmptyReceives"])
    item("Main SQS request model", sqs_requests, "modeled requests", sqs_rate, "One request per sent/received/deleted message plus empty receives; batching means this is a model, not billed request count; assumes payload below 64 KiB")
    total = sum(Decimal(str(row["estimated_usd"])) for row in items)
    runs = [json.loads(path.read_text()) for path in sorted((HERE / "results").glob("*/summary.json"))]
    runs = [run for run in runs if metrics["requested_start"] <= run["started_at"] < metrics["requested_end"]]
    completed = sum(run["completed"] for run in runs)
    if not completed:
        raise ValueError("No completed low-load records in the saved evidence window")
    billing = read("billing")
    account_total = sum(Decimal(group["Metrics"]["UnblendedCost"]["Amount"])
                        for period in billing.get("data", {}).get("ResultsByTime", []) for group in period["Groups"])
    return {
        "currency": "USD", "region": prices["region"], "price_retrieved_at": prices["retrieved_at"],
        "window_start": metrics["actual_window_start"], "window_end": metrics["actual_window_end"],
        "items": items, "estimated_modeled_subtotal_usd": float(total),
        "lambda_reports": reports, "log_incoming_bytes": int(log_bytes), "selected_rates": selected,
        "completed_low_load_records": completed,
        "run_ids": [run["run_id"] for run in runs],
        "scenario": {"devices": 100, "records_per_device_per_minute": 1, "days": 30,
                     "records": 4320000, "modeled_subtotal_usd": float(total * Decimal(4320000) / completed),
                     "assumption": "Linear extrapolation of this mixed experiment cost per completed low-load record, including query density, fault overhead and idle polling; not validated production workload or capacity."},
        "account_month_to_date_usd": float(account_total),
        "account_billing_queried_at": billing.get("queried_at"),
        "limitations": [
            "Estimated modeled subtotal, not an experiment invoice; shared aligned metrics and raw REPORT window differ by one minute at the end.",
            "No free tier, Learner Lab credits, discounts or taxes applied.",
            "Excludes dedicated fault SQS API calls, SNS, data transfer, S3 frontend, EC2/VPC/CloudShell environment and metric collection API charges.",
            "No abnormal alerts were sent in these runs; SNS publish/email delivery cost and delivery reliability were not measured.",
            "DynamoDB and log storage require retained byte-hours; snapshots are not experiment storage deltas. Reference only: $0.25/GB-month table and $0.03/GB-month logs.",
            "Current table metadata and IncomingBytes are approximate; missing monitoring points are not zero.",
            "Account month-to-date billing is delayed and includes unrelated resources; it is separate from this estimate.",
        ],
    }


def main():
    result = calculate()
    output = HERE / "costs"
    output.mkdir(exist_ok=True)
    (output / "costs.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (output / "costs.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["items"][0]))
        writer.writeheader()
        writer.writerows(result["items"])
    rows = "".join(f'<tr><td>{html.escape(row["service"])}</td><td>{row["quantity"]:,.6f}</td><td>{html.escape(row["unit"])}</td><td>${row["estimated_usd"]:.8f}</td></tr>' for row in result["items"])
    notes = "".join("<li>" + html.escape(note) + "</li>" for note in result["limitations"])
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>CloudSense measured cost estimate</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:35px auto;color:#162332;background:#f4f7fa}}main{{background:white;padding:30px;border-radius:14px}}h1{{font-size:28px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}.total{{font-size:27px;color:#08674b}}li{{margin:8px 0}}small{{color:#456}}</style><main>
<h1>CloudSense measured cost estimate</h1><p>us-east-1 | {html.escape(result["window_start"])} to {html.escape(result["window_end"])}</p>
<p class="total">Modeled subtotal USD {result["estimated_modeled_subtotal_usd"]:.6f}</p>
<table><tr><th>Service</th><th>Measured / modeled usage</th><th>Unit</th><th>Estimated USD</th></tr>{rows}</table>
<p>Lambda REPORT count: {sum(row["invocations"] for row in result["lambda_reports"].values())}; log IncomingBytes: {result["log_incoming_bytes"]:,}; low-load completion: {result["completed_low_load_records"]}/360.</p>
<p>100 devices, one reading/minute, 30 days: 4,320,000 readings; linear experiment scenario USD {result["scenario"]["modeled_subtotal_usd"]:.2f}. This includes the experiment query/fault/polling pattern and does not prove capacity.</p>
<p>Separate delayed account month-to-date bill: USD {result["account_month_to_date_usd"]:.6f}.</p><h2>Scope and limitations</h2><ul>{notes}</ul>
<small>Calculated from saved AWS evidence and official public regional Price Lists retrieved {html.escape(result["price_retrieved_at"])}. See costs.json for exact SKU, source URL and formula inputs.</small></main></html>'''
    (output / "costs.html").write_text(document, encoding="utf-8")
    print("MODELED_SUBTOTAL_USD", f'{result["estimated_modeled_subtotal_usd"]:.8f}')
    print("MONTHLY_EXPERIMENT_SCENARIO_USD", f'{result["scenario"]["modeled_subtotal_usd"]:.2f}')
    print(output / "costs.html")


if __name__ == "__main__":
    main()
