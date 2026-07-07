"""Hermes client for Big QMT internal Python HTTP executor."""

import json
import os
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CST = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(CST).isoformat()


class QMTInternalHTTPClient:
    """HTTP client for the QMT strategy-embedded local executor."""

    def __init__(self, base_url: str = None, token: str = None, timeout: float = 5.0):
        self.base_url = (base_url or os.environ.get("QMT_INTERNAL_HTTP_BASE_URL", "http://127.0.0.1:18765")).rstrip("/")
        self.token = token if token is not None else os.environ.get("QMT_INTERNAL_HTTP_TOKEN", "")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def health(self) -> dict:
        return self._get("/health")

    def state(self) -> dict:
        return self._get("/state")

    def get_orders(self) -> dict:
        return self._get("/orders")

    def get_fills(self) -> dict:
        return self._get("/fills")

    def place_orders(self, approval_id: str, orders: list[dict], batch_id: str = "") -> dict:
        payload = {
            "approval_id": approval_id,
            "batch_id": batch_id or approval_id,
            "live_trading_enabled": True,
            "orders": orders,
        }
        return self._post("/orders/place", payload)

    def cancel_order(self, approval_id: str, qmt_order_id: str) -> dict:
        return self._post("/orders/cancel", {"approval_id": approval_id, "qmt_order_id": qmt_order_id})

    def enable_live(self) -> dict:
        return self._post("/control/enable-live", {})

    def disable_live(self) -> dict:
        return self._post("/control/disable-live", {})

    def _get(self, path: str) -> dict:
        return self._request("GET", path)

    def _post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict = None) -> dict:
        if not self.base_url:
            return self._local_error("QMT_INTERNAL_HTTP_BASE_URL is not configured")
        if not self.token:
            return self._local_error("QMT_INTERNAL_HTTP_TOKEN is not configured")

        body = None
        headers = {
            "Accept": "application/json",
            "X-Hermes-Token": self.token,
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
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
            return self._local_error(f"invalid QMT internal HTTP JSON: {exc}")

    @staticmethod
    def _local_error(message: str) -> dict:
        return {
            "status": "error",
            "request_id": "",
            "timestamp": now_iso(),
            "data": None,
            "error": message,
        }
