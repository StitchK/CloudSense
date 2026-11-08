import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator import send_config  # noqa: E402


def test_local_endpoint_is_independent_of_working_directory(tmp_path, monkeypatch):
    config = tmp_path / "simulator.local.json"
    config.write_text(json.dumps({"api_base_url": "https://example.test/"}))
    monkeypatch.setattr(send_config, "LOCAL_CONFIG", config)
    monkeypatch.delenv("CLOUDSENSE_API_URL", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert send_config.resolve_api_url() == "https://example.test/readings"


def test_overrides_work_without_a_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(send_config, "LOCAL_CONFIG", tmp_path / "missing.json")
    monkeypatch.setenv("CLOUDSENSE_API_URL", "https://env.test/readings")
    assert send_config.resolve_api_url() == "https://env.test/readings"
    assert send_config.resolve_api_url("https://cli.test/readings") == "https://cli.test/readings"


@pytest.mark.parametrize("module_name,expected_count", [
    ("simulator.simulator_send", 6),
    ("simulator.simulator_send_random", 4),
])
def test_no_argument_entrypoint_sends_using_local_config(
    tmp_path, monkeypatch, module_name, expected_count
):
    config = tmp_path / "simulator.local.json"
    config.write_text(json.dumps({"api_base_url": "https://example.test"}))
    monkeypatch.setattr(send_config, "LOCAL_CONFIG", config)
    monkeypatch.delenv("CLOUDSENSE_API_URL", raising=False)
    module = importlib.import_module(module_name)
    sender = Mock(return_value={"status_code": 202})
    monkeypatch.setattr(module, "send_reading", sender)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    if module_name.endswith("_random"):
        # Stop after the first full cycle while exercising main([]).
        build = module.build_cycle
        cycles = 0

        def one_cycle(**kwargs):
            nonlocal cycles
            cycles += 1
            if cycles > 1:
                raise KeyboardInterrupt
            kwargs["warning_probability"] = 1.0
            return build(**kwargs)

        monkeypatch.setattr(module, "build_cycle", one_cycle)
    assert module.main([]) == 0
    assert sender.call_count == expected_count
    assert all(call.kwargs["api_url"] == "https://example.test/readings" for call in sender.call_args_list)
    assert {call.kwargs["reading"]["device_id"] for call in sender.call_args_list} == {"device-001"}
    assert len({call.kwargs["reading"]["reading_id"] for call in sender.call_args_list}) == expected_count


def test_demo_uses_one_device_and_orders_measurements():
    from simulator.simulator_send import generate_demo_readings

    readings = generate_demo_readings(42, "device-001", 2, 5)
    assert [level for level, _ in readings] == ["normal"] * 3 + ["warning", "critical", "critical"]
    assert {reading["device_id"] for _, reading in readings} == {"device-001"}
    timestamps = [datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00")) for _, reading in readings]
    assert [(later - earlier).total_seconds() for earlier, later in zip(timestamps, timestamps[1:])] == [2, 2, 2, 2, 5]


@pytest.mark.parametrize("module_name,arguments", [
    ("simulator.simulator_send", []),
    ("simulator.simulator_send_random", ["--max-cycles", "2", "--warning-probability", "1"]),
])
def test_override_is_used_for_all_scenarios_and_cycles(monkeypatch, module_name, arguments):
    module = importlib.import_module(module_name)
    sender = Mock(return_value={"status_code": 202})
    sleeps = Mock()
    monkeypatch.setattr(module, "send_reading", sender)
    monkeypatch.setattr(module.time, "sleep", sleeps)
    assert module.main(["--device-id", "other-device-002", "--api-url", "https://example.test/readings", "--interval-seconds", "0", *arguments]) == 0
    assert {call.kwargs["reading"]["device_id"] for call in sender.call_args_list} == {"other-device-002"}
    assert sleeps.call_count == sender.call_count - 1
    assert all(call.args[0] >= 1 for call in sleeps.call_args_list)


def test_sent_reading_gets_current_time_and_a_unique_id():
    reading = {"device_id": "device-001", "reading_id": "old-reading", "timestamp": "2099-01-01T00:00:00Z", "heart_rate_bpm": 75}
    before = datetime.now(timezone.utc).replace(microsecond=0)
    first = send_config.prepare_reading_for_send(reading)
    second = send_config.prepare_reading_for_send(reading)
    after = datetime.now(timezone.utc)
    assert before <= datetime.fromisoformat(first["timestamp"].replace("Z", "+00:00")) <= after
    assert first["reading_id"] != second["reading_id"]
    assert first["device_id"] == reading["device_id"]
    assert first["heart_rate_bpm"] == 75
    assert reading["reading_id"] == "old-reading"


def test_random_sequence_number_does_not_create_future_measurements():
    import random
    from simulator.simulator_send_random import build_cycle

    readings = build_cycle(random.Random(42), "device-001", 10000, 1)
    now = datetime.now(timezone.utc)
    assert all(datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00")) <= now for _, reading in readings)


@pytest.mark.parametrize("module_name,expected_code", [("simulator.simulator_send", 2), ("simulator.simulator_send_random", 1)])
def test_invalid_device_does_not_send(monkeypatch, module_name, expected_code):
    module = importlib.import_module(module_name)
    sender = Mock()
    monkeypatch.setattr(module, "send_reading", sender)
    assert module.main(["--device-id", "bad device", "--api-url", "https://example.test/readings"]) == expected_code
    sender.assert_not_called()
