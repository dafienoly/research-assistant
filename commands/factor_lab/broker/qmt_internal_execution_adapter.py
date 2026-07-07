"""Execution adapter for Big QMT internal HTTP executor."""

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.broker.qmt_execution_adapter import QMTLivePolicy
from factor_lab.broker.qmt_internal_http_client import QMTInternalHTTPClient
from factor_lab.execution.order_book import OrderBook
from factor_lab.live.account_profile import get_board
from factor_lab.risk.kill_switch import KillSwitch

CST = timezone(timedelta(hours=8))
REPORT_ROOT = Path("/mnt/d/HermesReports/qmt_internal")


def now_iso():
    return datetime.now(CST).isoformat()


class QMTInternalExecutionAdapter:
    """Live-trade entry point for Big QMT internal HTTP execution."""

    APPROVED_STATUSES = {"approved_for_manual_entry", "approved", "approved_for_qmt"}

    def __init__(
        self,
        client: Optional[QMTInternalHTTPClient] = None,
        policy: Optional[QMTLivePolicy] = None,
        kill_switch: Optional[KillSwitch] = None,
        order_book: Optional[OrderBook] = None,
        output_dir: str = None,
    ):
        self.client = client or QMTInternalHTTPClient()
        self.policy = policy or QMTLivePolicy.from_env()
        self.kill_switch = kill_switch or KillSwitch()
        self.order_book = order_book or OrderBook()
        self.output_dir = Path(output_dir) if output_dir else REPORT_ROOT / datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        self.audit_events = []

    def sync(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        health = self.client.health()
        state = self.client.state()
        orders = self.client.get_orders()
        fills = self.client.get_fills()

        order_rows = _as_list(orders.get("data"))
        fill_rows = _as_list(fills.get("data"))
        self._apply_order_statuses(order_rows)
        self._apply_fills(fill_rows)

        result = {
            "status": "ok" if all(r.get("status") == "ok" for r in [health, state, orders, fills]) else "partial",
            "generated_at": now_iso(),
            "health": health,
            "state": state,
            "orders": orders,
            "fills": fills,
        }
        self._write_json("qmt_internal_sync.json", result)
        self._write_csv("qmt_internal_orders.csv", order_rows, None)
        self._write_csv("qmt_internal_fills.csv", fill_rows, None)
        self.order_book.save(str(self.output_dir), "order_book.json")
        self._write_html_report("qmt_execution_report.html", result)
        self._flush_audit()
        return {**result, "output_dir": str(self.output_dir)}

    def place_approved_orders(self, approval_id: str, orders_path: str) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        orders_data = self._load_json(orders_path)
        preview_orders = orders_data.get("orders", []) if isinstance(orders_data, dict) else []
        approval = self._load_approval(approval_id)
        approved_ids = self._approved_order_ids(approval)
        preflight = self._preflight(approval_id)

        results = []
        batch_orders = []
        daily_value = 0.0
        existing_orders = self.client.get_orders() if preflight["allowed"] else {"status": "skipped", "data": []}

        for order in preview_orders:
            order_id = order.get("order_id", "")
            if order_id not in approved_ids:
                results.append(self._blocked(order, "approval_not_found", f"{order_id} is not approved"))
                continue

            if not preflight["allowed"]:
                results.append(self._blocked(order, "preflight_blocked", preflight["reason"]))
                continue

            risk = self._check_order_risk(order, daily_value)
            if not risk["allowed"]:
                results.append(self._blocked(order, risk["code"], risk["reason"]))
                continue

            client_order_id = f"{approval_id}:{order_id}"
            duplicate = self._find_existing_client_order(existing_orders, client_order_id)
            if duplicate:
                item = {
                    "order_id": order_id,
                    "symbol": order.get("symbol", ""),
                    "status": "duplicate_existing",
                    "client_order_id": client_order_id,
                    "reason": "client_order_id already exists at QMT internal executor",
                    "qmt_order": duplicate,
                }
                self._audit("duplicate_existing", item)
                results.append(item)
                continue

            payload_order = self._to_internal_order(order, client_order_id)
            batch_orders.append((order, payload_order))
            daily_value += float(order.get("estimated_amount", 0) or 0)

        if batch_orders:
            response = self.client.place_orders(approval_id=approval_id, orders=[p for _, p in batch_orders], batch_id=approval_id)
        else:
            response = {"status": "skipped", "data": {"orders": []}, "error": ""}

        response_rows = _response_orders(response)
        response_by_id = {row.get("client_order_id", ""): row for row in response_rows}
        for source_order, payload_order in batch_orders:
            order_id = source_order.get("order_id", "")
            client_order_id = payload_order.get("client_order_id", "")
            response_row = response_by_id.get(client_order_id, {})
            response_status = response_row.get("status", response.get("status", "error"))

            if response.get("status") == "ok" and response_status in ("queued", "accepted"):
                self.order_book.add_order(
                    order_id=order_id,
                    symbol=source_order.get("symbol", ""),
                    side=source_order.get("side", ""),
                    price=float(source_order.get("reference_price", 0) or 0),
                    limit_price=float(source_order.get("limit_price", 0) or 0),
                    quantity=int(source_order.get("order_shares", 0) or 0),
                    status="pending",
                    metadata={
                        "approval_id": approval_id,
                        "client_order_id": client_order_id,
                        "qmt_internal_status": "queued",
                    },
                )
                item = {
                    "order_id": order_id,
                    "symbol": source_order.get("symbol", ""),
                    "status": "queued",
                    "client_order_id": client_order_id,
                    "executor_response": response_row or response,
                }
                self._audit("queued", item)
                results.append(item)
            else:
                reason = response_row.get("reason") or response.get("error") or "QMT internal executor rejected order"
                item = {
                    "order_id": order_id,
                    "symbol": source_order.get("symbol", ""),
                    "status": "rejected",
                    "client_order_id": client_order_id,
                    "reason": reason,
                    "executor_response": response_row or response,
                }
                self._audit("rejected", item)
                results.append(item)

        result = {
            "status": "ok",
            "approval_id": approval_id,
            "orders_path": orders_path,
            "generated_at": now_iso(),
            "summary": {
                "total": len(results),
                "queued": sum(1 for r in results if r.get("status") == "queued"),
                "blocked": sum(1 for r in results if r.get("status") == "blocked"),
                "rejected": sum(1 for r in results if r.get("status") == "rejected"),
                "duplicate_existing": sum(1 for r in results if r.get("status") == "duplicate_existing"),
            },
            "results": results,
            "policy": asdict(self.policy),
            "executor_response": response,
        }
        self._write_json("qmt_internal_execution.json", result)
        self._write_csv("qmt_internal_execution_results.csv", results, None)
        self.order_book.save(str(self.output_dir), "order_book.json")
        self._write_html_report("qmt_execution_report.html", result)
        self._flush_audit()
        return {**result, "output_dir": str(self.output_dir)}

    def disable_live(self) -> dict:
        result = self.client.disable_live()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._audit("disable_live", result)
        self._flush_audit()
        return result

    def cancel_order(self, approval_id: str, qmt_order_id: str) -> dict:
        if not qmt_order_id:
            return {"status": "failed", "error": "qmt_order_id is required"}
        if self.kill_switch.is_blocked() and not self.policy.allow_cancel_when_kill_switch_triggered:
            return {"status": "blocked", "error": "kill switch blocks cancel"}
        approval = self._load_approval(approval_id)
        if not approval.get("valid"):
            return {"status": "blocked", "error": approval.get("error", "approval not found")}
        result = self.client.cancel_order(approval_id=approval_id, qmt_order_id=qmt_order_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json("qmt_internal_cancel.json", result)
        self._audit("cancel", result)
        self._flush_audit()
        return result

    def _preflight(self, approval_id: str) -> dict:
        if os.environ.get("QMT_LIVE_TRADING_ENABLED") != "1":
            return {"allowed": False, "reason": "QMT_LIVE_TRADING_ENABLED is not 1"}
        if not approval_id:
            return {"allowed": False, "reason": "approval_id is required"}
        if self.kill_switch.state != "armed":
            return {"allowed": False, "reason": f"kill switch is {self.kill_switch.state}"}
        health = self.client.health()
        if health.get("status") != "ok":
            return {"allowed": False, "reason": f"QMT internal health failed: {health.get('error')}"}
        return {"allowed": True, "reason": ""}

    def _check_order_risk(self, order: dict, daily_value: float) -> dict:
        amount = float(order.get("estimated_amount", 0) or 0)
        side = order.get("side", "")
        symbol = order.get("symbol", "")
        name = order.get("name", "")
        shares = int(order.get("order_shares", 0) or 0)
        board = "etf" if symbol.startswith(("1", "5")) else get_board(symbol)

        if not order.get("tradable", True):
            return {"allowed": False, "code": "not_tradable", "reason": order.get("block_reason", "order not tradable")}
        if board not in self.policy.allowed_boards:
            return {"allowed": False, "code": "board_blocked", "reason": f"board {board} is not allowed"}
        if side not in ("buy", "sell"):
            return {"allowed": False, "code": "side_blocked", "reason": "side must be buy or sell"}
        if shares <= 0 or shares % 100 != 0:
            return {"allowed": False, "code": "lot_blocked", "reason": "quantity must be positive 100-share lot"}
        if self.policy.block_st and ("ST" in name.upper() or order.get("is_st")):
            return {"allowed": False, "code": "st_blocked", "reason": "ST stock blocked"}
        if self.policy.block_suspended and order.get("is_suspended"):
            return {"allowed": False, "code": "suspended_blocked", "reason": "suspended stock blocked"}
        if self.policy.block_limit_up_buy and side == "buy" and order.get("is_limit_up"):
            return {"allowed": False, "code": "limit_up_blocked", "reason": "limit-up buy blocked"}
        if self.policy.block_limit_down_sell and side == "sell" and order.get("is_limit_down"):
            return {"allowed": False, "code": "limit_down_blocked", "reason": "limit-down sell blocked"}
        if amount > self.policy.max_order_value:
            return {"allowed": False, "code": "max_order_value", "reason": f"order value {amount:.2f} > {self.policy.max_order_value:.2f}"}
        if daily_value + amount > self.policy.max_daily_trade_value:
            return {"allowed": False, "code": "max_daily_trade_value", "reason": "daily trade value exceeded"}
        return {"allowed": True, "code": "", "reason": ""}

    def _to_internal_order(self, order: dict, client_order_id: str) -> dict:
        return {
            "client_order_id": client_order_id,
            "symbol": _normalize_qmt_symbol(order.get("symbol", "")),
            "side": order.get("side", ""),
            "quantity": int(order.get("order_shares", 0) or 0),
            "price_type": order.get("price_type", "limit"),
            "price": float(order.get("limit_price", 0) or 0),
            "estimated_amount": float(order.get("estimated_amount", 0) or 0),
        }

    def _find_existing_client_order(self, orders_resp: dict, client_order_id: str):
        for item in _as_list(orders_resp.get("data")):
            if item.get("client_order_id") == client_order_id:
                return item
        return None

    def _apply_order_statuses(self, orders: list[dict]):
        status_map = {
            "queued": "pending",
            "sent": "submitted",
            "accepted": "submitted",
            "submitted": "submitted",
            "partially_filled": "partially_filled",
            "filled": "filled",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "rejected": "rejected",
            "error": "rejected",
        }
        for row in orders:
            client_order_id = row.get("client_order_id", "")
            order_id = _order_id_from_client_id(client_order_id)
            if not order_id:
                order_id = client_order_id or row.get("order_id", "")
            if not order_id:
                continue
            if not self.order_book.get_order(order_id):
                self.order_book.add_order(
                    order_id=order_id,
                    symbol=row.get("symbol", ""),
                    side=row.get("side", "buy"),
                    price=float(row.get("price", 0) or 0),
                    limit_price=float(row.get("price", 0) or 0),
                    quantity=int(row.get("quantity", 0) or 0),
                    status="pending",
                    metadata={"client_order_id": client_order_id, "qmt_internal_status": row.get("status", "")},
                )
            status = status_map.get(str(row.get("status", "")).lower())
            if status:
                self.order_book.update_status(order_id, status, details=row)

    def _apply_fills(self, fills: list[dict]):
        for row in fills:
            client_order_id = row.get("client_order_id", "")
            order_id = _order_id_from_client_id(client_order_id) or client_order_id or row.get("order_id", "")
            if not order_id or not self.order_book.get_order(order_id):
                continue
            filled = int(float(row.get("filled_quantity", row.get("shares", row.get("volume", 0))) or 0))
            if filled <= 0:
                entry = self.order_book.get_order(order_id)
                filled = entry.quantity
            self.order_book.update_fill(order_id, filled, fill_price=float(row.get("price", 0) or 0))

    def _blocked(self, order: dict, code: str, reason: str) -> dict:
        item = {
            "order_id": order.get("order_id", ""),
            "symbol": order.get("symbol", ""),
            "status": "blocked",
            "code": code,
            "reason": reason,
        }
        self._audit("blocked", item)
        return item

    def _load_approval(self, approval_id: str) -> dict:
        candidates = []
        p = Path(approval_id)
        if p.exists():
            candidates.append(p / "approval_summary.json" if p.is_dir() else p)
        candidates.extend([
            Path("/mnt/d/HermesReports/approval") / approval_id / "approval_summary.json",
            Path("/mnt/d/HermesReports/approval") / f"{approval_id}.json",
        ])
        for candidate in candidates:
            if candidate.exists():
                try:
                    data = self._load_json(str(candidate))
                    return {"valid": True, "path": str(candidate), "data": data}
                except Exception as exc:
                    return {"valid": False, "error": str(exc), "path": str(candidate)}
        return {"valid": False, "error": f"approval not found: {approval_id}"}

    def _approved_order_ids(self, approval: dict) -> set:
        if not approval.get("valid"):
            return set()
        data = approval.get("data") or {}
        return {
            o.get("order_id", "")
            for o in data.get("orders", [])
            if o.get("approval_status") in self.APPROVED_STATUSES
        }

    def _load_json(self, path: str):
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def _write_json(self, name: str, data):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with open(self.output_dir / name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _write_csv(self, name: str, rows: list[dict], fields):
        rows = rows or []
        if fields is None:
            field_set = []
            for row in rows:
                for key in row.keys():
                    if key not in field_set:
                        field_set.append(key)
            fields = field_set or ["empty"]
        with open(self.output_dir / name, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            if rows:
                writer.writerows(rows)

    def _write_html_report(self, name: str, result: dict):
        summary = result.get("summary", {})
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>QMT Internal Execution</title></head>
<body><h1>QMT Internal Execution Report</h1><p>{now_iso()}</p><pre>{json.dumps(summary, ensure_ascii=False, indent=2)}</pre></body></html>"""
        (self.output_dir / name).write_text(html, encoding="utf-8")

    def _audit(self, event: str, data: dict):
        self.audit_events.append({"event": event, "timestamp": now_iso(), "data": data})

    def _flush_audit(self):
        path = self.output_dir / "qmt_execution_audit.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for event in self.audit_events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.audit_events.clear()


def _normalize_qmt_symbol(symbol: str) -> str:
    symbol = str(symbol or "").strip()
    if symbol.endswith(".SZ") or symbol.endswith(".SH"):
        return symbol
    if symbol.startswith(("0", "1", "2", "3")):
        return f"{symbol}.SZ"
    if symbol.startswith(("5", "6", "9")):
        return f"{symbol}.SH"
    return symbol


def _order_id_from_client_id(client_order_id: str) -> str:
    if not client_order_id:
        return ""
    if ":" in client_order_id:
        return client_order_id.rsplit(":", 1)[-1]
    return client_order_id


def _response_orders(response: dict) -> list[dict]:
    data = response.get("data") if isinstance(response, dict) else None
    rows = _as_list(data)
    if rows:
        return rows
    if isinstance(response, dict):
        return _as_list(response)
    return []


def _as_list(data):
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("orders", "fills", "trades", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []
