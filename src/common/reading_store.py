from decimal import Decimal
import time


def _dynamodb_value(value):
    """Convert JSON numeric values to types accepted by DynamoDB."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _dynamodb_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dynamodb_value(item) for item in value]
    return value


def _reading_key(reading_id):
    return {"PK": f"READING#{reading_id}", "SK": "DATA"}


def save_reading(table, reading, results, is_late, now, retention_seconds):
    """Upsert a complete reading and its four classifications for dashboard use.

    Dashboard contract: query DeviceTimeIndex with GSI1PK=DEVICE#<device_id>;
    GSI1SK is a zero-padded measurement epoch followed by reading_id.
    """
    reading_id = str(reading["reading_id"])
    reading_epoch = int(reading["_timestamp_epoch"])
    alert_history = {
        result["metric"]: {
            "level": result["level"],
            "message": result["message"],
            "status": "LATE" if is_late else "PENDING",
        }
        for result in results
    }
    table.update_item(
        Key=_reading_key(reading_id),
        UpdateExpression=(
            "SET #reading = :reading, evaluations = :evaluations, "
            "is_late = :is_late, measured_at_epoch = :measured_at, "
            "GSI1PK = :device_key, GSI1SK = :time_key, "
            "created_at = if_not_exists(created_at, :now), updated_at = :now, "
            "processing_status = if_not_exists(processing_status, :processing), "
            "alert_history = if_not_exists(alert_history, :alert_history), "
            "expires_at = :expires"
        ),
        ExpressionAttributeNames={"#reading": "reading"},
        ExpressionAttributeValues={
            ":reading": _dynamodb_value(
                {
                    key: value
                    for key, value in reading.items()
                    if key != "_timestamp_epoch"
                }
            ),
            ":evaluations": results,
            ":is_late": is_late,
            ":measured_at": reading_epoch,
            ":device_key": f"DEVICE#{reading['device_id']}",
            ":time_key": f"{reading_epoch:020d}#{reading_id}",
            ":now": int(now),
            ":processing": "PROCESSING",
            ":alert_history": alert_history,
            ":expires": int(now + retention_seconds),
        },
    )


def update_alert_history(table, reading_id, result, status, now):
    """Persist one metric's final alert decision without replacing the reading."""
    metric = result["metric"]
    table.update_item(
        Key=_reading_key(reading_id),
        UpdateExpression=(
            "SET alert_history.#metric = :entry, updated_at = :now, "
            "processing_status = :processing"
        ),
        ExpressionAttributeNames={"#metric": metric},
        ExpressionAttributeValues={
            ":entry": {
                "level": result["level"],
                "message": result["message"],
                "status": status,
            },
            ":now": int(now),
            ":processing": "PROCESSING",
        },
        ConditionExpression="attribute_exists(PK)",
    )


def finish_reading(table, reading_id, status, now):
    """Mark the dashboard history record as complete or late-only."""
    table.update_item(
        Key=_reading_key(reading_id),
        UpdateExpression="SET processing_status = :status, updated_at = :now, completed_at_ms = :completed",
        ExpressionAttributeValues={":status": status, ":now": int(now), ":completed": time.time_ns() // 1_000_000},
        ConditionExpression="attribute_exists(PK)",
    )
