# -*- coding: utf-8 -*-
"""
QMT strategy bridge (QMT built-in Python).
Provides account info via ContextInfo API, which is available in
QMT's built-in strategy environment (no miniQMT required).

Note: positions/orders/trades require miniQMT (xttrader) which is
NOT available in QMT's built-in strategy mode. These fields will
be empty in the JSON output.

Usage:
  1. QMT -> Strategy -> New Python strategy
  2. Paste this file into the editor
  3. Run the strategy (model trading mode)
"""

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
OUTPUT_DIR = "C:/Users/ly/Desktop/qmt_bridge/runtime"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "qmt_strategy_data.json")
INTERVAL = 3


def init(ContextInfo):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    t = threading.Thread(
        target=_dumper_loop, args=(ContextInfo,), daemon=True
    )
    t.start()


def handlebar(ContextInfo):
    """Publish a fail-visible read-only heartbeat on every QMT bar.

    QMT's built-in strategy callback cannot access miniQMT order/account APIs.
    The heartbeat therefore advertises that limitation explicitly and never
    attempts to place, cancel, or query an order.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    heartbeat = {
        "as_of": datetime.now(CST).isoformat(),
        "mode": "READ_ONLY",
        "no_live_trade": True,
        "live_enabled": False,
        "order_channel": "DISABLED",
        "account_channel": "BUILTIN_QMT_UNAVAILABLE",
        "source": "qmt_builtin_strategy_handlebar",
    }
    path = OUTPUT_FILE + ".heartbeat.json"
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(heartbeat, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception as exc:
        try:
            with open(OUTPUT_FILE + ".err", "a", encoding="utf-8") as handle:
                handle.write("heartbeat: " + repr(exc) + "\n")
        except Exception:
            return heartbeat
    return heartbeat


def _dumper_loop(ContextInfo, account_id=""):
    while True:
        try:
            data = {"as_of": datetime.now(CST).isoformat(), "account_id": account_id}
            _dump_account(ContextInfo, data)
            _dump_positions(ContextInfo, data)
            _dump_orders(ContextInfo, data)
            _dump_trades(ContextInfo, data)
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            try:
                with open(OUTPUT_FILE + ".err", "a") as f:
                    f.write(repr(e) + "\n")
            except Exception:
                pass
        time.sleep(INTERVAL)


def _attr(obj, name, default=""):
    return getattr(obj, name, default) if obj else default


def _dump_account(ContextInfo, data):
    """Account info is NOT available in QMT built-in Python strategy.
    Only miniQMT/xtquant xttrader supports this.
    """
    data["account"] = {
        "note": "账户/持仓/订单/成交需要 miniQMT (xttrader)，QMT 内置策略不支持查询",
        "source": "qmt_builtin_limited",
    }


def _dump_positions(ContextInfo, data):
    """QMT built-in strategy has no 'get all positions' API.
    Only miniQMT/xttrader supports this.
    """
    data["positions"] = []
    data["total_market_value"] = 0
    data["position_count"] = 0
    data["position_note"] = "positions require miniQMT (xtquant xttrader)"


def _dump_orders(ContextInfo, data):
    data["orders"] = []
    data["orders_note"] = "orders require miniQMT (xtquant xttrader)"


def _dump_trades(ContextInfo, data):
    data["trades"] = []
    data["trades_note"] = "trades require miniQMT (xtquant xttrader)"
