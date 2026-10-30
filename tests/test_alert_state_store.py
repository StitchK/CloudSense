import sys
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common.alert_state import (  # noqa: E402
    NotificationInProgress,
    claim_notification,
    is_reading_late,
    load_state,
    record_reading_result,
    reading_timestamp_epoch,
    release_claim,
    save_state,
)


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class TransactionCancelled(Exception):
    response = {"Error": {"Code": "TransactionCanceledException"}}


class FakeClient:
    def __init__(self):
        self.transaction = None
        self.transaction_errors = []

    def transact_write_items(self, **kwargs):
        if self.transaction_errors:
            raise self.transaction_errors.pop(0)
        self.transaction = kwargs


class FakeTable:
    name = "alert-state"

    def __init__(self):
        self.items = {}
        self.update_error = None
        self.update_calls = []
        self.meta = type("Meta", (), {"client": FakeClient()})()

    def get_item(self, **kwargs):
        key = kwargs["Key"]
        item = self.items.get((key["PK"], key["SK"]))
        return {"Item": item} if item else {}

    def update_item(self, **kwargs):
        self.update_calls.append(kwargs)
        if self.update_error:
            raise self.update_error


def test_load_state_returns_last_sent_fields_or_none():
    table = FakeTable()
    assert load_state(table, "device-1", "spo2_pct") is None

    table.items[("DEVICE#device-1", "METRIC#spo2_pct")] = {
        "last_sent_at": 1200,
        "last_level": "warning",
    }
    assert load_state(table, "device-1", "spo2_pct") == {
        "last_sent_at": 1200,
        "last_level": "warning",
        "critical_streak": 0,
        "last_observed_level": None,
        "last_reading_epoch": None,
    }


def test_claim_notification_uses_expiring_conditional_lease():
    table = FakeTable()
    token = claim_notification(
        table,
        "device-1",
        "spo2_pct",
        "critical",
        "reading-1",
        now=1000,
        cooldown=300,
        lease_seconds=60,
    )

    update = table.update_calls[0]
    assert token
    assert "ConditionExpression" in update
    assert update["ExpressionAttributeValues"][":lease"] == 1060


def test_active_claim_is_reported_as_in_progress():
    table = FakeTable()
    table.update_error = ConditionalFailure()
    table.items[("DEVICE#device-1", "METRIC#spo2_pct")] = {"claim_expires_at": 1100}

    with pytest.raises(NotificationInProgress):
        claim_notification(
            table,
            "device-1",
            "spo2_pct",
            "critical",
            "reading-1",
            now=1000,
        )


def test_save_state_commits_state_and_dedupe_in_one_transaction():
    table = FakeTable()
    save_state(
        table,
        "device-1",
        "spo2_pct",
        "critical",
        "reading-1",
        "claim-token",
        now=1000,
        progress_retention_seconds=86400,
    )

    actions = table.meta.client.transaction["TransactItems"]
    assert len(actions) == 2
    assert "claim_token = :token" in actions[0]["Update"]["ConditionExpression"]
    assert actions[1]["Update"]["ExpressionAttributeValues"][":sent"] == "SENT"


def test_release_claim_only_removes_the_matching_lease():
    table = FakeTable()
    release_claim(table, "device-1", "spo2_pct", "claim-token")

    assert table.update_calls[0]["ConditionExpression"] == "claim_token = :token"


def test_second_consecutive_critical_is_recorded_with_streak_two():
    table = FakeTable()
    table.items[("DEVICE#device-1", "METRIC#spo2_pct")] = {
        "last_observed_level": "critical",
        "critical_streak": 1,
        "last_reading_epoch": 1000,
    }

    progress = record_reading_result(
        table,
        "device-1",
        "spo2_pct",
        "critical",
        "reading-2",
        reading_epoch=1001,
        now=1001,
        retention_seconds=86400,
    )

    assert progress["critical_streak"] == 2
    update = table.meta.client.transaction["TransactItems"][0]["Update"]
    assert update["ExpressionAttributeValues"][":streak"] == 2


def test_noncritical_result_resets_critical_streak():
    table = FakeTable()
    table.items[("DEVICE#device-1", "METRIC#spo2_pct")] = {
        "last_observed_level": "critical",
        "critical_streak": 1,
        "last_reading_epoch": 1000,
    }

    progress = record_reading_result(
        table,
        "device-1",
        "spo2_pct",
        "warning",
        "reading-2",
        reading_epoch=1001,
        now=1001,
        retention_seconds=86400,
    )

    assert progress["critical_streak"] == 0


def test_record_reading_result_retries_transaction_conflicts():
    table = FakeTable()
    table.meta.client.transaction_errors = [TransactionCancelled()]

    with patch("src.common.alert_state.time.sleep"):
        progress = record_reading_result(
            table,
            "device-1",
            "spo2_pct",
            "warning",
            "reading-1",
            reading_epoch=1001,
            now=1001,
            retention_seconds=86400,
        )

    assert progress["accepted"] is True
    assert table.meta.client.transaction is not None


def test_is_reading_late_uses_timestamp_and_threshold():
    timestamp = "2026-10-30T12:00:00Z"
    measured_at = reading_timestamp_epoch(timestamp)

    assert not is_reading_late(timestamp, now=measured_at + 300)
    assert is_reading_late(timestamp, now=measured_at + 301)


def test_timestamp_without_timezone_is_rejected():
    with pytest.raises(ValueError, match="include a timezone"):
        reading_timestamp_epoch("2026-10-30T12:00:00")
