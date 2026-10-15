#!/usr/bin/env python3
"""Generate synthetic CloudSense health readings without sending them to AWS."""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ACTIVITY_TYPES = ("rest", "walking", "running", "sleeping")
SCENARIOS = ("normal", "warning", "critical", "mixed", "duplicate")
METRIC_TYPES = ("heart_rate", "temperature", "spo2", "blood_pressure")
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}

# 映射成带上单位的, 因为json的字段名得带单位, 不然不清楚单位需要额外的单位名文档
METRIC_TO_FIELD = {
    "heart_rate": "heart_rate_bpm",
    "temperature": "body_temperature_c",
    "spo2": "spo2_pct",
}

# Normal, Warning和Critical三个情况的随机生成模拟数范围
NORMAL_RANGES = {
    "heart_rate_bpm": (60, 100),
    "body_temperature_c": (36.1, 37.4),
    "spo2_pct": (95, 100),
    "systolic": (90, 130),
    "diastolic": (60, 85),
}

WARNING_RANGES = {
    "heart_rate_bpm": ((45, 59), (101, 120)),
    "body_temperature_c": ((35.0, 36.0), (37.5, 37.9)),
    "spo2_pct": ((92, 94),),
    "systolic": ((131, 180),),
    "diastolic": ((86, 119),),
}

CRITICAL_RANGES = {
    "heart_rate_bpm": ((35, 44), (121, 160)),
    "body_temperature_c": ((34.0, 34.9), (38.0, 39.5)),
    "spo2_pct": ((85, 91),),
    "systolic": ((181, 220),),
    "diastolic": ((121, 150),),
}

# 禁止设备名字以-或_开头
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")

# 将时间字符串解析成带时区的datetime, 并且转换为UTC
def parse_utc_datetime(value: str) -> datetime:
    """Parse an ISO-8601 value and normalize it to UTC."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid ISO-8601 datetime: {value!r}"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

# 将datetime转成UTC时间字符串
def format_utc_timestamp(value: datetime) -> str:
    """Return a second-precision ISO-8601 UTC timestamp ending in Z."""
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

# 判断数值是不是int或者float类型
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

# 校验函数, 判断数据是否符合协议
def validate_reading(reading: Dict[str, Any]) -> None:
    """Raise ValueError when a generated reading does not match the contract."""
    errors: List[str] = []

    required_fields = {
        "device_id",
        "reading_id",
        "timestamp",
        "heart_rate_bpm",
        "body_temperature_c",
        "spo2_pct",
        "blood_pressure",
        "activity",
    }
    missing = sorted(required_fields.difference(reading))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")

    device_id = reading.get("device_id")
    if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.fullmatch(device_id):
        errors.append("device_id must match [A-Za-z0-9][A-Za-z0-9_-]{2,63}")

    reading_id = reading.get("reading_id")
    if not isinstance(reading_id, str) or not reading_id.strip():
        errors.append("reading_id must be a non-empty string")

    timestamp = reading.get("timestamp")
    if not isinstance(timestamp, str):
        errors.append("timestamp must be an ISO-8601 string")
    else:
        try:
            parsed_timestamp = parse_utc_datetime(timestamp)
            if parsed_timestamp.tzinfo is None:
                errors.append("timestamp must include a timezone")
        except argparse.ArgumentTypeError as exc:
            errors.append(str(exc))

    heart_rate = reading.get("heart_rate_bpm")
    if type(heart_rate) is not int or not 20 <= heart_rate <= 250:
        errors.append("heart_rate_bpm must be an integer between 20 and 250")

    temperature = reading.get("body_temperature_c")
    if not _is_number(temperature) or not 30.0 <= float(temperature) <= 45.0:
        errors.append("body_temperature_c must be between 30.0 and 45.0")

    spo2 = reading.get("spo2_pct")
    if type(spo2) is not int or not 0 <= spo2 <= 100:
        errors.append("spo2_pct must be an integer between 0 and 100")

    blood_pressure = reading.get("blood_pressure")
    if not isinstance(blood_pressure, dict):
        errors.append("blood_pressure must be an object")
    else:
        systolic = blood_pressure.get("systolic")
        diastolic = blood_pressure.get("diastolic")
        if type(systolic) is not int or not 50 <= systolic <= 260:
            errors.append("blood_pressure.systolic must be between 50 and 260")
        if type(diastolic) is not int or not 30 <= diastolic <= 180:
            errors.append("blood_pressure.diastolic must be between 30 and 180")
        if (
            type(systolic) is int
            and type(diastolic) is int
            and systolic <= diastolic
        ):
            errors.append("blood_pressure.systolic must be greater than diastolic")

    activity = reading.get("activity")
    if activity not in ACTIVITY_TYPES:
        errors.append(f"activity must be one of: {', '.join(ACTIVITY_TYPES)}")

    if errors:
        raise ValueError("; ".join(errors))


class ReadingSimulator:
    """Deterministically generate valid normal and abnormal readings."""

    # 把时区问题在初始化的时候就先解决
    def __init__(
        self,
        seed: int = 42,
        start_time: Optional[datetime] = None,
    ) -> None:
        self._random = random.Random(seed)
        self._seed = seed
        self._start_time = start_time or datetime.now(timezone.utc)
        if self._start_time.tzinfo is None:
            self._start_time = self._start_time.replace(tzinfo=timezone.utc)
        self._start_time = self._start_time.astimezone(timezone.utc)

    # 生成数据的参数校验
    def generate_batch(
        self,
        count: int,
        device_count: int = 3,
        scenario: str = "normal",
        interval_seconds: float = 5.0,
        metric: Optional[str] = None,
        device_id: Optional[str] = None,
        sequence_offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Generate a list of readings using the requested scenario."""
        if count < 1:
            raise ValueError("count must be at least 1")
        if device_count < 1:
            raise ValueError("device_count must be at least 1")
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of: {', '.join(SCENARIOS)}")
        if metric is not None and metric not in METRIC_TYPES:
            raise ValueError(f"metric must be one of: {', '.join(METRIC_TYPES)}")
        if device_id is not None and not DEVICE_ID_PATTERN.fullmatch(device_id):
            raise ValueError(
                "device_id must match [A-Za-z0-9][A-Za-z0-9_-]{2,63}"
            )
        if interval_seconds < 0:
            raise ValueError("interval_seconds cannot be negative")
        if sequence_offset < 0:
            raise ValueError("sequence_offset cannot be negative")

        readings: List[Dict[str, Any]] = [] # 最终返回的列表
        first_reading: Optional[Dict[str, Any]] = None

        for index in range(count):
            if device_id is None:
                device_number = (index % device_count) + 1
                current_device_id = f"dev-{device_number:03d}" # 设备id都包含三个数字, 比如 dev-001
            else:
                current_device_id = device_id
            sequence = sequence_offset + index
            measured_at = self._start_time + timedelta(
                seconds=sequence * interval_seconds
            )
            reading_scenario = self._scenario_for_index(scenario, index)
            reading = self._build_reading(
                device_id=current_device_id,
                measured_at=measured_at,
                scenario=reading_scenario,
                sequence=sequence,
                metric=metric,
            )

            if first_reading is None:
                first_reading = copy.deepcopy(reading)

            if scenario == "duplicate":
                reading = copy.deepcopy(first_reading)

            validate_reading(reading)
            readings.append(reading)

        return readings

    def _scenario_for_index(self, scenario: str, index: int) -> str:
        if scenario == "mixed":
            pattern = ("normal", "normal", "warning", "critical")
            return pattern[index % len(pattern)]
        if scenario == "duplicate":
            return "normal"
        return scenario

    def _build_reading(
        self,
        device_id: str,
        measured_at: datetime,
        scenario: str,
        sequence: int,
        metric: Optional[str],
    ) -> Dict[str, Any]:
        values = self._normal_values()

        if scenario == "warning":
            self._apply_warning(values, metric)
        elif scenario == "critical":
            self._apply_critical(values, metric)
        elif scenario != "normal":
            raise ValueError(f"unsupported reading scenario: {scenario}")

        timestamp = format_utc_timestamp(measured_at)
        reading_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"cloudsense:{self._seed}:{device_id}:{sequence}:{timestamp}",
            )
        )

        return {
            "device_id": device_id,
            "reading_id": reading_id,
            "timestamp": timestamp,
            "heart_rate_bpm": values["heart_rate_bpm"],
            "body_temperature_c": values["body_temperature_c"],
            "spo2_pct": values["spo2_pct"],
            "blood_pressure": {
                "systolic": values["systolic"],
                "diastolic": values["diastolic"],
            },
            "activity": self._random.choice(ACTIVITY_TYPES),
        }

    # 生成正常数据
    def _normal_values(self) -> Dict[str, Any]:
        return {
            "heart_rate_bpm": self._random.randint(*NORMAL_RANGES["heart_rate_bpm"]),
            "body_temperature_c": round(
                self._random.uniform(*NORMAL_RANGES["body_temperature_c"]),
                1,
            ),
            "spo2_pct": self._random.randint(*NORMAL_RANGES["spo2_pct"]),
            "systolic": self._random.randint(*NORMAL_RANGES["systolic"]),
            "diastolic": self._random.randint(*NORMAL_RANGES["diastolic"]),
        }

    # 生成警告数据
    def _apply_warning(
        self,
        values: Dict[str, Any],
        metric: Optional[str],
    ) -> None:
        metric = self._select_metric(metric)

        if metric == "blood_pressure":
            metric = self._random.choice(("systolic", "diastolic"))
        else:
            metric = METRIC_TO_FIELD[metric]

        if metric in ("heart_rate_bpm", "body_temperature_c"):
            values[metric] = self._choose_warning_value(metric)
        elif metric == "spo2_pct":
            values[metric] = self._random.randint(*WARNING_RANGES[metric][0])
        elif metric == "systolic":
            values[metric] = self._random.randint(*WARNING_RANGES[metric][0])
            values["diastolic"] = self._random.randint(
                NORMAL_RANGES["diastolic"][0],
                min(NORMAL_RANGES["diastolic"][1], values[metric] - 1),
            )
        else:
            values[metric] = self._random.randint(*WARNING_RANGES[metric][0])
            values["systolic"] = self._random.randint(
                max(NORMAL_RANGES["systolic"][0], values[metric] + 1),
                NORMAL_RANGES["systolic"][1],
            )

    # 生成严重数据
    def _apply_critical(
        self,
        values: Dict[str, Any],
        metric: Optional[str],
    ) -> None:
        metric = self._select_metric(metric)

        if metric == "blood_pressure":
            metric = self._random.choice(("systolic", "diastolic"))
        else:
            metric = METRIC_TO_FIELD[metric]

        if metric in ("heart_rate_bpm", "body_temperature_c"):
            values[metric] = self._choose_critical_value(metric)
        elif metric == "spo2_pct":
            values[metric] = self._random.randint(*CRITICAL_RANGES[metric][0])
        elif metric == "systolic":
            values[metric] = self._random.randint(*CRITICAL_RANGES[metric][0])
            values["diastolic"] = self._random.randint(
                NORMAL_RANGES["diastolic"][0],
                min(NORMAL_RANGES["diastolic"][1], values[metric] - 1),
            )
        else:
            values[metric] = self._random.randint(*CRITICAL_RANGES[metric][0])
            values["systolic"] = self._random.randint(
                max(150, values[metric] + 1),
                min(180, 220),
            )

    # 选择指标
    def _select_metric(self, metric: Optional[str]) -> str:
        if metric is None:
            return self._random.choice(METRIC_TYPES)
        if metric not in METRIC_TYPES:
            raise ValueError(f"metric must be one of: {', '.join(METRIC_TYPES)}")
        return metric

    # 双区间随机选一个
    def _choose_warning_value(self, metric: str) -> Any:
        low_range, high_range = WARNING_RANGES[metric]
        selected_range = self._random.choice((low_range, high_range))
        return self._value_from_range(metric, selected_range)

    def _choose_critical_value(self, metric: str) -> Any:
        low_range, high_range = CRITICAL_RANGES[metric]
        selected_range = self._random.choice((low_range, high_range))
        return self._value_from_range(metric, selected_range)

    # 根据指标名判断生成的数据应该是int还是float
    def _value_from_range(
        self,
        metric: str,
        selected_range: Sequence[float],
    ) -> Any:
        if metric == "body_temperature_c":
            return round(self._random.uniform(*selected_range), 1)
        return self._random.randint(int(selected_range[0]), int(selected_range[1]))


INTERACTIVE_COMMANDS = {
    "n": ("normal", None),
    "w": ("warning", None),
    "c": ("critical", None),
    "d": ("duplicate", None),
    "wh": ("warning", "heart_rate"),
    "wt": ("warning", "temperature"),
    "wo": ("warning", "spo2"),
    "wb": ("warning", "blood_pressure"),
    "ch": ("critical", "heart_rate"),
    "ct": ("critical", "temperature"),
    "co": ("critical", "spo2"),
    "cb": ("critical", "blood_pressure"),
}


def send_reading(
    api_url: str,
    reading: Dict[str, Any],
    api_key: Optional[str] = None,
    timeout: float = 10.0,
    retries: int = 0,
) -> Dict[str, Any]:
    """POST one reading to API Gateway and return response metadata."""
    if not api_url.startswith(("http://", "https://")):
        raise ValueError("api_url must start with http:// or https://")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if retries < 0:
        raise ValueError("retries cannot be negative")

    validate_reading(reading)
    payload = json.dumps(reading, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    for attempt in range(retries + 1):
        request = Request(
            api_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                status_code = int(response.status)
                response_body = response.read().decode("utf-8", errors="replace")
                if status_code not in (200, 201, 202, 204):
                    raise RuntimeError(
                        f"unexpected HTTP status {status_code}: {response_body}"
                    )
                return {
                    "status_code": status_code,
                    "body": response_body,
                    "attempts": attempt + 1,
                }
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in RETRYABLE_HTTP_STATUSES and attempt < retries:
                time.sleep(min(2**attempt, 5))
                continue
            raise RuntimeError(
                f"HTTP {exc.code} while sending {reading['reading_id']}: "
                f"{response_body}"
            ) from exc
        except URLError as exc:
            if attempt < retries:
                time.sleep(min(2**attempt, 5))
                continue
            raise RuntimeError(
                f"network error while sending {reading['reading_id']}: {exc.reason}"
            ) from exc

    raise RuntimeError("send_reading exhausted all attempts")


def _json_output(readings: List[Dict[str, Any]], pretty: bool) -> str:
    return json.dumps(
        readings,
        ensure_ascii=False,
        indent=2 if pretty else None,
    )


def _write_dry_run_output(
    readings: List[Dict[str, Any]],
    output_path: Optional[Path],
    pretty: bool,
) -> None:
    json_text = _json_output(readings, pretty)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_text + "\n", encoding="utf-8")
        print(
            f"Generated {len(readings)} valid reading(s): {output_path}",
            file=sys.stderr,
        )
    else:
        print(json_text)


def run_auto_mode(args: argparse.Namespace) -> int:
    """Generate a batch in auto mode and optionally send every reading."""
    if args.send and not args.api_url:
        print("error: --api-url is required when --send is used", file=sys.stderr)
        return 2

    simulator = ReadingSimulator(seed=args.seed, start_time=args.start_time)
    try:
        readings = simulator.generate_batch(
            count=args.count,
            device_count=args.devices,
            scenario=args.scenario,
            interval_seconds=args.interval_seconds,
            metric=args.metric,
            device_id=args.device,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.send:
        _write_dry_run_output(readings, args.output, args.pretty)
        return 0

    for index, reading in enumerate(readings, start=1):
        try:
            result = send_reading(
                api_url=args.api_url,
                reading=reading,
                api_key=args.api_key,
                timeout=args.timeout,
                retries=args.retries,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(
            f"[{index}/{len(readings)}] "
            f"{reading['device_id']} {reading['reading_id']} "
            f"HTTP {result['status_code']}"
        )
        if index < len(readings) and args.interval_seconds > 0:
            time.sleep(args.interval_seconds)

    return 0


def run_interactive_mode(args: argparse.Namespace) -> int:
    """Generate one reading per console command and optionally send it."""
    if args.send and not args.api_url:
        print("error: --api-url is required when --send is used", file=sys.stderr)
        return 2

    print("Commands:")
    print("  n  normal")
    print("  w  warning, random metric")
    print("  c  critical, random metric")
    print("  d  duplicate")
    print("  wh/wt/wo/wb  warning heart/temperature/oxygen/blood pressure")
    print("  ch/ct/co/cb  critical heart/temperature/oxygen/blood pressure")
    print("  q  quit")

    sequence = 0
    while True:
        try:
            command = input("Command: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if command == "q":
            return 0
        if command not in INTERACTIVE_COMMANDS:
            print("Unknown command. Use n, w, c, d, metric commands, or q.")
            continue

        scenario, metric = INTERACTIVE_COMMANDS[command]
        simulator = ReadingSimulator(
            seed=args.seed + sequence,
            start_time=datetime.now(timezone.utc),
        )
        reading = simulator.generate_batch(
            count=1,
            device_count=1,
            scenario=scenario,
            interval_seconds=0,
            metric=metric,
            device_id=args.device,
            sequence_offset=sequence,
        )[0]

        if not args.send:
            print(_json_output([reading], args.pretty))
            sequence += 1
            continue

        try:
            result = send_reading(
                api_url=args.api_url,
                reading=reading,
                api_key=args.api_key,
                timeout=args.timeout,
                retries=args.retries,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            sequence += 1
            continue

        print(
            f"{scenario.upper()} {reading['device_id']} "
            f"{reading['reading_id']} HTTP {result['status_code']}"
        )
        sequence += 1


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
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
        description="Generate valid synthetic CloudSense readings."
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "interactive"),
        default="auto",
        help="Run an automatic batch or an interactive console.",
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="normal",
        help="Data pattern for auto mode.",
    )
    parser.add_argument(
        "--metric",
        choices=METRIC_TYPES,
        default=None,
        help="Force warning/critical data to use one metric.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Use one fixed device ID instead of rotating devices.",
    )
    parser.add_argument(
        "--count",
        type=_positive_int,
        default=1,
        help="Number of readings to generate.",
    )
    parser.add_argument(
        "--devices",
        type=_positive_int,
        default=3,
        help="Number of virtual devices to rotate through.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible values.",
    )
    parser.add_argument(
        "--start-time",
        type=parse_utc_datetime,
        default=None,
        help="ISO-8601 start time. Defaults to the current UTC time.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=_non_negative_float,
        default=5.0,
        help="Timestamp interval between generated readings.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON to a file instead of standard output.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON output.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="API Gateway POST endpoint.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CLOUDSENSE_API_KEY"),
        help="Optional API Gateway API key.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually POST readings to API Gateway.",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=10.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=_non_negative_int,
        default=0,
        help="Retries for 429 and 5xx responses.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "interactive":
        return run_interactive_mode(args)
    return run_auto_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
