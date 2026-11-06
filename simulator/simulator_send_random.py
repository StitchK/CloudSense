#!/usr/bin/env python3
"""Continuously send random warning or critical demo sequences."""

from __future__ import annotations

import argparse
import json
import os
import random
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


NORMAL_AFTER_ALERT = 3


def _probability(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError(
            "warning probability must be between 0 and 1"
        )
    return parsed


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
            "Continuously send either one warning or two consecutive critical "
            "readings, followed by three normal readings. Stop with Ctrl+C."
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
        default=None,
        help="Optional seed for reproducible scenario selection.",
    )
    parser.add_argument(
        "--warning-probability",
        type=_probability,
        default=0.5,
        help="Probability of choosing warning instead of critical.",
    )
    parser.add_argument(
        "--device-prefix",
        default="random-demo",
        help="Prefix used for the unique device ID in each cycle.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=_non_negative_float,
        default=5.0,
        help="Delay between every two sent messages.",
    )
    parser.add_argument(
        "--max-cycles",
        type=_non_negative_int,
        default=0,
        help="Stop after N cycles. Zero means run until Ctrl+C.",
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
        help="Print planned messages without sleeping or sending.",
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


def _device_id(prefix: str, run_id: str, cycle: int) -> str:
    suffix = f"-{run_id}-c{cycle:04d}"
    maximum_prefix_length = max(1, 64 - len(suffix))
    return f"{prefix[:maximum_prefix_length]}{suffix}"


def _generate_reading(
    seed: int,
    scenario: str,
    device_id: str,
    sequence: int,
) -> dict:
    reading = ReadingSimulator(
        seed=seed,
        start_time=datetime.now(timezone.utc),
    ).generate_batch(
        count=1,
        scenario=scenario,
        metric="blood_pressure" if scenario != "normal" else None,
        device_id=device_id,
        sequence_offset=sequence,
    )[0]
    validate_reading(reading)
    return reading


def build_cycle(
    rng: random.Random,
    device_id: str,
    start_sequence: int,
    warning_probability: float,
) -> list[tuple[str, dict]]:
    """Build one alert/recovery cycle in memory."""
    scenario = (
        "warning"
        if rng.random() < warning_probability
        else "critical"
    )
    alert_count = 1 if scenario == "warning" else 2
    readings: list[tuple[str, dict]] = []
    sequence = start_sequence

    for index in range(alert_count):
        readings.append(
            (
                scenario,
                _generate_reading(
                    seed=rng.randrange(1_000_000_000),
                    scenario=scenario,
                    device_id=device_id,
                    sequence=sequence + index,
                ),
            )
        )

    for index in range(NORMAL_AFTER_ALERT):
        readings.append(
            (
                "normal",
                _generate_reading(
                    seed=rng.randrange(1_000_000_000),
                    scenario="normal",
                    device_id=device_id,
                    sequence=sequence + alert_count + index,
                ),
            )
        )
    return readings


def _summary(reading: dict) -> str:
    pressure = reading["blood_pressure"]
    return (
        f"{reading['device_id']} "
        f"BP={pressure['systolic']}/{pressure['diastolic']}"
    )


def _print_dry_run(
    cycle: int,
    readings: list[tuple[str, dict]],
    pretty: bool,
) -> None:
    payload = {
        "cycle": cycle,
        "readings": [
            {"expected_level": scenario, **reading}
            for scenario, reading in readings
        ],
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if pretty else None,
        )
    )


def run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        try:
            args.api_url = resolve_api_url(args.api_url)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    rng = random.Random(args.seed)
    run_id = _run_id()
    cycle = 1
    sequence = 0
    dry_run_cycles = args.max_cycles or 1

    try:
        while args.max_cycles == 0 or cycle <= args.max_cycles:
            device_id = _device_id(args.device_prefix, run_id, cycle)
            readings = build_cycle(
                rng=rng,
                device_id=device_id,
                start_sequence=sequence,
                warning_probability=args.warning_probability,
            )

            if args.dry_run:
                _print_dry_run(cycle, readings, args.pretty)
                cycle += 1
                sequence += len(readings)
                if cycle > dry_run_cycles:
                    break
                continue

            print(
                f"\nCycle {cycle}: expected {readings[0][0].upper()} "
                f"on {device_id}"
            )
            for index, (scenario, reading) in enumerate(readings, start=1):
                result = send_reading(
                    api_url=args.api_url,
                    reading=reading,
                    api_key=args.api_key,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                print(
                    f"[{index}/{len(readings)}] {scenario.upper():8s} "
                    f"{_summary(reading)} HTTP {result['status_code']}"
                )
                if index < len(readings) and args.interval_seconds > 0:
                    time.sleep(args.interval_seconds)

            cycle += 1
            sequence += len(readings)
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 0
    except (RuntimeError, ValueError) as error:
        print(f"\nSend failed: {error}", file=sys.stderr)
        return 1

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
