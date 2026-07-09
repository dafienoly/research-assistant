# V3.4.1 Governed Dry Run — 子代理 Spec

## 依赖：V3.5.1 (KillSwitch) ✅ + V3.5.3 (MultiLayerRiskManager) + V3.5.2 (STWatchlist) + V3.1.1 (Real Benchmark) ✅

## 背景

V2.15 设计了 Governed Dry Run（6-Gate 全链路干跑），但从未实际完整执行过。6 个 Gate 各自分散在不同模块中，没有统一的入口脚本。

现在 V3.5.1/3/4 已经打通了风控管线，V3.1.1 修复了真实 benchmark 数据，需要一次完整的全链路干跑验证。

## 6-Gate 管线顺序

```mermaid
Gate1: Signal Generation    (factor_lab/live/signal_generator.py)
    ↓
Gate2: ETF Substitution     (factor_lab/etf/etf_selector.py)
    ↓
Gate3: Unified Report       (factor_lab/live/unified_premarket_report.py)
    ↓
Gate4: Rebalance Diff       (factor_lab/portfolio/rebalance_diff.py)
    ↓
Gate5: Order Preview        (factor_lab/order/order_preview.py) + RiskCheck (V3.5.3)
    ↓
Gate6: Risk Approval        (factor_lab/approval/risk_approval.py) + KillSwitch (V3.5.1)
```

## 修改文件

### 文件1: 新建 commands/factor_lab/daily/dry_run_pipeline.py

```python
"""V3.4.1 Governed Dry Run — 全链路干跑入口

执行顺序:
  1. Signal (Gate1)
  2. ETF Substitution (Gate2) 
  3. Unified Report (Gate3)
  4. Rebalance Diff (Gate4)
  5. Order Preview + RiskCheck (Gate5)
  6. Risk Approval (Gate6)
  
每个 Gate 输出:
  {"gate_name": "...", "verdict": "pass"/"fail"/"conditional_pass",
   "duration_seconds": 12.3, "checks": [...], "error": "..."}
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_SIGNAL_DATE = None  # 自动取当天

def run_gate1_signal(signal_date: str) -> dict:
    """Gate1: 信号生成"""
    from factor_lab.live.signal_generator import Ret5Ma20GateSignalGenerator
    gen = Ret5Ma20GateSignalGenerator()
    # ... 加载数据、生成信号
    
def run_gate2_etf(etf_plan: dict) -> dict:
    """Gate2: ETF替代"""
    from factor_lab.etf.etf_selector import ETFSelector
    ...

def run_gate3_unified(live_signal: dict, etf_plan: dict) -> dict:
    """Gate3: 统一报告"""
    from factor_lab.live.unified_premarket_report import generate_unified_report
    ...

def run_gate4_rebalance(signal: dict, current_positions: dict) -> dict:
    """Gate4: 调仓差异分析"""
    from factor_lab.portfolio.rebalance_diff import compute_rebalance_diff
    ...

def run_gate5_order_preview(rebalance_plan: dict, 
                             risk_manager: Optional[MultiLayerRiskManager] = None) -> dict:
    """Gate5: 委托预览 + 风控检查"""
    from factor_lab.order.order_preview import generate_order_preview
    from factor_lab.risk.multi_layer_risk_manager import MultiLayerRiskManager
    ...

def run_gate6_approval(order_preview: dict, 
                        kill_switch: KillSwitch = None) -> dict:
    """Gate6: 风控审批"""
    from factor_lab.approval.risk_approval import run_approval
    ...

def run_dry_run(signal_date: str = None, 
                with_risk: bool = True) -> dict:
    """执行全链路干跑
    
    Args:
        signal_date: 信号日期，默认当天
        with_risk: 是否启用风控（V3.5.1+V3.5.3）
        
    Returns:
        {"status": "completed"/"partial"/"failed",
         "gates": {gate1..gate6},
         "total_duration": 123.4,
         "blocker_gates": [...],
         "completion": {...}}
    """
    results = {}
    total_start = datetime.now()
    all_passed = True
    
    # 初始化风控（如果启用）
    kill_switch = None
    risk_manager = None
    if with_risk:
        from factor_lab.risk.kill_switch import KillSwitch
        from factor_lab.risk.multi_layer_risk_manager import MultiLayerRiskManager
        kill_switch = KillSwitch()
        risk_manager = MultiLayerRiskManager(kill_switch)
    
    # Gate1
    g1 = run_gate1_signal(signal_date)
    results["gate1_signal"] = g1
    if g1.get("verdict") == "fail": all_passed = False
    
    # Gate2
    if g1.get("verdict") != "fail":
        g2 = run_gate2_etf(...)
        results["gate2_etf"] = g2
        if g2.get("verdict") == "fail": all_passed = False
    
    # ... 继续后续 Gate
    
    return {
        "status": "completed" if all_passed else "partial",
        "gates": results,
        "total_duration": (datetime.now() - total_start).total_seconds(),
        "blocker_gates": [k for k, v in results.items() if v.get("verdict") == "fail"],
        "generated_at": datetime.now().isoformat(),
    }

def run_dry_run_and_report(signal_date: str = None):
    """执行干跑并输出报告"""
    result = run_dry_run(signal_date)
    
    # 输出结果
    output_dir = Path(f"/mnt/d/HermesReports/dry_run/{signal_date or datetime.now().strftime('%Y%m%d')}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON
    import json
    with open(output_dir / "dry_run_result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    
    # MD
    with open(output_dir / "dry_run_report.md", "w") as f:
        f.write(f"# Governed Dry Run Report\n")
        f.write(f"Date: {signal_date or datetime.now().strftime('%Y-%m-%d')}\n")
        f.write(f"Status: {result['status']}\n")
        f.write(f"Duration: {result['total_duration']:.1f}s\n\n")
        f.write("| Gate | Verdict | Duration |\n")
        f.write("|------|---------|----------|\n")
        for gate_name, gate_result in result["gates"].items():
            f.write(f"| {gate_name} | {gate_result.get('verdict', '?')} | {gate_result.get('duration_seconds', 0):.1f}s |\n")
    
    return result

if __name__ == "__main__":
    run_dry_run_and_report()
```

### 文件2: results output directory

执行结果输出到：
```
/mnt/d/HermesReports/dry_run/<yyyymmdd>/
├── dry_run_result.json
├── dry_run_report.md
└── gates/
    ├── gate1_signal.json
    ├── gate2_etf.json
    ├── gate3_unified.json
    ├── gate4_rebalance.json
    ├── gate5_order_preview.json
    └── gate6_approval.json
```

## 注意事项

1. **不自动下单**：所有 Gate 都是只读/模拟操作，不会触发真实交易
2. **数据不存在时 graceful skip**：如果某个模块的数据文件不存在，标记为 `skip` 而非 `fail`
3. **风控阻断是可选的**：`with_risk=False` 时跳过风控检查，只验证管线通畅
4. 首次运行的目的是发现阻塞点并修复，不是一次通过
5. 如果市场未开盘（周末/盘前），使用最近交易日数据

## 验收标准

```python
# 测试：执行干跑（不启用风控，最小依赖）
result = run_dry_run(signal_date="2026-07-08", with_risk=False)
print(f"状态: {result['status']}")
print(f"耗时: {result['total_duration']:.1f}s")
for g, r in result["gates"].items():
    print(f"  {g}: {r.get('verdict', '?')} ({r.get('duration_seconds', 0):.1f}s)")

# 结果应该是 6 个 Gate 全部执行完毕（可能部分 skip）
assert "gate1_signal" in result["gates"]
assert "gate6_approval" in result["gates"]
```

## CLI 集成

添加 CLI 命令（在 `factor_commands.py` 中）：

```python
@cli.command("dry-run")
@click.option("--date", default=None, help="信号日期 YYYY-MM-DD")
@click.option("--with-risk", is_flag=True, default=True)
def cmd_dry_run(date, with_risk):
    """执行全链路干跑（6-Gate）"""
    from factor_lab.daily.dry_run_pipeline import run_dry_run_and_report
    result = run_dry_run_and_report(date)
    click.echo(f"状态: {result['status']}")
    click.echo(f"耗时: {result['total_duration']:.1f}s")
```
