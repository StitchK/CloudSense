import sys
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.notification import send_alert  # noqa: E402


def test_send_alert_formats_reading_and_alert_for_sns():
    sns = Mock()
    reading = {
        "device_id": "device-1",
        "reading_id": "reading-1",
        "timestamp": "2026-10-28T12:00:00Z",
    }
    alert = {
        "metric": "spo2_pct",
        "level": "critical",
        "message": "Blood oxygen: 89%",
    }

    send_alert("topic-arn", reading, alert, sns_client=sns)

    publish = sns.publish.call_args.kwargs
    assert publish["TopicArn"] == "topic-arn"
    assert publish["Subject"] == "CloudSense CRITICAL alert"
    assert "Device: device-1" in publish["Message"]
    assert "Reading ID: reading-1" in publish["Message"]
    assert "Measured at: 2026-10-28T12:00:00Z" in publish["Message"]
    assert "Alert: Blood oxygen: 89%" in publish["Message"]
    assert publish["MessageAttributes"]["metric"]["StringValue"] == "spo2_pct"
