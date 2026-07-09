# V3.5.4 数据异常检测 — 子代理 Spec

## 依赖：V3.5.1 (KillSwitch 守护进程) 已完成

## 修改文件

### 1. commands/factor_lab/risk/risk_rules.py — 追加数据异常规则

在 `build_default_rules()` 末尾追加：

```python
# === 数据异常规则 ===

# 行情延迟超过60秒
RiskRule(
    name="market_data_lag_60s",
    category=RuleCategory.DATA.value,
    description="行情延迟超过60秒 — 停止交易",
    severity=RuleSeverity.CRITICAL.value,
    threshold=60,
    max_consecutive_failures=2,
    cooldown_seconds=30,
    auto_recoverable=True,
    tags=["data", "market", "lag"],
)

# 行情延迟超过300秒 → 企业微信告警
RiskRule(
    name="market_data_lag_300s",
    category=RuleCategory.DATA.value,
    description="行情延迟超过300秒 — 企业微信告警",
    severity=RuleSeverity.BLOCKER.value,
    threshold=300,
    max_consecutive_failures=1,
    cooldown_seconds=120,
    auto_recoverable=True,
    tags=["data", "market", "alert"],
)

# 价格异常：单日涨跌幅>15%（非ST/创业板/科创板）
RiskRule(
    name="price_anomaly_15pct",
    category=RuleCategory.DATA.value,
    description="单日涨跌幅>15% — 价格异常标记",
    severity=RuleSeverity.WARNING.value,
    threshold=0.15,
    max_consecutive_failures=1,
    cooldown_seconds=300,
    auto_recoverable=True,
    tags=["data", "price", "anomaly"],
)

# 委托失败次数超过阈值
RiskRule(
    name="consecutive_order_failures_5",
    category=RuleCategory.EXECUTION.value,
    description="连续订单失败5次 — 停止交易",
    severity=RuleSeverity.CRITICAL.value,
    threshold=5,
    max_consecutive_failures=1,
    cooldown_seconds=600,
    auto_recoverable=True,
    tags=["execution", "order", "failure"],
)

# 数据缺失率异常
RiskRule(
    name="data_missing_rate_high",
    category=RuleCategory.DATA.value,
    description="数据缺失率超过30% — 标记数据不可用",
    severity=RuleSeverity.CRITICAL.value,
    threshold=0.30,
    max_consecutive_failures=2,
    cooldown_seconds=300,
    auto_recoverable=True,
    tags=["data", "missing"],
)

# 重复下单检测
RiskRule(
    name="duplicate_order_protection",
    category=RuleCategory.EXECUTION.value,
    description="防止重复下单 — 同一symbol 5分钟内重复买入",
    severity=RuleSeverity.WARNING.value,
    threshold=300,  # 5分钟冷却
    max_consecutive_failures=1,
    cooldown_seconds=600,
    auto_recoverable=True,
    tags=["execution", "duplicate", "protection"],
)
```

### 2. 实现数据异常检测器

文件：`commands/factor_lab/risk/data_anomaly_detector.py`

```python
class DataAnomalyDetector:
    """数据异常检测器
    
    负责：
    1. 实时监测行情延迟
    2. 检测价格异常（涨跌幅>15%, 价格跳空）
    3. 检测数据缺失率
    4. 检测订单异常（重复、连续失败）
    """
    
    def __init__(self, kill_switch: KillSwitch):
        self.kill_switch = kill_switch
        self.recent_orders: list[dict] = []  # 最近订单记录
        self.last_market_timestamp: Optional[datetime] = None
        self.order_failures: dict[str, int] = {}  # symbol → 失败次数
    
    def check_market_lag(self, current_timestamp: datetime) -> dict:
        """检查行情延迟
        
        Args:
            current_timestamp: 最新行情时间戳
            
        Returns:
            {"lag_seconds": int, "status": "ok"/"warn"/"critical"}
        """
        # 计算延迟秒数
        # >60s → 触发 market_data_lag_60s
        # >300s → 触发 market_data_lag_300s + 企业微信推送
    
    def check_price_anomaly(self, symbol: str, price: float, 
                            prev_close: float, board: str) -> dict:
        """检查价格是否异常
        
        Args:
            board: "main"/"gem"/"star"（主板/创业板/科创板）
            
        Returns:
            {"anomaly": bool, "reason": str, "change_pct": float}
        """
        # 主板 ±10%, 创业板/科创板 ±20%
        # 如果超过正常范围，标记 anomaly=True
    
    def check_data_missing_rate(self, expected: int, actual: int) -> dict:
        """检查数据缺失率
        
        Args:
            expected: 预期数据数量
            actual: 实际数据数量
        """
    
    def check_duplicate_order(self, symbol: str, side: str) -> dict:
        """检测重复订单
        
        检查最近5分钟是否已有同一symbol的相同方向订单
        """
    
    def record_order_attempt(self, symbol: str, side: str, 
                              success: bool, reason: str = ""):
        """记录订单尝试（用于重复检测和连续失败检测）"""
    
    def get_order_failure_rate(self, window_minutes: int = 60) -> float:
        """获取最近 N 分钟内的订单失败率"""
```

### 3. 集成到 RiskSentinel

修改 `commands/factor_lab/risk/risk_sentinel.py`（上一任务创建的）：

- `RiskSentinel.__init__()` 增加 `anomaly_detector: Optional[DataAnomalyDetector] = None`
- `run_cycle()` 中增加异常检测步骤：
  1. 调用 `data_health.health_check()` 检查数据新鲜度
  2. 调用 `anomaly_detector.check_market_lag()` 检查行情延迟
  3. 如果任何异常检测触发，调用 `kill_switch.trigger()`

### 4. 企业微信集成

在触发 `market_data_lag_300s` 或 `price_anomaly` 时，调用：

```python
from factor_lab.notify import notify_risk_event

def _send_anomaly_alert(self, rule_name: str, detail: str):
    notify_risk_event(
        event_type="data_anomaly",
        detail=detail,
    )
```

### 5. 验证

```python
# 创建
ks = KillSwitch()
detector = DataAnomalyDetector(ks)

# 行情延迟测试
now = datetime.now(CST)
old_time = now - timedelta(seconds=120)  # 2分钟前
result = detector.check_market_lag(old_time)
assert result["lag_seconds"] >= 120
assert result["status"] in ("warn", "critical")

# KillSwitch 应被触发（>=60s）
assert ks.is_triggered, "行情延迟>60s 应触发 KillSwitch"

# 释放后重新测试
ks.release("test", "test release")
ks.arm()

# 价格异常测试
result = detector.check_price_anomaly("000001", 15.0, 10.0, "main")  # 涨50%
assert result["anomaly"]
assert "50.0%" in result["reason"]

# 重复订单检测
r1 = detector.check_duplicate_order("000001", "buy")
assert not r1.get("duplicate", False)  # 第一次不重复
detector.record_order_attempt("000001", "buy", True)
import time
# 短时间内再试
r2 = detector.check_duplicate_order("000001", "buy")
assert r2.get("duplicate", False)  # 第二次应标记为重复
```

## 注意事项

1. DataAnomalyDetector 不直接阻断交易，通过 KillSwitch 统一管理阻断
2. 所有检测结果写入 kill_switch._incident_log
3. 行情延迟检测使用系统时间对比，需要先确认系统时间准确
4. 重复检测基于内存记录（最近5分钟的订单），不持久化到文件
5. 连续失败检测基于持久化计数器（以防进程重启丢失计数）
