"""Read-only MiniQMT reconciliation; broker data never overwrites confirmed positions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from factor_lab.broker.qmt_client import QMTClient

from .authorization import AuthorizationService
from .models import Book, Position, PositionDiff
from .position_ingestion import PositionIngestionService
from .storage import DecisionLoopStore


def _first(raw: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in raw and raw[name] is not None:
            return raw[name]
    return default


class QMTReconciliationService:
    def __init__(
        self,
        store: DecisionLoopStore | None = None,
        client: QMTClient | None = None,
        failure_limit: int = 3,
    ):
        self.store = store or DecisionLoopStore()
        self.client = client or QMTClient()
        self.positions = PositionIngestionService(self.store)
        self.authorizations = AuthorizationService(self.store)
        self.failure_limit = failure_limit

    def preview(self) -> PositionDiff:
        try:
            with self.store.exclusive("reconciliation/sync", timeout=0.5):
                return self._preview_locked()
        except TimeoutError as exc:
            raise RuntimeError("position reconciliation already in progress") from exc

    def _preview_locked(self) -> PositionDiff:
        account_response = self.client.get_account()
        positions_response = self.client.get_positions()
        if account_response.get("status") != "ok":
            self._record_failure(account_response.get("error") or "account_read_failed")
            raise RuntimeError(account_response.get("error") or "QMT account read failed")
        if positions_response.get("status") != "ok" or not isinstance(positions_response.get("data"), list):
            self._record_failure(positions_response.get("error") or "positions_read_failed")
            raise RuntimeError(positions_response.get("error") or "QMT positions read failed")
        account = account_response.get("data") or {}
        rows = [self._position(raw) for raw in positions_response["data"]]
        preview = self.positions.preview_positions(rows, "miniqmt")
        reconciliation = {
            "preview_id": preview.preview_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "status": "awaiting_human_confirmation",
            "account": {
                "total_asset": _first(account, "m_dTotalAsset", "total_asset"),
                "available_cash": _first(account, "m_dAvailable", "cash"),
                "market_value": _first(account, "m_dMarketValue", "stock_value"),
                "frozen_cash": _first(account, "m_dFrozenCash", "frozen_cash"),
            },
            "broker_position_count": len(rows),
            "diff": preview.model_dump(mode="json"),
        }
        self.store.write_json("reconciliation/latest.json", reconciliation)
        self.store.append_jsonl("reconciliation/history.jsonl", reconciliation)
        self.store.write_json("reconciliation/failures.json", {"consecutive": 0, "last_error": None})
        return preview

    def confirm(self, preview_id: str, expected_hash: str):
        try:
            with self.store.exclusive("reconciliation/sync", timeout=0.5):
                snapshot = self.positions.confirm(preview_id, expected_hash)
                latest = self.store.read_json("reconciliation/latest.json", default={})
                if latest.get("preview_id") == preview_id:
                    latest.update({
                        "status": "confirmed",
                        "confirmed_at": datetime.now().astimezone().isoformat(),
                        "snapshot_id": snapshot.snapshot_id,
                    })
                    self.store.write_json("reconciliation/latest.json", latest)
                return snapshot
        except TimeoutError as exc:
            raise RuntimeError("position reconciliation already in progress") from exc

    def latest(self) -> dict:
        return self.store.read_json("reconciliation/latest.json", default={})

    def _record_failure(self, reason: str) -> None:
        holder: dict[str, dict] = {}

        def bump(state: dict) -> dict:
            consecutive = int(state.get("consecutive", 0)) + 1
            record = {
                "consecutive": consecutive,
                "last_error": reason,
                "failed_at": datetime.now().astimezone().isoformat(),
            }
            holder["record"] = record
            return record

        self.store.update_json("reconciliation/failures.json", {}, bump)
        record = holder["record"]
        self.store.append_jsonl("reconciliation/failure_history.jsonl", record)
        if record["consecutive"] >= self.failure_limit:
            today = datetime.now().astimezone().date().isoformat()
            auth = self.authorizations.current(today)
            if auth and auth.status in {"pending", "active"}:
                self.authorizations.revoke(today, "qmt_consecutive_read_failures")

    @staticmethod
    def _position(raw: dict[str, Any]) -> Position:
        symbol = str(_first(raw, "m_strInstrumentID", "stock_code", "symbol", default="")).upper()
        quantity = int(_first(raw, "m_nVolume", "volume", "amount", "shares", default=0) or 0)
        available = int(_first(raw, "m_nCanUseVolume", "can_use_volume", "can_use_amount", "available_shares", default=0) or 0)
        explicit_frozen = int(_first(raw, "m_nFrozenVolume", "frozen_volume", "frozen_shares", default=0) or 0)
        frozen = min(quantity, max(explicit_frozen, quantity - available))
        available = min(available, quantity - frozen)
        price = float(_first(raw, "m_dLastPrice", "last_price", "current_price", default=0) or 0)
        cost = float(_first(raw, "m_dOpenPrice", "open_price", "cost_price", default=0) or 0)
        instrument = "etf" if symbol.startswith(("15", "16", "50", "51", "52", "56", "58")) else "stock"
        return Position(
            symbol=symbol,
            name=str(_first(raw, "m_strInstrumentName", "stock_name", "name", default="")),
            quantity=quantity,
            available_quantity=min(available, quantity),
            frozen_quantity=frozen,
            cost_price=max(0.0, cost),
            market_price=max(0.0, price) or None,
            instrument_type=instrument,
            book=Book.SWING,
            theme="broker_import",
        )
