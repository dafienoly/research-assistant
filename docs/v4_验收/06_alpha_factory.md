# Alpha Factory 报告

> **生成时间**: 2026-07-08 23:40 CST
> **审计依据**: `commands/factor_lab/alpha/schema.py`, `factor_lab/alpha/llm_alpha_discovery.py`, `factor_lab/evolution.py`
> **模块文档**: `docs/gitnexus-wiki/alpha-factory.md` (531 行)

---

## 1. Alpha Factory 架构

```
Alpha 候选生成
  ├── LLM Alpha Discovery (llm_alpha_discovery.py)
  │   ├── 产业假设生成 ← prompt 输入
  │   ├── 因子表达式映射 ← 价量字段组合
  │   └── AlphaSpec 输出
  │
  └── 因子进化 (evolution.py)
      ├── 基于现有因子模板
      ├── 随机组合/变异
      └── LLM 生成新候选
              │
              ▼
      Alpha 注册表 (schema.py: AlphaSpec)
      ├── alpha_id / name / hypothesis
      ├── status: draft / candidate / active / retired
      ├── paper_enabled / live_enabled
      ├── shadow_status: pending / observing / available / unstable
      └── validation_history: [{date, ic, sharpe}]
              │
              ▼
      Alpha 验证管线
      ├── V3 验证 → IC / IR / Walk-forward
      ├── V4 验证 → 同池基准 / 成本 / 风险归因
      └── 晋级判定 → promotion_eligible
              │
              ▼
      Alpha 退役 (alpha:retire)
      └── 状态更新 + 审计日志
```

---

## 2. 关键文件与实现

### 2.1 Alpha Schema (`commands/factor_lab/alpha/schema.py`)

```python
@dataclass
class AlphaSpec:
    alpha_id: str = ""
    name: str = ""
    description: str = ""
    hypothesis: str = ""
    universe: str = "all_watchlist"
    data_requirements: list = ["close", "volume", "amount"]
    factor_expression: str = ""
    signal_direction: str = "long"
    rebalance_frequency: str = "monthly"
    risk_constraints: dict = {"max_position_weight": 0.25, "max_drawdown": 0.15}
    author: str = "system"
    source: str = "manual"
    version: str = "0.0.1"
    status: str = "draft"           # draft/candidate/active/retired
    enabled: bool = False
    paper_enabled: bool = False
    live_enabled: bool = False
    shadow_status: str = "pending"  # pending/observing/available/unstable
    validation_history: list = []   # [{date, ic, sharpe}]
    # V3.2.5 扩展
    delay: int = 0
    cost_assumption: dict = {...}
    audit_log: list = []
```

### 2.2 LLM Alpha Discovery (`commands/factor_lab/alpha/llm_alpha_discovery.py`)

**当前能力**:
- ✅ 产业假设生成 (hypothesis 字段)
- ✅ 可计算字段映射 (factor_expression)
- ✅ 数据可得性检查 (AlphaSpecValidator)
- ❌ 字段覆盖面窄 (仅 8 个价量字段)
- ❌ 无基本面/产业链数据字段

**问题: LLM prompt 中的 Available Data Fields**:
```python
# 只有: close/open/high/low/volume/amount/returns/vwap
# 缺少: pe_ttm, pb_lf, roe, revenue_growth, profit_growth, ...
```

这导致 LLM 不可能提出基本面或产业链因子，只能生成价量公式组合。

### 2.3 因子进化 (`commands/factor_lab/evolution.py`)

**模板数量**: 仅 6 个价量模板
**输出**: evolved_candidates.json (10 个全部为价量组合)
**迭代闭环**: ⚠️ 有基于已有结果生成新因子, 但无失败归因→新因子假设闭环

---

## 3. Alpha 生命周期管理

### 3.1 CLI 命令

```bash
# Alpha 注册
python3 hermes_cli.py alpha:register --spec path/to/spec.json
python3 hermes_cli.py alpha:list
python3 hermes_cli.py alpha:show --alpha-id <id>
python3 hermes_cli.py alpha:retire --alpha-id <id>

# Alpha 评估
python3 hermes_cli.py alpha:evaluation-plan --alpha-id <id>

# Alpha 示例初始化
python3 hermes_cli.py alpha:init-samples

# 因子迁移到 Alpha 注册表
python3 hermes_cli.py alpha:migrate-existing-factors --dry-run
python3 hermes_cli.py alpha:migrate-existing-factors --category momentum

# 因子 ↔ Alpha 联动
python3 hermes_cli.py factor:sync --dry-run
python3 hermes_cli.py factor:list --alpha
```

### 3.2 Alpha 状态流转

```
draft ──→ candidate ──→ active ──→ retired
           │               │
           ▼               ▼
      evaluation     paper_enabled=true
      + V3/V4        shadow_status=observing
      validation          │
                          ▼
                    live_enabled=true
```

---

## 4. 当前状态评估

| 能力 | 状态 | 证据或缺口 |
|------|------|-----------|
| Alpha 注册表 | ✅ 存在 | `schema.py:AlphaSpec` + registry_index.json |
| LLM 产业假设生成 | ⚠️ 有框架无实质 | 数据字段仅限价量 |
| 因子公式生成 | ✅ 可工作 | 但 99% 输出为价量组合 |
| 数据可得性检查 | ⚠️ 有框架 | 未对接实际数据目录 |
| 未来函数检查 | ✅ 存在 | `future_leakage_gate.py` |
| 同池等权对比 | ✅ V4.3 已修复 | `beats_semiconductor_peer` 已替代旧 beats_peer |
| 风险暴露归因 | ✅ V4.4 已实现 | `risk_exposure.py` (6 维度) |
| 失败归因与迭代 | ❌ | 无失败归因→新假设闭环 |
| 自动晋级/退役 | ❌ | 注册表与验证结果未自动联动 |
| V4.5 半导体专属因子库 | ❌ | 未实现 |

---

## 5. LLM 角色评估

**问题: LLM 不是纯价量公式生成器?**

**当前回答**: ❌ **LLM 当前本质上是纯价量公式生成器**。

证据:
1. `evolution.py` 仅 6 个价量模板 (第 26-34 行)
2. `llm_alpha_discovery.py` 的 prompt 中 Available Data Fields 仅 8 个价量字段
3. 产出 10 个 evolved_candidates.json 全部为价量组合
4. 无基本面/产业链标签/政策/事件/海外映射因子生成能力

**改进方向** (V4.6 目标):
- 扩大 LLM 可访问的数据字段 (加入 pe/roe/revenue/industry/tags)
- 加入产业因子模板 (产业链位置/国产替代/库存周期)
- 建立失败归因→新假设闭环

---

## 6. 已知限制

1. **LLM 因子生成偏价量**: 99% 输出为价量技术指标组合
2. **Alpha 注册表与验证结果未联动**: `alpha register/retire` 命令独立运作, 未与 validate_v4 结果自动联动
3. **无 Alphalens 风格分层回测报告**: V4 验证有增强指标但无专业归因报告
4. **无因子拥挤度/衰减监控**: 无法监测因子有效期和拥挤程度
5. **无多 Alpha 组合优化**: alpha composites 存在但限于简单加权
6. **V4.5 半导体专属因子库未实现**: 这是 V4 系列的 P0 缺口
