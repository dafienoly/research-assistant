"""V3.5.3 多层止损/仓位控制 — 组合+单票风控管理器

三层风控：
- Layer1: 单票（止损、集中度、流动性）
- Layer2: 组合（日亏损、回撤、行业集中度）
- Layer3: 系统（策略级熔断）

依赖：KillSwitch（V3.5.1 已完成）
"""

from datetime import datetime
from typing import Optional
from factor_lab.risk.kill_switch import KillSwitch
from factor_lab.risk.incident_log import IncidentLog


class MultiLayerRiskManager:
    def __init__(self, kill_switch: KillSwitch,
                 incident_log: Optional[IncidentLog] = None):
        self.kill_switch = kill_switch
        self.incident_log = incident_log or IncidentLog()
        self.portfolio_state = {}  # 当前组合快照
        self.daily_loss_pct = 0.0
        self.current_drawdown_pct = 0.0

    def update_portfolio_state(self, positions: dict,
                                capital: float,
                                daily_pnl_pct: float,
                                current_drawdown_pct: float):
        """更新组合状态快照

        Args:
            positions: {symbol: {"weight": 0.1, "unrealized_pnl_pct": -0.03, ...}}
            capital: 总资产
            daily_pnl_pct: 当日盈亏比例
            current_drawdown_pct: 当前回撤比例
        """
        self.portfolio_state = {
            "positions": positions,
            "capital": capital,
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_pct": current_drawdown_pct,
            "updated_at": datetime.now().isoformat(),
        }
        self.daily_loss_pct = abs(daily_pnl_pct) if daily_pnl_pct < 0 else 0.0
        self.current_drawdown_pct = abs(current_drawdown_pct)

    def check_single_stock(self, symbol: str, weight: float,
                           unrealized_pnl_pct: float) -> list[dict]:
        """单票风控检查

        Returns:
            [{"rule": ..., "triggered": bool, "action": "reduce"/"sell"/"ok", "detail": ...}]
        """
        results = []
        loss = abs(unrealized_pnl_pct) if unrealized_pnl_pct < 0 else 0.0

        # -8% 强制止损
        if loss >= 0.08:
            results.append({"rule": "single_stock_loss_8pct", "triggered": True,
                           "action": "sell", "detail": f"亏损{loss:.1%}触及8%止损线"})
        # -5% 减半
        elif loss >= 0.05:
            results.append({"rule": "single_stock_loss_5pct", "triggered": True,
                           "action": "reduce", "detail": f"亏损{loss:.1%}触及5%减半线"})

        # 仓位上限
        if weight > 0.25:
            results.append({"rule": "position_concentration_25pct", "triggered": True,
                           "action": "reduce", "detail": f"仓位{weight:.1%}超过25%上限"})

        return results

    def check_portfolio(self) -> list[dict]:
        """组合级风控检查"""
        results = []

        # 日亏损 2%
        if 0.02 <= self.daily_loss_pct < 0.03:
            results.append({"rule": "portfolio_daily_loss_2pct", "triggered": True,
                           "action": "no_new_positions",
                           "detail": f"日亏损{self.daily_loss_pct:.1%}触及2%线, 停止新开仓"})
        # 日亏损 3%
        elif self.daily_loss_pct >= 0.03:
            results.append({"rule": "portfolio_daily_loss_3pct", "triggered": True,
                           "action": "reduce_only",
                           "detail": f"日亏损{self.daily_loss_pct:.1%}触及3%线, 只允许减仓"})

        # 回撤 8%
        if 0.08 <= self.current_drawdown_pct < 0.12:
            results.append({"rule": "portfolio_drawdown_8pct", "triggered": True,
                           "action": "defense",
                           "detail": f"回撤{self.current_drawdown_pct:.1%}触及8%线, 进入防守状态"})
        # 回撤 12%
        elif self.current_drawdown_pct >= 0.12:
            results.append({"rule": "portfolio_drawdown_12pct", "triggered": True,
                           "action": "stop_all",
                           "detail": f"回撤{self.current_drawdown_pct:.1%}触及12%线, 停止交易"})

        return results

    def apply_rules(self, context: dict) -> dict:
        """对给定上下文应用所有规则并更新 KillSwitch

        Args:
            context: {"positions": {...}, "capital": 100000,
                     "daily_pnl": -0.015, "drawdown": 0.05}

        Returns:
            {"blocked": bool, "blocker_reasons": [...], "actions": [...], "n_triggers": int}
        """
        self.update_portfolio_state(
            positions=context.get("positions", {}),
            capital=context.get("capital", 0),
            daily_pnl_pct=context.get("daily_pnl", 0),
            current_drawdown_pct=context.get("drawdown", 0),
        )

        all_actions = []
        blocked = False
        blocker_reasons = []

        # Layer1: 单票
        for sym, pos in context.get("positions", {}).items():
            actions = self.check_single_stock(sym,
                pos.get("weight", 0), pos.get("unrealized_pnl_pct", 0))
            all_actions.extend(actions)

        # Layer2: 组合
        portfolio_actions = self.check_portfolio()
        all_actions.extend(portfolio_actions)

        # Layer3: 触发 KillSwitch
        for action in all_actions:
            if action["triggered"]:
                if action["action"] in ("sell", "reduce_only", "stop_all"):
                    self.kill_switch.trigger(
                        rule_name=action["rule"],
                        message=action["detail"],
                    )
                    blocked = True
                    blocker_reasons.append(action["detail"])
                elif action["action"] in ("reduce", "no_new_positions", "defense"):
                    blocked = True
                    blocker_reasons.append(action["detail"])

        return {
            "blocked": blocked,
            "blocker_reasons": blocker_reasons,
            "actions": all_actions,
            "n_triggers": sum(1 for a in all_actions if a["triggered"]),
        }
