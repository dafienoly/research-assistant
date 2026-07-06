"""Alpha Governance V3.8 — 候选审核、证据、风险

构建在 V3.7 LLM Alpha Discovery 之上，提供治理层:
  1. EvidenceScorer — 证据评分（来源可信度、完整性、质量）
  2. RiskAssessor — 风险评估（过拟合、体制依赖、容量、实现）
  3. GovernanceReview — 综合治理审核（证据 + 风险 + 验证 + 查重）
  4. 审核记录持久化到 Alpha 候选目录

用法:
    from factor_lab.alpha.governance import (
        GovernanceReview,
        EvidenceScorer,
        RiskAssessor,
        run_governance_review,
        generate_governance_report,
    )

安全边界:
    - auto_apply=False
    - no_live_trade=True
    - 所有审核不下单、不改配置
"""

import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
GOVERNANCE_ROOT = BASE / "alpha_governance"
GOVERNANCE_ROOT.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# EvidenceScorer — 证据评分
# ═══════════════════════════════════════════════════════════════════

# 证据来源可信度权重
EVIDENCE_SOURCE_WEIGHTS = {
    "academic_paper": 1.0,       # 学术论文
    "industry_research": 0.9,    # 行业研究报告
    "empirical_observation": 0.7,  # 实证观察
    "financial_theory": 0.8,     # 金融理论
    "llm_reasoning": 0.4,        # LLM 推理
    "proprietary_research": 0.8, # 内部研究
    "trader_anecdote": 0.3,      # 交易员经验
    "unknown": 0.3,              # 未知来源
}

# 证据类型权重
EVIDENCE_TYPE_WEIGHTS = {
    "backtest_result": 1.0,
    "academic_citation": 0.9,
    "statistical_analysis": 0.8,
    "logical_argument": 0.5,
    "empirical_pattern": 0.6,
    "market_observation": 0.4,
    "unknown": 0.3,
}


def _detect_evidence_source(evidence_text: str) -> str:
    """从 evidence 文本检测来源类型"""
    if not evidence_text:
        return "unknown"
    text_lower = evidence_text.lower()

    # 学术论文特征: 关键词或引用模式 "(Author Year)"
    if any(kw in text_lower for kw in ["paper", "journal", "research", "study finds",
                                        "literature", "published", "academic", "et al",
                                        "citation"]):
        return "academic_paper"
    import re
    # 匹配引用模式: (Author Year) 或 (Author & Author Year) 或 Author (Year)
    if re.search(r'\([A-Z][A-Za-z\s&\.]+\d{4}\)', evidence_text):
        return "academic_paper"
    if re.search(r'[A-Z][a-z]+[\s&]+[A-Z][a-z]+[\s&]*\d{4}', evidence_text):
        return "academic_paper"
    # 行业报告
    if any(kw in text_lower for kw in ["industry report", "whitepaper", "gs report",
                                        "morgan stanley", "citics", "wind report"]):
        return "industry_research"
    # 金融理论
    if any(kw in text_lower for kw in ["theory", "rationale", "behind", "intuition"]):
        return "financial_theory"
    # 实证观察
    if any(kw in text_lower for kw in ["observed", "empirical", "data shows",
                                        "historical pattern", "over the past"]):
        return "empirical_observation"
    # LLM 生成
    if any(kw in text_lower for kw in ["llm suggests", "generated", "based on model",
                                        "language model"]):
        return "llm_reasoning"

    return "unknown"


def _detect_evidence_type(evidence_text: str) -> str:
    """从 evidence 文本检测证据类型"""
    if not evidence_text:
        return "unknown"
    text_lower = evidence_text.lower()

    if any(kw in text_lower for kw in ["backtest", "return", "sharpe", "ic", "factor return"]):
        return "backtest_result"
    if any(kw in text_lower for kw in ["et al", "citation", "referenced", "see "]):
        return "academic_citation"
    if any(kw in text_lower for kw in ["statistically", "p-value", "t-stat", "correlation",
                                        "regression", "significant"]):
        return "statistical_analysis"
    if any(kw in text_lower for kw in ["because", "therefore", "implies", "suggests"]):
        return "logical_argument"
    if any(kw in text_lower for kw in ["often", "tend to", "typically", "pattern"]):
        return "empirical_pattern"

    return "unknown"


class EvidenceScorer:
    """证据评分器

    评估 Alpha 候选的证据维度:
      - 来源可信度 (source_credibility)
      - 证据完整性 (completeness) — 是否有 hypothesis, rationale, data link
      - 证据质量 (quality) — 长度、细节、具体性
      - 综合分数 (整体)
    """

    def __init__(self):
        self.scores: dict = {}
        self.details: list[str] = []

    def score(self, candidate: dict) -> dict:
        """对候选 Alpha 进行证据评分

        参数:
            candidate: candidates_index 条目或完整候选记录

        返回:
            包含 evidence_score, source_credibility, completeness,
            quality, details, verdict 的 dict
        """
        self.scores = {}
        self.details = []

        # 获取证据文本
        if "spec" in candidate:
            spec = candidate["spec"]
        else:
            spec = candidate

        evidence_text = spec.get("evidence", "")
        hypothesis_text = spec.get("hypothesis", "")
        description_text = spec.get("description", "")

        # 1. 来源可信度
        source_type = _detect_evidence_source(evidence_text)
        source_weight = EVIDENCE_SOURCE_WEIGHTS.get(source_type, 0.3)
        self.details.append(f"证据来源类型: {source_type} (权重: {source_weight:.1f})")

        # 2. 完整性评分
        completeness = 0.0
        if evidence_text and len(evidence_text) > 10:
            completeness += 0.3
            self.details.append("✓ 包含证据文本")
        if hypothesis_text and len(hypothesis_text) > 20:
            completeness += 0.3
            self.details.append("✓ 包含详细假设")
        if description_text and len(description_text) > 20:
            completeness += 0.2
            self.details.append("✓ 包含详细描述")
        if spec.get("risk_notes", ""):
            completeness += 0.2
            self.details.append("✓ 包含风险说明")
        self.details.append(f"完整性得分: {completeness:.1f}/1.0")

        # 3. 质量评分
        quality = 0.0
        if evidence_text:
            # 长度质量
            word_count = len(evidence_text.split())
            if word_count >= 50:
                quality += 0.3
            elif word_count >= 20:
                quality += 0.15
            # 具体性 — 包含数字/数据
            import re
            has_numbers = bool(re.search(r'\d+[\.\d]*%|\d+\.\d+|\d+[bp]{2}', evidence_text))
            if has_numbers:
                quality += 0.3
                self.details.append("✓ 证据包含具体数据/数字")
            # 引用/来源
            if any(kw in evidence_text.lower() for kw in ["according to", "source", "reference",
                                                            "based on", "cited"]):
                quality += 0.2
                self.details.append("✓ 证据包含引用来源")
            # 细节丰富度
            if any(kw in evidence_text.lower() for kw in ["for example", "e.g.", "specifically",
                                                            "in particular", "such as"]):
                quality += 0.2
                self.details.append("✓ 证据包含具体示例")
        self.details.append(f"质量得分: {quality:.1f}/1.0")

        # 4. 综合分数
        evidence_score = (
            source_weight * 0.3 +  # 来源可信度权重
            completeness * 0.35 +  # 完整性权重
            quality * 0.35         # 质量权重
        )
        evidence_score = round(min(1.0, max(0.0, evidence_score)), 4)

        # 5. 评级
        if evidence_score >= 0.7:
            verdict = "strong"
        elif evidence_score >= 0.4:
            verdict = "moderate"
        else:
            verdict = "weak"

        self.scores = {
            "evidence_score": evidence_score,
            "source_credibility": round(source_weight, 2),
            "completeness": round(completeness, 2),
            "quality": round(quality, 2),
            "source_type": source_type,
            "verdict": verdict,
            "details": self.details,
        }
        return self.scores


# ═══════════════════════════════════════════════════════════════════
# RiskAssessor — 风险评估
# ═══════════════════════════════════════════════════════════════════


class RiskAssessor:
    """风险评估器

    评估 Alpha 候选的风险维度:
      - 过拟合风险 (overfitting) — 复杂度过高、参数过多、信号不稳定
      - 体制依赖风险 (regime_dependency) — 是否只在特定市场环境有效
      - 容量风险 (capacity) — 是否与流动性/资金规模有关
      - 实现风险 (implementation) — 数据依赖、交易成本敏感
      - 综合风险分数
    """

    RISK_KEYWORDS = {
        "overfitting": [
            "overfit", "overfit", "excessive parameters", "too many", "complex",
            "nonlinear", "non-linear", "many conditions", "many terms",
        ],
        "regime_dependency": [
            "regime", "market condition", "bull market", "bear market",
            "volatile", "low volatility", "high volatility", "trending",
            "sideways", "range-bound", "cycle", "economic regime",
        ],
        "capacity": [
            "capacity", "liquidity", "small cap", "large cap", "turnover",
            "trading volume", "slippage", "impact cost", "market impact",
            "thinly traded", "illiquid",
        ],
        "implementation": [
            "data delay", "data lag", "look-ahead", "survivorship",
            "trading cost", "commission", "bid-ask", "execution",
            "rebalance cost", "implementation shortfall",
        ],
    }

    def __init__(self):
        self.scores: dict = {}
        self.details: list[str] = []

    def assess(self, candidate: dict) -> dict:
        """对候选 Alpha 进行风险评估

        参数:
            candidate: 候选 dict (可包含 spec 子字段，或直接是 spec)

        返回:
            包含 risk_score, overfitting, regime_dependency, capacity,
            implementation, overall_risk_level, details 的 dict
        """
        self.scores = {}
        self.details = []

        if "spec" in candidate:
            spec = candidate["spec"]
        else:
            spec = candidate

        expression = spec.get("factor_expression", "")
        risk_notes = spec.get("risk_notes", "")
        evidence_text = spec.get("evidence", "")
        hypothesis = spec.get("hypothesis", "")

        all_text = f"{expression} {risk_notes} {evidence_text} {hypothesis}"

        # 各维度风险评分 (0=无风险, 1=高风险)
        dimensions = {}

        for dim, keywords in self.RISK_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw.lower() in all_text.lower())
            score = min(1.0, hits / max(len(keywords) * 0.4, 1))
            if dim == "overfitting":
                # 额外检查表达式复杂度
                complexity_penalty = self._assess_expression_complexity(expression)
                score = min(1.0, score * 0.5 + complexity_penalty * 0.5)
            dimensions[dim] = round(score, 4)
            if score > 0.3:
                self.details.append(f"⚠️ {dim} 风险 {score:.2f} — {hits} 个关键词命中")

        # 综合风险分数
        risk_score = round(
            dimensions.get("overfitting", 0) * 0.30 +
            dimensions.get("regime_dependency", 0) * 0.25 +
            dimensions.get("capacity", 0) * 0.20 +
            dimensions.get("implementation", 0) * 0.25,
            4,
        )

        # 风险等级
        if risk_score >= 0.7:
            overall_risk_level = "high"
        elif risk_score >= 0.4:
            overall_risk_level = "medium"
        else:
            overall_risk_level = "low"

        self.scores = {
            "risk_score": risk_score,
            "overall_risk_level": overall_risk_level,
            **dimensions,
            "details": self.details,
        }
        return self.scores

    def _assess_expression_complexity(self, expression: str) -> float:
        """评估因子表达式复杂度

        返回 0~1 浮点数, 越高越复杂/越容易过拟合
        """
        if not expression:
            return 0.5

        import re
        # 计算函数调用数
        func_calls = len(re.findall(r'\b[a-z_]+\s*\(', expression))
        # 计算运算符数
        operators = len(re.findall(r'[\+\-\*/]', expression))
        # 计算条件语句
        conditions = len(re.findall(r'\bwhere\b', expression))

        complexity = min(1.0, (func_calls * 0.15 + operators * 0.05 + conditions * 0.2))
        return round(complexity, 4)


# ═══════════════════════════════════════════════════════════════════
# GovernanceReview — 综合治理审核
# ═══════════════════════════════════════════════════════════════════


class GovernanceReview:
    """综合治理审核

    每次审核结合以下维度:
      1. Validation — AlphaSpecValidator 结果
      2. Evidence — EvidenceScorer 结果
      3. Risk — RiskAssessor 结果
      4. Duplicate check — 查重结果
      5. 综合评分 → 治理建议

    用法:
        review = GovernanceReview()
        result = review.run(candidate_id)
    """

    def __init__(self):
        self.result: dict = {}

    def run(self, candidate_id: str, override_verdict: str = "") -> dict:
        """对指定候选执行完整治理审核

        参数:
            candidate_id: 候选 ID (如 cand_20260705_...)
            override_verdict: 强制指定审核结论
                             ("approve", "reject", ""=自动判断)

        返回:
            包含 validation, evidence, risk, duplicate, governance 的 dict
        """
        # 加载候选
        from factor_lab.alpha.llm_alpha_discovery import CANDIDATES_ROOT, get_candidate
        candidate = get_candidate(candidate_id)
        if "error" in candidate:
            return {"error": candidate["error"]}

        if candidate["status"] != "pending_review":
            self.result = {
                "candidate_id": candidate_id,
                "error": f"候选状态为 '{candidate['status']}', 需要 'pending_review'",
            }
            return self.result

        now = datetime.now(CST).isoformat()
        spec = candidate.get("spec", {})

        # 1. Validation — 重新验证
        from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator
        validator = AlphaSpecValidator()
        validation_passed = validator.validate(spec)
        validation_report = validator.get_report()

        # 2. Evidence — 证据评分
        evidence_scorer = EvidenceScorer()
        evidence_scores = evidence_scorer.score(candidate)

        # 3. Risk — 风险评估
        risk_assessor = RiskAssessor()
        risk_scores = risk_assessor.assess(candidate)

        # 4. Duplicate check
        from factor_lab.alpha.llm_alpha_discovery import (
            check_duplicate_in_registry,
            check_duplicate_in_queue,
        )
        duplicate_registry = check_duplicate_in_registry(spec)
        duplicate_queue = check_duplicate_in_queue(spec)

        # 5. 综合治理评分
        governance = self._compute_governance(
            validation_report=validation_report,
            evidence_scores=evidence_scores,
            risk_scores=risk_scores,
            duplicate_registry=duplicate_registry,
            duplicate_queue=duplicate_queue,
            override_verdict=override_verdict,
        )

        # 6. 写入审核记录
        review_record = {
            "candidate_id": candidate_id,
            "candidate_name": spec.get("name", ""),
            "reviewed_at": now,
            "validation": validation_report,
            "evidence": evidence_scores,
            "risk": risk_scores,
            "duplicate": {
                "registry": duplicate_registry,
                "queue": duplicate_queue,
            },
            "governance": governance,
            "auto_apply": False,
            "no_live_trade": True,
        }

        # 持久化
        self._persist_review(candidate_id, review_record)

        self.result = review_record
        return review_record

    def _compute_governance(
        self,
        validation_report: dict,
        evidence_scores: dict,
        risk_scores: dict,
        duplicate_registry: dict,
        duplicate_queue: dict,
        override_verdict: str = "",
    ) -> dict:
        """计算综合治理分数和建议"""
        is_duplicate = (
            duplicate_registry.get("is_duplicate", False)
            or duplicate_queue.get("is_duplicate", False)
        )

        # 权重配置
        weights = {
            "validation": 0.30,   # 验证通过是必要条件
            "evidence": 0.25,      # 证据充分性
            "risk": 0.25,          # 风险评估
            "novelty": 0.20,       # 新颖性 (非重复)
        }

        # 各部分分数 (0~1)
        validation_score = 1.0 if validation_report.get("passed", False) else 0.0
        evidence_score = evidence_scores.get("evidence_score", 0)
        risk_score = 1.0 - risk_scores.get("risk_score", 0)  # 风险越低分越高
        novelty_score = 0.0 if is_duplicate else 1.0

        overall_score = round(
            validation_score * weights["validation"] +
            evidence_score * weights["evidence"] +
            risk_score * weights["risk"] +
            novelty_score * weights["novelty"],
            4,
        )

        # 硬性否决条件
        hard_vetoes = []
        if not validation_report.get("passed", False):
            hard_vetoes.append("验证不通过")
        if is_duplicate:
            hard_vetoes.append("与现有 Alpha/候选重复")

        # 审核结论
        if override_verdict == "approve":
            verdict = "approve"
            confidence = "manual_override"
        elif override_verdict == "reject":
            verdict = "reject"
            confidence = "manual_override"
        elif hard_vetoes:
            verdict = "reject"
            confidence = "high"
        elif overall_score >= 0.65:
            verdict = "approve"
            confidence = "high" if overall_score >= 0.8 else "medium"
        elif overall_score >= 0.45:
            verdict = "request_changes"  # 需要补充证据或降低风险
            confidence = "medium"
        else:
            verdict = "reject"
            confidence = "high" if overall_score < 0.3 else "medium"

        return {
            "overall_score": overall_score,
            "weights": weights,
            "component_scores": {
                "validation": validation_score,
                "evidence": evidence_score,
                "risk": risk_score,
                "novelty": novelty_score,
            },
            "hard_vetoes": hard_vetoes,
            "verdict": verdict,
            "confidence": confidence,
            "note": self._verdict_note(verdict, overall_score, hard_vetoes),
        }

    def _verdict_note(self, verdict: str, score: float, vetoes: list) -> str:
        """生成审核结论说明"""
        if vetoes:
            return "否决: " + "; ".join(vetoes)
        notes = {
            "approve": f"批准 (综合评分 {score:.2f})",
            "reject": f"拒绝 (综合评分 {score:.2f})",
            "request_changes": f"需要修改 (综合评分 {score:.2f}, 需补充证据或降低风险)",
        }
        return notes.get(verdict, f"审核完成 (综合评分 {score:.2f})")

    def _persist_review(self, candidate_id: str, review_record: dict):
        """将审核记录持久化到候选目录"""
        from factor_lab.alpha.llm_alpha_discovery import CANDIDATES_ROOT
        candidate_dir = CANDIDATES_ROOT / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)

        # 写入 governance report
        (candidate_dir / "governance_review.json").write_text(
            json.dumps(review_record, indent=2, ensure_ascii=False)
        )

        # 追加到 governance master log
        master_log = GOVERNANCE_ROOT / "governance_log.jsonl"
        entry = {
            "timestamp": review_record["reviewed_at"],
            "candidate_id": candidate_id,
            "candidate_name": review_record.get("candidate_name", ""),
            "overall_score": review_record["governance"]["overall_score"],
            "verdict": review_record["governance"]["verdict"],
            "confidence": review_record["governance"]["confidence"],
            "auto_apply": False,
        }
        with open(master_log, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_review(self, candidate_id: str) -> dict:
        """获取已存储的审核记录"""
        from factor_lab.alpha.llm_alpha_discovery import CANDIDATES_ROOT
        review_path = CANDIDATES_ROOT / candidate_id / "governance_review.json"
        if review_path.exists():
            return json.loads(review_path.read_text())
        return {"error": f"审核记录不存在: {candidate_id}"}


# ═══════════════════════════════════════════════════════════════════
# 审核报告生成
# ═══════════════════════════════════════════════════════════════════


def generate_governance_report(candidate_id: str = "", output_dir: str = "") -> dict:
    """生成治理审核报告

    参数:
        candidate_id: 候选 ID (空=全部候选)
        output_dir: 输出目录 (空=自动)

    返回:
        dict 包含报告路径、统计信息
    """
    from factor_lab.alpha.llm_alpha_discovery import (
        CANDIDATES_ROOT,
        list_candidates,
        get_candidate,
    )

    if not output_dir:
        rid = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        output_dir = str(GOVERNANCE_ROOT / rid)
    os.makedirs(output_dir, exist_ok=True)

    if candidate_id:
        # 单个候选报告
        review = GovernanceReview().get_review(candidate_id)
        if "error" in review:
            return review
        candidates_data = [review]
    else:
        # 全部候选
        all_candidates = list_candidates()
        candidates_data = []
        for entry in all_candidates:
            cid = entry.get("candidate_id", "")
            review = GovernanceReview().get_review(cid)
            if "error" not in review and review.get("governance"):
                candidates_data.append(review)

    # 统计
    stats = {
        "total": len(candidates_data),
        "approved": sum(1 for r in candidates_data if r.get("governance", {}).get("verdict") == "approve"),
        "rejected": sum(1 for r in candidates_data if r.get("governance", {}).get("verdict") == "reject"),
        "request_changes": sum(1 for r in candidates_data if r.get("governance", {}).get("verdict") == "request_changes"),
    }

    # JSON 报告
    report = {
        "report_type": "alpha_governance_report",
        "generated_at": datetime.now(CST).isoformat(),
        "candidate_id": candidate_id or "all",
        "stats": stats,
        "reviews": candidates_data,
        "safety": {
            "auto_apply": False,
            "no_live_trade": True,
            "all_disabled": True,
        },
    }

    report_path = os.path.join(output_dir, "governance_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # HTML 报告
    html_path = os.path.join(output_dir, "governance_report.html")
    _write_governance_html(html_path, report, stats)

    # CSV 导出
    csv_path = os.path.join(output_dir, "governance_report.csv")
    _write_governance_csv(csv_path, candidates_data)

    # 审计
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== ALPHA GOVERNANCE AUDIT V3.8 ===\n")
        f.write(f"Report at: {report['generated_at']}\n")
        f.write(f"Total reviewed: {stats['total']}\n")
        f.write(f"Approved: {stats['approved']}\n")
        f.write(f"Rejected: {stats['rejected']}\n")
        f.write(f"Request changes: {stats['request_changes']}\n")
        f.write(f"Auto apply: False\n")
        f.write(f"No live trade: True\n")
        f.write(f"=== END ===\n")

    result = {
        "output_dir": output_dir,
        "report_path": report_path,
        "html_path": html_path,
        "csv_path": csv_path,
        "stats": stats,
        "safety": report["safety"],
    }

    return result


def _write_governance_html(html_path: str, report: dict, stats: dict):
    """写入 HTML 治理报告"""
    rows = ""
    for r in report.get("reviews", []):
        gov = r.get("governance", {})
        verdict = gov.get("verdict", "?")
        color = {"approve": "#00c853", "reject": "#ff1744", "request_changes": "#ff9100"}.get(verdict, "#888")
        score = gov.get("overall_score", 0)
        ev_score = r.get("evidence", {}).get("evidence_score", 0)
        risk_score = r.get("risk", {}).get("risk_score", 0)
        name = r.get("candidate_name", "?")
        cid = r.get("candidate_id", "?")
        rows += (
            f"<tr>"
            f"<td>{cid[:30]}</td>"
            f"<td>{name}</td>"
            f"<td>{ev_score:.2f}</td>"
            f"<td>{risk_score:.2f}</td>"
            f"<td>{score:.2f}</td>"
            f"<td style='color:{color}'>{verdict}</td>"
            f"</tr>"
        )

    safety_rows = "".join(
        f"<li>{k}: {'✅' if v else '❌'}</li>"
        for k, v in report.get("safety", {}).items()
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Alpha Governance V3.8</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>🏛️ Alpha Governance V3.8</h1>
<p style="color:#aaa;">Generated: {report['generated_at']}</p>
<p>Total: {stats['total']} | ✅ Approve: {stats['approved']} | ❌ Reject: {stats['rejected']} | 🟡 Request changes: {stats['request_changes']}</p></div>
<div class="card"><h2>📋 Governance Reviews</h2>
<table>
<tr><th>ID</th><th>Name</th><th>Evidence</th><th>Risk</th><th>Score</th><th>Verdict</th></tr>
{rows}
</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul>{safety_rows}</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.8 | Auto-apply: False | No live trade</p></div>
</body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _write_governance_csv(csv_path: str, candidates_data: list):
    """写入 CSV 治理报告"""
    if not candidates_data:
        with open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write("candidate_id,candidate_name,evidence_score,risk_score,overall_score,verdict\n")
        return

    fieldnames = [
        "candidate_id", "candidate_name",
        "evidence_score", "risk_score",
        "overall_score", "verdict",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in candidates_data:
            gov = r.get("governance", {})
            w.writerow({
                "candidate_id": r.get("candidate_id", ""),
                "candidate_name": r.get("candidate_name", ""),
                "evidence_score": r.get("evidence", {}).get("evidence_score", 0),
                "risk_score": r.get("risk", {}).get("risk_score", 0),
                "overall_score": gov.get("overall_score", 0),
                "verdict": gov.get("verdict", ""),
            })


# ═══════════════════════════════════════════════════════════════════
# 快捷入口
# ═══════════════════════════════════════════════════════════════════


def run_governance_review(candidate_id: str) -> dict:
    """运行治理审核 (快捷函数)"""
    review = GovernanceReview()
    return review.run(candidate_id)


def list_governance_status() -> list:
    """列出所有候选的治理状态"""
    from factor_lab.alpha.llm_alpha_discovery import list_candidates
    all_candidates = list_candidates()
    status_list = []
    for entry in all_candidates:
        cid = entry.get("candidate_id", "")
        name = entry.get("name", "")
        candidate_status = entry.get("status", "")

        review = GovernanceReview().get_review(cid)
        if "error" not in review and review.get("governance"):
            gov = review["governance"]
            status_list.append({
                "candidate_id": cid,
                "name": name,
                "candidate_status": candidate_status,
                "governance_score": gov.get("overall_score", 0),
                "governance_verdict": gov.get("verdict", ""),
                "evidence_score": review.get("evidence", {}).get("evidence_score", 0),
                "risk_score": review.get("risk", {}).get("risk_score", 0),
                "reviewed_at": review.get("reviewed_at", ""),
            })
        else:
            status_list.append({
                "candidate_id": cid,
                "name": name,
                "candidate_status": candidate_status,
                "governance_score": None,
                "governance_verdict": "not_reviewed",
                "evidence_score": None,
                "risk_score": None,
                "reviewed_at": "",
            })
    return status_list


# ═══════════════════════════════════════════════════════════════════
# CLI 集成函数
# ═══════════════════════════════════════════════════════════════════


def cmd_review(candidate_id: str) -> dict:
    """CLI 入口: alpha:review"""
    result = run_governance_review(candidate_id)
    if "error" in result:
        print(f"❌ {result['error']}")
        return result

    gov = result.get("governance", {})
    print(f"\n{'='*60}")
    print(f"  🏛️ Alpha Governance Review V3.8")
    print(f"  Candidate: {result.get('candidate_name', '?')} ({candidate_id})")
    print(f"{'='*60}")
    print(f"  📊 Overall Score: {gov.get('overall_score', 0):.4f}")
    print(f"  🎯 Verdict: {gov.get('verdict', '?')}")
    print(f"  Confidence: {gov.get('confidence', '?')}")
    print(f"  Note: {gov.get('note', '')}")
    print()
    print(f"  Evidence Score: {result.get('evidence', {}).get('evidence_score', 0):.4f}")
    print(f"    Source: {result.get('evidence', {}).get('source_type', '?')}")
    print(f"    Verdict: {result.get('evidence', {}).get('verdict', '?')}")
    print()
    print(f"  Risk Score: {result.get('risk', {}).get('risk_score', 0):.4f}")
    print(f"    Level: {result.get('risk', {}).get('overall_risk_level', '?')}")
    print(f"    Overfitting: {result.get('risk', {}).get('overfitting', 0):.2f}")
    print(f"    Regime: {result.get('risk', {}).get('regime_dependency', 0):.2f}")
    print(f"    Capacity: {result.get('risk', {}).get('capacity', 0):.2f}")
    print(f"    Implementation: {result.get('risk', {}).get('implementation', 0):.2f}")
    print()
    if gov.get("hard_vetoes"):
        print(f"  🚫 Hard Vetoes: {', '.join(gov['hard_vetoes'])}")
    print(f"{'='*60}\n")
    return result


def cmd_governance_report(candidate_id: str = "") -> None:
    """CLI 入口: alpha:governance-report"""
    result = generate_governance_report(candidate_id=candidate_id)
    if "error" in result:
        print(f"❌ {result['error']}")
        return
    print(f"\n{'='*60}")
    print(f"  📊 Governance Report Generated")
    print(f"  Output: {result['output_dir']}")
    print(f"  Total: {result['stats']['total']}")
    print(f"  ✅ Approved: {result['stats']['approved']}")
    print(f"  ❌ Rejected: {result['stats']['rejected']}")
    print(f"  🟡 Request Changes: {result['stats']['request_changes']}")
    print(f"{'='*60}\n")


def cmd_governance_list() -> None:
    """CLI 入口: alpha:governance-list"""
    status_list = list_governance_status()
    if not status_list:
        print("  (empty)")
        return
    for s in status_list:
        if s["governance_verdict"] == "not_reviewed":
            tag = "⚪"
        elif s["governance_verdict"] == "approve":
            tag = "🟢"
        elif s["governance_verdict"] == "reject":
            tag = "🔴"
        else:
            tag = "🟡"
        score_str = f"{s['governance_score']:.2f}" if s["governance_score"] is not None else "?"
        print(f"  {tag} {s['candidate_id'][:35]:35s} {s['name'][:25]:25s} "
              f"state={s['candidate_status']:16s} score={score_str} verdict={s['governance_verdict']}")
