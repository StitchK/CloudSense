#!/usr/bin/env python3
"""Send a repeatable normal, warning, and critical alarm demonstration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

try:
    from .send_config import resolve_api_url
    from .simulator import ReadingSimulator, send_reading, validate_reading
except ImportError:
    from send_config import resolve_api_url
    from simulator import ReadingSimulator, send_reading, validate_reading


NORMAL_COUNT = 3
CRITICAL_COUNT = 2


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send 3 normal readings, 1 warning, and 2 consecutive critical "
            "readings from the same critical-test device."
        )
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("CLOUDSENSE_API_URL"),
        help="Override the environment or private local config; include /readings.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("CLOUDSENSE_API_KEY"),
        help="Optional API key. The current test API does not require one.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Base random seed for reproducible generated values.",
    )
    parser.add_argument(
        "--device-prefix",
        default="manual-demo",
        help="Prefix used for unique device IDs in this run.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=_non_negative_float,
        default=2.0,
        help="Delay between normal, warning, and first critical messages.",
    )
    parser.add_argument(
        "--critical-interval-seconds",
        type=_non_negative_float,
        default=5.0,
        help="Delay between the two critical readings.",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=10.0,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=_non_negative_int,
        default=0,
        help="Retries for network errors and retryable HTTP responses.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and print the six readings without sending them.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print readings in dry-run mode.",
    )
    return parser


def _run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{timestamp}-{uuid.uuid4().hex[:4]}"


def generate_demo_readings(
    seed: int,
    device_prefix: str,
    normal_interval_seconds: float,
    critical_interval_seconds: float,
) -> list[tuple[str, dict]]:
    """Generate the full demonstration sequence without sending it."""
    run_id = _run_id()
    normal_device = f"{device_prefix}-{run_id}-normal"
    warning_device = f"{device_prefix}-{run_id}-warning"
    critical_device = f"{device_prefix}-{run_id}-critical"

    normal_readings = ReadingSimulator(
        seed=seed,
        start_time=datetime.now(timezone.utc),
    ).generate_batch(
        count=NORMAL_COUNT,
        device_count=1,
        scenario="normal",
        interval_seconds=normal_interval_seconds,
        device_id=normal_device,
    )
    warning_reading = ReadingSimulator(
        seed=seed + 1,
        start_time=datetime.now(timezone.utc),
    ).generate_batch(
        count=1,
        scenario="warning",
        metric="blood_pressure",
        device_id=warning_device,
    )[0]
    critical_readings = ReadingSimulator(
        seed=seed + 2,
        start_time=datetime.now(timezone.utc),
    ).generate_batch(
        count=CRITICAL_COUNT,
        scenario="critical",
        interval_seconds=critical_interval_seconds,
        metric="blood_pressure",
        device_id=critical_device,
    )

    readings = [
        *(("normal", reading) for reading in normal_readings),
        ("warning", warning_reading),
        *(("critical", reading) for reading in critical_readings),
    ]
    for _, reading in readings:
        validate_reading(reading)
    return readings


def _summary(reading: dict) -> str:
    pressure = reading["blood_pressure"]
    return (
        f"{reading['device_id']} "
        f"BP={pressure['systolic']}/{pressure['diastolic']}"
    )


def send_demo(
    readings: list[tuple[str, dict]],
    api_url: str,
    api_key: Optional[str],
    timeout: float,
    retries: int,
    interval_seconds: float,
    critical_interval_seconds: float,
) -> int:
    """Send all generated readings in their intended order."""
    for index, (scenario, reading) in enumerate(readings, start=1):
        try:
            result = send_reading(
                api_url=api_url,
                reading=reading,
                api_key=api_key,
                timeout=timeout,
                retries=retries,
            )
        except (RuntimeError, ValueError) as error:
            print(f"[{index}/{len(readings)}] {scenario.upper()} failed: {error}")
            return 1

        print(
            f"[{index}/{len(readings)}] {scenario.upper():8s} "
            f"{_summary(reading)} HTTP {result['status_code']}"
        )

        if index == len(readings):
            continue

        next_scenario = readings[index][0]
        if scenario == "critical" and next_scenario == "critical":
            delay = critical_interval_seconds
        else:
            delay = interval_seconds
        if delay > 0:
            time.sleep(delay)

    print("\nSequence complete.")
    print("Expected email alerts: 1 warning and 1 critical.")
    print("The first critical should be CRITICAL_PENDING and send no email.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    readings = generate_demo_readings(
        seed=args.seed,
        device_prefix=args.device_prefix,
        normal_interval_seconds=args.interval_seconds,
        critical_interval_seconds=args.critical_interval_seconds,
    )

    if args.dry_run:
        output = [
            {"expected_level": scenario, **reading}
            for scenario, reading in readings
        ]
        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
        )
        return 0

    try:
        args.api_url = resolve_api_url(args.api_url)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return send_demo(
        readings=readings,
        api_url=args.api_url,
        api_key=args.api_key,
        timeout=args.timeout,
        retries=args.retries,
        interval_seconds=args.interval_seconds,
        critical_interval_seconds=args.critical_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
