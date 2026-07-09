# V3.5.3 多层止损/仓位控制 — 子代理 Spec

## 依赖：V3.5.1 (KillSwitch 守护进程) 已完成

## 修改文件

### 1. commands/factor_lab/risk/risk_rules.py

在 `build_default_rules()` 末尾追加以下规则：

```python
# === 单票风控规则 ===

# 单票 -5% → 减半
RiskRule(
    name="single_stock_loss_5pct",
    category=RuleCategory.LOSS.value,
    description="单票亏损5% — 仓位减半",
    severity=RuleSeverity.WARNING.value,
    threshold=0.05,
    max_consecutive_failures=1,
    cooldown_seconds=3600,
    auto_recoverable=False,
    tags=["loss", "position", "stop_loss"],
)

# 单票 -8% → 强制止损
RiskRule(
    name="single_stock_loss_8pct",
    category=RuleCategory.LOSS.value,
    description="单票亏损8% — 强制止损",
    severity=RuleSeverity.CRITICAL.value,
    threshold=0.08,
    max_consecutive_failures=1,
    cooldown_seconds=7200,
    auto_recoverable=False,
    tags=["loss", "position", "stop_loss"],
)

# 单票仓位上限 25%
RiskRule(
    name="position_concentration_25pct",
    category=RuleCategory.ACCOUNT.value,
    description="单票仓位不超过25%",
    severity=RuleSeverity.CRITICAL.value,
    threshold=0.25,
    max_consecutive_failures=1,
    cooldown_seconds=600,
    auto_recoverable=True,
    tags=["position", "concentration"],
)

# 日成交额低于 5000 万禁止买入
RiskRule(
    name="low_liquidity_50m",
    category=RuleCategory.DATA.value,
    description="日成交额低于5000万禁止买入",
    severity=RuleSeverity.WARNING.value,
    threshold=50_000_000,
    max_consecutive_failures=3,
    cooldown_seconds=300,
    auto_recoverable=True,
    tags=["liquidity", "volume"],
)

# 单日买入总额上限（小资金限制）
RiskRule(
    name="daily_buy_limit",
    category=RuleCategory.ACCOUNT.value,
    description="单日买入总额不超过总资产70%",
    severity=RuleSeverity.WARNING.value,
    threshold=0.70,
    max_consecutive_failures=1,
    cooldown_seconds=86400,
    auto_recoverable=False,
    tags=["order", "limit"],
)


# === 组合风控规则 ===

# 组合当日亏损 2% → 停止新开仓
RiskRule(
    name="portfolio_daily_loss_2pct",
    category=RuleCategory.LOSS.value,
    description="当日亏损2% — 停止新开仓",
    severity=RuleSeverity.CRITICAL.value,
    threshold=0.02,
    max_consecutive_failures=1,
    cooldown_seconds=3600,
    auto_recoverable=False,
    tags=["loss", "portfolio", "circuit_breaker"],
)

# 组合当日亏损 3% → 只允许减仓
RiskRule(
    name="portfolio_daily_loss_3pct",
    category=RuleCategory.LOSS.value,
    description="当日亏损3% — 只允许减仓",
    severity=RuleSeverity.BLOCKER.value,
    threshold=0.03,
    max_consecutive_failures=1,
    cooldown_seconds=7200,
    auto_recoverable=False,
    tags=["loss", "portfolio", "circuit_breaker"],
)

# 最大回撤 8% → 进入防守状态
RiskRule(
    name="portfolio_drawdown_8pct",
    category=RuleCategory.LOSS.value,
    description="最大回撤8% — 进入防守状态",
    severity=RuleSeverity.CRITICAL.value,
    threshold=0.08,
    max_consecutive_failures=1,
    cooldown_seconds=86400,
    auto_recoverable=False,
    tags=["loss", "drawdown", "defense"],
)

# 最大回撤 12% → 停止交易
RiskRule(
    name="portfolio_drawdown_12pct",
    category=RuleCategory.LOSS.value,
    description="最大回撤12% — 停止交易",
    severity=RuleSeverity.BLOCKER.value,
    threshold=0.12,
    max_consecutive_failures=1,
    cooldown_seconds=86400,
    auto_recoverable=False,
    tags=["loss", "drawdown", "stop"],
)

# 单行业集中度 30%
RiskRule(
    name="industry_concentration_30pct",
    category=RuleCategory.ACCOUNT.value,
    description="单行业仓位不超过30%",
    severity=RuleSeverity.WARNING.value,
    threshold=0.30,
    max_consecutive_failures=3,
    cooldown_seconds=600,
    auto_recoverable=True,
    tags=["industry", "concentration"],
)
```

### 2. 新增 MultiLayerRiskManager

文件：`commands/factor_lab/risk/multi_layer_risk_manager.py`

```python
class MultiLayerRiskManager:
    """多层仓位/止损管理器
    
    三层风控：
    - Layer1: 单票（止损、集中度、流动性）
    - Layer2: 组合（日亏损、回撤、行业集中度）
    - Layer3: 系统（策略级熔断）
    """
    
    def __init__(self, kill_switch: KillSwitch, 
                 incident_log: Optional[IncidentLog] = None):
        """初始化，使用已有的 KillSwitch"""
        self.kill_switch = kill_switch
        self.portfolio_state = {}  # 当前组合快照
    
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
    
    def check_single_stock(self, symbol: str, weight: float, 
                           unrealized_pnl_pct: float) -> list[dict]:
        """单票风控检查
        
        Returns:
            [{"rule": "single_stock_loss_5pct", "triggered": True, "action": "reduce"},
             {"rule": "single_stock_loss_8pct", "triggered": False, ...}]
        """
    
    def check_portfolio(self) -> list[dict]:
        """组合级风控检查"""
    
    def get_actions(self) -> list[dict]:
        """获取建议操作（风控需要的调仓）"""
    
    def apply_rules(self, rules_context: dict) -> dict:
        """对给定上下文应用所有规则
        
        Args:
            rules_context: {
                "positions": {...},
                "capital": 100000,
                "daily_pnl": -0.015,
                "drawdown": 0.05,
                ...
            }
        Returns:
            {"blocked": bool, "reasons": [...], "actions": [...]}
        """
```

### 3. 集成到 order_preview.py

修改 `commands/factor_lab/order/order_preview.py` 中的 `generate_order_preview()`：

- 增加参数 `risk_manager: Optional[MultiLayerRiskManager] = None`
- 生成订单前调用 `risk_manager.apply_rules()` 
- 如果 blocked，所有买入订单标记为 `tradable=False`
- 如果需要减仓，风控卖出订单标记 `source="risk_sell"`
- 审计日志记录风控触发的订单修改

### 4. 验证

```python
# 创建
ks = KillSwitch()
manager = MultiLayerRiskManager(ks)

# 正常状态
manager.update_portfolio_state(
    positions={"000001": {"weight": 0.05, "unrealized_pnl_pct": 0.02}},
    capital=100000, daily_pnl_pct=0.005, current_drawdown_pct=0.02,
)
actions = manager.apply_rules({"daily_pnl": 0.005, "drawdown": 0.02})
assert not any(a.get("triggered") for a in actions), "正常状态不应触发"

# 单票亏损8%
manager.update_portfolio_state(
    positions={"000001": {"weight": 0.20, "unrealized_pnl_pct": -0.09}},
    capital=100000, daily_pnl_pct=-0.03, current_drawdown_pct=0.05,
)
actions = manager.apply_rules({"daily_pnl": -0.03, "drawdown": 0.05})
assert ks.is_triggered(), "单票-8% 应触发 KillSwitch"
```

## 注意事项

1. 规则本身不执行交易，只产生建议（`action: reduce/sell/hold`）
2. 风控建议通过 `order_preview.py` 传递给人工审批
3. 单票 -5% 触发后不直接卖，而是 weight 减半并在下次调仓时反映
4. 组合 -3% 触发后所有买入单被阻断（KillSwitch 统一管理）
5. 与 V3.5.4（数据异常检测）共享 RiskSentinel 框架
