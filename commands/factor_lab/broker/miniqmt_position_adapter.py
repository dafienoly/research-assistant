"""miniQMT 只读持仓接入 — 统一通过 QMT Bridge。"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))

# 禁止调用的交易方法列表
BLOCKED_TRADE_METHODS = [
    "buy", "sell", "order", "cancel_order", "send_order",
    "place_order", "execute_trade", "trade", "auto_trade",
]


class MiniQMTPositionAdapter:
    """miniQMT 只读持仓适配器

    只封装只读方法:
      - is_available
      - get_status
      - load_account_asset
      - load_positions
      - normalize_positions
      - export_normalized_positions

    不得封装 buy/sell/order/cancel 等交易方法。
    """

    def __init__(self, account_id: str = "", account_type: str = "STOCK"):
        self.account_id = account_id
        self.account_type = account_type
        self._available = None
        self._connection = None
        self._checked_at = None

    # ─── 只读方法 ───────────────────────────────────────────────

    def is_available(self) -> bool:
        """检查 QMT Bridge 的 XtQuantTrader 只读会话是否可用。"""
        from factor_lab.broker.qmt_client import QMTClient

        response = QMTClient().health()
        data = response.get("data") or {}
        self._available = bool(response.get("status") == "ok" and data.get("xttrader_connected"))
        self._checked_at = datetime.now(CST).isoformat()
        self._connection = response
        return self._available

    def get_status(self) -> dict:
        """获取适配器状态"""
        available = self.is_available()
        return {
            "adapter": "miniqmt",
            "status": "available" if available else "unavailable",
            "readonly": True,
            "xtquant_available": available,
            "connected": available,
            "account_id_masked": self.account_id[-4:] if len(self.account_id) >= 4 else "",
            "account_type": self.account_type,
            "error_message": "" if available else "xtquant/QMT Bridge 不可用: " + str((self._connection or {}).get("error") or "XtQuantTrader 未连接"),
            "checked_at": datetime.now(CST).isoformat(),
            "no_trade": True,
        }

    def load_account_asset(self) -> dict:
        """通过 QMT Bridge 读取账户资产。"""
        from factor_lab.broker.qmt_client import QMTClient

        if not self.is_available():
            return {
                "status": "unavailable",
                "total_asset": None,
                "cash": None,
                "stock_value": None,
                "etf_value": None,
                "frozen_cash": None,
                "error": "miniQMT 不可用",
            }

        response = QMTClient().get_account()
        if response.get("status") != "ok" or not isinstance(response.get("data"), dict):
            return {
                "status": "unavailable", "total_asset": None, "cash": None,
                "stock_value": None, "etf_value": None, "frozen_cash": None,
                "error": response.get("error") or "QMT 账户资产读取失败",
            }
        raw = response["data"]
        return {
            "status": "ok",
            "total_asset": raw.get("m_dTotalAsset", raw.get("total_asset")),
            "cash": raw.get("m_dAvailable", raw.get("cash")),
            "stock_value": raw.get("m_dMarketValue", raw.get("stock_value")),
            "etf_value": raw.get("etf_value"),
            "frozen_cash": raw.get("m_dFrozenCash", raw.get("frozen_cash")),
            "account_id_masked": self.account_id[-4:] if self.account_id else "",
            "raw": raw,
            "error": "",
        }

    def load_positions(self) -> list:
        """通过 QMT Bridge 读取当前持仓；失败显式抛错，禁止静默空仓。"""
        from factor_lab.broker.qmt_client import QMTClient

        if not self.is_available():
            raise RuntimeError("QMT Bridge/XtQuantTrader 不可用")
        response = QMTClient().get_positions()
        if response.get("status") != "ok" or not isinstance(response.get("data"), list):
            raise RuntimeError(response.get("error") or "QMT 持仓读取失败")
        return response["data"]

    def normalize_positions(self, raw_positions: list) -> list:
        """标准化持仓为统一格式"""
        from factor_lab.live.account_profile import get_board

        normalized = []
        for p in raw_positions:
            sym = str(p.get("m_strInstrumentID", p.get("stock_code", p.get("symbol", ""))))
            if not sym:
                continue

            shares = int(p.get("m_nVolume", p.get("volume", p.get("amount", p.get("shares", 0)))) or 0)
            available = int(p.get("m_nCanUseVolume", p.get("can_use_volume", p.get("can_use_amount", p.get("available_shares", shares)))) or 0)
            frozen = max(shares - available, int(p.get("m_nFrozenVolume", p.get("frozen_volume", 0)) or 0))
            price = float(p.get("m_dLastPrice", p.get("last_price", p.get("current_price", 0))) or 0)
            cost = float(p.get("m_dOpenPrice", p.get("open_price", p.get("cost_price", 0))) or 0)
            market_value = float(p.get("m_dMarketValue", p.get("market_value", shares * price)) or 0)

            normalized.append({
                "symbol": sym,
                "name": str(p.get("stock_name", p.get("name", ""))),
                "shares": shares,
                "available_shares": min(available, shares),
                "frozen_shares": frozen,
                "cost_price": round(cost, 4),
                "current_price": round(price, 4),
                "market_value": round(market_value, 2),
                "profit_loss": round(market_value - shares * cost, 2),
                "profit_loss_pct": round((price / cost - 1) * 100, 2) if cost > 0 else 0.0,
                "board": get_board(sym),
                "source": "miniqmt",
                "updated_at": datetime.now(CST).strftime("%Y-%m-%d"),
            })

        # 添加现金行
        asset = self.load_account_asset()
        if asset.get("cash") is not None:
            normalized.append({
                "symbol": "CASH",
                "name": "现金",
                "shares": int(asset["cash"]),
                "available_shares": int(asset["cash"]),
                "current_price": 1.0,
                "market_value": asset["cash"],
                "board": "cash",
                "source": "miniqmt",
            })

        return normalized

    def export_normalized_positions(self, output_path: str) -> str:
        """输出标准化持仓 CSV"""
        import csv
        from factor_lab.broker.broker_position_adapter import STANDARD_FIELDS

        positions = self.normalize_positions(self.load_positions())
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=STANDARD_FIELDS + ["profit_loss", "profit_loss_pct"], extrasaction="ignore")
            w.writeheader()
            w.writerows(positions)
        return str(path)


def verify_readonly_guard(module_path: str = None) -> dict:
    """扫描适配器代码, 确认没有交易方法"""
    import inspect

    adapter = MiniQMTPositionAdapter()
    methods = [m for m in dir(adapter) if not m.startswith("_")]

    blocked_found = []
    for m in methods:
        if m.lower() in BLOCKED_TRADE_METHODS:
            blocked_found.append(m)

    return {
        "readonly_mode": True,
        "blocked_methods": BLOCKED_TRADE_METHODS,
        "exposed_methods": methods,
        "trade_methods_called": len(blocked_found) == 0,
        "guard_status": "passed" if len(blocked_found) == 0 else "failed",
        "blocked_methods_found": blocked_found,
        "verified_at": datetime.now(CST).isoformat(),
    }
