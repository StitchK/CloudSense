import base64
import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common.alert_rules import evaluate_reading_results  # noqa: E402
from src.common.reading_store import save_reading  # noqa: E402
from src.query import app  # noqa: E402


NOW = 1793361600


def stored_reading(reading_id="reading-1", epoch=NOW, abnormal=True):
    """Construct the fixture from the actual Lambda2 storage contract."""
    reading = {
        "device_id": "device-001",
        "reading_id": reading_id,
        "timestamp": app._iso(epoch),
        "_timestamp_epoch": epoch,
        "heart_rate_bpm": 110 if abnormal else 78,
        "body_temperature_c": 36.7,
        "spo2_pct": 89 if abnormal else 98,
        "blood_pressure": {"systolic": 118, "diastolic": 76},
        "activity": "rest",
    }
    table = Mock()
    save_reading(table, reading, evaluate_reading_results(reading), False, NOW, 86400)
    call = table.update_item.call_args.kwargs
    values = call["ExpressionAttributeValues"]
    return {
        **call["Key"],
        "reading": values[":reading"],
        "evaluations": values[":evaluations"],
        "measured_at_epoch": Decimal(epoch),
        "GSI1PK": values[":device_key"],
        "GSI1SK": values[":time_key"],
        "expires_at": values[":expires"],
        "is_late": False,
        "processing_status": "COMPLETE",
        "updated_at": NOW,
        "alert_history": {"spo2_pct": {"status": "CRITICAL_PENDING"}},
    }


def cursor_key(item):
    return {key: item[key] for key in app.CURSOR_KEYS}


def event(view="latest", params=None, device_id="device-001"):
    return {
        "version": "2.0",
        "routeKey": f"GET /devices/{{device_id}}/{view}",
        "requestContext": {"requestId": "request-1", "http": {"method": "GET"}},
        "pathParameters": {"device_id": device_id},
        "queryStringParameters": params,
    }


@pytest.fixture
def table(monkeypatch):
    mock = Mock()
    mock.query.return_value = {"Items": []}
    monkeypatch.setattr(app, "get_table", Mock(return_value=mock))
    monkeypatch.setattr(app.time, "time", lambda: NOW)
    monkeypatch.setenv("DATA_STALE_SECONDS", "300")
    return mock


def invoke(request):
    response = app.lambda_handler(request, None)
    return response["statusCode"], json.loads(response["body"])


def test_latest_matches_lambda2_storage_and_keeps_metric_and_mail_status_separate(
    table,
):
    table.query.return_value = {"Items": [stored_reading()]}
    status, body = invoke(event())
    assert status == 200
    data = body["data"]
    assert data["reading"]["body_temperature_c"] == 36.7
    assert data["reading"]["blood_pressure"] == {"systolic": 118, "diastolic": 76}
    assert data["overall_status"] == "critical"
    assert len(data["evaluations"]) == 4
    assert len(data["alerts"]) == 2
    oxygen = next(alert for alert in data["alerts"] if alert["metric"] == "spo2_pct")
    assert oxygen["level"] == "critical"
    assert oxygen["notification_status"] == "CRITICAL_PENDING"
    assert body["is_stale"] is False
    assert body["age_seconds"] == 0
    assert "PK" not in data and "GSI1PK" not in data
    args = table.query.call_args.kwargs
    assert args["IndexName"] == "DeviceTimeIndex"
    assert args["ScanIndexForward"] is False
    assert args["ExpressionAttributeValues"][":device"] == "DEVICE#device-001"
    assert (
        args["FilterExpression"]
        == "attribute_not_exists(expires_at) OR expires_at > :now"
    )
    table.scan.assert_not_called()
    table.update_item.assert_not_called()


def test_latest_old_normal_reading_is_stale_instead_of_current_normal(table):
    table.query.return_value = {
        "Items": [stored_reading(epoch=NOW - 301, abnormal=False)]
    }
    status, body = invoke(event())
    assert status == 200
    assert body["is_stale"] is True
    assert body["data"]["overall_status"] == "normal"
    assert body["data"]["alerts"] == []


def test_latest_continues_after_ttl_filtered_empty_page(table):
    key = cursor_key(stored_reading())
    table.query.side_effect = [
        {"Items": [], "LastEvaluatedKey": key},
        {"Items": [stored_reading(epoch=NOW - 1)]},
    ]
    status, body = invoke(event())
    assert status == 200 and body["age_seconds"] == 1
    assert table.query.call_args.kwargs["ExclusiveStartKey"] == key


def test_latest_no_data_and_bounded_lookup(table):
    assert invoke(event())[0] == 404
    table.query.return_value = {
        "Items": [],
        "LastEvaluatedKey": cursor_key(stored_reading()),
    }
    table.query.reset_mock()
    assert invoke(event())[0] == 503
    assert table.query.call_count == 5


def test_history_uses_inclusive_time_bounds_and_returns_all_classifications(table):
    table.query.return_value = {"Items": [stored_reading()]}
    start, end = "2026-10-30T19:00:00+08:00", "2026-10-30T20:00:00+08:00"
    status, body = invoke(event("history", {"from": start, "to": end, "limit": "10"}))
    assert status == 200 and body["count"] == 1
    assert body["from"] == "2026-10-30T11:00:00Z"
    assert body["to"] == "2026-10-30T12:00:00Z"
    args = table.query.call_args.kwargs
    assert args["Limit"] == 10
    values = args["ExpressionAttributeValues"]
    assert values[":start"] <= f"{NOW:020d}#first" <= values[":end"]
    assert values[":start"] <= f"{NOW:020d}#last" <= values[":end"]
    assert f"{NOW + 1:020d}#first" > values[":end"]
    assert body["next_token"] is None


def test_alerts_include_abnormal_readings_even_if_no_email_was_sent(table):
    table.query.return_value = {
        "Items": [stored_reading(), stored_reading("normal", abnormal=False)]
    }
    status, body = invoke(event("alerts"))
    assert status == 200 and body["count"] == 1
    assert body["items"][0]["overall_status"] == "critical"


def test_empty_alert_page_preserves_cursor_and_default_window_across_polls(
    table, monkeypatch
):
    item = stored_reading(abnormal=False)
    key = cursor_key(item)
    table.query.return_value = {"Items": [item], "LastEvaluatedKey": key}
    status, first = invoke(event("alerts", {"limit": "1"}))
    assert status == 200 and first["items"] == [] and first["next_token"]
    monkeypatch.setattr(app.time, "time", lambda: NOW + 10)
    table.query.return_value = {"Items": [stored_reading("older", NOW - 1)]}
    status, second = invoke(
        event("alerts", {"limit": "1", "next_token": first["next_token"]})
    )
    assert status == 200 and second["count"] == 1
    assert second["from"] == first["from"] and second["to"] == first["to"]
    assert table.query.call_args.kwargs["ExclusiveStartKey"] == key


@pytest.mark.parametrize("change", ["device", "route", "range", "key", "bounds"])
def test_cursor_cannot_be_reused_for_other_queries_or_invalid_keys(table, change):
    table.query.return_value = {
        "Items": [],
        "LastEvaluatedKey": cursor_key(stored_reading()),
    }
    _, first = invoke(event("history"))
    request = event("history", {"next_token": first["next_token"]})
    if change == "device":
        request["pathParameters"]["device_id"] = "other-device"
    elif change == "route":
        request["routeKey"] = "GET /devices/{device_id}/alerts"
    elif change == "range":
        request["queryStringParameters"]["from"] = app._iso(NOW - 100)
    else:
        raw = json.loads(
            base64.urlsafe_b64decode(
                first["next_token"] + "=" * (-len(first["next_token"]) % 4)
            )
        )
        if change == "key":
            raw["key"]["GSI1PK"] = "DEVICE#other-device"
        else:
            raw["end"] = 10**100
        request["queryStringParameters"]["next_token"] = base64.urlsafe_b64encode(
            json.dumps(raw).encode()
        ).decode()
    table.query.reset_mock()
    assert invoke(request)[0] == 400
    table.query.assert_not_called()


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "1.5"},
        {"from": "2026-10-30"},
        {"from": "2026-10-30T12:00:00"},
        {"from": "2026-10-30T12:00:00.500Z"},
        {"to": "invalid"},
        {"from": "2026-10-31T00:00:00Z", "to": "2026-10-30T00:00:00Z"},
        {"next_token": "!invalid!"},
        {"next_token": "W10"},
        {"next_token": ""},
        {"unknown": "x"},
    ],
)
def test_invalid_parameters_do_not_access_database(table, params):
    assert invoke(event("history", params))[0] == 400
    table.query.assert_not_called()
    app.get_table.assert_not_called()


def test_routing_validation_and_database_errors(table, capsys):
    assert invoke(event("missing"))[0] == 404
    assert invoke(event(device_id="bad/id"))[0] == 400
    assert invoke(event(params={"limit": "1"}))[0] == 400
    request = event()
    request["requestContext"]["http"]["method"] = "POST"
    assert invoke(request)[0] == 405
    table.query.assert_not_called()
    table.query.side_effect = RuntimeError("private database details")
    status, body = invoke(event())
    assert status == 503
    assert "private database details" not in json.dumps(body)
    assert "private database details" not in capsys.readouterr().out


def test_response_disables_caching_and_correlates_request(table):
    response = app.lambda_handler(event("history"), None)
    assert response["statusCode"] == 200
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["x-request-id"] == "request-1"
    assert json.loads(response["body"])["items"] == []
