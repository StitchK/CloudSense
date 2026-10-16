"""API Gateway ingestion Lambda for CloudSense readings."""

from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from common.validation import ReadingValidationError, validate_reading


MAX_BODY_BYTES = 16 * 1024
SCHEMA_VERSION = "1.0"

_sqs_client = None


class RequestError(Exception):
    """A request-level error with an HTTP status code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        details: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def get_sqs_client():
    """Create the SQS client lazily so unit tests do not need boto3."""
    global _sqs_client
    if _sqs_client is None:
        import boto3

        _sqs_client = boto3.client("sqs")
    return _sqs_client


def response(
    status_code: int,
    body: Dict[str, Any],
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if request_id:
        headers["x-request-id"] = request_id

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body, separators=(",", ":")),
    }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _content_type(event: Dict[str, Any]) -> Optional[str]:
    headers = event.get("headers") or {}
    for name, value in headers.items():
        if str(name).lower() == "content-type":
            return str(value).lower()
    return None


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    content_type = _content_type(event)
    if content_type and "application/json" not in content_type:
        raise RequestError(
            415,
            "Content-Type must be application/json",
        )

    body = event.get("body")
    if body is None or body == "":
        raise RequestError(400, "request body is required")

    if isinstance(body, dict):
        raw_body = json.dumps(body).encode("utf-8")
        text = json.dumps(body)
    else:
        if event.get("isBase64Encoded"):
            if not isinstance(body, str):
                raise RequestError(400, "base64 body must be a string")
            try:
                raw_body = base64.b64decode(body, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RequestError(400, "body is not valid base64") from exc
        elif isinstance(body, bytes):
            raw_body = body
        elif isinstance(body, str):
            raw_body = body.encode("utf-8")
        else:
            raise RequestError(400, "request body must be text or JSON")

        if len(raw_body) > MAX_BODY_BYTES:
            raise RequestError(413, "request body is too large")

        try:
            text = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestError(400, "request body must be UTF-8") from exc

    if len(raw_body) > MAX_BODY_BYTES:
        raise RequestError(413, "request body is too large")

    try:
        parsed = json.loads(text, parse_constant=_reject_json_constant)
    except (TypeError, ValueError) as exc:
        raise RequestError(
            400,
            "invalid JSON",
            {"body": str(exc)},
        ) from exc

    if not isinstance(parsed, dict):
        raise RequestError(400, "reading must be a JSON object")

    return parsed


def _request_id(event: Dict[str, Any], context: Any) -> Optional[str]:
    request_context = event.get("requestContext") or {}
    return (
        request_context.get("requestId")
        or getattr(context, "aws_request_id", None)
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Validate an API Gateway reading and enqueue it for processing."""
    request_id = _request_id(event, context)

    try:
        reading = _parse_body(event)
        received_at = datetime.now(timezone.utc)
        validation = validate_reading(reading, now=received_at)
    except RequestError as exc:
        return response(
            exc.status_code,
            {"message": exc.message, "errors": exc.details},
            request_id,
        )
    except ReadingValidationError as exc:
        return response(
            400,
            {"message": "reading validation failed", "errors": exc.errors},
            request_id,
        )

    enriched = dict(validation.reading)
    enriched["received_at"] = received_at.isoformat()
    enriched["source"] = "api-gateway"
    enriched["request_id"] = request_id
    enriched["schema_version"] = SCHEMA_VERSION
    enriched["is_late"] = validation.is_late
    enriched["ingest_age_seconds"] = validation.ingest_age_seconds

    print(
        json.dumps(
            {
                "event": "reading_received",
                "device_id": enriched.get("device_id"),
                "reading_id": enriched.get("reading_id"),
                "request_id": request_id,
                "is_late": validation.is_late,
                "payload": enriched,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )

    queue_url = os.environ.get("READING_QUEUE_URL")
    if not queue_url:
        print(json.dumps({"event": "configuration_error"}))
        return response(
            503,
            {"message": "reading queue is not configured"},
            request_id,
        )

    try:
        get_sqs_client().send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(enriched, separators=(",", ":")),
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "sqs_send_failed",
                    "reading_id": enriched.get("reading_id"),
                    "error": str(exc),
                },
                separators=(",", ":"),
            )
        )
        return response(
            503,
            {"message": "failed to enqueue reading"},
            request_id,
        )

    return response(
        202,
        {
            "message": "accepted",
            "reading_id": enriched.get("reading_id"),
            "request_id": request_id,
        },
        request_id,
    )
