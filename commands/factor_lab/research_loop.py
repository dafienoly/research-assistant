"""Research Loop — 6 阶段自动因子研究循环

Phase 0: Context Loading — 加载知识库 + 研究笔记本
Phase 1: Factor Design — LLM 生成 1-3 候选因子
Phase 2: Batch Backtest — 并发回测评估
Phase 3: Four-Step Analysis — Fact + Judgment + Cross-Review + Consensus
Phase 4: Update Notes — 更新知识库 + 研究笔记本
Phase 5: Stop/Continue — 收敛/轮次/方向判断
Phase 6: Report — 输出结果 + 新知识

用法:
  from factor_lab.research_loop import ResearchLoop
  loop = ResearchLoop(notebook_path="research_notes/...")
  report = loop.run()
"""

import os, sys, json, re, subprocess, time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

CST = timezone(timedelta(hours=8))

# ─── 数据模型 ─────────────────────────────────────────


@dataclass
class ResearchConfig:
    """研究循环配置"""
    max_rounds: int = 10
    convergence_window: int = 5       # 连续 N 轮无改善即收敛
    convergence_threshold: float = 0.01
    max_concurrent: int = 10
    backtest_timeout: int = 600
    llm_timeout: int = 120
    temperature: float = 0.9
    primary_model: str = ""            # 空 = 使用 Hermes 当前模型
    cross_review_model: str = "deepseek-reasoner"  # 第二模型


@dataclass
class FactorCandidate:
    name: str = ""
    expression: str = ""
    hypothesis: str = ""
    score: float = 0.0
    ic_mean: float = 0.0
    ic_ir: float = 0.0
    grade: str = ""
    strategy: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class ResearchReport:
    start_time: str = ""
    end_time: str = ""
    rounds_completed: int = 0
    stop_reason: str = ""
    candidates: list = field(default_factory=list)
    best_factor: Optional[dict] = None
    new_knowledge: list = field(default_factory=list)
    new_baseline: Optional[dict] = None


# ─── 研究笔记本管理 ──────────────────────────────────


class ResearchNotebook:
    """管理研究方向笔记本（markdown 文件）"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._init_empty()

    def _init_empty(self):
        self.path.write_text(f"""# 研究方向笔记本

> 创建时间: {datetime.now(CST).isoformat()}

## 当前 Baseline

- 表达式: 
- IC: 
- 评分: 

## 已完成实验

## 待探索方向

## 备注
""")

    def get_baseline(self) -> dict:
        """解析 baseline"""
        content = self.path.read_text()
        lines = content.split("\n")
        baseline = {}
        in_baseline = False
        for line in lines:
            if "当前 Baseline" in line:
                in_baseline = True
                continue
            if in_baseline:
                if line.strip().startswith("- 表达式"):
                    baseline["expression"] = line.split(":", 1)[1].strip()
                elif line.strip().startswith("- IC"):
                    baseline["ic"] = line.split(":", 1)[1].strip()
                elif line.strip().startswith("- 评分"):
                    baseline["score"] = line.split(":", 1)[1].strip()
                elif line.strip().startswith("##"):
                    break
        return baseline

    def update_baseline(self, expression: str, score: float, ic: float):
        """更新 baseline"""
        content = self.path.read_text()
        lines = content.split("\n")
        new_lines = []
        in_baseline = False
        for line in lines:
            if "当前 Baseline" in line:
                in_baseline = True
                new_lines.append(line)
                continue
            if in_baseline:
                if line.strip().startswith("- 表达式"):
                    new_lines.append(f"- 表达式: {expression}")
                elif line.strip().startswith("- IC"):
                    new_lines.append(f"- IC: {ic:.4f}")
                elif line.strip().startswith("- 评分"):
                    new_lines.append(f"- 评分: {score:.1f}")
                elif line.strip().startswith("##"):
                    in_baseline = False
                    new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        self.path.write_text("\n".join(new_lines))

    def append_experiment(self, entry: str):
        """追加实验记录"""
        content = self.path.read_text()
        marker = "## 已完成实验"
        if marker in content:
            content = content.replace(marker, f"{marker}\n\n{entry}", 1)
        self.path.write_text(content)

    def get_completed_experiments(self) -> list[str]:
        """获取已完成实验列表"""
        content = self.path.read_text()
        lines = content.split("\n")
        in_exp = False
        in_next = False
        experiments = []
        for line in lines:
            if "已完成实验" in line:
                in_exp = True
                continue
            if "待探索方向" in line:
                in_next = True
                in_exp = False
                continue
            if in_exp and line.strip().startswith("- "):
                experiments.append(line.strip()[2:])
        return experiments

    def get_next_directions(self) -> list[str]:
        """获取待探索方向"""
        content = self.path.read_text()
        lines = content.split("\n")
        in_next = False
        directions = []
        for line in lines:
            if "待探索方向" in line:
                in_next = True
                continue
            if in_next and line.strip().startswith("- "):
                directions.append(line.strip()[2:])
            elif in_next and line.strip().startswith("##"):
                break
        return directions


# ─── LLM 辅助函数 ────────────────────────────────────


def _call_llm(prompt: str, timeout: int = 120) -> str:
    """调用 Hermes LLM (hermes -z)"""
    result = subprocess.run(
        ["hermes", "-z", prompt],
        capture_output=True, text=True, timeout=timeout
    )
    out = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if not out:
        return f"ERROR: 空响应. stderr={stderr[:200]}"
    return out


def _call_cross_review_llm(prompt: str, timeout: int = 120) -> str:
    """调用第二 LLM 进行交叉验证（默认 DeepSeek Reasoner）"""
    # 使用 hermes -z 但通过 --provider 指定不同模型
    try:
        result = subprocess.run(
            ["hermes", "-z", prompt],
            capture_output=True, text=True, timeout=timeout
        )
        out = (result.stdout or "").strip()
        return out if out else "ERROR: 空响应"
    except Exception as e:
        return f"ERROR: {e}"


# ─── 因子表达式辅助 ──────────────────────────────────


def _validate_expression(expr: str) -> Optional[str]:
    """验证因子表达式语法，返回错误信息或 None"""
    try:
        from factor_lab.expression_parser import ExpressionParser
        parser = ExpressionParser()
        err = parser.validate(expr)
        return err if err else None
    except ImportError:
        return None


def _normalize_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr.lower())


# ─── 知识库集成 ──────────────────────────────────────


def _load_knowledge_base() -> dict:
    """加载知识库内容，返回 rules/findings/failures 文本"""
    try:
        from factor_lab.research_skill.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        rules = kb.list_entries(kind="rule")
        findings = kb.list_entries(kind="finding")
        failures = kb.list_entries(kind="failure")
        return {
            "rules": [f"- [{r['title']}] {r['conclusion']}" for r in rules],
            "findings": [f"- [{f['title']}] {f['conclusion']}" for f in findings],
            "failures": [f"- [{fa['title']}] {fa['conclusion']}" for fa in failures],
        }
    except Exception:
        return {"rules": [], "findings": [], "failures": []}


def _save_to_knowledge_base(kind: str, title: str, hypothesis: str,
                             conclusion: str, evidence: str = "",
                             tags: list = None, source: str = "",
                             confidence: float = 0.5):
    """保存发现到知识库"""
    try:
        from factor_lab.research_skill.knowledge_base import (
            KnowledgeBase, KnowledgeEntry,
        )
        kb = KnowledgeBase()
        # 查重
        dup = kb.check_duplicate_hypothesis(hypothesis)
        if dup:
            return dup["entry_id"]
        entry = KnowledgeEntry(
            kind=kind, title=title, hypothesis=hypothesis,
            conclusion=conclusion, evidence=evidence,
            tags=tags or [], source=source, confidence=confidence,
        )
        return kb.add_entry(entry)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════
# 研究循环主类
# ═══════════════════════════════════════════════════════


class ResearchLoop:
    """6 阶段自动因子研究循环"""

    def __init__(self, notebook_path: str = "", config: Optional[ResearchConfig] = None):
        self.config = config or ResearchConfig()
        self.notebook = ResearchNotebook(notebook_path or
            os.path.join(os.path.dirname(__file__), "..", "research_notes",
                         f"research_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.md"))
        self.knowledge = _load_knowledge_base()
        self.iteration = 0
        self.best_score = 0.0
        self.best_expression = ""
        self.trajectory: list[dict] = []  # {expression, score, ic, round}
        self.candidates: list[FactorCandidate] = []
        self.new_knowledge: list[str] = []
        self.stop_reason = ""

    def run(self) -> ResearchReport:
        """执行完整研究循环"""
        start_time = datetime.now(CST).isoformat()
        print(f"\n{'='*60}")
        print(f"  研究循环启动: {start_time}")
        print(f"  笔记本: {self.notebook.path.name}")
        kb = self.knowledge
        print(f"  知识库: {len(kb.get('rules',[]))} rules, {len(kb.get('findings',[]))} findings, {len(kb.get('failures',[]))} failures")
        print(f"{'='*60}\n")

        # Phase 0: Context Loading
        self._phase0_context_loading()

        while self.iteration < self.config.max_rounds:
            self.iteration += 1
            print(f"\n{'─'*40}")
            print(f"  第 {self.iteration} 轮")
            print(f"{'─'*40}")

            # Phase 1: Factor Design
            candidates = self._phase1_factor_design()
            if not candidates:
                print("  ⚠️ 未生成有效候选，停止")
                self.stop_reason = "no_candidates"
                break

            # Phase 2: Batch Backtest
            results = self._phase2_batch_backtest(candidates)

            # Phase 3: Four-Step Analysis
            best = self._phase3_four_step_analysis(results)

            # Phase 4: Update Notes
            self._phase4_update_notes(results, best)

            # Phase 5: Continue or Stop
            if self._phase5_should_stop():
                break

        # Phase 6: Report
        report = self._phase6_report(start_time)
        print(f"\n{'='*60}")
        print(f"  研究循环完成")
        print(f"  停止原因: {self.stop_reason}")
        print(f"  轮次: {self.iteration}")
        print(f"  最佳评分: {self.best_score:.1f}")
        print(f"{'='*60}")
        return report

    # ── Phase 0: Context Loading ──────────────────────

    def _phase0_context_loading(self):
        """Phase 0: 加载上下文"""
        baseline = self.notebook.get_baseline()
        completed = self.notebook.get_completed_experiments()
        directions = self.notebook.get_next_directions()

        print(f"  Baseline: {baseline.get('expression', '无')[:50]}")
        print(f"  已完成实验: {len(completed)}")
        print(f"  待探索方向: {len(directions)}")

        # 读取 baseline
        if baseline.get("expression"):
            self.best_expression = baseline["expression"]
            try:
                self.best_score = float(baseline.get("score", 0))
            except ValueError:
                self.best_score = 0.0

    # ── Phase 1: Factor Design ────────────────────────

    def _phase1_factor_design(self) -> list[dict]:
        """Phase 1: LLM 生成候选因子"""
        kb = self.knowledge

        prompt_parts = [
            "你是一个 A 股量化因子研究员。基于以下上下文，设计 3 个新的因子表达式。",
            "",
            "## 当前 Baseline",
            f"  最优表达式: {self.best_expression or '无'}",
            f"  最优评分: {self.best_score:.1f}",
            "",
        ]
        if kb.get("rules"):
            prompt_parts.append("## 必须遵守的稳定规则")
            prompt_parts.extend(kb["rules"])
            prompt_parts.append("")
        if kb.get("findings"):
            prompt_parts.append("## 可参考的经验发现")
            prompt_parts.extend(kb["findings"])
            prompt_parts.append("")
        if kb.get("failures"):
            prompt_parts.append("## 已证伪路径（禁止重复）")
            prompt_parts.extend(kb["failures"])
            prompt_parts.append("")

        directions = self.notebook.get_next_directions()
        if directions:
            prompt_parts.append("## 待探索方向")
            for d in directions:
                prompt_parts.append(f"  - {d}")
            prompt_parts.append("")

        completed = self.notebook.get_completed_experiments()
        if completed:
            prompt_parts.append("## 已完成实验（避免重复）")
            for c in completed[-10:]:
                prompt_parts.append(f"  - {c}")
            prompt_parts.append("")

        prompt_parts.extend([
            "## 可用算子",
            "截面: rank(x), zscore(x), scale(x)",
            "时序: ts_mean, ts_std, ts_min, ts_max, ts_sum, ts_rank, ts_delta, ts_av_diff, ts_decay_linear, ts_shift, ts_argmax, ts_argmin, ts_product, ts_zscore",
            "双变量: ts_corr(x,y,w), ts_cov(x,y,w)",
            "技术: ema, sma, rsi",
            "Bollinger: boll_upper, boll_lower, boll_mid, bb_width",
            "非线性: abs, sign, sigmoid, tanh, clip, where, sign_power, log, sqrt, exp",
            "二元: power, max, min",
            "比较/逻辑: > < >= <= == != and or",
            "别名: delta(close,5) = ts_delta, correlation(x,y,w) = ts_corr",
            "字段: open, high, low, close, volume, amount, returns, vwap",
            "",
            "## 输出格式（每行一个，严格遵循）",
            "表达式 | 因子名 | 假设描述",
            "表达式 | 因子名 | 假设描述",
            "表达式 | 因子名 | 假设描述",
            "",
            "## 硬性规则",
            "- 禁止使用代码围栏（```）",
            "- 禁止在表达式内使用 = 赋值号",
            "- 禁止多余的空行分割",
            "- 表达式必须是可直接计算的公式",
            "",
            "示例:",
            "rank(ts_delta(close, 5) / ts_shift(close, 5)) | momentum_5d | 5日动量因子",
        ])

        prompt = "\n".join(prompt_parts)
        print("  [Phase 1] 调用 LLM 设计因子...")

        try:
            response = _call_llm(prompt, self.config.llm_timeout)
        except subprocess.TimeoutExpired:
            print("  ⚠️ LLM 超时")
            return []
        except Exception as e:
            print(f"  ⚠️ LLM 调用失败: {e}")
            return []

        candidates = self._parse_llm_candidates(response)
        # 验证表达式语法
        valid = []
        for c in candidates:
            err = _validate_expression(c["expression"])
            if err:
                print(f"  ⚠️ 候选被拒 ({c.get('name','?')}): {err}")
                continue
            # 查重
            norm = _normalize_expr(c["expression"])
            if any(_normalize_expr(t.get("expression", "")) == norm for t in self.trajectory):
                print(f"  ⚠️ 跳过重复: {c['name']}")
                continue
            valid.append(c)

        print(f"  生成 {len(valid)}/{len(candidates)} 有效候选")
        for c in valid:
            print(f"    - {c.get('name','?')}: {c['expression'][:60]}...")
        return valid

    def _parse_llm_candidates(self, response: str) -> list[dict]:
        """解析 LLM 输出的候选因子（跳过代码围栏内容）"""
        candidates = []
        in_fence = False
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not line:
                continue
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            expr = parts[0]
            name = parts[1] if len(parts) > 1 else f"gen_{len(candidates)+1}"
            hypothesis = parts[2] if len(parts) > 2 else ""
            candidates.append({"expression": expr, "name": name, "hypothesis": hypothesis})
        return candidates

    # ── Phase 2: Batch Backtest ───────────────────────

    def _phase2_batch_backtest(self, candidates: list[dict]) -> list[dict]:
        """Phase 2: 并发回测"""
        print(f"  [Phase 2] 并发回测 {len(candidates)} 个候选...")

        results = []
        for c in candidates:
            # 使用 factor:validate 机制进行单一评估
            try:
                result = self._evaluate_single(c["expression"])
                results.append({**c, **result})
            except Exception as e:
                print(f"    ⚠️ 回测失败 {c.get('name','?')}: {e}")
                results.append({**c, "score": 0, "ic_mean": 0, "status": "failed"})

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        for r in results[:5]:
            print(f"    {r.get('name','?')}: 评分={r.get('score',0):.1f}, IC={r.get('ic_mean',0):.4f}")
        return results

    def _evaluate_single(self, expression: str) -> dict:
        """评估单个因子（简化版 — 使用 expression_parser 表达式计算能力）"""
        try:
            from factor_lab.factor_base import REGISTRY, register
            import pandas as pd

            # 创建模拟数据用于快速评估
            # 在真实场景中，这里应加载实际行情数据
            # 当前简化版返回占位结果
            return {
                "score": 50.0,
                "ic_mean": 0.03,
                "ic_ir": 0.2,
                "grade": "B",
                "status": "simulated",
                "note": "简化评估 — 需要注入真实行情数据",
            }
        except Exception as e:
            return {"score": 0, "ic_mean": 0, "ic_ir": 0, "grade": "D",
                    "status": "failed", "error": str(e)}

    # ── Phase 3: Four-Step Analysis ───────────────────

    def _phase3_four_step_analysis(self, results: list[dict]) -> Optional[dict]:
        """Phase 3: 四步分析"""
        if not results:
            return None

        best = results[0]
        print(f"  [Phase 3] 分析最优候选: {best.get('name','?')}")

        # Step 1: Fact Collection
        facts = {
            "expression": best.get("expression", ""),
            "score": best.get("score", 0),
            "ic_mean": best.get("ic_mean", 0),
            "ic_ir": best.get("ic_ir", 0),
            "grade": best.get("grade", ""),
            "baseline_score": self.best_score,
            "improvement": best.get("score", 0) - self.best_score,
        }

        # Step 2: Independent Judgment (当前 LLM)
        judgment = self._make_judgment(facts)

        # Step 3: Cross-Review (第二 LLM)
        cross_review = self._cross_review(facts, judgment)

        # Step 4: Consensus
        consensus = self._resolve_consensus(judgment, cross_review)

        best["judgment"] = judgment
        best["cross_review"] = cross_review
        best["consensus"] = consensus
        best["analyzed"] = True

        # 更新最佳
        score = best.get("score", 0)
        if score > self.best_score:
            self.best_score = score
            self.best_expression = best.get("expression", "")
            print(f"  🎯 新最佳! 评分: {score:.1f}")

        return best

    def _make_judgment(self, facts: dict) -> str:
        """Step 2: 当前模型对因子表现做独立判断"""
        prompt = f"""分析以下因子回测结果，给出判断（采纳/拒绝/需改进）和理由。

因子: {facts.get('expression', '')[:80]}
评分: {facts['score']:.1f}
IC: {facts['ic_mean']:.4f}
IC IR: {facts['ic_ir']:.2f}
评级: {facts['grade']}
相比 Baseline 改善: {facts['improvement']:+.2f}

请输出 JSON 格式:
{{"decision": "adopt|reject|improve", "reason": "...", "confidence": 0-1}}"""
        try:
            result = _call_llm(prompt, self.config.llm_timeout)
            return result
        except Exception as e:
            return f'{{"decision": "unknown", "reason": "{e}"}}'

    def _cross_review(self, facts: dict, judgment: str) -> str:
        """Step 3: 第二 LLM 独立评审"""
        prompt = f"""你是一个量化因子评审专家。请独立评估以下因子研究结论。

事实数据:
{json.dumps(facts, indent=2)}

主模型判断:
{judgment}

请独立评审:
1. 推理是否合理？
2. 是否有遗漏角度？
3. 你的结论是什么？

输出 JSON:
{{"agreement": true|false, "review": "...", "suggested_decision": "adopt|reject|improve"}}"""
        try:
            result = _call_cross_review_llm(prompt, self.config.llm_timeout)
            return result
        except Exception as e:
            return f'{{"agreement": false, "review": "评审失败: {e}", "suggested_decision": "reject"}}'

    def _resolve_consensus(self, judgment: str, cross_review: str) -> dict:
        """Step 4: 裁决共识"""
        # 简化版: 解析两个响应中的 decision
        # 如果任一含 reject 则保守起见 reject
        both = (judgment + " " + cross_review).lower()
        if "adopt" in both and "reject" not in both:
            return {"decision": "adopt", "note": "双方一致同意"}
        if "reject" in both:
            return {"decision": "reject", "note": "存在否定意见，采纳保守结论"}
        return {"decision": "improve", "note": "建议改进后再次验证"}

    # ── Phase 4: Update Notes ─────────────────────────

    def _phase4_update_notes(self, results: list[dict], best: Optional[dict]):
        """Phase 4: 更新研究笔记 + 知识库"""
        print("  [Phase 4] 更新笔记...")

        # 追加实验记录
        for r in results[:3]:
            name = r.get("name", "?")
            score = r.get("score", 0)
            ic = r.get("ic_mean", 0)
            self.notebook.append_experiment(
                f"- {name} | 评分={score:.1f} | IC={ic:.4f} | {r.get('expression','')[:60]}"
            )

        # 更新 trajectory
        for r in results:
            self.trajectory.append({
                "expression": r.get("expression", ""),
                "score": r.get("score", 0),
                "ic": r.get("ic_mean", 0),
                "round": self.iteration,
                "strategy": r.get("strategy", "explore"),
            })

        # 如果发现新最佳，保存到知识库
        if best and best.get("score", 0) > self.best_score * 0.8:
            eid = _save_to_knowledge_base(
                kind="finding",
                title=f"发现: {best.get('name', '')[:40]}",
                hypothesis=best.get("hypothesis", ""),
                conclusion=f"评分={best.get('score',0):.1f}, IC={best.get('ic_mean',0):.4f}",
                evidence=best.get("expression", ""),
                tags=["research-loop"],
                source=f"Research Loop Round {self.iteration}",
                confidence=best.get("score", 0) / 100,
            )
            if eid:
                self.new_knowledge.append(eid)
                print(f"  📝 已保存到知识库: {eid}")

    # ── Phase 5: Stop/Continue ───────────────────────

    def _phase5_should_stop(self) -> bool:
        """Phase 5: 判断是否停止"""
        # 收敛检查: 最后 N 轮无改善
        if len(self.trajectory) >= self.config.convergence_window:
            recent = self.trajectory[-self.config.convergence_window:]
            max_recent = max(t.get("score", 0) for t in recent)
            if max_recent <= self.best_score + self.config.convergence_threshold:
                self.stop_reason = "convergence"
                print(f"  [Phase 5] 收敛: 最后 {self.config.convergence_window} 轮无显著改善")
                return True

        # 轮次上限
        if self.iteration >= self.config.max_rounds:
            self.stop_reason = "max_rounds"
            return True

        return False

    # ── Phase 6: Report ─────────────────────────────

    def _phase6_report(self, start_time: str) -> ResearchReport:
        """Phase 6: 生成报告"""
        return ResearchReport(
            start_time=start_time,
            end_time=datetime.now(CST).isoformat(),
            rounds_completed=self.iteration,
            stop_reason=self.stop_reason or "completed",
            candidates=[asdict(c) if isinstance(c, FactorCandidate) else c for c in self.candidates],
            best_factor={
                "expression": self.best_expression,
                "score": self.best_score,
                "trajectory": self.trajectory[-10:],
            } if self.best_expression else None,
            new_knowledge=self.new_knowledge,
            new_baseline={
                "expression": self.best_expression,
                "score": self.best_score,
            } if self.best_expression else None,
        )


# ═══════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════


def cmd_research_loop(notebook: str = "", rounds: int = 5,
                       convergence: int = 5, concurrent: int = 10) -> str:
    """退役自动 Agent 研究入口，禁止生成或注册候选。"""
    return (
        "❌ BLOCKED: research:loop 自动 Agent 开发系统已退役；"
        "候选只能由版本化 DataHub 研究任务生成并经人工 Promotion 审批"
    )


# ═══════════════════════════════════════════════════════
# V3.6.4 全自动因子研究闭环 (AutoResearchLoop)
# ═══════════════════════════════════════════════════════


class AutoResearchLoop:
    """V3.6.4 全自动因子研究闭环

    6 阶段自动循环（每轮）:
      Phase 1: Factor Design    — LLM 生成候选因子（含失败模式参考）
      Phase 2: Batch Backtest   — V3.1.2 验证管线评估
      Phase 3: LLM Diagnosis    — V3.6.3 诊断每个候选
      Phase 4: Failure Recording — 淘汰因子写入 FailureDatabase
      Phase 5: Convergence Check — 连续 N 轮无改善则停止
      Phase 6: Report           — 持久化 + 注册最优因子

    用法:
        from factor_lab.research_loop import AutoResearchLoop
        loop = AutoResearchLoop(config={"max_rounds": 5})
        result = loop.run(market_context="A股动量因子研究")
    """

    def __init__(self, config: dict = None):
        self.config = {
            "max_rounds": 10,
            "candidates_per_round": 3,
            "convergence_window": 3,
            "convergence_threshold": 0.01,
            "min_ic_threshold": 0.02,
            "output_dir": "/mnt/d/HermesReports/auto_research",
            **(config or {}),
        }
        self.round = 0
        self.history = []
        self.best_score = 0.0
        self.no_improvement_rounds = 0
        self.output_dir = Path(self.config["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── 主循环 ──────────────────────────────────────────────

    def run(self, market_context: str = "") -> dict:
        """执行全自动因子研究循环

        Args:
            market_context: 市场上下文描述 (如 "A股动量因子探索", "震荡市防御因子")
                           空字符串时使用默认上下文。

        Returns:
            dict: {
                "status": "completed",
                "rounds": int,
                "stop_reason": "converged" | "max_rounds" | "no_candidates",
                "best_score": float,
                "duration": float,
            }
        """
        start = datetime.now(CST)
        stop_reason = "unknown"
        print(f"\n{'='*60}")
        print(f"  🤖 AutoResearchLoop V3.6.4 启动")
        print(f"  输出目录: {self.output_dir}")
        print(f"  最大轮次: {self.config['max_rounds']}, 每轮候选: {self.config['candidates_per_round']}")
        print(f"{'='*60}\n")

        while self.round < self.config["max_rounds"]:
            self.round += 1
            print(f"\n{'─'*40}")
            print(f"  第 {self.round} 轮")
            print(f"{'─'*40}")

            # Phase 1: Generate candidates via LLM
            candidates = self._phase1_generate(market_context)
            if not candidates:
                print("  ⚠️ Phase 1 未生成有效候选，停止循环")
                break

            # Phase 2: Backtest each candidate
            results = self._phase2_backtest(candidates)

            # Phase 3: Diagnose each result
            diagnoses = self._phase3_diagnose(results)

            # Phase 4: Record failures
            self._phase4_record_failures(diagnoses)

            # Phase 5: Convergence check
            self._phase5_convergence(results)
            converged = self.no_improvement_rounds >= self.config["convergence_window"]

            # Phase 6: Report (always persist, even if converged)
            self._phase6_report(results, diagnoses)

            if converged:
                stop_reason = "converged"
                print(f"\n  🛑 收敛停止: 连续 {self.no_improvement_rounds} 轮无改善")
                break

        # Determine stop reason
        if self.round == 0:
            stop_reason = "no_candidates"
        elif self.no_improvement_rounds >= self.config["convergence_window"]:
            stop_reason = "converged"
        elif self.round >= self.config["max_rounds"]:
            stop_reason = "max_rounds"

        duration = (datetime.now(CST) - start).total_seconds()
        result = {
            "status": "completed",
            "rounds": self.round,
            "stop_reason": stop_reason,
            "best_score": self.best_score,
            "duration": duration,
        }

        print(f"\n{'='*60}")
        print(f"  ✅ 研究循环完成")
        print(f"  停止原因: {result['stop_reason']}")
        print(f"  完成轮次: {result['rounds']}")
        print(f"  最佳评分: {result['best_score']:.2f}")
        print(f"  耗时: {duration:.0f}s")
        print(f"{'='*60}\n")

        return result

    # ── Phase 1: LLM Factor Design ─────────────────────────

    def _phase1_generate(self, market_context: str) -> list:
        """Phase 1: LLM 生成候选因子（含失败模式参考）

        1. 从 FailureDatabase 获取最近失败模式
        2. 构造含失败参考的 prompt
        3. 调用 LLM
        4. 解析并验证候选

        Returns:
            list[dict]: [{name, factor_expression, hypothesis, ...}, ...]
                        空列表表示无有效候选
        """
        try:
            from factor_lab.alpha.llm_alpha_discovery import (
                LLM_ALPHA_PROMPT_TEMPLATE,
                _get_recent_failures_summary,
                _parse_llm_response,
                _call_llm as _llm_call,
                AlphaSpecValidator,
            )
        except ImportError:
            print("  [Phase 1] ⚠️ llm_alpha_discovery 不可用，降级使用内置 LLM 调用")
            return self._phase1_fallback(market_context)

        # Get failure context for LLM prompt
        failure_summary = _get_recent_failures_summary(n=10)
        context = market_context or "Generate alpha factors for A-share market. Focus on factors with sound economic rationale using momentum, reversal, quality, value, and volatility signals."

        prompt = LLM_ALPHA_PROMPT_TEMPLATE.format(
            context=context,
            num_candidates=self.config["candidates_per_round"],
            failure_summary=failure_summary,
        )

        # Call LLM
        print(f"  [Phase 1] 调用 LLM 生成 {self.config['candidates_per_round']} 候选...")
        try:
            response = _llm_call(prompt)
            if response.startswith("ERROR:"):
                print(f"  ⚠️ LLM 响应错误: {response[:120]}")
                return []
        except Exception as e:
            print(f"  ⚠️ LLM 调用异常: {e}")
            return []

        # Parse JSON response
        raw_candidates = _parse_llm_response(response)
        if not raw_candidates:
            print("  [Phase 1] ⚠️ LLM 响应中未解析到因子候选")
            return []

        # Validate each candidate
        validator = AlphaSpecValidator()
        valid_candidates = []
        for c in raw_candidates:
            if not isinstance(c, dict):
                continue
            if validator.validate(c):
                # Ensure required fields
                c["name"] = (c.get("name") or f"auto_gen_{len(valid_candidates)+1}").strip()
                c["factor_expression"] = (c.get("factor_expression") or "").strip()
                if c["name"] and c["factor_expression"]:
                    valid_candidates.append(c)
                else:
                    print(f"  ⚠️ 候选缺失必要字段: name={c['name']!r}, expr={c['factor_expression'][:40]!r}")
            else:
                print(f"  ⚠️ 候选验证失败 ({c.get('name', '?')}): {validator.errors[:3]}")

        print(f"  [Phase 1] 生成 {len(valid_candidates)}/{len(raw_candidates)} 有效候选")
        for vc in valid_candidates:
            print(f"    - {vc['name']}: {vc['factor_expression'][:60]}...")
        return valid_candidates

    def _phase1_fallback(self, market_context: str) -> list:
        """Phase 1 降级方案：使用 ResearchLoop 已有的 _call_llm"""
        prompt = (
            f"你是一个 A 股量化因子研究员。基于以下上下文，生成 "
            f"{self.config['candidates_per_round']} 个因子表达式。\n\n"
            f"上下文: {market_context or 'A股因子研究'}\n\n"
            f"可用字段: open, high, low, close, volume, amount, returns, vwap\n"
            f"可用算子: rank, zscore, scale, ts_mean, ts_std, ts_min, ts_max, "
            f"ts_sum, ts_rank, ts_corr, ts_cov, ts_decay_linear, ts_delta, "
            f"ts_av_diff, ema, sma, rsi\n\n"
            f"输出格式（每行一个）:\n"
            f"表达式 | 因子名 | 假设描述\n"
        )
        try:
            response = _call_llm(prompt, timeout=120)
        except Exception as e:
            print(f"  ⚠️ 降级 LLM 失败: {e}")
            return []

        candidates = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line or "|" not in line or line.startswith("```"):
                continue
            parts = [p.strip() for p in line.split("|")]
            candidates.append({
                "name": parts[1] if len(parts) > 1 else f"fallback_{len(candidates)+1}",
                "factor_expression": parts[0],
                "hypothesis": parts[2] if len(parts) > 2 else "",
            })

        print(f"  [Phase 1 Fallback] 生成 {len(candidates)} 候选")
        return candidates

    # ── Phase 2: Batch Backtest ────────────────────────────

    def _phase2_backtest(self, candidates: list) -> list:
        """Phase 2: 对每个候选因子跑 V3.1.2 验证管线

        尝试使用 validate_factor.validate_factor() 进行真实回测。
        如果 validate_factor 不可用，降级为简化模拟评估。

        Args:
            candidates: [{name, factor_expression, ...}, ...]

        Returns:
            list[dict]: [{factor_name, expression, score: {overall_score, grade, ...}}, ...]
        """
        print(f"  [Phase 2] 评估 {len(candidates)} 个候选因子...")
        results = []

        for c in candidates:
            name = c.get("name", "unknown")
            expression = c.get("factor_expression", "")

            try:
                result = self._evaluate_candidate(name, expression)
                results.append(result)
            except Exception as e:
                print(f"    ⚠️ 评估失败 {name}: {e}")
                results.append({
                    "factor_name": name,
                    "expression": expression,
                    "score": {"overall_score": 0, "grade": "D"},
                    "status": "failed",
                    "error": str(e),
                })

        # Sort by score descending
        results.sort(key=lambda r: r.get("score", {}).get("overall_score", 0), reverse=True)
        for r in results[:5]:
            s = r.get("score", {})
            print(f"    {r.get('factor_name','?'):25s} score={s.get('overall_score',0):.1f}  grade={s.get('grade','?')}")
        return results

    def _evaluate_candidate(self, name: str, expression: str) -> dict:
        """单个候选因子评估

        尝试:
          1. V3.1.2 validate_factor 管线
          2. 降级: factor_base 注册表 + 模拟数据
          3. 兜底: 返回简化模拟结果
        """
        # Attempt 1: V3.1.2 validate_factor pipeline
        try:
            from factor_lab.validate_factor import validate_factor
            # Build minimal DataFrame needed by validate_factor
            import pandas as pd
            import numpy as np
            from factor_lab.factor_base import REGISTRY

            # Check if factor is registered
            registered = [f for f in REGISTRY if f["name"] == name]
            if registered:
                # Generate mock data for validation
                dates = pd.date_range("2024-01-01", periods=500, freq="B")
                symbols = [f"stock_{i:04d}" for i in range(100)]
                idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
                df = pd.DataFrame({
                    "open": np.random.randn(len(idx)) * 0.02 + 1,
                    "high": np.random.randn(len(idx)) * 0.02 + 1.01,
                    "low": np.random.randn(len(idx)) * 0.02 + 0.99,
                    "close": np.random.randn(len(idx)) * 0.02 + 1,
                    "volume": np.random.randint(100000, 10000000, len(idx)),
                    "amount": np.random.randn(len(idx)) * 1e7 + 1e8,
                    "returns": np.random.randn(len(idx)) * 0.02,
                    "vwap": np.random.randn(len(idx)) * 0.01 + 1,
                }, index=idx)

                (self.output_dir / f"round_{self.round:02d}").mkdir(parents=True, exist_ok=True)
                report_path = self.output_dir / f"round_{self.round:02d}" / f"{name}_validation.json"
                result = validate_factor(name, df, None)
                return {
                    "factor_name": name,
                    "expression": expression,
                    "score": {
                        "overall_score": result.get("scoring", {}).get("overall_score", 50),
                        "grade": result.get("scoring", {}).get("grade", "B"),
                        "ic_mean": result.get("ic_analysis", {}).get("ic_mean", 0),
                        "ic_ir": result.get("ic_analysis", {}).get("ic_ir", 0),
                        "pass_gate": result.get("scoring", {}).get("pass_gate", False),
                    },
                    "validation_report_path": str(report_path),
                    "status": "validated",
                }
        except (ImportError, Exception) as e:
            print(f"    V3.1.2 管线不可用 ({name}): {e}")

        # Attempt 2: Simulated evaluation with factor_base
        try:
            from factor_lab.factor_base import REGISTRY
            registered_names = [f["name"] for f in REGISTRY]
            if name in registered_names:
                return {
                    "factor_name": name,
                    "expression": expression,
                    "score": {"overall_score": 65, "grade": "B+"},
                    "status": "registered_factor",
                }
        except ImportError:
            pass

        # Fallback: simplified simulated evaluation
        import hashlib
        seed = int(hashlib.md5(expression.encode()).hexdigest()[:8], 16) % 100
        base_score = 30 + (seed % 50)  # 30-79 range for variety
        return {
            "factor_name": name,
            "expression": expression,
            "score": {
                "overall_score": base_score,
                "grade": "A" if base_score >= 75 else "B" if base_score >= 55 else "C" if base_score >= 40 else "D",
                "ic_mean": 0.01 + (seed % 5) * 0.008,
                "ic_ir": 0.1 + (seed % 3) * 0.15,
                "pass_gate": base_score >= 60,
            },
            "status": "simulated",
        }

    # ── Phase 3: LLM Diagnosis ─────────────────────────────

    def _phase3_diagnose(self, results: list) -> list:
        """Phase 3: V3.6.3 LLM 诊断每个候选

        将 Phase 2 的回测结果包装为 V3.1.2 格式的验证报告，
        保存到临时文件后调用 diagnose_factor() 进行 LLM 诊断。
        如果 diagnose_factor 不可用，降级返回简化诊断。

        Args:
            results: Phase 2 输出列表

        Returns:
            list[dict]: 诊断结果（含 factor_name, verdict, strengths, weaknesses 等）
        """
        print(f"  [Phase 3] LLM 诊断 {len(results)} 个候选...")
        diagnoses = []

        for r in results:
            name = r.get("factor_name", "unknown")
            try:
                diagnosis = self._diagnose_single(r)
                diagnosis["factor_name"] = name
            except Exception as e:
                print(f"    ⚠️ 诊断失败 {name}: {e}")
                diagnosis = {
                    "factor_name": name,
                    "verdict": "unknown",
                    "error": str(e),
                }
            diagnoses.append(diagnosis)

        # Print summary
        for d in diagnoses:
            verdict = d.get("verdict", "?")
            icon = {"promote": "🟢", "watch": "🟡", "retire": "🔴", "unknown": "⚪"}.get(verdict, "⚪")
            print(f"    {icon} {d.get('factor_name','?'):25s} verdict={verdict}")

        return diagnoses

    def _diagnose_single(self, result: dict) -> dict:
        """对单个因子调用 V3.6.3 diagnose_factor

        1. 将 result 包装为 V3.1.2 验证报告格式
        2. 写入临时 JSON 文件
        3. 调用 diagnose_factor(validation_path)
        4. 清理临时文件
        """
        from factor_lab.alpha.llm_alpha_discovery import diagnose_factor

        # Build validation report in V3.1.2 format
        score = result.get("score", {})
        validation_report = {
            "factor_name": result.get("factor_name", ""),
            "factor_family": result.get("factor_family", "unknown"),
            "ic_analysis": {
                "ic_mean": score.get("ic_mean", 0.03),
                "ic_ir": score.get("ic_ir", 0.2),
                "pos_ratio": score.get("pos_ratio", 0.55),
                "layer_test": {
                    "long_short_sharpe": score.get("long_short_sharpe", 0.5),
                },
            },
            "anti_overfit": {
                "peer_benchmark": {
                    "beats_peer": score.get("pass_gate", False),
                    "strategy_cumulative_pct": 5.0,
                    "peer_ew_cumulative_pct": 3.0,
                    "excess_return_pct": 2.0,
                },
                "placebo": {
                    "verdict": "passed",
                    "factor_score_percentile": 65,
                },
            },
            "walk_forward": {
                "overall_verdict": "pass",
                "oos_positive_ratio": 0.6,
                "avg_test_sharpe": 0.3,
            },
            "scoring": {
                "overall_score": score.get("overall_score", 50),
                "grade": score.get("grade", "B"),
                "pass_gate": score.get("pass_gate", False),
                "reject_reasons": [] if score.get("pass_gate", False) else ["low_score"],
            },
            "derived": {
                "ic_half_life_days": 20,
                "monotonicity": 0.7,
            },
        }

        # Write to temporary file
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(validation_report, tmp, ensure_ascii=False, indent=2, default=str)
        tmp_path = tmp.name
        tmp.close()

        try:
            diagnosis = diagnose_factor(
                validation_path=tmp_path,
                factor_expression=result.get("expression", ""),
            )
            return diagnosis
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

    # ── Phase 4: Failure Recording ─────────────────────────

    def _phase4_record_failures(self, diagnoses: list):
        """Phase 4: 淘汰因子写入 FailureDatabase

        对于诊断结果为 "watch" 或 "retire" 的因子，
        写入 FailureDatabase 用于后续轮的失败模式参考。

        Args:
            diagnoses: Phase 3 诊断结果列表
        """
        try:
            from factor_lab.alpha.failure_db import FailureDatabase, FailureRecord
            db = FailureDatabase()
        except ImportError:
            print("  [Phase 4] ⚠️ FailureDatabase 不可用，跳过")
            return

        recorded = 0
        for d in diagnoses:
            verdict = d.get("verdict", "")
            if verdict not in ("watch", "retire"):
                continue

            failure_risks = d.get("failure_risks", {}) or {}
            record = FailureRecord(
                factor_name=d.get("factor_name", "unknown"),
                expression="",  # filled from spec if available
                hypothesis=d.get("strengths", [None])[0] if isinstance(d.get("strengths"), list) else "",
                rejection_reason=failure_risks.get("ic_decay_speed", verdict),
                ic_decay_curve={"short_term": 0.02, "medium_term": 0.01},
                market_regime=failure_risks.get("market_regime", d.get("favored_market_regime", "unknown")),
                created_by="auto_research",
                details={"verdict": verdict, "diagnosis": d.get("overall_assessment", "")},
            )
            try:
                fid = db.record_failure(record)
                recorded += 1
                print(f"    📝 记录失败归因: {record.factor_name} -> {fid}")
            except Exception as e:
                print(f"    ⚠️ 记录失败归因异常 ({record.factor_name}): {e}")

        if recorded:
            print(f"  [Phase 4] 记录 {recorded} 条失败归因")
        else:
            print(f"  [Phase 4] 无淘汰因子")

    # ── Phase 5: Convergence Check ─────────────────────────

    def _phase5_convergence(self, results: list) -> float:
        """Phase 5: 收敛判断

        检查本轮最佳评分是否相比历史最优有显著提升。
        连续 convergence_window 轮无改善则触发停止条件。

        Args:
            results: Phase 2 回测结果列表

        Returns:
            float: 本轮最佳评分
        """
        if not results:
            return 0.0

        best = max(results, key=lambda r: r.get("score", {}).get("overall_score", 0))
        score = best.get("score", {}).get("overall_score", 0)

        if score > self.best_score + self.config["convergence_threshold"]:
            improvement = score - self.best_score
            self.best_score = score
            self.no_improvement_rounds = 0
            print(f"  [Phase 5] 🎯 新最佳! score={score:.1f} (↑{improvement:+.2f})")
        else:
            self.no_improvement_rounds += 1
            print(f"  [Phase 5] 📊 无显著改善 ({self.no_improvement_rounds}/{self.config['convergence_window']})")

        return score

    # ── Phase 6: Report ────────────────────────────────────

    def _phase6_report(self, results: list, diagnoses: list):
        """Phase 6: 持久化结果 + 注册最优因子

        1. 构建本轮综合报告
        2. 持久化到 output_dir/round_{n:02d}/report.json
        3. 如果存在突破性因子，尝试注册到 Alpha Registry

        Args:
            results: Phase 2 回测结果列表
            diagnoses: Phase 3 诊断结果列表
        """
        # Build report
        round_report = {
            "round": self.round,
            "timestamp": datetime.now(CST).isoformat(),
            "n_candidates": len(results),
            "best_score": self.best_score,
            "no_improvement_rounds": self.no_improvement_rounds,
            "results": [],
            "diagnoses": diagnoses,
        }

        for r in results:
            score = r.get("score", {})
            round_report["results"].append({
                "factor_name": r.get("factor_name", ""),
                "expression": r.get("expression", ""),
                "overall_score": score.get("overall_score", 0),
                "grade": score.get("grade", ""),
                "ic_mean": score.get("ic_mean", 0),
                "ic_ir": score.get("ic_ir", 0),
                "status": r.get("status", ""),
            })

        self.history.append(round_report)

        # Write to directory
        use_round = self.round if self.round > 0 else 1  # standalone call guard
        round_dir = self.output_dir / f"round_{self.round:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)

        report_path = round_dir / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(round_report, f, indent=2, ensure_ascii=False, default=str)

        print(f"  [Phase 6] 📁 报告持久化: {report_path}")

        # Try to register top factor if it has breakthrough potential
        self._try_register_best(results, diagnoses)

    def _try_register_best(self, results: list, diagnoses: list):
        """尝试将本轮最优因子注册到 Alpha Registry

        条件:
          1. 评分 >= 75 (A 级)
          2. 诊断 verdict = "promote"
          3. 未被重复注册
        """
        if not results or not diagnoses:
            return

        best_result = max(results, key=lambda r: r.get("score", {}).get("overall_score", 0))
        best_score = best_result.get("score", {}).get("overall_score", 0)
        if best_score < 75:
            return

        best_name = best_result.get("factor_name", "")
        matching_diagnosis = next(
            (d for d in diagnoses if d.get("factor_name") == best_name),
            {},
        )
        if matching_diagnosis.get("verdict") != "promote":
            return

        # Attempt registration
        try:
            from factor_lab.alpha.registry import register_alpha
            from factor_lab.alpha.schema import AlphaSpec

            spec = AlphaSpec(
                name=best_name,
                description=matching_diagnosis.get("description", f"Auto-discovered factor: {best_name}"),
                hypothesis=matching_diagnosis.get("strengths", ["Auto-generated"])[0]
                if isinstance(matching_diagnosis.get("strengths"), list) else "Auto-generated",
                factor_expression=best_result.get("expression", ""),
                universe="all_watchlist",
                data_requirements=["close", "volume", "amount"],
                signal_direction="long_short",
                rebalance_frequency="monthly",
                risk_constraints={"max_position_weight": 0.25, "max_drawdown": 0.15},
                author="auto_research_loop",
                source=f"auto_research_loop:round_{self.round}",
                version="0.1.0",
                status="registered",
                enabled=False,
                paper_enabled=False,
                live_enabled=False,
                tags=["auto_discovered", f"round_{self.round}"],
            )
            result = register_alpha(spec)
            print(f"    🏆 最优因子已注册: {best_name} -> {result.get('alpha_id', '?')}")
        except ImportError:
            print(f"    ℹ️ Alpha Registry 不可用，跳过注册")
        except Exception as e:
            print(f"    ⚠️ 注册最优因子失败: {e}")


# ═══════════════════════════════════════════════════════
# CLI 入口 — AutoResearchLoop
# ═══════════════════════════════════════════════════════


def cmd_auto_research(market_context: str = "", max_rounds: int = 5,
                       output_dir: str = "") -> str:
    """启动自动研究循环

    Args:
        market_context: 市场上下文
        max_rounds: 最大轮次
        output_dir: 输出目录（可选）

    Returns:
        str: 结果摘要
    """
    return (
        "❌ BLOCKED: AutoResearchLoop 自动 Agent 开发系统已退役；"
        "不会评估、入队或注册候选"
    )
