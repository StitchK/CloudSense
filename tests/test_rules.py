import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.simulator import ReadingSimulator  # noqa: E402
from src.common.alert_rules import (  # noqa: E402
    check_blood_pressure,
    evaluate_reading_results,
)


def test_evaluate_reading_results_classifies_all_four_metrics():
    reading = {
        "heart_rate_bpm": 110,
        "body_temperature_c": 36.5,
        "spo2_pct": 89,
        "blood_pressure": {"systolic": 120, "diastolic": 80},
    }

    results = evaluate_reading_results(reading)

    assert [result["metric"] for result in results] == [
        "heart_rate_bpm",
        "body_temperature_c",
        "spo2_pct",
        "blood_pressure",
    ]
    assert [result["level"] for result in results] == [
        "warning",
        "normal",
        "critical",
        "normal",
    ]


def test_blood_pressure_low_and_high_boundaries():
    assert check_blood_pressure(90, 60) == "normal"
    assert check_blood_pressure(90, 59) == "warning"
    assert check_blood_pressure(80, 59) == "warning"
    assert check_blood_pressure(79, 50) == "critical"
    assert check_blood_pressure(90, 49) == "critical"
    assert check_blood_pressure(130, 85) == "normal"
    assert check_blood_pressure(131, 85) == "warning"
    assert check_blood_pressure(120, 86) == "warning"
    assert check_blood_pressure(180, 120) == "warning"
    assert check_blood_pressure(181, 80) == "critical"
    assert check_blood_pressure(120, 121) == "critical"


def test_simulator_low_blood_pressure_is_classified_by_process_rules():
    start = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)

    warning_reading = ReadingSimulator(
        seed=3,
        start_time=start,
    ).generate_batch(
        count=1,
        scenario="warning",
        metric="blood_pressure",
        device_id="dev-low-warning",
    )[0]
    critical_reading = ReadingSimulator(
        seed=3,
        start_time=start,
    ).generate_batch(
        count=1,
        scenario="critical",
        metric="blood_pressure",
        device_id="dev-low-critical",
    )[0]

    warning_results = {
        result["metric"]: result["level"]
        for result in evaluate_reading_results(warning_reading)
    }
    critical_results = {
        result["metric"]: result["level"]
        for result in evaluate_reading_results(critical_reading)
    }

    assert warning_reading["blood_pressure"] == {
        "systolic": 90,
        "diastolic": 59,
    }
    assert critical_reading["blood_pressure"] == {
        "systolic": 90,
        "diastolic": 49,
    }
    assert warning_results["blood_pressure"] == "warning"
    assert critical_results["blood_pressure"] == "critical"
