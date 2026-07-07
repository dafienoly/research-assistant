"""QMT execution adapter with approval, risk, and audit gates."""

import csv
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.broker.broker_position_adapter import STANDARD_FIELDS
from factor_lab.broker.qmt_client import QMTClient
from factor_lab.execution.order_book import OrderBook
from factor_lab.live.account_profile import get_board
from factor_lab.risk.kill_switch import KillSwitch

CST = timezone(timedelta(hours=8))
REPORT_ROOT = Path("/mnt/d/HermesReports/qmt")


def now_iso():
    return datetime.now(CST).isoformat()


@dataclass
class QMTLivePolicy:
    max_order_value: float = 10000.0
    max_daily_trade_value: float = 50000.0
    max_position_pct: float = 0.25
    allowed_boards: tuple = ("main", "etf")
    block_st: bool = True
    block_suspended: bool = True
    block_limit_up_buy: bool = True
    block_limit_down_sell: bool = True
    require_manual_approval: bool = True
    allow_cancel_when_kill_switch_triggered: bool = True

    @staticmethod
    def from_env() -> "QMTLivePolicy":
        return QMTLivePolicy(
            max_order_value=float(os.environ.get("QMT_MAX_ORDER_VALUE", "10000")),
            max_daily_trade_value=float(os.environ.get("QMT_MAX_DAILY_TRADE_VALUE", "50000")),
            max_position_pct=float(os.environ.get("QMT_MAX_POSITION_PCT", "0.25")),
        )


class QMTExecutionAdapter:
    """Only live-trade entry point for Hermes QMT integration."""

    APPROVED_STATUSES = {"approved_for_manual_entry", "approved", "approved_for_qmt"}

    def __init__(
        self,
        client: Optional[QMTClient] = None,
        policy: Optional[QMTLivePolicy] = None,
        kill_switch: Optional[KillSwitch] = None,
        order_book: Optional[OrderBook] = None,
        output_dir: str = None,
    ):
        self.client = client or QMTClient()
        self.policy = policy or QMTLivePolicy.from_env()
        self.kill_switch = kill_switch or KillSwitch()
        self.order_book = order_book or OrderBook()
        self.output_dir = Path(output_dir) if output_dir else REPORT_ROOT / datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        self.audit_events = []

    def sync(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        account = self.client.get_account()
        positions = self.client.get_positions()
        orders = self.client.get_orders()
        trades = self.client.get_trades()

        result = {
            "status": "ok" if all(r.get("status") == "ok" for r in [account, positions, orders, trades]) else "partial",
            "generated_at": now_iso(),
            "account": account,
            "positions": positions,
            "orders": orders,
            "trades": trades,
        }
        self._write_json("qmt_sync.json", result)
        self._write_csv("qmt_positions.csv", _as_list(positions.get("data")), STANDARD_FIELDS)
        self._write_csv("qmt_orders.csv", _as_list(orders.get("data")), None)
        self._write_csv("qmt_trades.csv", _as_list(trades.get("data")), None)
        self._apply_order_statuses(_as_list(orders.get("data")))
        self._apply_trade_fills(_as_list(trades.get("data")))
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
        daily_value = 0.0
        account = self.client.get_account() if preflight["allowed"] else {"status": "skipped", "data": {}}
        positions = self.client.get_positions() if preflight["allowed"] else {"status": "skipped", "data": []}
        existing_orders = self.client.get_orders() if preflight["allowed"] else {"status": "skipped", "data": []}

        for order in preview_orders:
            order_id = order.get("order_id", "")
            if order_id not in approved_ids:
                results.append(self._blocked(order, "approval_not_found", f"{order_id} is not approved"))
                continue

            if not preflight["allowed"]:
                results.append(self._blocked(order, "preflight_blocked", preflight["reason"]))
                continue

            risk = self._check_order_risk(order, account, positions, daily_value)
            if not risk["allowed"]:
                results.append(self._blocked(order, risk["code"], risk["reason"]))
                continue

            client_order_id = f"{approval_id}:{order_id}"
            duplicate = self._find_existing_client_order(existing_orders, client_order_id)
            if duplicate:
                duplicate_result = {
                    "order_id": order_id,
                    "symbol": order.get("symbol", ""),
                    "status": "duplicate_existing",
                    "client_order_id": client_order_id,
                    "qmt_order_id": duplicate.get("qmt_order_id", duplicate.get("order_id", "")),
                    "reason": "client_order_id already exists at bridge",
                }
                self._audit("duplicate_existing", duplicate_result)
                results.append(duplicate_result)
                continue

            payload_order = self._to_qmt_order(order, client_order_id)
            self.order_book.add_order(
                order_id=order_id,
                symbol=order.get("symbol", ""),
                side=order.get("side", ""),
                price=float(order.get("reference_price", 0) or 0),
                limit_price=float(order.get("limit_price", 0) or 0),
                quantity=int(order.get("order_shares", 0) or 0),
                status="pending",
                metadata={"approval_id": approval_id, "client_order_id": client_order_id},
            )
            response = self.client.place_order(payload_order, approval_id)
            if response.get("status") == "ok":
                data = response.get("data") or {}
                qmt_order_id = data.get("qmt_order_id") or (data.get("result") or {}).get("qmt_order_id", "")
                self.order_book.update_status(order_id, "submitted", details={"qmt_order_id": qmt_order_id})
                daily_value += float(order.get("estimated_amount", 0) or 0)
                submitted_result = {
                    "order_id": order_id,
                    "symbol": order.get("symbol", ""),
                    "status": "submitted",
                    "client_order_id": client_order_id,
                    "qmt_order_id": qmt_order_id,
                    "bridge_response": response,
                }
                self._audit("submitted", submitted_result)
                results.append(submitted_result)
            else:
                self.order_book.update_status(order_id, "rejected", reject_reason=response.get("error", "bridge error"))
                rejected_result = {
                    "order_id": order_id,
                    "symbol": order.get("symbol", ""),
                    "status": "rejected",
                    "client_order_id": client_order_id,
                    "reason": response.get("error", "bridge error"),
                    "bridge_response": response,
                }
                self._audit("rejected", rejected_result)
                results.append(rejected_result)

        result = {
            "status": "ok",
            "approval_id": approval_id,
            "orders_path": orders_path,
            "generated_at": now_iso(),
            "summary": {
                "total": len(results),
                "submitted": sum(1 for r in results if r.get("status") == "submitted"),
                "blocked": sum(1 for r in results if r.get("status") == "blocked"),
                "rejected": sum(1 for r in results if r.get("status") == "rejected"),
                "duplicate_existing": sum(1 for r in results if r.get("status") == "duplicate_existing"),
            },
            "results": results,
            "policy": asdict(self.policy),
        }
        self._write_json("qmt_execution.json", result)
        self._write_csv("qmt_execution_results.csv", results, None)
        self.order_book.save(str(self.output_dir), "order_book.json")
        self._write_html_report("qmt_execution_report.html", result)
        self._flush_audit()
        return {**result, "output_dir": str(self.output_dir)}

    def cancel_order(self, approval_id: str, qmt_order_id: str) -> dict:
        if not qmt_order_id:
            return {"status": "failed", "error": "qmt_order_id is required"}
        if self.kill_switch.is_blocked() and not self.policy.allow_cancel_when_kill_switch_triggered:
            return {"status": "blocked", "error": "kill switch blocks cancel"}
        approval = self._load_approval(approval_id)
        if not approval.get("valid"):
            return {"status": "blocked", "error": approval.get("error", "approval not found")}
        response = self.client.cancel_order(qmt_order_id, approval_id)
        result = {
            "status": "ok" if response.get("status") == "ok" else "failed",
            "approval_id": approval_id,
            "qmt_order_id": qmt_order_id,
            "bridge_response": response,
            "generated_at": now_iso(),
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json("qmt_cancel.json", result)
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
            return {"allowed": False, "reason": f"bridge health failed: {health.get('error')}"}
        return {"allowed": True, "reason": ""}

    def _check_order_risk(self, order: dict, account_resp: dict, positions_resp: dict, daily_value: float) -> dict:
        amount = float(order.get("estimated_amount", 0) or 0)
        side = order.get("side", "")
        symbol = order.get("symbol", "")
        name = order.get("name", "")
        board = "etf" if symbol.startswith(("1", "5")) else get_board(symbol)

        if not order.get("tradable", True):
            return {"allowed": False, "code": "not_tradable", "reason": order.get("block_reason", "order not tradable")}
        if board not in self.policy.allowed_boards:
            return {"allowed": False, "code": "board_blocked", "reason": f"board {board} is not allowed"}
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

        account = account_resp.get("data") or {}
        if isinstance(account, dict) and side == "buy":
            cash = float(account.get("cash", account.get("available_cash", 0)) or 0)
            if cash > 0 and amount > cash:
                return {"allowed": False, "code": "cash_insufficient", "reason": f"cash {cash:.2f} < order value {amount:.2f}"}

        if side == "sell":
            available = self._available_shares(symbol, positions_resp)
            shares = int(order.get("order_shares", 0) or 0)
            if available is not None and shares > available:
                return {"allowed": False, "code": "shares_insufficient", "reason": f"available {available} < sell shares {shares}"}

        return {"allowed": True, "code": "", "reason": ""}

    def _available_shares(self, symbol: str, positions_resp: dict):
        for p in _as_list(positions_resp.get("data")):
            if str(p.get("symbol", p.get("stock_code", ""))).split(".")[0] == symbol.split(".")[0]:
                return int(float(p.get("available_shares", p.get("can_use_amount", p.get("shares", 0))) or 0))
        return None

    def _to_qmt_order(self, order: dict, client_order_id: str) -> dict:
        return {
            "client_order_id": client_order_id,
            "order_id": order.get("order_id", ""),
            "symbol": order.get("symbol", ""),
            "side": order.get("side", ""),
            "quantity": int(order.get("order_shares", 0) or 0),
            "price": float(order.get("limit_price", 0) or 0),
            "price_type": "limit",
            "source": "hermes_order_preview",
        }

    def _find_existing_client_order(self, orders_resp: dict, client_order_id: str):
        for item in _as_list(orders_resp.get("data")):
            if item.get("client_order_id") == client_order_id:
                return item
        return None

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

    def _apply_order_statuses(self, orders: list[dict]):
        status_map = {
            "submitted": "submitted",
            "pending": "submitted",
            "partially_filled": "partially_filled",
            "filled": "filled",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "rejected": "rejected",
        }
        for o in orders:
            oid = o.get("order_id") or o.get("client_order_id")
            if not oid or not self.order_book.get_order(oid):
                continue
            status = status_map.get(str(o.get("status", "")).lower())
            if status:
                self.order_book.update_status(oid, status, filled_quantity=int(o.get("filled_quantity", 0) or 0), details=o)

    def _apply_trade_fills(self, trades: list[dict]):
        for t in trades:
            oid = t.get("order_id") or t.get("client_order_id")
            if oid and self.order_book.get_order(oid):
                self.order_book.update_fill(
                    oid,
                    int(t.get("filled_quantity", t.get("shares", 0)) or 0),
                    fill_price=float(t.get("price", 0) or 0),
                )

    def _load_json(self, path: str):
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def _write_json(self, name: str, data):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with open(self.output_dir / name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _write_csv(self, name: str, rows: list[dict], fields):
        path = self.output_dir / name
        rows = rows or []
        if fields is None:
            field_set = []
            for row in rows:
                for key in row.keys():
                    if key not in field_set:
                        field_set.append(key)
            fields = field_set or ["empty"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            if rows:
                w.writerows(rows)

    def _write_html_report(self, name: str, result: dict):
        summary = result.get("summary", {})
        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>QMT Execution</title></head>
<body><h1>QMT Execution Report</h1><p>{now_iso()}</p><pre>{json.dumps(summary, ensure_ascii=False, indent=2)}</pre></body></html>"""
        (self.output_dir / name).write_text(html, encoding="utf-8")

    def _audit(self, event: str, data: dict):
        self.audit_events.append({"event": event, "timestamp": now_iso(), "data": data})

    def _flush_audit(self):
        path = self.output_dir / "qmt_execution_audit.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for event in self.audit_events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.audit_events.clear()


def _as_list(data):
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("positions", "orders", "trades", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []
