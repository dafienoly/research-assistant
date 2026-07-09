"""V3.5.4 数据异常检测—行情延迟/价格异常/重复订单/数据缺失

依赖：KillSwitch（V3.5.1 已完成）
"""

from datetime import datetime, timedelta
from typing import Optional
from factor_lab.risk.kill_switch import KillSwitch
from factor_lab.risk.incident_log import IncidentLog


class DataAnomalyDetector:
    def __init__(self, kill_switch: KillSwitch,
                 incident_log: Optional[IncidentLog] = None):
        self.kill_switch = kill_switch
        self.incident_log = incident_log or IncidentLog()
        self.recent_orders: list[dict] = []
        self.last_market_timestamp: Optional[datetime] = None
        self.order_failures: dict[str, int] = {}

    def check_market_lag(self, current_timestamp: datetime) -> dict:
        """检查行情延迟

        Args:
            current_timestamp: 最新行情时间戳

        Returns:
            {"lag_seconds": int, "status": "ok"/"warn"/"critical"}
        """
        now = datetime.now()
        lag = (now - current_timestamp).total_seconds()

        if lag > 300:
            self.kill_switch.trigger("market_data_lag_300s",
                f"行情延迟 {lag:.0f}秒, 超过300秒阈值")
            return {"lag_seconds": int(lag), "status": "critical"}
        elif lag > 60:
            self.kill_switch.trigger("market_data_lag_60s",
                f"行情延迟 {lag:.0f}秒, 超过60秒阈值")
            return {"lag_seconds": int(lag), "status": "warn"}

        return {"lag_seconds": int(lag), "status": "ok"}

    def check_price_anomaly(self, symbol: str, price: float,
                             prev_close: float, board: str = "main") -> dict:
        """检查价格是否异常

        Args:
            board: "main"(主板±10%) / "gem"(创业板±20%) / "star"(科创板±20%)

        Returns:
            {"anomaly": bool, "reason": str, "change_pct": float}
        """
        if prev_close <= 0:
            return {"anomaly": False, "reason": "", "change_pct": 0}

        change_pct = abs(price / prev_close - 1)
        limits = {"main": 0.10, "gem": 0.20, "star": 0.20}
        limit = limits.get(board, 0.10)

        if change_pct > limit + 0.05:  # 超出正常涨跌幅+5%视为异常
            return {"anomaly": True, "reason": f"涨跌幅{change_pct:.1%}超过{board}正常范围{limit:.0%}",
                   "change_pct": round(change_pct, 4)}

        return {"anomaly": False, "reason": "", "change_pct": round(change_pct, 4)}

    def check_duplicate_order(self, symbol: str, side: str,
                               minutes_window: int = 5) -> dict:
        """检测重复订单

        检查最近 N 分钟内是否有同一symbol + 同一方向的订单

        Returns:
            {"duplicate": bool, "last_attempt": str or None, "reason": str}
        """
        cutoff = datetime.now() - timedelta(minutes=minutes_window)
        recent = [o for o in self.recent_orders
                  if o["symbol"] == symbol and o["side"] == side
                  and o["timestamp"] > cutoff]

        if recent:
            last = recent[-1]
            return {"duplicate": True,
                   "last_attempt": last["timestamp"].isoformat(),
                   "reason": f"{symbol} {side} 在过去{minutes_window}分钟内已有订单"}

        return {"duplicate": False, "last_attempt": None, "reason": ""}

    def record_order_attempt(self, symbol: str, side: str,
                              success: bool, reason: str = ""):
        """记录订单尝试"""
        self.recent_orders.append({
            "symbol": symbol,
            "side": side,
            "success": success,
            "timestamp": datetime.now(),
            "reason": reason,
        })
        # 保留最近100条
        if len(self.recent_orders) > 100:
            self.recent_orders = self.recent_orders[-100:]

        if not success:
            self.order_failures[symbol] = self.order_failures.get(symbol, 0) + 1
            total_fails = sum(self.order_failures.values())
            if total_fails >= 5:
                self.kill_switch.trigger("consecutive_order_failures_5",
                    f"连续订单失败{total_fails}次")

    def check_data_missing_rate(self, expected: int, actual: int) -> dict:
        """检查数据缺失率"""
        if expected <= 0:
            return {"missing_rate": 0, "anomaly": False}
        rate = 1 - actual / expected
        if rate > 0.30:
            self.kill_switch.trigger("data_missing_rate_high",
                f"数据缺失率{rate:.1%}超过30%阈值")
            return {"missing_rate": round(rate, 4), "anomaly": True}
        return {"missing_rate": round(rate, 4), "anomaly": False}

    def get_order_failure_rate(self, window_minutes: int = 60) -> float:
        """获取最近 N 分钟内的订单失败率"""
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        recent = [o for o in self.recent_orders if o["timestamp"] > cutoff]
        if not recent:
            return 0.0
        failures = sum(1 for o in recent if not o["success"])
        return failures / len(recent)
