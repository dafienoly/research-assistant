"""Hermes-side QMT Bridge client."""

import json
import os
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CST = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(CST).isoformat()


class QMTClient:
    """HTTP client for the Windows QMT bridge.

    The client never imports xtquant. It only talks to QMT through the local
    bridge process.
    """

    def __init__(self, base_url: str = None, timeout: float = 5.0):
        configured = (
            os.environ.get("QMT_BRIDGE_BASE_URL", "") if base_url is None else base_url
        )
        self.base_url = configured.rstrip("/")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def health(self) -> dict:
        if not self.is_configured():
            return self._local_error("QMT_BRIDGE_BASE_URL is not configured")
        return self._get("/health")

    def get_quotes(self, symbols: list[str]) -> dict:
        return self._get("/quotes", {"symbols": ",".join(symbols)})

    def get_bars(self, symbol: str, period: str = "1d", count: int = 120) -> dict:
        return self._get("/bars", {"symbol": symbol, "period": period, "count": str(count)})

    def get_account(self) -> dict:
        return self._get("/account")

    def get_positions(self) -> dict:
        return self._get("/positions")

    def get_orders(self) -> dict:
        return self._get("/orders")

    def get_trades(self) -> dict:
        return self._get("/trades")

    def place_order(self, order: dict, approval_id: str) -> dict:
        payload = {"order": order, "approval_id": approval_id}
        return self._post("/orders/place", payload)

    def cancel_order(self, qmt_order_id: str, approval_id: str) -> dict:
        return self._post("/orders/cancel", {"qmt_order_id": qmt_order_id, "approval_id": approval_id})

    def _get(self, path: str, params: dict = None) -> dict:
        query = f"?{urlencode(params)}" if params else ""
        return self._request("GET", f"{path}{query}")

    def _post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict = None) -> dict:
        if not self.is_configured():
            return self._local_error("QMT_BRIDGE_BASE_URL is not configured")
        url = f"{self.base_url}{path}"
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8")
                return json.loads(raw)
            except Exception:
                return self._local_error(f"HTTP {exc.code}: {exc.reason}")
        except (URLError, TimeoutError, OSError) as exc:
            return self._local_error(str(exc))
        except json.JSONDecodeError as exc:
            return self._local_error(f"invalid bridge JSON: {exc}")

    @staticmethod
    def _local_error(message: str) -> dict:
        return {
            "status": "error",
            "request_id": "",
            "timestamp": now_iso(),
            "data": None,
            "error": message,
        }
