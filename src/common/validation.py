"""Validation and normalization for CloudSense readings."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


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

ALLOWED_ACTIVITIES = {
    "rest",
    "walking",
    "running",
    "sleeping",
}

DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")

MAX_FUTURE_SECONDS = 300
LATE_THRESHOLD_SECONDS = 300


class ReadingValidationError(ValueError):
    """Raised when a reading fails server-side validation."""

    def __init__(self, errors: Dict[str, str]) -> None:
        self.errors = errors
        super().__init__("reading validation failed")


@dataclass(frozen=True)
class ValidationResult:
    """Normalized reading plus server-side ingest metadata."""

    reading: Dict[str, Any]
    is_late: bool
    ingest_age_seconds: int


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty string")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp must be valid ISO-8601") from exc

    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")

    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def validate_reading(
    reading: Any,
    now: Optional[datetime] = None,
) -> ValidationResult:
    """Validate a reading and return a normalized copy."""
    errors: Dict[str, str] = {}

    if not isinstance(reading, dict):
        raise ReadingValidationError(
            {"body": "reading must be a JSON object"}
        )

    missing = sorted(REQUIRED_FIELDS.difference(reading))
    if missing:
        for field in missing:
            errors[field] = "field is required"

    normalized: Dict[str, Any] = dict(reading)

    device_id = reading.get("device_id")
    if isinstance(device_id, str):
        device_id = device_id.strip()
        normalized["device_id"] = device_id
    if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.fullmatch(
        device_id
    ):
        errors["device_id"] = (
            "must match [A-Za-z0-9][A-Za-z0-9_-]{2,63}"
        )

    reading_id = reading.get("reading_id")
    if isinstance(reading_id, str):
        reading_id = reading_id.strip()
        normalized["reading_id"] = reading_id
    if not isinstance(reading_id, str) or not reading_id:
        errors["reading_id"] = "must be a non-empty string"
    elif len(reading_id) > 128:
        errors["reading_id"] = "must be at most 128 characters"

    parsed_timestamp: Optional[datetime] = None
    try:
        parsed_timestamp = _parse_timestamp(reading.get("timestamp"))
        normalized["timestamp"] = _format_timestamp(parsed_timestamp)
    except ValueError as exc:
        errors["timestamp"] = str(exc)

    heart_rate = reading.get("heart_rate_bpm")
    if type(heart_rate) is not int:
        errors["heart_rate_bpm"] = "must be an integer"
    elif not 20 <= heart_rate <= 250:
        errors["heart_rate_bpm"] = "must be between 20 and 250"

    temperature = reading.get("body_temperature_c")
    if not _is_number(temperature) or not math.isfinite(float(temperature)):
        errors["body_temperature_c"] = "must be a finite number"
    elif not 30.0 <= float(temperature) <= 45.0:
        errors["body_temperature_c"] = "must be between 30.0 and 45.0"

    spo2 = reading.get("spo2_pct")
    if type(spo2) is not int:
        errors["spo2_pct"] = "must be an integer"
    elif not 0 <= spo2 <= 100:
        errors["spo2_pct"] = "must be between 0 and 100"

    blood_pressure = reading.get("blood_pressure")
    if not isinstance(blood_pressure, dict):
        errors["blood_pressure"] = "must be an object"
    else:
        normalized_pressure = dict(blood_pressure)
        normalized["blood_pressure"] = normalized_pressure

        systolic = blood_pressure.get("systolic")
        diastolic = blood_pressure.get("diastolic")

        if type(systolic) is not int:
            errors["blood_pressure.systolic"] = "must be an integer"
        elif not 50 <= systolic <= 260:
            errors[
                "blood_pressure.systolic"
            ] = "must be between 50 and 260"

        if type(diastolic) is not int:
            errors["blood_pressure.diastolic"] = "must be an integer"
        elif not 30 <= diastolic <= 180:
            errors[
                "blood_pressure.diastolic"
            ] = "must be between 30 and 180"

        if (
            type(systolic) is int
            and type(diastolic) is int
            and systolic <= diastolic
        ):
            errors["blood_pressure"] = (
                "systolic must be greater than diastolic"
            )

    activity = reading.get("activity")
    if activity not in ALLOWED_ACTIVITIES:
        errors["activity"] = (
            "must be one of: " + ", ".join(sorted(ALLOWED_ACTIVITIES))
        )

    if parsed_timestamp is not None:
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        if parsed_timestamp > current_time + timedelta(
            seconds=MAX_FUTURE_SECONDS
        ):
            errors["timestamp"] = "must not be more than 5 minutes in the future"

        ingest_age_seconds = max(
            0,
            int((current_time - parsed_timestamp).total_seconds()),
        )
    else:
        ingest_age_seconds = 0

    if errors:
        raise ReadingValidationError(errors)

    return ValidationResult(
        reading=normalized,
        is_late=ingest_age_seconds > LATE_THRESHOLD_SECONDS,
        ingest_age_seconds=ingest_age_seconds,
    )
