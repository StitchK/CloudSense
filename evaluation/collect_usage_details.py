"""CloudShell: supplement the fixed evidence window with log ingestion and metadata."""
import json
from datetime import datetime, timezone

from cloud_lab import EVIDENCE, FUNCTIONS, client, resources, save


def main():
    metadata = json.loads((EVIDENCE / "metrics.json").read_text())
    start = datetime.fromisoformat(metadata["actual_window_start"])
    end = datetime.fromisoformat(metadata["actual_window_end"])
    fault = json.loads((EVIDENCE / "faults.json").read_text())
    groups = FUNCTIONS + [fault["test_function"]]
    logs = []
    for function in groups:
        group = "/aws/lambda/" + function
        result = client("cloudwatch").get_metric_statistics(
            Namespace="AWS/Logs", MetricName="IncomingBytes",
            Dimensions=[{"Name": "LogGroupName", "Value": group}],
            StartTime=start, EndTime=end, Period=60, Statistics=["Sum"],
        )
        logs.append({"function": function, "points": sorted(result["Datapoints"], key=lambda p: p["Timestamp"])})
    table = client("dynamodb").describe_table(TableName=resources()["AlertStateTableName"])["Table"]
    data = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "log_incoming_bytes": logs,
        "table": {key: table.get(key) for key in ["BillingModeSummary", "TableSizeBytes", "ItemCount", "TableClassSummary"]},
        "note": "Shared resources; table size/item count are approximate and not experiment deltas. Log bytes include all events for these functions in this window.",
    }
    save("usage_details.json", data)
    print("LOG_INGESTION_BYTES", sum(p["Sum"] for row in logs for p in row["points"]))
    print("TABLE_BILLING_MODE", data["table"]["BillingModeSummary"])


if __name__ == "__main__":
    main()
