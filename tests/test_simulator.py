from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CLOUDSENSE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLOUDSENSE_ROOT))

from simulator.simulator import (  # noqa: E402
    ACTIVITY_TYPES,
    METRIC_TYPES,
    ReadingSimulator,
    run_auto_mode,
    run_interactive_mode,
    send_reading,
    validate_reading,
)


START_TIME = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)


def has_critical_metric(reading):
    blood_pressure = reading["blood_pressure"]
    return any(
        (
            reading["heart_rate_bpm"] < 45 or reading["heart_rate_bpm"] > 120,
            reading["body_temperature_c"] < 35.0
            or reading["body_temperature_c"] >= 38.0,
            reading["spo2_pct"] < 92,
            blood_pressure["systolic"] > 180,
            blood_pressure["diastolic"] > 120,
        )
    )


def has_warning_metric(reading):
    blood_pressure = reading["blood_pressure"]
    return any(
        (
            45 <= reading["heart_rate_bpm"] <= 59
            or 101 <= reading["heart_rate_bpm"] <= 120,
            35.0 <= reading["body_temperature_c"] <= 36.0
            or 37.5 <= reading["body_temperature_c"] < 38.0,
            92 <= reading["spo2_pct"] <= 94,
            131 <= blood_pressure["systolic"] <= 180,
            86 <= blood_pressure["diastolic"] <= 120,
        )
    )


def classify_reading(reading):
    if has_critical_metric(reading):
        return "critical"
    if has_warning_metric(reading):
        return "warning"
    return "normal"


class FakeHTTPResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._body


def print_example_readings():
    """Print one normal, one warning, and one critical example."""
    simulator = ReadingSimulator(seed=42, start_time=START_TIME)
    examples = simulator.generate_batch(
        count=4,
        device_count=3,
        scenario="mixed",
    )

    print("Generated CloudSense examples")
    print("=" * 32)
    for index, reading in enumerate(examples, start=1):
        print(
            f"\nExample {index}: {classify_reading(reading).upper()}"
        )
        print(json.dumps(reading, ensure_ascii=False, indent=2))
        validate_reading(reading)


class ReadingSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.simulator = ReadingSimulator(seed=42, start_time=START_TIME)

    def test_normal_readings_are_valid(self):
        readings = self.simulator.generate_batch(
            count=10,
            device_count=3,
            scenario="normal",
        )

        self.assertEqual(len(readings), 10)
        for reading in readings:
            validate_reading(reading)
            self.assertFalse(has_warning_metric(reading))
            self.assertFalse(has_critical_metric(reading))
            self.assertIn(reading["activity"], ACTIVITY_TYPES)
            self.assertTrue(reading["timestamp"].endswith("Z"))

    def test_warning_readings_are_valid_and_warning(self):
        readings = self.simulator.generate_batch(
            count=12,
            scenario="warning",
        )

        for reading in readings:
            validate_reading(reading)
            self.assertTrue(has_warning_metric(reading))
            self.assertFalse(has_critical_metric(reading))

    def test_critical_readings_are_valid_and_critical(self):
        readings = self.simulator.generate_batch(
            count=12,
            scenario="critical",
        )

        for reading in readings:
            validate_reading(reading)
            self.assertTrue(has_critical_metric(reading))

    def test_mixed_scenario_contains_all_severities(self):
        readings = self.simulator.generate_batch(
            count=12,
            scenario="mixed",
        )

        normal = [
            reading
            for reading in readings
            if not has_warning_metric(reading) and not has_critical_metric(reading)
        ]
        warning = [
            reading
            for reading in readings
            if has_warning_metric(reading) and not has_critical_metric(reading)
        ]
        critical = [reading for reading in readings if has_critical_metric(reading)]

        self.assertTrue(normal)
        self.assertTrue(warning)
        self.assertTrue(critical)

    def test_duplicate_scenario_repeats_the_same_reading(self):
        readings = self.simulator.generate_batch(
            count=3,
            scenario="duplicate",
        )

        self.assertEqual(readings[0], readings[1])
        self.assertEqual(readings[0], readings[2])

    def test_reading_ids_are_unique_for_non_duplicate_data(self):
        readings = self.simulator.generate_batch(
            count=100,
            scenario="mixed",
        )
        reading_ids = [reading["reading_id"] for reading in readings]

        self.assertEqual(len(reading_ids), len(set(reading_ids)))

    def test_same_seed_and_start_time_are_reproducible(self):
        first = ReadingSimulator(seed=7, start_time=START_TIME).generate_batch(
            count=5,
            scenario="mixed",
        )
        second = ReadingSimulator(seed=7, start_time=START_TIME).generate_batch(
            count=5,
            scenario="mixed",
        )

        self.assertEqual(first, second)

    def test_invalid_reading_is_rejected(self):
        reading = self.simulator.generate_batch(count=1)[0]
        del reading["blood_pressure"]["diastolic"]

        with self.assertRaises(ValueError):
            validate_reading(reading)

    def test_explicit_critical_metric_is_applied(self):
        for metric in METRIC_TYPES:
            with self.subTest(metric=metric):
                reading = self.simulator.generate_batch(
                    count=1,
                    scenario="critical",
                    metric=metric,
                )[0]
                validate_reading(reading)

                blood_pressure = reading["blood_pressure"]
                actual_critical = {
                    "heart_rate": (
                        reading["heart_rate_bpm"] < 45
                        or reading["heart_rate_bpm"] > 120
                    ),
                    "temperature": (
                        reading["body_temperature_c"] < 35.0
                        or reading["body_temperature_c"] >= 38.0
                    ),
                    "spo2": reading["spo2_pct"] < 92,
                    "blood_pressure": (
                        blood_pressure["systolic"] > 180
                        or blood_pressure["diastolic"] > 120
                    ),
                }
                self.assertTrue(actual_critical[metric])

    def test_send_reading_posts_json_to_api_gateway(self):
        reading = self.simulator.generate_batch(count=1)[0]
        response = FakeHTTPResponse(202, '{"message":"accepted"}')

        with patch("simulator.simulator.urlopen", return_value=response) as mocked:
            result = send_reading(
                api_url="https://example.execute-api.us-east-1.amazonaws.com/readings",
                reading=reading,
                api_key="test-key",
                timeout=5,
                retries=0,
            )

        request = mocked.call_args.args[0]
        sent_payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        self.assertEqual(sent_payload, reading)
        self.assertEqual(result["status_code"], 202)

    def test_auto_mode_can_send_readings(self):
        args = SimpleNamespace(
            send=True,
            api_url="https://example.execute-api.us-east-1.amazonaws.com/readings",
            api_key=None,
            timeout=5,
            retries=0,
            seed=42,
            start_time=START_TIME,
            count=2,
            devices=1,
            scenario="normal",
            interval_seconds=0,
            metric=None,
            device="dev-001",
            output=None,
            pretty=False,
        )

        with patch(
            "simulator.simulator.send_reading",
            return_value={"status_code": 202, "body": "", "attempts": 1},
        ) as mocked:
            with redirect_stdout(StringIO()):
                result = run_auto_mode(args)

        self.assertEqual(result, 0)
        self.assertEqual(mocked.call_count, 2)

    def test_interactive_mode_accepts_normal_and_critical_commands(self):
        args = SimpleNamespace(
            send=False,
            api_url=None,
            seed=42,
            device="dev-001",
            pretty=False,
        )
        output = StringIO()

        with patch("builtins.input", side_effect=["n", "ch", "q"]):
            with redirect_stdout(output):
                result = run_interactive_mode(args)

        self.assertEqual(result, 0)
        self.assertIn('"device_id": "dev-001"', output.getvalue())
        self.assertIn('"heart_rate_bpm"', output.getvalue())


if __name__ == "__main__":
    print_example_readings()
    print("\nRunning simulator unit tests...\n")
    sys.stdout.flush()
    unittest.main()
