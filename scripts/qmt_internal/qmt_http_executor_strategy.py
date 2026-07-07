#coding:gbk
"""Hermes QMT internal HTTP executor strategy.

Paste this file into Big QMT's Python strategy editor, bind a stock account,
attach it to a 1m or tick chart, and start the strategy.

HTTP only validates and queues approved Hermes orders. Actual passorder(...)
calls are made from handlebar(ContextInfo), inside QMT's strategy context.
"""

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse


CONFIG_PATH = r"D:\HermesQMTBridge\qmt_http_executor_config.json"
ROOT_DIR = r"D:\HermesQMTBridge"
STATE_DIR = os.path.join(ROOT_DIR, "state")
AUDIT_DIR = os.path.join(ROOT_DIR, "audit")

DEFAULT_CONFIG = {
    "HOST": "127.0.0.1",
    "PORT": 18765,
    "TOKEN": "",
    "ACCOUNT_ID": "",
    "LIVE_TRADING_ENABLED": False,
    "FUNCTION_TRADING_ENABLED": False,
    "MAX_ORDER_VALUE": 10000.0,
    "MAX_DAILY_TRADE_VALUE": 50000.0,
    "ALLOW_CANCEL": False,
}

STATE = {
    "config": DEFAULT_CONFIG.copy(),
    "server_started": False,
    "server_error": "",
    "started_at": "",
    "orders": {},
    "fills": [],
    "errors": [],
    "executed_ids": [],
    "queue": [],
    "cancel_queue": [],
    "daily_trade_value": 0.0,
    "last_handlebar_at": "",
    "lock": threading.RLock(),
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())


def _mkdirs():
    for path in (ROOT_DIR, STATE_DIR, AUDIT_DIR):
        if not os.path.exists(path):
            os.makedirs(path)


def _read_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
    except Exception as exc:
        _append_jsonl("error_events.jsonl", {"event": "read_json_failed", "path": path, "error": str(exc)})
    return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _append_jsonl(name, data):
    try:
        _mkdirs()
        payload = dict(data or {})
        payload.setdefault("timestamp", _now())
        with open(os.path.join(AUDIT_DIR, name), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _state_path(name):
    return os.path.join(STATE_DIR, name)


def load_config():
    _mkdirs()
    cfg = DEFAULT_CONFIG.copy()
    user_cfg = _read_json(CONFIG_PATH, {})
    if isinstance(user_cfg, dict):
        cfg.update(user_cfg)
    if cfg.get("HOST") != "127.0.0.1":
        cfg["HOST"] = "127.0.0.1"
    STATE["config"] = cfg
    return cfg


def load_state():
    with STATE["lock"]:
        executed = _read_json(_state_path("executed_ids.json"), [])
        queued = _read_json(_state_path("queued_orders.json"), [])
        if isinstance(executed, list):
            STATE["executed_ids"] = executed
        if isinstance(queued, list):
            STATE["queue"] = queued
            for item in queued:
                cid = item.get("client_order_id", "")
                if cid and cid not in STATE["orders"]:
                    STATE["orders"][cid] = item


def save_state():
    with STATE["lock"]:
        _write_json(_state_path("executed_ids.json"), STATE["executed_ids"])
        queued = [o for o in STATE["queue"] if o.get("status") == "queued"]
        _write_json(_state_path("queued_orders.json"), queued)


def _response(status, data=None, error="", request_id=None, http_status=200, extra=None):
    body = {
        "status": status,
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": _now(),
        "data": data,
        "error": error,
    }
    if extra:
        body.update(extra)
    return http_status, body


def _validate_order(order, approval_id):
    cfg = STATE["config"]
    cid = str(order.get("client_order_id", "")).strip()
    side = str(order.get("side", "")).lower()
    symbol = str(order.get("symbol", "")).strip()
    price_type = str(order.get("price_type", "")).lower()
    qty = int(float(order.get("quantity", 0) or 0))
    estimated = float(order.get("estimated_amount", 0) or 0)

    if not approval_id:
        return False, "approval_id is required"
    if not cid:
        return False, "client_order_id is required"
    if cid in STATE["orders"] or cid in STATE["executed_ids"]:
        return False, "duplicate client_order_id"
    if side not in ("buy", "sell"):
        return False, "side must be buy or sell"
    if price_type not in ("limit", "latest"):
        return False, "price_type must be limit or latest"
    if not (symbol.endswith(".SZ") or symbol.endswith(".SH")):
        return False, "symbol must end with .SZ or .SH"
    if qty <= 0 or qty % 100 != 0:
        return False, "quantity must be positive 100-share lot"
    if estimated <= 0:
        estimated = qty * float(order.get("price", 0) or 0)
    if estimated > float(cfg.get("MAX_ORDER_VALUE", 10000.0)):
        return False, "max order value exceeded"
    if STATE["daily_trade_value"] + estimated > float(cfg.get("MAX_DAILY_TRADE_VALUE", 50000.0)):
        return False, "max daily trade value exceeded"
    return True, ""


def _enqueue_orders(payload, request_id):
    cfg = STATE["config"]
    if not cfg.get("LIVE_TRADING_ENABLED"):
        return _response("error", error="local LIVE_TRADING_ENABLED is false", request_id=request_id, http_status=403)
    if not cfg.get("FUNCTION_TRADING_ENABLED"):
        return _response("error", error="FUNCTION_TRADING_ENABLED is false; QMT function trading permission is required for passorder", request_id=request_id, http_status=403)
    if payload.get("live_trading_enabled") is not True:
        return _response("error", error="payload live_trading_enabled must be true", request_id=request_id, http_status=403)

    approval_id = str(payload.get("approval_id", "")).strip()
    batch_id = str(payload.get("batch_id", approval_id)).strip()
    orders = payload.get("orders") or []
    if not isinstance(orders, list):
        return _response("error", error="orders must be a list", request_id=request_id, http_status=400)

    accepted = []
    rejected = []
    batch_value = 0.0
    with STATE["lock"]:
        for raw in orders:
            order = dict(raw or {})
            ok, reason = _validate_order(order, approval_id)
            cid = str(order.get("client_order_id", ""))
            if not ok:
                rejected.append({"client_order_id": cid, "status": "rejected", "reason": reason})
                continue
            estimated = float(order.get("estimated_amount", 0) or 0)
            if estimated <= 0:
                estimated = int(float(order.get("quantity", 0) or 0)) * float(order.get("price", 0) or 0)
            if STATE["daily_trade_value"] + batch_value + estimated > float(cfg.get("MAX_DAILY_TRADE_VALUE", 50000.0)):
                rejected.append({"client_order_id": cid, "status": "rejected", "reason": "max daily trade value exceeded"})
                continue
            item = {
                "client_order_id": cid,
                "approval_id": approval_id,
                "batch_id": batch_id,
                "symbol": order.get("symbol", ""),
                "side": str(order.get("side", "")).lower(),
                "quantity": int(float(order.get("quantity", 0) or 0)),
                "price_type": str(order.get("price_type", "")).lower(),
                "price": float(order.get("price", 0) or 0),
                "estimated_amount": estimated,
                "status": "queued",
                "queued_at": _now(),
                "updated_at": _now(),
            }
            STATE["queue"].append(item)
            STATE["orders"][cid] = item
            accepted.append({"client_order_id": cid, "status": "queued"})
            batch_value += estimated
            _append_jsonl("order_events.jsonl", {"event": "queued", "order": item})
        save_state()

    data = {"accepted": len(accepted), "rejected": len(rejected), "orders": accepted + rejected}
    return _response("ok", data=data, request_id=request_id, extra=data)


def _enqueue_cancel(payload, request_id):
    cfg = STATE["config"]
    if not cfg.get("ALLOW_CANCEL"):
        return _response("error", error="cancel is disabled in first version", request_id=request_id, http_status=403)
    approval_id = str(payload.get("approval_id", "")).strip()
    qmt_order_id = str(payload.get("qmt_order_id", "")).strip()
    if not approval_id or not qmt_order_id:
        return _response("error", error="approval_id and qmt_order_id are required", request_id=request_id, http_status=400)
    with STATE["lock"]:
        item = {"approval_id": approval_id, "qmt_order_id": qmt_order_id, "status": "queued", "queued_at": _now()}
        STATE["cancel_queue"].append(item)
    _append_jsonl("order_events.jsonl", {"event": "cancel_queued", "cancel": item})
    return _response("ok", data=item, request_id=request_id)


class HermesHandler(BaseHTTPRequestHandler):
    server_version = "HermesQMTInternalHTTP/1.0"

    def log_message(self, fmt, *args):
        return

    def _send(self, http_status, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(http_status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        token = STATE["config"].get("TOKEN", "")
        return token and self.headers.get("X-Hermes-Token", "") == token

    def _read_payload(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _guard(self, request_id):
        if not self._authorized():
            return _response("error", error="unauthorized", request_id=request_id, http_status=401)
        return None

    def do_GET(self):
        request_id = str(uuid.uuid4())
        guard = self._guard(request_id)
        if guard:
            self._send(*guard)
            return
        path = urlparse(self.path).path
        if path == "/ping":
            self._send(*_response("ok", data={"pong": True}, request_id=request_id))
            return
        if path == "/health":
            data = {
                "connected": True,
                "server_started": STATE["server_started"],
                "server_error": STATE["server_error"],
                "live_trading_enabled": bool(STATE["config"].get("LIVE_TRADING_ENABLED")),
                "function_trading_enabled": bool(STATE["config"].get("FUNCTION_TRADING_ENABLED")),
                "account_id": STATE["config"].get("ACCOUNT_ID", ""),
                "queue_length": len(STATE["queue"]),
                "last_handlebar_at": STATE.get("last_handlebar_at", ""),
            }
            self._send(*_response("ok", data=data, request_id=request_id))
            return
        with STATE["lock"]:
            if path == "/state":
                data = {
                    "started_at": STATE["started_at"],
                    "daily_trade_value": STATE["daily_trade_value"],
                    "queue_length": len(STATE["queue"]),
                    "orders_count": len(STATE["orders"]),
                    "fills_count": len(STATE["fills"]),
                    "last_handlebar_at": STATE.get("last_handlebar_at", ""),
                }
                self._send(*_response("ok", data=data, request_id=request_id))
                return
            if path == "/orders":
                self._send(*_response("ok", data=list(STATE["orders"].values()), request_id=request_id))
                return
            if path == "/fills":
                self._send(*_response("ok", data=STATE["fills"], request_id=request_id))
                return
        self._send(*_response("error", error="not found", request_id=request_id, http_status=404))

    def do_POST(self):
        request_id = str(uuid.uuid4())
        guard = self._guard(request_id)
        if guard:
            self._send(*guard)
            return
        path = urlparse(self.path).path
        try:
            payload = self._read_payload()
        except Exception as exc:
            self._send(*_response("error", error="invalid JSON: %s" % exc, request_id=request_id, http_status=400))
            return
        _append_jsonl("http_requests.jsonl", {"request_id": request_id, "path": path, "payload": payload})

        if path == "/orders/place":
            self._send(*_enqueue_orders(payload, request_id))
            return
        if path == "/orders/cancel":
            self._send(*_enqueue_cancel(payload, request_id))
            return
        if path == "/control/enable-live":
            with STATE["lock"]:
                STATE["config"]["LIVE_TRADING_ENABLED"] = True
            self._send(*_response("ok", data={"live_trading_enabled": True}, request_id=request_id))
            return
        if path == "/control/disable-live":
            with STATE["lock"]:
                STATE["config"]["LIVE_TRADING_ENABLED"] = False
            self._send(*_response("ok", data={"live_trading_enabled": False}, request_id=request_id))
            return
        self._send(*_response("error", error="not found", request_id=request_id, http_status=404))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start_local_http_server():
    cfg = STATE["config"]
    if STATE["server_started"]:
        return

    def run():
        try:
            server = ThreadedHTTPServer((cfg.get("HOST", "127.0.0.1"), int(cfg.get("PORT", 18765))), HermesHandler)
            STATE["server_started"] = True
            STATE["server_error"] = ""
            server.serve_forever()
        except Exception as exc:
            STATE["server_error"] = str(exc)
            _append_jsonl("error_events.jsonl", {"event": "server_error", "error": str(exc)})

    t = threading.Thread(target=run)
    t.daemon = True
    t.start()


def _map_passorder(order):
    op_type = 23 if order.get("side") == "buy" else 24
    price_type = order.get("price_type")
    pr_type = 11 if price_type == "limit" else 5
    model_price = float(order.get("price", 0) or 0) if price_type == "limit" else 0
    return op_type, pr_type, model_price


def drain_order_queue(ContextInfo):
    if not STATE["queue"]:
        return
    to_send = []
    with STATE["lock"]:
        while STATE["queue"]:
            to_send.append(STATE["queue"].pop(0))

    for order in to_send:
        cid = order.get("client_order_id", "")
        try:
            op_type, pr_type, model_price = _map_passorder(order)
            order["status"] = "sent"
            order["sent_at"] = _now()
            order["updated_at"] = _now()
            STATE["daily_trade_value"] += float(order.get("estimated_amount", 0) or 0)
            with STATE["lock"]:
                STATE["orders"][cid] = order
                if cid not in STATE["executed_ids"]:
                    STATE["executed_ids"].append(cid)
            save_state()
            _append_jsonl("order_events.jsonl", {"event": "sent", "order": order})
            passorder(
                op_type,
                1101,
                STATE["config"].get("ACCOUNT_ID", ""),
                order.get("symbol", ""),
                pr_type,
                model_price,
                int(order.get("quantity", 0) or 0),
                "HermesHTTP",
                1,
                cid,
                ContextInfo,
            )
        except Exception as exc:
            order["status"] = "error"
            order["error"] = str(exc)
            order["updated_at"] = _now()
            with STATE["lock"]:
                STATE["orders"][cid] = order
                STATE["errors"].append(order)
            _append_jsonl("error_events.jsonl", {"event": "passorder_error", "order": order, "error": str(exc)})
    save_state()


def _obj_to_dict(obj):
    result = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        try:
            json.dumps(value, ensure_ascii=False)
            result[name] = value
        except Exception:
            result[name] = str(value)
    return result


def init(ContextInfo):
    cfg = load_config()
    load_state()
    STATE["started_at"] = _now()
    if cfg.get("ACCOUNT_ID"):
        ContextInfo.set_account(cfg.get("ACCOUNT_ID"))
    start_local_http_server()


def handlebar(ContextInfo):
    STATE["last_handlebar_at"] = _now()
    drain_order_queue(ContextInfo)
    try:
        ContextInfo.paint("HERMES_HTTP", 1 if STATE["server_started"] else 0, -1, 0)
    except Exception:
        pass


def order_callback(ContextInfo, order):
    data = _obj_to_dict(order)
    cid = str(data.get("userOrderId", data.get("m_strRemark", data.get("remark", ""))))
    if cid:
        with STATE["lock"]:
            item = STATE["orders"].get(cid, {"client_order_id": cid})
            item.update({"status": "accepted", "qmt_order": data, "updated_at": _now()})
            STATE["orders"][cid] = item
    _append_jsonl("order_events.jsonl", {"event": "order_callback", "order": data})


def deal_callback(ContextInfo, deal):
    data = _obj_to_dict(deal)
    cid = str(data.get("userOrderId", data.get("m_strRemark", data.get("remark", ""))))
    if cid:
        data["client_order_id"] = cid
    with STATE["lock"]:
        STATE["fills"].append(data)
        if cid and cid in STATE["orders"]:
            item = STATE["orders"][cid]
            item["status"] = "filled"
            item["fill"] = data
            item["updated_at"] = _now()
    _append_jsonl("deal_events.jsonl", {"event": "deal_callback", "deal": data})


def orderError_callback(ContextInfo, orderError):
    data = _obj_to_dict(orderError)
    cid = str(data.get("userOrderId", data.get("m_strRemark", data.get("remark", ""))))
    if cid:
        with STATE["lock"]:
            item = STATE["orders"].get(cid, {"client_order_id": cid})
            item.update({"status": "rejected", "error": data, "updated_at": _now()})
            STATE["orders"][cid] = item
    _append_jsonl("error_events.jsonl", {"event": "order_error_callback", "error": data})
