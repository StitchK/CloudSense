import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common.reading_store import (  # noqa: E402
    finish_reading,
    save_reading,
    update_alert_history,
)


def test_save_reading_stores_full_payload_classifications_and_dashboard_keys():
    table = Mock()
    reading = {
        "device_id": "device-1",
        "reading_id": "reading-1",
        "timestamp": "2026-10-30T12:00:00Z",
        "_timestamp_epoch": 1793361600,
        "body_temperature_c": 36.9,
        "activity": "resting",
        "blood_pressure": {"systolic": 120, "diastolic": 80},
    }
    results = [{"metric": "heart_rate_bpm", "level": "normal", "message": "Normal"}]

    save_reading(table, reading, results, False, 1793361600, 86400)

    call = table.update_item.call_args.kwargs
    assert call["Key"] == {"PK": "READING#reading-1", "SK": "DATA"}
    values = call["ExpressionAttributeValues"]
    assert values[":reading"]["activity"] == "resting"
    assert values[":reading"]["body_temperature_c"] == Decimal("36.9")
    assert values[":evaluations"] == results
    assert values[":device_key"] == "DEVICE#device-1"
    assert values[":time_key"] == "00000000001793361600#reading-1"


def test_update_alert_history_and_finish_reading_write_status():
    table = Mock()
    result = {
        "metric": "spo2_pct",
        "level": "critical",
        "message": "Blood oxygen low",
    }

    update_alert_history(table, "reading-1", result, "CRITICAL_PENDING", 1000)
    finish_reading(table, "reading-1", "COMPLETE", 1001)

    assert table.update_item.call_count == 2
    assert (
        table.update_item.call_args.kwargs["ExpressionAttributeValues"][":status"]
        == "COMPLETE"
    )
