"""miniQMT 只读持仓接入 — 适配器 + 只读保护 + 标准化"""
import os, json
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
        """检查 miniQMT 环境是否可用 (不连接, 仅检查 SDK)"""
        if self._available is not None:
            return self._available
        try:
            import xtquant
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def get_status(self) -> dict:
        """获取适配器状态"""
        available = self.is_available()
        return {
            "adapter": "miniqmt",
            "status": "available" if available else "unavailable",
            "readonly": True,
            "xtquant_available": available,
            "connected": False,  # 需要 miniQMT 运行时才可连接
            "account_id_masked": self.account_id[-4:] if len(self.account_id) >= 4 else "",
            "account_type": self.account_type,
            "error_message": "" if available else "xtquant 未安装, miniQMT 环境不可用",
            "checked_at": datetime.now(CST).isoformat(),
            "no_trade": True,
        }

    def load_account_asset(self) -> dict:
        """读取账户资产 (骨架实现)"""
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

        # TODO: 替换为 real QMT 调用
        # from xtquant import xtdata
        # account = xtdata.get_account(self.account_id)
        return {
            "status": "unavailable",
            "total_asset": None,
            "cash": None,
            "stock_value": None,
            "etf_value": None,
            "frozen_cash": None,
            "error": "miniQMT 接口骨架, 未实现 real QMT 调用",
        }

    def load_positions(self) -> list:
        """读取当前持仓 (骨架实现)"""
        if not self.is_available():
            return []

        # TODO: 替换为 real QMT 调用
        # from xtquant import xtdata
        # positions = xtdata.get_trade_detail_data(...)
        return []

    def normalize_positions(self, raw_positions: list) -> list:
        """标准化持仓为统一格式"""
        from factor_lab.live.account_profile import get_board

        normalized = []
        for p in raw_positions:
            sym = str(p.get("stock_code", p.get("symbol", "")))
            if not sym:
                continue

            shares = int(p.get("amount", p.get("shares", 0)))
            available = int(p.get("can_use_amount", p.get("available_shares", shares)))
            price = float(p.get("last_price", p.get("current_price", 0)))
            cost = float(p.get("open_price", p.get("cost_price", 0)))
            market_value = shares * price

            normalized.append({
                "symbol": sym,
                "name": str(p.get("stock_name", p.get("name", ""))),
                "shares": shares,
                "available_shares": min(available, shares),
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
