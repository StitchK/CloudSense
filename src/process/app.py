import hashlib
import json
import os
import time

try:
    from common.alert_rules import evaluate_reading_results
    from common.alert_state import (
        claim_notification,
        has_reading_progress,
        is_reading_late,
        load_state,
        reading_timestamp_epoch,
        record_reading_result,
        release_claim,
        save_reading_progress,
        save_state,
        should_notify,
        update_reading_progress,
    )
    from common.reading_store import finish_reading, save_reading, update_alert_history
    from notification import send_alert
except ModuleNotFoundError:
    from src.common.alert_rules import evaluate_reading_results
    from src.common.alert_state import (
        claim_notification,
        has_reading_progress,
        is_reading_late,
        load_state,
        reading_timestamp_epoch,
        record_reading_result,
        release_claim,
        save_reading_progress,
        save_state,
        should_notify,
        update_reading_progress,
    )
    from src.common.reading_store import (
        finish_reading,
        save_reading,
        update_alert_history,
    )
    from src.notification import send_alert


DONE_METRIC = "__DONE__"
READING_RETENTION_SECONDS = 14 * 24 * 60 * 60
READING_HISTORY_RETENTION_SECONDS = int(
    os.getenv("READING_HISTORY_RETENTION_SECONDS", str(90 * 24 * 60 * 60))
)


def _reading_id(reading):
    """Use the supplied ID or derive a stable ID for older event payloads."""
    if reading.get("reading_id"):
        return str(reading["reading_id"])

    canonical_reading = json.dumps(
        reading,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical_reading).hexdigest()


def _get_dependencies():
    """Create AWS clients lazily so importing the handler needs no AWS config."""
    import boto3

    table_name = os.environ["ALERT_STATE_TABLE"]
    topic_arn = os.environ["ALERTS_TOPIC_ARN"]
    table = boto3.resource("dynamodb").Table(table_name)
    return table, topic_arn


def process_reading(reading, table, topic_arn, now=None):
    """Store, evaluate, and process one reading with per-metric idempotency."""
    now = int(time.time() if now is None else now)
    reading = dict(reading)
    reading_id = _reading_id(reading)
    reading["reading_id"] = reading_id

    if has_reading_progress(table, reading_id, DONE_METRIC):
        return

    cooldown = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
    lease_seconds = int(os.getenv("CLAIM_LEASE_SECONDS", "60"))
    max_age_seconds = int(os.getenv("MAX_READING_AGE_SECONDS", "300"))
    reading_epoch = reading_timestamp_epoch(reading["timestamp"])
    reading["_timestamp_epoch"] = reading_epoch
    results = evaluate_reading_results(reading)
    late = is_reading_late(reading["timestamp"], now, max_age_seconds)

    # Save the original measurement and its classifications before notifications.
    save_reading(table, reading, results, late, now, READING_HISTORY_RETENTION_SECONDS)

    if late:
        for result in results:
            metric = result["metric"]
            save_reading_progress(
                table,
                reading_id,
                metric,
                "LATE",
                now,
                READING_RETENTION_SECONDS,
                details={"level": result["level"], "accepted": False},
            )
            update_alert_history(table, reading_id, result, "LATE", now)
        finish_reading(table, reading_id, "LATE", now)
        save_reading_progress(
            table,
            reading_id,
            DONE_METRIC,
            "COMPLETE",
            now,
            READING_RETENTION_SECONDS,
        )
        return

    for result in results:
        metric = result["metric"]
        progress = record_reading_result(
            table,
            reading["device_id"],
            metric,
            result["level"],
            reading_id,
            reading_epoch,
            now,
            READING_RETENTION_SECONDS,
        )
        status = progress.get("status")
        if status in (
            "SENT",
            "SUPPRESSED",
            "OUT_OF_ORDER",
            "NORMAL",
            "CRITICAL_PENDING",
        ):
            update_alert_history(table, reading_id, result, status, now)
            continue

        if not progress.get("accepted", True):
            update_alert_history(table, reading_id, result, "OUT_OF_ORDER", now)
            continue

        if result["level"] == "normal":
            update_reading_progress(table, reading_id, metric, "NORMAL", now)
            update_alert_history(table, reading_id, result, "NORMAL", now)
            continue

        if result["level"] == "critical" and progress["critical_streak"] < 2:
            update_reading_progress(table, reading_id, metric, "CRITICAL_PENDING", now)
            update_alert_history(table, reading_id, result, "CRITICAL_PENDING", now)
            continue

        alert = result
        previous = load_state(table, reading["device_id"], metric)
        if not should_notify(alert, previous, now, cooldown):
            update_reading_progress(table, reading_id, metric, "SUPPRESSED", now)
            update_alert_history(table, reading_id, result, "SUPPRESSED", now)
            continue

        claim_token = claim_notification(
            table,
            reading["device_id"],
            metric,
            result["level"],
            reading_id,
            now,
            cooldown,
            lease_seconds,
        )
        if claim_token is None:
            update_reading_progress(table, reading_id, metric, "SUPPRESSED", now)
            update_alert_history(table, reading_id, result, "SUPPRESSED", now)
            continue

        try:
            send_alert(topic_arn, reading, alert)
            save_state(
                table,
                reading["device_id"],
                metric,
                result["level"],
                reading_id,
                claim_token,
                now,
                READING_RETENTION_SECONDS,
            )
            update_alert_history(table, reading_id, result, "SENT", now)
        except Exception:
            release_claim(table, reading["device_id"], metric, claim_token)
            update_reading_progress(table, reading_id, metric, "RETRY_PENDING", now)
            update_alert_history(table, reading_id, result, "SEND_FAILED", now)
            raise

    finish_reading(table, reading_id, "COMPLETE", now)
    save_reading_progress(
        table,
        reading_id,
        DONE_METRIC,
        "COMPLETE",
        now,
        READING_RETENTION_SECONDS,
    )


def lambda_handler(event, context):
    """Process an SQS batch and ask Lambda to retry only failed messages."""
    table, topic_arn = _get_dependencies()
    batch_item_failures = []

    for record in event.get("Records", []):
        try:
            reading = json.loads(record["body"])
            if not isinstance(reading, dict):
                raise ValueError("SQS body must contain a JSON object")
            process_reading(reading, table, topic_arn)
        except Exception as error:
            error_response = getattr(error, "response", {})
            print(
                json.dumps(
                    {
                        "event": "reading_processing_failed",
                        "message_id": record.get("messageId"),
                        "error": str(error),
                        "error_code": error_response.get("Error", {}).get("Code"),
                        "cancellation_reasons": error_response.get(
                            "CancellationReasons"
                        ),
                    },
                    separators=(",", ":"),
                    default=str,
                )
            )
            batch_item_failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": batch_item_failures}
