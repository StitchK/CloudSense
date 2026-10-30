import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.process import app  # noqa: E402


def sample_reading(reading_id="reading-1"):
    return {
        "device_id": "device-1",
        "reading_id": reading_id,
        "timestamp": "2026-10-28T12:00:00Z",
        "heart_rate_bpm": 110,
        "body_temperature_c": 38.5,
        "spo2_pct": 89,
        "blood_pressure": {"systolic": 190, "diastolic": 100},
    }


def configure_processing_mocks(monkeypatch, alerts):
    calls = {
        "sent": [],
        "saved": [],
        "progress": [],
        "released": [],
        "history": [],
        "reading": [],
        "finished": [],
    }
    monkeypatch.setattr(app, "evaluate_reading_results", lambda reading: alerts)
    monkeypatch.setattr(app, "has_reading_progress", lambda *args: False)
    monkeypatch.setattr(app, "is_reading_late", lambda *args: False)
    monkeypatch.setattr(app, "reading_timestamp_epoch", lambda timestamp: 1000)
    monkeypatch.setattr(
        app,
        "save_reading",
        lambda *args: calls["reading"].append(args[1]["reading_id"]),
    )
    monkeypatch.setattr(
        app,
        "record_reading_result",
        lambda table, device_id, metric, level, *args: {
            "status": "EVALUATED",
            "level": level,
            "critical_streak": 2 if level == "critical" else 0,
            "accepted": True,
        },
    )
    monkeypatch.setattr(app, "load_state", lambda *args: None)
    monkeypatch.setattr(app, "should_notify", lambda *args: True)
    monkeypatch.setattr(app, "claim_notification", lambda *args: "claim-token")
    monkeypatch.setattr(
        app,
        "send_alert",
        lambda topic, reading, alert: calls["sent"].append(alert["metric"]),
    )
    monkeypatch.setattr(
        app,
        "save_state",
        lambda *args: calls["saved"].append(args[2]),
    )
    monkeypatch.setattr(
        app,
        "save_reading_progress",
        lambda table, reading_id, metric, status, now, retention, **kwargs: calls[
            "progress"
        ].append((metric, status)),
    )
    monkeypatch.setattr(
        app,
        "update_reading_progress",
        lambda table, reading_id, metric, status, now: calls["progress"].append(
            (metric, status)
        ),
    )
    monkeypatch.setattr(
        app,
        "update_alert_history",
        lambda table, reading_id, result, status, now: calls["history"].append(
            (result["metric"], status)
        ),
    )
    monkeypatch.setattr(
        app,
        "finish_reading",
        lambda table, reading_id, status, now: calls["finished"].append(status),
    )
    monkeypatch.setattr(
        app,
        "release_claim",
        lambda table, device_id, metric, token: calls["released"].append(metric),
    )
    return calls


def test_process_reading_saves_each_sent_metric_and_completion(monkeypatch):
    alerts = [
        {"metric": "heart_rate_bpm", "level": "warning", "message": "HR"},
        {"metric": "spo2_pct", "level": "critical", "message": "O2"},
    ]
    calls = configure_processing_mocks(monkeypatch, alerts)

    app.process_reading(sample_reading(), object(), "topic", now=1000)

    assert calls["sent"] == ["heart_rate_bpm", "spo2_pct"]
    assert calls["saved"] == ["heart_rate_bpm", "spo2_pct"]
    assert calls["progress"] == [(app.DONE_METRIC, "COMPLETE")]
    assert calls["reading"] == ["reading-1"]
    assert calls["finished"] == ["COMPLETE"]


def test_failed_notification_releases_claim_and_does_not_mark_complete(monkeypatch):
    alert = {"metric": "spo2_pct", "level": "critical", "message": "O2"}
    calls = configure_processing_mocks(monkeypatch, [alert])
    monkeypatch.setattr(
        app,
        "send_alert",
        Mock(side_effect=RuntimeError("SNS unavailable")),
    )

    with pytest.raises(RuntimeError, match="SNS unavailable"):
        app.process_reading(sample_reading(), object(), "topic", now=1000)

    assert calls["saved"] == []
    assert calls["progress"] == [("spo2_pct", "RETRY_PENDING")]
    assert calls["released"] == ["spo2_pct"]


def test_cooldown_suppression_is_recorded_without_sending(monkeypatch):
    alert = {"metric": "spo2_pct", "level": "warning", "message": "O2"}
    calls = configure_processing_mocks(monkeypatch, [alert])
    monkeypatch.setattr(app, "should_notify", lambda *args: False)

    app.process_reading(sample_reading(), object(), "topic", now=1000)

    assert calls["sent"] == []
    assert calls["saved"] == []
    assert calls["progress"] == [
        ("spo2_pct", "SUPPRESSED"),
        (app.DONE_METRIC, "COMPLETE"),
    ]


def test_first_critical_is_recorded_without_sending(monkeypatch):
    alert = {"metric": "spo2_pct", "level": "critical", "message": "O2"}
    calls = configure_processing_mocks(monkeypatch, [alert])
    monkeypatch.setattr(
        app,
        "record_reading_result",
        lambda *args: {
            "status": "EVALUATED",
            "level": "critical",
            "critical_streak": 1,
            "accepted": True,
        },
    )

    app.process_reading(sample_reading(), object(), "topic", now=1000)

    assert calls["sent"] == []
    assert calls["saved"] == []
    assert calls["progress"] == [
        ("spo2_pct", "CRITICAL_PENDING"),
        (app.DONE_METRIC, "COMPLETE"),
    ]
    assert calls["history"] == [("spo2_pct", "CRITICAL_PENDING")]


def test_late_reading_is_saved_but_not_counted_or_notified(monkeypatch):
    alert = {"metric": "spo2_pct", "level": "critical", "message": "O2"}
    calls = configure_processing_mocks(monkeypatch, [alert])
    monkeypatch.setattr(app, "is_reading_late", lambda *args: True)
    monkeypatch.setattr(
        app,
        "record_reading_result",
        Mock(side_effect=AssertionError("late reading must not update streak")),
    )

    app.process_reading(sample_reading(), object(), "topic", now=1000)

    assert calls["sent"] == []
    assert calls["reading"] == ["reading-1"]
    assert calls["progress"] == [
        ("spo2_pct", "LATE"),
        (app.DONE_METRIC, "COMPLETE"),
    ]
    assert calls["finished"] == ["LATE"]


def test_lambda_reports_only_failed_sqs_records(monkeypatch):
    table = object()
    monkeypatch.setattr(app, "_get_dependencies", lambda: (table, "topic"))

    def process(reading, table_arg, topic):
        if reading["reading_id"] == "bad":
            raise RuntimeError("temporary failure")

    monkeypatch.setattr(app, "process_reading", process)
    result = app.lambda_handler(
        {
            "Records": [
                {
                    "messageId": "message-ok",
                    "body": '{"reading_id":"ok"}',
                },
                {
                    "messageId": "message-failed",
                    "body": '{"reading_id":"bad"}',
                },
            ]
        },
        None,
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-failed"}]}


def test_reading_id_fallback_is_stable():
    reading = sample_reading(reading_id=None)
    reading.pop("reading_id")

    assert app._reading_id(reading) == app._reading_id(reading)
