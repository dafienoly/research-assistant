#!/usr/bin/env python3
"""Windows QMT Bridge.

Run this script on the Windows machine where QMT/miniQMT and xtquant are
installed. Hermes talks to this local HTTP service from WSL instead of
importing xtquant directly.
"""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CST = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(CST).isoformat()


class QMTBackend:
    """Small xtquant facade with explicit unavailable results."""

    def __init__(self):
        self.xtdata = None
        self.xttrader = None
        self.xtconstant = None
        self.account = None
        self.connected = False
        self.trader_connected = False
        self.trader_connect_result = None
        self.error = ""
        self._connect()

    def _connect(self):
        try:
            from xtquant import xtdata

            port_text = os.environ.get("QMT_XTDATA_PORT", "").strip()
            port = int(port_text) if port_text else None
            xtdata.connect(port=port)
            self.xtdata = xtdata
            self.connected = True
        except Exception as exc:
            self.connected = False
            self.error = str(exc)
        self._connect_trader()

    def _connect_trader(self):
        userdata_path = os.environ.get("QMT_USERDATA_PATH", "")
        account_id = os.environ.get("QMT_ACCOUNT_ID", "")
        account_type = os.environ.get("QMT_ACCOUNT_TYPE", "STOCK")
        if not userdata_path or not account_id:
            return
        try:
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
            from xtquant import xtconstant

            session_id = int(os.environ.get("QMT_SESSION_ID", "100"))
            self.xttrader = XtQuantTrader(userdata_path, session_id)
            self.xtconstant = xtconstant
            self.account = StockAccount(account_id, account_type)
            self.xttrader.start()
            connect_result = self.xttrader.connect()
            self.trader_connect_result = connect_result
            if connect_result == 0 or connect_result is None:
                self.xttrader.subscribe(self.account)
            self.trader_connected = connect_result == 0 or connect_result is None
        except Exception as exc:
            self.trader_connected = False
            self.error = f"{self.error}; xttrader: {exc}" if self.error else f"xttrader: {exc}"

    def health(self):
        return {
            "connected": self.connected,
            "xtdata_available": self.xtdata is not None,
            "xttrader_available": self.xttrader is not None,
            "xttrader_connected": self.trader_connected,
            "xttrader_connect_result": self.trader_connect_result,
            "live_trading_enabled": os.environ.get("QMT_LIVE_TRADING_ENABLED") == "1",
            "error": self.error,
        }

    @staticmethod
    def _to_qmt_symbol(symbol):
        symbol = symbol.strip().upper()
        if "." in symbol:
            return symbol
        suffix = "SH" if symbol.startswith(("6", "9")) else "SZ"
        return f"{symbol}.{suffix}"

    def quotes(self, symbols):
        if not self.xtdata:
            raise RuntimeError("xtdata unavailable")
        qmt_symbols = [self._to_qmt_symbol(s) for s in symbols if s]
        raw = self.xtdata.get_full_tick(qmt_symbols) or {}
        out = {}
        for code, tick in raw.items():
            sym = code.split(".")[0]
            out[sym] = {
                "symbol": sym,
                "qmt_symbol": code,
                "price": tick.get("lastPrice", 0),
                "open": tick.get("open", 0),
                "high": tick.get("high", 0),
                "low": tick.get("low", 0),
                "pre_close": tick.get("preClose", 0),
                "volume": tick.get("volume", 0),
                "amount": tick.get("amount", 0),
                "bid_price": tick.get("bidPrice", []),
                "ask_price": tick.get("askPrice", []),
                "bid_volume": tick.get("bidVol", []),
                "ask_volume": tick.get("askVol", []),
            }
        return out

    def bars(self, symbol, period="1d", count=120):
        if not self.xtdata:
            raise RuntimeError("xtdata unavailable")
        qmt_symbol = self._to_qmt_symbol(symbol)
        data = self.xtdata.get_local_data(
            field_list=["time", "open", "high", "low", "close", "volume", "amount"],
            stock_code=[qmt_symbol],
            period=period,
            start_time="",
            end_time="",
            count=int(count),
        )
        if data is None:
            return []
        try:
            frame = data[qmt_symbol] if isinstance(data, dict) and qmt_symbol in data else data
            rows = frame.reset_index().to_dict("records")
        except Exception:
            rows = []
        return rows

    def query_account(self):
        self._require_trader()
        return self._serialize(self.xttrader.query_stock_asset(self.account))

    def query_positions(self):
        self._require_trader()
        return [self._serialize(p) for p in (self.xttrader.query_stock_positions(self.account) or [])]

    def query_orders(self):
        self._require_trader()
        return [self._serialize(o) for o in (self.xttrader.query_stock_orders(self.account) or [])]

    def query_trades(self):
        self._require_trader()
        return [self._serialize(t) for t in (self.xttrader.query_stock_trades(self.account) or [])]

    def place_order(self, payload):
        if os.environ.get("QMT_LIVE_TRADING_ENABLED") != "1":
            raise PermissionError("QMT_LIVE_TRADING_ENABLED is not 1")
        self._require_trader()
        order = payload.get("order") or {}
        side = str(order.get("side", "")).lower()
        order_type = self.xtconstant.STOCK_BUY if side == "buy" else self.xtconstant.STOCK_SELL
        price_type = self.xtconstant.FIX_PRICE
        qmt_order_id = self.xttrader.order_stock(
            self.account,
            self._to_qmt_symbol(order.get("symbol", "")),
            order_type,
            int(order.get("quantity", 0)),
            price_type,
            float(order.get("price", 0)),
            "hermes",
            order.get("client_order_id", ""),
        )
        return {
            "qmt_order_id": str(qmt_order_id),
            "client_order_id": order.get("client_order_id", ""),
            "symbol": order.get("symbol", ""),
            "side": side,
            "quantity": int(order.get("quantity", 0)),
            "price": float(order.get("price", 0)),
        }

    def cancel_order(self, payload):
        if os.environ.get("QMT_LIVE_TRADING_ENABLED") != "1":
            raise PermissionError("QMT_LIVE_TRADING_ENABLED is not 1")
        self._require_trader()
        qmt_order_id = int(payload.get("qmt_order_id", 0))
        result = self.xttrader.cancel_order_stock(self.account, qmt_order_id)
        return {"qmt_order_id": str(qmt_order_id), "cancel_result": result}

    def _require_trader(self):
        if not self.xttrader or not self.account:
            raise RuntimeError("xttrader is not configured; set QMT_USERDATA_PATH and QMT_ACCOUNT_ID")
        if not self.trader_connected:
            raise RuntimeError("xttrader is not connected")

    @staticmethod
    def _serialize(obj):
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        data = {}
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            if callable(value):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                data[name] = value
        return data


class BridgeHandler(BaseHTTPRequestHandler):
    backend = QMTBackend()
    audit_path = Path(os.environ.get("QMT_BRIDGE_AUDIT_PATH", "qmt_bridge_audit.jsonl"))

    def log_message(self, fmt, *args):
        return

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _audit(self, record):
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _send(self, status, data=None, error=""):
        request_id = str(uuid.uuid4())
        body = {
            "status": status,
            "request_id": request_id,
            "timestamp": now_iso(),
            "data": data,
            "error": error,
        }
        raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200 if status == "ok" else 500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
        self._audit({"path": self.path, "response": body})

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send("ok", self.backend.health())
            elif parsed.path == "/quotes":
                symbols = ",".join(qs.get("symbols", [""])).split(",")
                self._send("ok", self.backend.quotes(symbols))
            elif parsed.path == "/bars":
                self._send(
                    "ok",
                    self.backend.bars(
                        qs.get("symbol", [""])[0],
                        qs.get("period", ["1d"])[0],
                        int(qs.get("count", ["120"])[0]),
                    ),
                )
            elif parsed.path == "/account":
                self._send("ok", self.backend.query_account())
            elif parsed.path == "/positions":
                self._send("ok", self.backend.query_positions())
            elif parsed.path == "/orders":
                self._send("ok", self.backend.query_orders())
            elif parsed.path == "/trades":
                self._send("ok", self.backend.query_trades())
            else:
                self._send("error", error=f"unknown path: {parsed.path}")
        except Exception as exc:
            self._send("error", error=str(exc))

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self._read_body()
        self._audit({"path": self.path, "request": payload, "timestamp": now_iso()})
        try:
            if parsed.path == "/orders/place":
                result = self.backend.place_order(payload)
                qmt_order_id = result.get("qmt_order_id") if isinstance(result, dict) else result
                self._send("ok", {"result": result, "qmt_order_id": qmt_order_id})
            elif parsed.path == "/orders/cancel":
                self._send("ok", self.backend.cancel_order(payload))
            else:
                self._send("error", error=f"unknown path: {parsed.path}")
        except Exception as exc:
            self._send("error", error=str(exc))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("QMT_BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("QMT_BRIDGE_PORT", "8765")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    print(f"QMT bridge listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
