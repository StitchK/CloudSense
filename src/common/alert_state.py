from datetime import datetime, timezone
import time
import uuid


class NotificationInProgress(Exception):
    """Raised when another Lambda invocation holds the notification lease."""


def _state_key(device_id, metric):
    return {"PK": f"DEVICE#{device_id}", "SK": f"METRIC#{metric}"}


def _progress_key(reading_id, metric):
    return {"PK": f"READING#{reading_id}", "SK": f"METRIC#{metric}"}


def reading_timestamp_epoch(timestamp):
    """Convert an ISO-8601 timestamp to UTC epoch seconds."""
    if isinstance(timestamp, (int, float)):
        return int(timestamp)
    if not isinstance(timestamp, str):
        raise ValueError("reading timestamp must be ISO-8601 or epoch seconds")

    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("reading timestamp must be valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError("reading timestamp must include a timezone")
    return int(parsed.astimezone(timezone.utc).timestamp())


def is_reading_late(timestamp, now=None, max_age_seconds=300):
    """Return whether the measurement is older than the allowed processing age."""
    current_epoch = int(datetime.now(timezone.utc).timestamp() if now is None else now)
    return current_epoch - reading_timestamp_epoch(timestamp) > max_age_seconds


def _is_conditional_failure(error):
    return (
        getattr(error, "response", {}).get("Error", {}).get("Code")
        == "ConditionalCheckFailedException"
    )


def should_notify(alert, previous, now, cooldown=300):
    """Return whether a new alert qualifies by cooldown or severity escalation."""
    if previous is None:
        return True

    if previous["last_level"] == "warning" and alert["level"] == "critical":
        return True

    return now - previous["last_sent_at"] >= cooldown


def load_state(table, device_id, metric):
    """Read the last successful notification for one device metric."""
    response = table.get_item(
        Key=_state_key(device_id, metric),
        ConsistentRead=True,
    )
    item = response.get("Item")
    if item is None or "last_sent_at" not in item or "last_level" not in item:
        return None
    return {
        "last_sent_at": item["last_sent_at"],
        "last_level": item["last_level"],
        "critical_streak": item.get("critical_streak", 0),
        "last_observed_level": item.get("last_observed_level"),
        "last_reading_epoch": item.get("last_reading_epoch"),
    }


def load_reading_progress(table, reading_id, metric):
    """Load persisted processing status for one reading and metric."""
    response = table.get_item(
        Key=_progress_key(reading_id, metric),
        ConsistentRead=True,
    )
    return response.get("Item")


def has_reading_progress(table, reading_id, metric):
    """Check whether this reading metric was already sent or suppressed."""
    return load_reading_progress(table, reading_id, metric) is not None


def record_reading_result(
    table,
    device_id,
    metric,
    level,
    reading_id,
    reading_epoch,
    now,
    retention_seconds,
):
    """Atomically update the metric streak and dedupe this reading."""
    progress_key = _progress_key(reading_id, metric)
    existing = load_reading_progress(table, reading_id, metric)
    if existing is not None:
        return existing

    client = table.meta.client
    state_key = _state_key(device_id, metric)
    for attempt in range(8):
        state = table.get_item(Key=state_key, ConsistentRead=True).get("Item", {})
        previous_epoch = state.get("last_reading_epoch")
        if previous_epoch is not None and reading_epoch <= previous_epoch:
            result = {
                "status": "OUT_OF_ORDER",
                "level": level,
                "critical_streak": state.get("critical_streak", 0),
                "accepted": False,
            }
            save_reading_progress(
                table,
                reading_id,
                metric,
                result["status"],
                now,
                retention_seconds,
                details=result,
            )
            return result

        previous_level = state.get("last_observed_level")
        previous_streak = state.get("critical_streak", 0)
        critical_streak = (
            previous_streak + 1
            if level == "critical" and previous_level == "critical"
            else 1
            if level == "critical"
            else 0
        )
        progress = {
            "PK": progress_key["PK"],
            "SK": progress_key["SK"],
            "status": "EVALUATED",
            "level": level,
            "critical_streak": critical_streak,
            "accepted": True,
            "expires_at": int(now + retention_seconds),
        }
        condition = (
            "attribute_not_exists(last_reading_epoch)"
            if previous_epoch is None
            else "last_reading_epoch = :previous_epoch"
        )
        values = {
            ":reading_epoch": int(reading_epoch),
            ":level": level,
            ":streak": critical_streak,
        }
        if previous_epoch is not None:
            values[":previous_epoch"] = int(previous_epoch)

        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": table.name,
                            "Key": state_key,
                            "UpdateExpression": (
                                "SET last_reading_epoch = :reading_epoch, "
                                "last_observed_level = :level, "
                                "critical_streak = :streak"
                            ),
                            "ConditionExpression": condition,
                            "ExpressionAttributeValues": values,
                        }
                    },
                    {
                        "Put": {
                            "TableName": table.name,
                            "Item": progress,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
            return progress
        except Exception as error:
            existing = load_reading_progress(table, reading_id, metric)
            if existing is not None:
                return existing
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code not in (
                "ConditionalCheckFailedException",
                "TransactionCanceledException",
            ):
                raise
            time.sleep(min(0.05 * (2**attempt), 0.4))

    raise RuntimeError("could not record reading result after concurrent updates")


def claim_notification(
    table,
    device_id,
    metric,
    level,
    reading_id,
    now,
    cooldown=300,
    lease_seconds=60,
):
    """Atomically reserve an eligible notification until the lease expires."""
    token = uuid.uuid4().hex
    try:
        table.update_item(
            Key=_state_key(device_id, metric),
            UpdateExpression=(
                "SET claim_token = :token, claim_expires_at = :lease, "
                "active_reading_id = :reading_id"
            ),
            ConditionExpression=(
                "(attribute_not_exists(claim_expires_at) "
                "OR claim_expires_at <= :now) AND "
                "(attribute_not_exists(last_sent_at) "
                "OR last_sent_at <= :cooldown_cutoff "
                "OR (last_level = :warning AND :level = :critical))"
            ),
            ExpressionAttributeValues={
                ":token": token,
                ":lease": int(now + lease_seconds),
                ":reading_id": reading_id,
                ":now": int(now),
                ":cooldown_cutoff": int(now - cooldown),
                ":warning": "warning",
                ":critical": "critical",
                ":level": level,
            },
        )
    except Exception as error:
        if not _is_conditional_failure(error):
            raise

        current = table.get_item(
            Key=_state_key(device_id, metric),
            ConsistentRead=True,
        ).get("Item", {})
        if current.get("claim_expires_at", 0) > now:
            raise NotificationInProgress from error
        return None

    return token


def save_state(
    table,
    device_id,
    metric,
    level,
    reading_id,
    claim_token,
    now,
    progress_retention_seconds,
):
    """Commit sent status and reading dedupe progress atomically."""
    client = table.meta.client
    state_key = _state_key(device_id, metric)
    progress_key = _progress_key(reading_id, metric)

    client.transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": table.name,
                    "Key": state_key,
                    "UpdateExpression": (
                        "SET last_sent_at = :now, last_level = :level "
                        "REMOVE claim_token, claim_expires_at, active_reading_id"
                    ),
                    "ConditionExpression": "claim_token = :token",
                    "ExpressionAttributeValues": {
                        ":now": int(now),
                        ":level": level,
                        ":token": claim_token,
                    },
                }
            },
            {
                "Update": {
                    "TableName": table.name,
                    "Key": progress_key,
                    "UpdateExpression": (
                        "SET #status = :sent, sent_at = :now, expires_at = :expires"
                    ),
                    "ConditionExpression": "attribute_exists(PK)",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": {
                        ":sent": "SENT",
                        ":now": int(now),
                        ":expires": int(now + progress_retention_seconds),
                    },
                }
            },
        ]
    )


def save_reading_progress(
    table, reading_id, metric, status, now, retention_seconds, details=None
):
    """Record a suppressed metric or a fully processed reading for dedupe."""
    key = _progress_key(reading_id, metric)
    try:
        table.put_item(
            Item={
                **key,
                "status": status,
                "expires_at": int(now + retention_seconds),
                **(details or {}),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except Exception as error:
        if not _is_conditional_failure(error):
            raise


def update_reading_progress(table, reading_id, metric, status, now):
    """Update the outcome for an already recorded reading metric."""
    table.update_item(
        Key=_progress_key(reading_id, metric),
        UpdateExpression="SET #status = :status, updated_at = :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": status, ":now": int(now)},
        ConditionExpression="attribute_exists(PK)",
    )


def release_claim(table, device_id, metric, claim_token):
    """Release a failed notification reservation so SQS retry can proceed."""
    try:
        table.update_item(
            Key=_state_key(device_id, metric),
            UpdateExpression=(
                "REMOVE claim_token, claim_expires_at, active_reading_id"
            ),
            ConditionExpression="claim_token = :token",
            ExpressionAttributeValues={":token": claim_token},
        )
    except Exception as error:
        if not _is_conditional_failure(error):
            raise
