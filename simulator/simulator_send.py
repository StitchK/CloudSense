#!/usr/bin/env python3
"""Send a repeatable normal, warning, and critical alarm demonstration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

try:
    from .send_config import prepare_reading_for_send, resolve_api_url
    from .simulator import ReadingSimulator, send_reading, validate_reading
except ImportError:
    from send_config import prepare_reading_for_send, resolve_api_url
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
            "readings from the dashboard demonstration device."
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
        "--device-id",
        default="device-001",
        help="Device monitored by the dashboard (default: device-001).",
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


def generate_demo_readings(
    seed: int,
    device_id: str,
    normal_interval_seconds: float,
    critical_interval_seconds: float,
) -> list[tuple[str, dict]]:
    """Generate the full demonstration sequence without sending it."""
    start_time = datetime.now(timezone.utc)
    normal_interval_seconds = max(1.0, normal_interval_seconds)
    critical_interval_seconds = max(1.0, critical_interval_seconds)

    normal_readings = ReadingSimulator(
        seed=seed,
        start_time=start_time,
    ).generate_batch(
        count=NORMAL_COUNT,
        device_count=1,
        scenario="normal",
        interval_seconds=normal_interval_seconds,
        device_id=device_id,
    )
    warning_reading = ReadingSimulator(
        seed=seed + 1,
        start_time=start_time + timedelta(seconds=NORMAL_COUNT * normal_interval_seconds),
    ).generate_batch(
        count=1,
        scenario="warning",
        metric="blood_pressure",
        device_id=device_id,
    )[0]
    critical_readings = ReadingSimulator(
        seed=seed + 2,
        start_time=start_time + timedelta(seconds=(NORMAL_COUNT + 1) * normal_interval_seconds),
    ).generate_batch(
        count=CRITICAL_COUNT,
        scenario="critical",
        interval_seconds=critical_interval_seconds,
        metric="blood_pressure",
        device_id=device_id,
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
        reading = prepare_reading_for_send(reading)
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
        time.sleep(max(1.0, delay))

    print("\nSequence complete.")
    print("Notification delivery depends on the device's existing alert state and cooldown.")
    print("Critical notifications require consecutive critical readings.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        readings = generate_demo_readings(
            seed=args.seed,
            device_id=args.device_id,
            normal_interval_seconds=args.interval_seconds,
            critical_interval_seconds=args.critical_interval_seconds,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

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

    print(f"Dashboard device: {args.device_id}")
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
