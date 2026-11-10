"""Read stored classifications for the CloudSense dashboard (HTTP API v2)."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal

try:
    from common.observability import emit
except ModuleNotFoundError:
    def emit(event, **fields):
        print(json.dumps({"event": event, "logged_at_ms": time.time_ns() // 1_000_000, **fields}))


ROUTES = {
    "GET /devices/{device_id}/latest": "latest",
    "GET /devices/{device_id}/history": "history",
    "GET /devices/{device_id}/alerts": "alerts",
}
DEVICE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}")
LEVEL_RANK = {"normal": 0, "warning": 1, "critical": 2}
CURSOR_KEYS = {"PK", "SK", "GSI1PK", "GSI1SK"}


class RequestError(ValueError):
    def __init__(self, status_code, message):
        self.status_code = status_code
        super().__init__(message)


def get_table():
    # Lambda provides boto3; local tests inject a table and need no AWS credentials.
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["ALERT_STATE_TABLE"])


def _json_number(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def _response(status, body, request_id):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "x-request-id": request_id,
        },
        "body": json.dumps(body, default=_json_number, separators=(",", ":")),
    }


def _timestamp(value, name):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.microsecond:
            raise ValueError
        epoch = int(parsed.timestamp())
        if epoch < 0:
            raise ValueError
        return epoch
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise RequestError(
            400, f"{name} must be an ISO 8601 timestamp with timezone and whole seconds"
        ) from exc


def _iso(epoch):
    return (
        datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _encode_cursor(scope, start, end, key):
    payload = {"version": 1, "scope": scope, "start": start, "end": end, "key": key}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _decode_cursor(token, scope):
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            raise ValueError
        raw = base64.b64decode(
            token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(raw)
        if payload["version"] != 1 or payload["scope"] != scope:
            raise ValueError
        start, end, key = payload["start"], payload["end"], payload["key"]
        if type(start) is not int or type(end) is not int or not 0 <= start <= end:
            raise ValueError
        if set(key) != CURSOR_KEYS or not all(isinstance(v, str) for v in key.values()):
            raise ValueError
        if key["GSI1PK"] != f"DEVICE#{scope['device_id']}" or key["SK"] != "DATA":
            raise ValueError
        epoch, reading_id = key["GSI1SK"].split("#", 1)
        if not re.fullmatch(r"[0-9]{20}", epoch) or not start <= int(epoch) <= end:
            raise ValueError
        if not 1 <= len(reading_id) <= 128 or key["PK"] != f"READING#{reading_id}":
            raise ValueError
        # A cursor may resume only the same device, route and requested time window.
        if scope["from"] is not None and _timestamp(scope["from"], "from") != start:
            raise ValueError
        if scope["to"] is not None and _timestamp(scope["to"], "to") != end:
            raise ValueError
        _iso(start)
        _iso(end)
        return start, end, key
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        UnicodeDecodeError,
        binascii.Error,
    ) as exc:
        raise RequestError(
            400, "next_token is invalid or belongs to another query"
        ) from exc


def _query_args(device_id, now):
    return {
        "IndexName": "DeviceTimeIndex",
        "KeyConditionExpression": "GSI1PK = :device",
        "FilterExpression": "attribute_not_exists(expires_at) OR expires_at > :now",
        "ExpressionAttributeValues": {":device": f"DEVICE#{device_id}", ":now": now},
        "ScanIndexForward": False,
    }


def _public_reading(item):
    evaluations = item.get("evaluations", [])
    history = item.get("alert_history", {})
    alerts = [
        {
            **result,
            "notification_status": history.get(result["metric"], {}).get("status"),
        }
        for result in evaluations
        if result["level"] in ("warning", "critical")
    ]
    return {
        "reading": item["reading"],
        "evaluations": evaluations,
        "overall_status": max(
            (result["level"] for result in evaluations),
            key=lambda level: LEVEL_RANK.get(level, -1),
            default="unknown",
        ),
        "alerts": alerts,
        "is_late": bool(item.get("is_late", False)),
        "measured_at_epoch": item["measured_at_epoch"],
        "processing_status": item.get("processing_status", "UNKNOWN"),
        "updated_at": item.get("updated_at"),
        "completed_at_ms": item.get("completed_at_ms"),
    }


def _latest(table, device_id, now):
    args = _query_args(device_id, now)
    args["Limit"] = 100
    # DynamoDB can return an empty page with a continuation key after TTL filtering.
    for _ in range(5):
        page = table.query(**args)
        if page.get("Items"):
            item = page["Items"][0]
            age = max(0, now - int(item["measured_at_epoch"]))
            return {
                "device_id": device_id,
                "data": _public_reading(item),
                "age_seconds": age,
                "is_stale": age > int(os.getenv("DATA_STALE_SECONDS", "300")),
            }
        key = page.get("LastEvaluatedKey")
        if not key:
            raise RequestError(404, "No unexpired readings found for this device")
        args["ExclusiveStartKey"] = key
    raise RequestError(
        503, "Latest reading lookup exceeded its page budget; retry later"
    )


def _list_readings(table_factory, device_id, view, params, now):
    try:
        limit = int(params.get("limit", "50"))
        if not 1 <= limit <= 100:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise RequestError(400, "limit must be an integer between 1 and 100") from exc

    scope = {
        "device_id": device_id,
        "view": view,
        "from": params.get("from"),
        "to": params.get("to"),
    }
    key = None
    if "next_token" in params:
        start, end, key = _decode_cursor(params["next_token"], scope)
    else:
        end = _timestamp(params["to"], "to") if "to" in params else now
        start = (
            _timestamp(params["from"], "from")
            if "from" in params
            else max(0, end - 86400)
        )
        if start > end:
            raise RequestError(400, "from must not be after to")

    args = _query_args(device_id, now)
    args["KeyConditionExpression"] += " AND GSI1SK BETWEEN :start AND :end"
    args["ExpressionAttributeValues"].update(
        {
            ":start": f"{start:020d}#",
            # The next second's prefix includes every ID in the inclusive final second.
            ":end": f"{end + 1:020d}#",
        }
    )
    args["Limit"] = limit
    if key:
        args["ExclusiveStartKey"] = key
    page = table_factory().query(**args)
    items = [_public_reading(item) for item in page.get("Items", [])]
    if view == "alerts":
        items = [item for item in items if item["alerts"]]
    next_key = page.get("LastEvaluatedKey")
    return {
        "device_id": device_id,
        "from": _iso(start),
        "to": _iso(end),
        "items": items,
        "count": len(items),
        "next_token": _encode_cursor(scope, start, end, next_key) if next_key else None,
    }


def lambda_handler(event, context):
    started = time.perf_counter()
    request_context = event.get("requestContext") or {}
    request_id = request_context.get("requestId") or getattr(
        context, "aws_request_id", "unknown"
    )
    try:
        method = (request_context.get("http") or {}).get("method", "GET")
        if method != "GET":
            raise RequestError(405, "Only GET is supported")
        view = ROUTES.get(event.get("routeKey"))
        if view is None:
            raise RequestError(404, "Unknown query route")
        device_id = (event.get("pathParameters") or {}).get("device_id", "")
        if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise RequestError(
                400, "device_id must match the ingestion device ID format"
            )
        params = event.get("queryStringParameters") or {}
        allowed = set() if view == "latest" else {"from", "to", "limit", "next_token"}
        if set(params) - allowed:
            raise RequestError(400, "Unsupported query parameters")
        now = int(time.time())
        # Validate parameters before creating an AWS client or reading DynamoDB.
        if view == "latest":
            body = _latest(get_table(), device_id, now)
        else:
            body = _list_readings(get_table, device_id, view, params, now)
        emit("dashboard_query_completed", request_id=request_id, device_id=device_id, view=view, status_code=200, count=body.get("count", 1), duration_ms=round((time.perf_counter() - started) * 1000, 3))
        return _response(200, body, request_id)
    except RequestError as exc:
        emit("dashboard_query_rejected", request_id=request_id, status_code=exc.status_code)
        return _response(
            exc.status_code, {"message": str(exc), "request_id": request_id}, request_id
        )
    except Exception as exc:
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        print(
            json.dumps(
                {
                    "event": "dashboard_query_failed",
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                    "error_code": error_code,
                }
            )
        )
        return _response(
            503,
            {
                "message": "Reading data is temporarily unavailable",
                "request_id": request_id,
            },
            request_id,
        )
