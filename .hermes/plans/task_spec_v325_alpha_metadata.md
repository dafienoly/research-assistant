# V3.2.5 AlphaSpec 元数据补齐 — 子代理 Spec

## 依赖：已完成

## 现有基础设施

`commands/factor_lab/alpha/schema.py` — AlphaSpec dataclass（22 字段）
`commands/factor_lab/alpha/registry.py` — 文件系统注册表
`commands/factor_lab/alpha/lifecycle.py` — 12 状态生命周期

`alpha:list` 显示 142+ 个已注册 Alpha，但元数据不完整（缺少 delay/cost_assumption/valid_period/audit_log）。

## 目标

### 1. 扩展 AlphaSpec

在 `commands/factor_lab/alpha/schema.py` 中追加字段：

```python
@dataclass
class AlphaSpec:
    # ... 现有 22 个字段保持不变 ...
    
    # V3.2.5 新增元数据字段
    delay: int = 0                    # 信号滞后天数（0=T+0, 1=T+1等）
    cost_assumption: dict = field(default_factory=lambda: {
        "commission": 0.0003,         # 佣金费率
        "slippage_bps": 10,           # 滑点bps
        "min_commission": 5.0,        # 最低佣金
        "stamp_tax_sell": 0.001,      # 卖出印花税
    })
    valid_period: str = ""            # 有效窗口 "2023-01_to_2026-06"
    audit_log: list = field(default_factory=list)  # [{date, event, detail}]
    ic_mean_history: list = field(default_factory=list)  # [{date, ic_mean, window}]
    peer_benchmark_result: dict = field(default_factory=dict)  # 最新同池等权对比结果
```

### 2. 从因子验证结果回填元数据

在 `commands/factor_lab/alpha/registry.py` 中新增方法：

```python
def update_alpha_from_validation(alpha_id: str, validation_path: str) -> dict:
    """从因子验证结果 JSON 更新 Alpha 元数据
    
    读取 research_outputs/factor_validation/<factor>/report.json
    回填 ic_mean_history, peer_benchmark_result, score 等
    """
    import json
    from pathlib import Path
    
    val_path = Path(validation_path)
    if not val_path.exists():
        return {"error": f"验证结果不存在: {validation_path}"}
    
    with open(val_path) as f:
        data = json.load(f)
    
    updates = {}
    
    # IC 数据
    if "ic_analysis" in data:
        ic = data["ic_analysis"]
        updates["ic_mean_history"] = [{
            "date": "2026-07-08",
            "ic_mean": ic.get("ic_mean", 0),
            "ic_ir": ic.get("ic_ir", 0),
            "pos_ratio": ic.get("pos_ratio", 0),
        }]
    
    # 同池等权结果
    if "score" in data:
        score = data["score"]
        updates["grade"] = score.get("grade", "unknown")
        updates["overall_score"] = score.get("overall_score", 0)
    
    # 更新注册表
    self._update_alpha_spec(alpha_id, updates)
    return {"updated": True, "fields": list(updates.keys())}
```

### 3. CLI 补全

在 `commands/factor_lab/alpha/alpha_cli.py` 中添加：

```python
@cli.command("alpha:update-from-validation")
@click.option("--alpha-id", required=True)
@click.option("--validation-path", required=True)
def cmd_update_from_validation(alpha_id, validation_path):
    """从因子验证结果更新 Alpha 元数据"""
    from factor_lab.alpha.registry import AlphaRegistry
    reg = AlphaRegistry()
    result = reg.update_alpha_from_validation(alpha_id, validation_path)
    click.echo(f"更新: {result}")
```

### 验证

```python
# 测试 AlphaSpec 扩展
from factor_lab.alpha.schema import AlphaSpec
spec = AlphaSpec(alpha_id="test_001", name="test")
assert hasattr(spec, "delay"), "缺少 delay 字段"
assert hasattr(spec, "cost_assumption"), "缺少 cost_assumption 字段"
assert hasattr(spec, "valid_period"), "缺少 valid_period 字段"
assert hasattr(spec, "audit_log"), "缺少 audit_log 字段"
assert spec.delay == 0, "delay 默认值应为 0"
assert spec.cost_assumption["commission"] == 0.0003
print("✅ AlphaSpec 扩展验证通过")

# 测试 registry 更新
from factor_lab.alpha.registry import AlphaRegistry
import tempfile, json
reg = AlphaRegistry()

# 模拟验证结果
fake_val = Path(tempfile.mktemp(suffix=".json"))
with open(fake_val, "w") as f:
    json.dump({"ic_analysis": {"ic_mean": 0.031, "ic_ir": 0.23},
               "score": {"grade": "A", "overall_score": 86}}, f)

# 注册测试 Alpha
from factor_lab.alpha.schema import AlphaSpec
alpha = AlphaSpec(alpha_id="test_val_001", name="test_factor")
reg.register(alpha)

# 更新
result = reg.update_alpha_from_validation("test_val_001", str(fake_val))
assert result["updated"], f"更新失败: {result}"
print(f"✅ Registry 更新: {result['fields']}")

fake_val.unlink()
print("✅ AlphaSpec 元数据补齐完成")
```

## 注意事项
1. 不修改现有 AlphaSpec 的必填字段（保持向后兼容）
2. cost_assumption 有默认值，现有 Alpha 条目不报错
3. audit_log 按 append-only 模式操作