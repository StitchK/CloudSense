import json
import os
from datetime import datetime, timezone

import boto3


sqs = boto3.client("sqs")
QUEUE_URL = os.environ["READING_QUEUE_URL"]

REQUIRED_FIELDS = {
    "device_id",
    "reading_id",
    "timestamp",
    "heart_rate_bpm",
    "body_temperature_c",
    "spo2_pct",
    "blood_pressure",
    "activity",
}


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    try:
        body = event.get("body", "")
        reading = json.loads(body) if isinstance(body, str) else body
    except (TypeError, ValueError) as exc:
        return response(400, {"message": "invalid JSON", "error": str(exc)})

    if not isinstance(reading, dict):
        return response(400, {"message": "reading must be a JSON object"})

    missing = sorted(REQUIRED_FIELDS.difference(reading))
    if missing:
        return response(
            400,
            {"message": "missing required fields", "fields": missing},
        )

    enriched = dict(reading)
    enriched["received_at"] = datetime.now(timezone.utc).isoformat()
    enriched["source"] = "api-gateway"

    print(
        json.dumps(
            {
                "event": "reading_received",
                "device_id": reading.get("device_id"),
                "reading_id": reading.get("reading_id"),
                "payload": enriched,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(enriched, separators=(",", ":")),
        )
    except Exception as exc:
        print(json.dumps({"event": "sqs_send_failed", "error": str(exc)}))
        return response(502, {"message": "failed to enqueue reading"})

    return response(
        202,
        {
            "message": "accepted",
            "reading_id": reading.get("reading_id"),
        },
    )
