# V3.5.5 企业微信风控告警 — 子代理 Spec

## 依赖：V3.5.1 (KillSwitch) ✅ | 可独立开发，但 KillSwitch 集成测试需 V3.5.1

## 现有基础设施

- `commands/factor_lab/notify.py` 已有 `notify_goal_done()` 函数
- 使用 `WECHAT_WEBHOOK_URL` 环境变量（在 `.bashrc` 中已配置）
- 格式：企业微信 Markdown 消息

## 修改文件

### 文件1: commands/factor_lab/notify.py — 扩展通知函数

当前已有：
```python
def notify_goal_done(task_name: str, summary: str):
    """发送长任务完成通知到企业微信（仅 >3min 的任务）"""
```

需要添加：

```python
import requests
import os
from datetime import datetime
from typing import Optional

WECHAT_WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "")

# 颜色映射
_COLORS = {
    "info": "info",        # 绿色
    "warning": "warning",  # 橙色
    "critical": "warning", # 橙色
    "blocker": "warning",  # 橙色
}

_SEVERITY_LABELS = {
    "info": "ℹ️ 信息",
    "warning": "⚠️ 警告", 
    "critical": "🚨 严重",
    "blocker": "🛑 阻断",
}

# 通知冷却（相同 event_type 5分钟内不重复发送）
_last_sent: dict[str, datetime] = {}

def _send_wecom_markdown(title: str, content: str) -> bool:
    """发送企业微信 Markdown 消息（通用函数）
    
    企业微信 Markdown 支持：
    - # H1（蓝色大标题）
    - **bold**
    - <font color="info">绿色</font>
    - <font color="warning">橙色</font>  
    - <font color="comment">灰色</font>
    
    Returns: True if sent successfully
    """
    if not WECHAT_WEBHOOK_URL:
        return False
    
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content}
    }
    
    try:
        resp = requests.post(WECHAT_WEBHOOK_URL, json=payload, timeout=10)
        data = resp.json()
        return resp.status_code == 200 and data.get("errcode") == 0
    except Exception as e:
        print(f"[notify] 发送失败: {e}")
        return False


def _check_cooldown(event_key: str, cooldown_seconds: int = 300) -> bool:
    """检查冷却时间，避免重复推送"""
    global _last_sent
    now = datetime.now()
    if event_key in _last_sent:
        elapsed = (now - _last_sent[event_key]).total_seconds()
        if elapsed < cooldown_seconds:
            return False  # 冷却中
    _last_sent[event_key] = now
    return True


def notify_risk_event(event_type: str, detail: str,
                       severity: str = "warning",
                       symbol: Optional[str] = None,
                       value: Optional[float] = None,
                       threshold: Optional[float] = None):
    """推送风控事件到企业微信
    
    Args:
        event_type: "kill_switch_triggered" / "market_lag" / 
                    "drawdown_warning" / "st_alert" / "regulatory_alert"
        detail: 事件详情描述
        severity: "info" / "warning" / "critical" / "blocker"
        symbol: 相关股票代码（可选）
        value: 触发值（可选）
        threshold: 阈值（可选）
    """
    # 冷却检查
    if not _check_cooldown(f"risk_{event_type}", cooldown_seconds=300):
        return False
    
    color = _COLORS.get(severity, "comment")
    label = _SEVERITY_LABELS.get(severity, "ℹ️")
    
    content = f"""# {label} 风控事件
> **类型**: {event_type}
> **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **详情**: <font color="{color}">{detail}</font>"""
    
    if symbol:
        content += f"\n> **股票**: {symbol}"
    if value is not None:
        content += f"\n> **触发值**: {value:.4f}"
    if threshold is not None:
        content += f"\n> **阈值**: {threshold:.4f}"
    
    return _send_wecom_markdown(
        title=f"{'🔴' if severity in ('critical','blocker') else '⚠️'} 风控: {event_type}",
        content=content,
    )


def notify_risk_summary(summary: dict):
    """推送每日风控总结
    
    Args:
        summary: {
            "date": "2026-07-08",
            "total_checks": 20,
            "passed": 18,
            "warnings": 1,
            "blockers": 1,
            "kill_switch_state": "triggered",
            "top_events": ["行情延迟60s", "单票-8%止损"],
        }
    """
    d = summary.get("date", "?")
    total = summary.get("total_checks", 0)
    passed = summary.get("passed", 0)
    warnings = summary.get("warnings", 0)
    blockers = summary.get("blockers", 0)
    ks_state = summary.get("kill_switch_state", "armed")
    events = summary.get("top_events", [])
    
    content = f"""# 📊 风控日结 {d}
> **检查总数**: {total}
> **通过**: <font color="info">{passed}</font>
> **警告**: <font color="warning">{warnings}</font>
> **阻断**: <font color="warning">{blockers}</font>
> **KillSwitch**: {ks_state}"""
    
    if events:
        content += "\n> **主要事件**:\n"
        for e in events:
            content += f"> - {e}\n"
    
    return _send_wecom_markdown(
        title=f"📊 风控日结 {d}",
        content=content,
    )


def notify_signal_summary(signal_date: str, strategy: str,
                           n_candidates: int, n_blocked: int,
                           top5: list[str]):
    """推送盘前信号摘要
    
    Args:
        signal_date: YYYY-MM-DD
        strategy: 策略名称
        n_candidates: 候选总数
        n_blocked: 风控排除数
        top5: Top5 股票代码/名称
    """
    content = f"""# 📈 盘前信号 {signal_date}
> **策略**: {strategy}
> **候选**: {n_candidates} 只
> **风控排除**: <font color="warning">{n_blocked}</font> 只
> **Top5**: {', '.join(top5[:5])}"""
    
    return _send_wecom_markdown(
        title=f"📈 盘前信号 {signal_date}",
        content=content,
    )


def notify_live_readiness(result: dict):
    """推送 Live Readiness 评估结果
    
    Args:
        result: 来自 live_readiness.py 的结果 dict
    """
    verdict = result.get("recommendation", "unknown")
    gaps = result.get("gaps", [])
    
    emoji = {"go": "✅", "conditional_go": "⚠️", "no_go": "❌", "insufficient_evidence": "❓"}
    e = emoji.get(verdict, "❓")
    
    content = f"""# {e} Live Readiness 评估
> **结论**: <font color="{'info' if verdict=='go' else 'warning'}">{verdict}</font>
> **缺口数**: {len(gaps)}"""
    
    if gaps:
        content += "\n> **主要缺口**:\n"
        for g in gaps[:5]:
            content += f"> - {g.get('description', str(g))}\n"
    
    return _send_wecom_markdown(
        title=f"{e} Live Readiness 评估",
        content=content,
    )
```

### 文件2: 集成到其他模块

#### 2a: KillSwitch.trigger() 集成（在 commands/factor_lab/risk/kill_switch.py）

在 `trigger()` 方法末尾添加可选通知：

```python
def trigger(self, rule_name, message="", details=None):
    # ... 现有逻辑 ...
    
    # 新增：触发时发送企业微信通知（可选）
    try:
        from factor_lab.notify import notify_risk_event
        notify_risk_event(
            event_type="kill_switch_triggered",
            detail=f"规则 {rule_name} 触发: {message}",
            severity="blocker",
        )
    except Exception:
        pass  # 通知失败不影响核心逻辑
    
    return incident
```

#### 2b: RiskSentinel.run_cycle() 集成（在 commands/factor_lab/risk/risk_sentinel.py）

在 `run_cycle()` 方法末尾添加摘要通知：

```python
def run_cycle(self) -> dict:
    results = super().run_cycle()  # 或现有逻辑
    
    # 新增：如果检测到严重问题，发送通知（每日最多1次）
    blockers = [r for r in results.get("rule_results", []) 
                if r.get("severity") == "blocker"]
    if blockers and self._should_send_daily_summary():
        try:
            from factor_lab.notify import notify_risk_summary
            summary = {
                "date": datetime.now(CST).strftime("%Y-%m-%d"),
                "total_checks": len(results.get("rule_results", [])),
                "passed": sum(1 for r in results.get("rule_results", []) 
                             if r.get("status") == "passed"),
                "warnings": len([r for r in results.get("rule_results", [])
                                if r.get("severity") == "warning"]),
                "blockers": len(blockers),
                "kill_switch_state": self.kill_switch.state,
                "top_events": [b.get("message", "") for b in blockers[:5]],
            }
            notify_risk_summary(summary)
        except Exception:
            pass
    
    return results


def _should_send_daily_summary(self) -> bool:
    """每天只发送一次风控总结"""
    today = datetime.now(CST).strftime("%Y-%m-%d")
    if getattr(self, '_last_summary_date', None) != today:
        self._last_summary_date = today
        return True
    return False
```

### 文件3: 通知配置（可选 — 非必须，有默认值即可）

新建 `commands/factor_lab/notify_config.py`（或直接在 notify.py 顶部定义）：

```python
# 通知规则配置
NOTIFICATION_RULES = {
    # key: event_type → (send: bool, cooldown_seconds: int)
    "kill_switch_triggered": {"send": True, "cooldown": 300},
    "market_lag_60s": {"send": False, "cooldown": 60},
    "market_lag_300s": {"send": True, "cooldown": 300},
    "single_stock_loss_8pct": {"send": True, "cooldown": 600},
    "drawdown_8pct": {"send": True, "cooldown": 86400},  # 每天1次
    "drawdown_12pct": {"send": True, "cooldown": 86400},  # 每天1次
    "st_alert": {"send": True, "cooldown": 86400},  # 每天1次
    "regulatory_alert": {"send": True, "cooldown": 3600},
    "daily_summary": {"send": True, "cooldown": 86400},  # 每天1次
    "signal_summary": {"send": True, "cooldown": 86400},  # 每天1次
}
```

## 注意事项

1. **不阻塞核心流程**：通知失败不抛异常、不阻断主流程
2. **冷却机制**：相同 event_type 不重复发送（默认5分钟冷却）
3. **Markdown 长度限制**：企业微信 Markdown 消息最长 4096 字节，超过时截断
4. **不存储 webhook URL**：从环境变量读取，不硬编码
5. `_send_wecom_markdown` 的 `title` 参数是企业微信通知栏显示的内容，`content` 是消息体

## 验收标准

```python
# 单元测试（不实际发送，验证函数不报错）
import os
# 没有 webhook URL 时应静默返回 False
os.environ.pop("WECHAT_WEBHOOK_URL", None)
from factor_lab.notify import notify_risk_event, notify_risk_summary

result = notify_risk_event("test", "测试通知", severity="info")
assert result == False, "无 webhook 时应返回 False"

result = notify_risk_summary({
    "date": "2026-07-08",
    "total_checks": 20,
    "passed": 18,
    "warnings": 1,
    "blockers": 1,
    "kill_switch_state": "armed",
    "top_events": [],
})
assert result == False, "无 webhook 时应返回 False"

print("✅ 单元测试通过（通知不会实际发送）")
```

## CLI 集成（可选）

在 notify.py 末尾添加 CLI 入口：

```python
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 测试发送（需要 WECHAT_WEBHOOK_URL 已设置）
        result = notify_risk_event("test", "Hermes 风控通知测试", severity="info")
        print(f"测试通知: {'✅ 已发送' if result else '❌ 发送失败'}")
```
