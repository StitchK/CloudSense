import importlib
import json
import sys
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
