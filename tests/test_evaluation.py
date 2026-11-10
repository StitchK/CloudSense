import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.run_low_load import Experiment, history, percentile
from src.common.observability import emit
from src.common.reading_store import finish_reading
from evaluation.calculate_costs import calculate, read


def test_history_collects_all_pages_and_counts_requests():
    counter = Mock()
    with patch("evaluation.run_low_load.request_json", side_effect=[
        (200, {"items": ["first"], "next_token": "cursor"}),
        (200, {"items": ["second"], "next_token": None}),
    ]):
        assert history("https://example.test", "device", "start", "end", counter) == ["first", "second"]
    assert counter.call_count == 2


def test_history_rejects_cursor_loop():
    with patch("evaluation.run_low_load.request_json", return_value=(200, {"items": [], "next_token": "same"})):
        with pytest.raises(RuntimeError, match="Repeated"):
            history("https://example.test", "device", "start", "end")


def test_accepted_is_not_completed(tmp_path):
    with patch("evaluation.run_low_load.HERE", tmp_path):
        experiment = Experiment("https://example.test/readings", 1, 1, 2, 10)
    experiment.rows["one"] = {"http_status": 202, "http_ms": 10}
    summary = experiment.summary()
    assert summary["accepted"] == summary["pending_accepted"] == 1
    assert summary["completed"] == 0
    assert summary["backend_p95_ms"] is None
    assert percentile([None, 1, 2, 3], 95) == 2.9


def test_logs_are_structured_and_completion_has_milliseconds(capsys):
    emit("processing_completed", reading_id="evaluation-test", duration_ms=12.5)
    event = json.loads(capsys.readouterr().out)
    assert event["reading_id"] == "evaluation-test"
    assert isinstance(event["logged_at_ms"], int)
    table = Mock()
    with patch("src.common.reading_store.time.time_ns", return_value=1234567890000000):
        finish_reading(table, "evaluation-test", "COMPLETE", 1234567)
    assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":completed"] == 1234567890


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "evaluation/cloud_evidence/usage_details.json").exists(),
    reason="Requires local AWS experiment evidence, which is excluded from GitHub synchronization",
)
def test_saved_billing_reports_reconcile_with_cloudwatch_and_test_manifest():
    """Cross-check independent evidence rather than only arithmetic constants."""
    result = calculate()
    metrics = read("metrics")["metrics"]
    for row in metrics:
        if row["namespace"] == "AWS/Lambda" and row["metric"] == "Invocations":
            assert result["lambda_reports"][row["resource"]]["invocations"] == sum(point["Sum"] for point in row["points"])
    root = Path(__file__).resolve().parents[1] / "evaluation"
    manifests = [json.loads((root / "results" / run_id / "summary.json").read_text()) for run_id in result["run_ids"]]
    expected_api_calls = sum(run["sent"] + run["query_requests"] for run in manifests) + 1
    assert next(row["quantity"] for row in result["items"] if row["service"] == "HTTP API") == expected_api_calls
    assert result["selected_rates"]["http_api_request"]["attributes"]["operation"] == "ApiGatewayHttpApi"
    assert result["estimated_modeled_subtotal_usd"] < result["account_month_to_date_usd"]
