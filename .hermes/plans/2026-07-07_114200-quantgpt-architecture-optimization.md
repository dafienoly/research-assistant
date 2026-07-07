# QuantGPT 架构对标与投研系统优化计划

> **For Hermes:** Use subagent-driven-development to implement this plan task-by-task.

**Goal:** 对标 QuantGPT 的架构设计，识别投研系统可优化的关键差距，分阶段补齐，使因子挖掘系统具备完整的 Autonomous Factor Mining 闭环能力。

**Architecture:** QuantGPT 的 Agent-Driven Research Engine 有 6 个核心层（Agent 接口 + 表达式引擎 + 回测引擎 + 验证体系 + 数据管道 + 进化引擎）。投研系统在表达式引擎（V2 已升级）和 Alpha Factory 方面已接近，但在**研究循环自动化、双模型交叉验证、持久化知识库、进化引擎、MCP 工具化**方面存在系统级差距。

**Tech Stack:** Python, Rust (future), FastAPI, LLM (DeepSeek/Hermes), MCP, SQLite

---
## Current Context / Assumptions

### 投研系统当前位置

| 模块 | 状态 | 说明 |
|------|------|------|
| 表达式引擎 (V2) | ✅ 完整 (64算子) | 已追平 QuantGPT 算子能力 |
| Alpha Factory | ✅ 完整 (注册/晋升/退役) | 含 LLM 发现 + 治理 + 晋升流水线 |
| 因子验证 | ✅ 有 | IC/IR/Walk-Forward/Anti-Overfit |
| 因子挖掘 Agent | ⏸️ factor_mining/ | 有结构但缺完整研究循环 |
| 持久化知识库 | ❌ 无 | 研究结果靠记忆，不能跨会话复用 |
| 双模型交叉验证 | ❌ 无 | 单模型推理含 confirmation bias |
| 进化引擎 | ⏸️ 简单 iteration | 无 trajectory/meta-evolution/crossover |
| MCP 工具化 | ❌ 无 | 只有 CLI 入口，无标准化 MCP Server |
| 批处理并发回测 | ❌ 无 | 串行单因子验证 |

### QuantGPT 核心优势

QuantGPT 是 **Agent-Driven 因子研究引擎**，核心差异化：

1. **6 阶段 Research Loop** — Context Loading → Factor Design → Batch Backtest → 4-Step Analysis → Update Notes → Stop/Continue
2. **Dual-LLM Cross-Review** — 每个结论经过第二个 LLM 独立评审，解决 confirmation bias
3. **Persistent Knowledge Base** — `rules/` + `findings/` + `failures/` 跨会话积累
4. **Evolution Engine** — Trajectory Analyzer → Meta-Evolution Selector → Mutation/Crossover/Explore
5. **MCP Tool Server** — 14 个标准化工具供 Agent 直接调用
6. **Batch Evaluation** — 10-20 表达式并发回测 + 3 波重试
7. **Adversarial Validation** — 4 项破坏性检验（标签置换、时序打乱、随机池、噪声注入）
8. **Fitness Formula** — Sharpe × √(|Returns| / max(Turnover, 0.125))

---

## 分阶段实现计划

### Phase 1: 研究循环基础设施（优先级最高）

建立 Autonomous Factor Mining 的核心循环骨架，这是当前最关键的缺失。

#### Task 1.1: 创建持久化知识库结构

**Objective:** 建立 `research_notes/knowledge/{rules,findings,failures}/` 目录结构和索引系统

**Files:**
- Modify: `commands/factor_lab/__init__.py`
- Create: `commands/research_notes/__init__.py`
- Create: `commands/research_notes/knowledge/INDEX.md`
- Create: `commands/research_notes/knowledge/rules/.gitkeep`
- Create: `commands/research_notes/knowledge/findings/.gitkeep`
- Create: `commands/research_notes/knowledge/failures/.gitkeep`
- Modify: `commands/factor_lab/research_skill/skill_registry.py` — 注册 knowledge 操作
- Test: `commands/tests/test_knowledge_base.py`

**Design:**

```python
# Knowledge Base 核心数据模型
@dataclass
class KnowledgeEntry:
    entry_id: str          # uuid
    kind: str              # "rule" | "finding" | "failure"
    title: str
    hypothesis: str        # 原始假设
    evidence: str          # 证据/数据支持
    conclusion: str        # 结论
    source: str            # 来源（哪个研究方向）
    tags: list[str]        # 标签（momentum, reversal, volume 等）
    confidence: float      # 置信度 0-1
    created_at: str
    updated_at: str
    cross_reviewed: bool   # 是否经过双模型验证
    cross_review_note: str
```

**Step 1: 创建目录结构和 INDEX.md 索引**

```markdown
# Knowledge Base Index

## Rules (稳定规则)
已验证的稳定操作规则，必须遵守。

## Findings (经验发现)
可复用的经验发现有价值的方向。

## Failures (已证伪路径)
已尝试并证伪的方向，避免重复。
```

**Step 2: 实现 KnowledgeBase 类**

提供 CRUD 操作 + 搜索/查重功能：

```python
class KnowledgeBase:
    def __init__(self, root: str = "research_notes/knowledge"):
        pass
    def get_index(self) -> dict: ...
    def get_entry(self, entry_id: str) -> KnowledgeEntry: ...
    def add_entry(self, entry: KnowledgeEntry) -> str: ...
    def search(self, query: str, kind: str = None) -> list[KnowledgeEntry]: ...
    def check_duplicate_hypothesis(self, hypothesis: str) -> bool: ...
    def generate_report(self) -> str: ...
```

**Step 3: 编写测试**

```python
def test_knowledge_base_add_and_search():
    kb = KnowledgeBase(temp_dir)
    eid = kb.add_entry(KnowledgeEntry(
        kind="finding", title="测试", ...
    ))
    results = kb.search("测试")
    assert len(results) == 1
```

**Step 4: 注册到 `hermes_cli.py`**

新增 `research:knowledge-list`, `research:knowledge-add`, `research:knowledge-search` 命令

**Verification:**
- `pytest tests/test_knowledge_base.py -v` → 通过
- `python hermes_cli.py research:knowledge-add --kind finding --title "..." --hypothesis "..."` → 正常写入
- `python hermes_cli.py research:knowledge-search --query "volume"` → 返回结果

---

#### Task 1.2: 实现 6 阶段 Research Loop (研究循环 Agent)

**Objective:** 创建 `factor_lab/research_loop.py`，实现完整的 6 阶段自动因子研究循环

**Files:**
- Create: `commands/factor_lab/research_loop.py`
- Modify: `commands/hermes_cli.py` — 注册 `factor:research-loop` 命令
- Test: `commands/tests/test_research_loop.py`

**Research Loop 核心结构：**

```python
class ResearchLoop:
    """6 阶段自动因子研究循环"""
    
    def __init__(self, notebook_path: str, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base
        self.notebook_path = notebook_path
        self.iteration = 0
        self.max_rounds = 10
        self.convergence_window = 5
        self.convergence_threshold = 0.01
        self.direction = None
        
    def run(self) -> ResearchReport:
        self.phase0_context_loading()
        while not self._should_stop():
            self.phase1_factor_design()
            self.phase2_batch_backtest()
            self.phase3_four_step_analysis()
            self.phase4_update_notes()
            self.phase5_decide_continue()
        return self.phase6_report()
```

**Step 1: Phase 0 — Context Loading**

从研究笔记本 (markdown) 加载：
- 当前 baseline (表达式 + 指标)
- 已完成实验列表（避免重复）
- 下一个待探索方向
- Knowledge Base 加载

**Step 2: Phase 1 — Factor Design**

调用 LLM (`hermes -z`) 生成 1-3 个候选因子表达式：
- 输入: baseline, 已完成实验, knowledge base rules/findings/failures, 当前方向
- 输出: 表达式列表 + 每条假设

**Step 3: Phase 2 — Batch Backtest**

并发提交多个因子进行回测：
- 通过现有 `factor:validate` 机制
- 使用 ThreadPoolExecutor 并发
- 结果按 IC/IR 排序

**Step 4: Phase 3 — Four-Step Analysis**

对每个结论性判断执行：
1. **Fact Collection** — 提取指标 vs baseline 对比表
2. **Independent Judgment** — 当前 LLM 形成判断
3. **Cross-Review** — 调用第二 LLM (DeepSeek Reasoner) 独立评审
4. **Consensus** — 一致则输出，分歧则采用保守结论

```python
def cross_review(self, facts: dict, judgment: str) -> CrossReviewResult:
    """双模型交叉验证"""
    # Step 2: 当前模型判断
    primary_judgment = judgment
    
    # Step 3: 第二模型评审
    review_prompt = f"""Review this factor research conclusion independently.
    
Facts: {json.dumps(facts)}
Primary judgment: {judgment}

Evaluate: Is the reasoning sound? Missing perspectives?
Output: agree/disagree + your reasoning."""
    
    # 调用 DeepSeek Reasoner (或第二 Hermes 实例)
    secondary_review = self._call_secondary_llm(review_prompt)
    
    # Step 4: Consensus
    if self._is_agreement(primary_judgment, secondary_review):
        return CrossReviewResult(consensus=True, conclusion=primary_judgment)
    else:
        return CrossReviewResult(consensus=False, 
                                 primary=primary_judgment,
                                 secondary=secondary_review,
                                 adopted=self._more_conservative(...))
```

**Step 5: Phase 4 — Update Notes**

- 追加实验记录到 notebook
- 如果发现新 best 则更新 baseline
- 提炼可复用知识 → knowledge base
  - 稳定规则 → `rules/`
  - 经验发现 → `findings/`
  - 证伪路径 → `failures/`

**Step 6: Phase 5 — Continue/Stop Decision**

停止条件:
1. 轮次达到上限 (默认 10)
2. 收敛: 连续 N 轮无改善 (默认 5)
3. 所有方向耗尽
4. 用户手动停止

**Step 7: Phase 6 — Report**

输出:
- A/B 评级因子列表
- 关键发现
- 新增 knowledge base 条目
- 建议下一步方向

**Verification:**
- `pytest tests/test_research_loop.py -v` → 通过
- 模拟 2 轮循环验证状态机正确性
- 验证 cross-review 分歧处理逻辑

---

### Phase 2: 进化引擎

建立三阶段自适应因子迭代架构。

#### Task 2.1: Trajectory Analyzer

**Objective:** 评估因子质量轨迹（探索多样性、收敛速率、稳定性）

**Files:**
- Create: `commands/factor_lab/research_loop/trajectory.py`
- Test: `commands/tests/test_trajectory.py`

**Implementation (参考 QuantGPT trajectory_analyzer.py):**

```python
@dataclass
class TrajectoryMetrics:
    exploration_diversity: float   # 分数变异系数
    convergence_rate: float        # 分数趋势斜率
    stability_score: float         # 分数稳定性
    consecutive_declines: int      # 连续下降次数
    best_score: float
    best_expression: str
    num_iterations: int

def analyze_trajectory(iterations: list[dict]) -> TrajectoryMetrics:
    """从迭代历史计算轨迹质量指标"""
    scores = [it.get("score", 0) for it in iterations]
    if not scores:
        return TrajectoryMetrics(0, 0, 0, 0, 0, "", 0)
    # 计算各项指标...
    return TrajectoryMetrics(...)
```

---

#### Task 2.2: Meta-Evolution Strategy Selector

**Objective:** 基于轨迹特征自适应选择进化策略

**Files:**
- Create: `commands/factor_lab/research_loop/meta_evolution.py`
- Test: `commands/tests/test_meta_evolution.py`

**策略决策树 (按优先级):**
1. 嵌套过深 → SIMPLIFY
2. 高分 + 低多样性 → EXPLOIT (精调当前最优)
3. 平台期 (2+ 下降, ≥3 轮) → RECOMBINE (交叉重组历史高分)
4. 低分 + 早期 → EXPLORE (全新方向)
5. 高分多样性 + 低收敛 → EXPLORE
6. 中分 + 稳定 → EXPLOIT
7. 默认 → EXPLOIT

```python
class EvolutionStrategy(Enum):
    EXPLOIT = "exploit"        # 定向突变精调
    EXPLORE = "explore"        # 全新方向探索
    RECOMBINE = "recombine"    # 历史高分交叉重组
    SIMPLIFY = "simplify"      # 降低复杂度
```

---

#### Task 2.3: Mutation Engine + Crossover Engine

**Objective:** 基于诊断结果的定向突变 + 高分因子交叉重组

**Files:**
- Create: `commands/factor_lab/research_loop/mutation.py`
- Create: `commands/factor_lab/research_loop/crossover.py`
- Test: `commands/tests/test_mutation.py`

**MutationEngine 诊断决策:**

```python
class MutationStrategy(Enum):
    MUTATE_WINDOW         # 调整时序窗口
    MUTATE_OPERATOR       # 替换核心算子
    MUTATE_NORMALIZATION  # 添加标准化
    MUTATE_SIGNAL_TYPE    # 翻转因子方向
    MUTATE_NONLINEAR      # 引入非线性变换
    MUTATE_INTERACTION    # 组合多信号源
    SIMPLIFY              # 简化表达式
    REGENERATE_FULL       # 完全重写
```

**CrossoverEngine:**
- 从迭代历史提取 top 3-5 高分表达式
- 构建 crossover prompt: "A的窗口 + B的算子 + C的标准化"
- 调用 LLM 生成重组表达式

---

### Phase 3: 验证体系增强

#### Task 3.1: Adversarial Validation

**Objective:** 增加 4 项破坏性检验，补充现有反过拟合体系

**Files:**
- Create: `commands/factor_lab/validation/adversarial.py`
- Modify: `commands/factor_lab/validate_factor.py` — 集成 adversarial validation
- Test: `commands/tests/test_adversarial_validation.py`

**4 项检验 (参考 QuantGPT adversarial_validator.py):**

1. **Label Permutation** — 打乱 forward returns，因子应失去显著性
2. **Temporal Shuffle** — block shuffle 破坏时序结构
3. **Random Universe** — 随机股票子集，因子不应泛化
4. **Noise Injection** — 高斯噪声注入因子值，测 IC 衰减率

```python
class AdversarialValidator:
    def test_label_permutation(self, n_perms=50) -> TestResult: ...
    def test_temporal_shuffle(self, block_size=20) -> TestResult: ...
    def test_random_universe(self, n_trials=30, sample_frac=0.3) -> TestResult: ...
    def test_noise_injection(self, noise_levels=[0.1, 0.2, 0.5, 1.0, 2.0]) -> TestResult: ...
    def run_all(self) -> AdversarialResult: ...
```

---

#### Task 3.2: Fitness Formula + A-Rating System

**Objective:** 引入 QuantGPT 的 fitness 公式和 A/B/C/D 评级体系

**Files:**
- Modify: `commands/factor_lab/scoring/factor_score.py`
- Test: `commands/tests/test_fitness_scoring.py`

```python
def compute_factor_score(backtest_summary: dict, report_metrics: dict, 
                          anti_overfit_score: float = None) -> dict:
    """6 分量综合评分 + Cloud Alignment"""
    score = (ic_mean * 0.15 + ic_ir * 0.15 + stability * 0.15 
             + ao * 0.15 + group_bt * 0.15 + cloud * 0.25)
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    return {"score": score, "grade": grade, "component_scores": {...}}
```

---

### Phase 4: MCP 工具化

#### Task 4.1: MCP Server

**Objective:** 创建 MCP Server，提供标准化工具供 Agent 直接调用

**Files:**
- Create: `commands/factor_lab/mcp_server.py`
- Modify: `commands/hermes_cli.py` — 注册 `hermes mcp` 兼容入口
- Test: `commands/tests/test_mcp_server.py`

**MCP 工具清单 (参考 QuantGPT mcp_server.py):**

| 工具 | 功能 |
|------|------|
| `list_operators` | 列出可用算子 |
| `list_universes` | 列出股票池 |
| `validate_expression` | 语法校验 |
| `run_backtest` | 全流程回测 |
| `score_factor` | 复合评分 (0-100) |
| `diagnose_factor` | 诊断并建议突变策略 |
| `run_anti_overfit` | 反过拟合检验 |
| `run_walk_forward` | Walk-Forward 验证 |
| `run_adversarial` | 对抗性验证 |
| `batch_evaluate` | 批处理并发回测 |
| `knowledge_search` | 知识库搜索 |
| `knowledge_add` | 知识库写入 |

**实现方案：**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("research-assistant", ...)

@mcp.tool()
def list_operators() -> str:
    """返回所有可用表达式算子"""
    from factor_lab.expression_parser import FUNC_REGISTRY
    return json.dumps(sorted(FUNC_REGISTRY.keys()))

@mcp.tool()
def run_backtest(expression: str, universe: str = "all_watchlist",
                 start: str = "2025-01-02", end: str = "2026-06-30") -> str:
    """执行因子回测全流程"""
    ...
```

---

#### Task 4.2: Batch Evaluation 引擎

**Objective:** 支持 10-20 个表达式并发回测 + 3 波重试

**Files:**
- Create: `commands/factor_lab/research_loop/batch_evaluator.py`
- Test: `commands/tests/test_batch_evaluator.py`

```python
def batch_evaluate(
    expressions: list[str],
    params: dict,
    max_concurrent: int = 10,
    timeout: int = 600,
) -> list[dict]:
    """并发提交 + 轮询 + 排序 by fitness"""
    # Phase 1: 提交所有 (3 波重试)
    # Phase 2: 并发轮询
    # 返回按 fitness 降序
```

---

### Phase 5: 路线图 (Plan B) — Rust 引擎集成

#### Task 5.1: 编译 QuantGPT Rust Engine 为 PyO3

**Objective:** 将 QuantGPT 的 Rust 表达式引擎编译为 Python `.so` 绑定

**Files:**
- Modify: `commands/factor_lab/rust_engine/` (新建目录)
- Modify: `commands/pyproject.toml` — 添加 maturin 构建配置
- Test: `commands/tests/test_rust_bridge.py`

**步骤:**
1. Fork QuantGPT 的 `engine/` 作为子模块
2. 使用 PyO3 + maturin 创建 Python 绑定
3. 实现 `rust_bridge.py` 对接: `from engine import evaluate_expression`
4. 替换 `expression_parser.py` 后端（保持接口兼容）
5. 性能测试对比 Python vs Rust

**预期性能提升:** 10-100x (Rust 列式计算 + Rayon 并行)

---

## 测试 / Validation 策略

| 层级 | 工具 | 覆盖 |
|------|------|------|
| 单元测试 | pytest | 每个组件独立验证 |
| 集成测试 | pytest + 真实数据子集 | 端到端流程验证 |
| 回归测试 | 现有 105+ tests | 确保不破坏现有功能 |
| 验证方法 | ad-hoc 临时脚本 | 修改后立即验证 |

## Risks / Tradeoffs / Open Questions

| 风险 | 影响 | 缓解 |
|------|------|------|
| MCP Server 依赖 FastMCP 库 | Phase 4 阻塞 | 先用 CLI 命令模拟 MCP，MCP 库就绪后再改 |
| Dual-LLM Cross-Review 需要 DeepSeek API | Phase 1 依赖 | 使用 `hermes -z` 作为第二 LLM (同一模型也是双视角) |
| Rust 引擎编译复杂 | Phase 5 可能卡住 | 先完成 Python 版全部功能优化，Rust 作为可选的性能加速 |
| 研究循环可能长时间运行 | 用户体验 | 加入进度回调 + 中间结果保存 + 可中断 |
| Knowledge Base 文件 vs DB | 一致性 | 初期文件系统 (markdown)，后续可迁移到 SQLite |

## Open Questions for User

1. **Knowledge Base 存储**: 初期用 markdown 文件还是 SQLite? QuantGPT 用文件系统，我们的 alpha_registry 已用文件系统 + JSON index，建议保持一致。
2. **DeepSeek API**: 双模型交叉验证是否使用 DeepSeek Reasoner (需 API key) 还是 Hermes 自身作为第二模型?
3. **MCP 优先级**: Phase 4 MCP Server 是现在做还是在所有功能稳定后再做?
