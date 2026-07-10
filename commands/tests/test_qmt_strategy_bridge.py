from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_bridge():
    path = Path(__file__).resolve().parents[2] / "scripts" / "qmt_windows" / "runtime" / "qmt_strategy_bridge.py"
    spec = importlib.util.spec_from_file_location("qmt_strategy_bridge", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_handlebar_emits_read_only_no_live_heartbeat(tmp_path):
    bridge = _load_bridge()
    bridge.OUTPUT_DIR = str(tmp_path)
    bridge.OUTPUT_FILE = str(tmp_path / "qmt_strategy_data.json")
    heartbeat = bridge.handlebar(None)
    written = json.loads((tmp_path / "qmt_strategy_data.json.heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat == written
    assert written["mode"] == "READ_ONLY"
    assert written["no_live_trade"] is True
    assert written["live_enabled"] is False
    assert written["order_channel"] == "DISABLED"
    assert "order" not in written or written["order_channel"] == "DISABLED"
