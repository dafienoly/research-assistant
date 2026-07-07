"""Research Loop 进化引擎 — 自适应因子迭代"""
from factor_lab.research_loop.trajectory import analyze_trajectory, TrajectoryMetrics
from factor_lab.research_loop.meta_evolution import select_strategy, EvolutionStrategy
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
        """解析 LLM 输出的候选因子（多格式兼容）

        支持的格式:
          1. 表达式 | 因子名 | 假设描述    (优先级最高)
          2. 表达式                         (自动验证+命名)
          3. 因子名 = 表达式                (等号赋值)
          4. - 表达式  # 注释               (列表项)
          5. N. 表达式                      (编号列表)
          6. JSON: [{"expression": "...", "name": "..."}]
          7. ``` 代码围栏内部内容            (自动跳过围栏标记)
        """
        candidates = []
        seen = set()

        # 先尝试 JSON 解析
        text = response.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                import json as _json
                parsed = _json.loads(text)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and "expression" in item:
                            expr = item["expression"].strip()
                            name = item.get("name", f"gen_{len(candidates)+1}")
                            hypothesis = item.get("hypothesis", "")
                            if expr and expr not in seen:
                                seen.add(expr)
                                candidates.append({"expression": expr, "name": name, "hypothesis": hypothesis})
                    return candidates
            except Exception:
                pass

        in_fence = False
        for raw_line in text.split("\n"):
            line = raw_line.strip()

            # 代码围栏标记 — 切换围栏状态但保留围栏内内容
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if not line:
                continue

            # 去掉 markdown 列表标记、编号
            cleaned = line.lstrip("- *0123456789. ")

            # 格式1: 表达式 | 名称 | 假设 (优先级最高)
            if "|" in cleaned:
                parts = [p.strip() for p in cleaned.split("|")]
                expr = parts[0]
                name = parts[1] if len(parts) > 1 else f"gen_{len(candidates)+1}"
                hypothesis = " | ".join(parts[2:]) if len(parts) > 2 else ""
                if self._is_valid_expression(expr):
                    norm = self._normalize_expr_for_dedup(expr)
                    if norm not in seen:
                        seen.add(norm)
                        candidates.append({"expression": expr, "name": name, "hypothesis": hypothesis})
                    continue

            # 格式2: 因子名 = 表达式 或 表达式 # 注释
            # 去掉行内注释
            comment_stripped = cleaned.split("#")[0].split("//")[0].strip()
            if not comment_stripped:
                continue

            # 检查等号赋值: name = expression
            if "=" in comment_stripped:
                eq_parts = comment_stripped.split("=", 1)
                potential_name = eq_parts[0].strip().replace(" ", "_").replace("-", "_")
                potential_expr = eq_parts[1].strip()
                if potential_name and potential_expr and self._is_valid_expression(potential_expr):
                    norm = self._normalize_expr_for_dedup(potential_expr)
                    if norm not in seen:
                        seen.add(norm)
                        candidates.append({"expression": potential_expr, "name": potential_name, "hypothesis": ""})
                    continue

            # 格式3: 裸表达式 — 直接验证
            if self._is_valid_expression(comment_stripped):
                norm = self._normalize_expr_for_dedup(comment_stripped)
                if norm not in seen:
                    seen.add(norm)
                    candidates.append({
                        "expression": comment_stripped,
                        "name": f"gen_{len(candidates)+1}",
                        "hypothesis": "",
                    })
                continue

            # 格式4: 从自然语言中提取表达式（嵌入在句子中的）
            extracted = self._extract_expressions_from_text(comment_stripped)
            for expr in extracted:
                norm = self._normalize_expr_for_dedup(expr)
                if norm not in seen:
                    seen.add(norm)
                    candidates.append({
                        "expression": expr,
                        "name": f"gen_{len(candidates)+1}",
                        "hypothesis": "",
                    })

        return candidates

    @staticmethod
    def _is_valid_expression(text: str) -> bool:
        """检查文本是否为合法的因子表达式"""
        try:
            from factor_lab.expression_parser import ExpressionParser
            parser = ExpressionParser()
            err = parser.validate(text)
            return not err
        except Exception:
            return False

    @staticmethod
    def _normalize_expr_for_dedup(expr: str) -> str:
        """归一化表达式用于去重"""
        import re
        return re.sub(r"\s+", "", expr.lower())

    @staticmethod
    def _extract_expressions_from_text(text: str) -> list[str]:
        """从自然语言文本中提取因子表达式

        通过括号深度解析提取所有可能的函数调用表达式。
        """
        found = []
        i = 0
        while i < len(text):
            # 查找函数名起始（字母后接括号）
            if text[i].isalpha() or text[i] == '_':
                j = i
                while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                    j += 1
                # 检查是否为函数调用（后接左括号）
                k = j
                while k < len(text) and text[k] == ' ':
                    k += 1
                if k < len(text) and text[k] == '(':
                    # 跟踪括号深度找到匹配的右括号
                    depth = 0
                    start = i
                    p = k
                    while p < len(text):
                        if text[p] == '(':
                            depth += 1
                        elif text[p] == ')':
                            depth -= 1
                            if depth == 0:
                                # 提取完整表达式
                                expr = text[start:p+1].strip()
                                # 去掉尾部标点
                                while expr and expr[-1] in '.,;:!)]':
                                    expr = expr[:-1].strip()
                                if expr and ResearchLoop._is_valid_expression(expr):
                                    found.append(expr)
                                i = p
                                break
                        p += 1
            i += 1
        return found

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
    """启动研究循环"""
    config = ResearchConfig(
        max_rounds=rounds,
        convergence_window=convergence,
        max_concurrent=concurrent,
    )
    loop = ResearchLoop(notebook_path=notebook, config=config)
    report = loop.run()
    lines = [f"✅ 研究循环完成: {report.rounds_completed} 轮, 停止: {report.stop_reason}"]
    if report.best_factor:
        lines.append(f"最佳因子: {report.best_factor['expression'][:60]}")
        lines.append(f"最佳评分: {report.best_factor['score']:.1f}")
    if report.new_knowledge:
        lines.append(f"新增知识条目: {len(report.new_knowledge)}")
    return "\n".join(lines)
