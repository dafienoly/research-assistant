"""Core Gate V2.14.3 — 统一 GateEngine + V4.3 半导体同池等权 Gate"""
from dataclasses import dataclass, field
from typing import Optional

from factor_lab.risk.kill_switch import KillSwitch


@dataclass
class GateCheck:
    name: str
    passed: bool = True
    severity: str = "warning"  # blocker/warning/info
    message: str = ""
    evidence: str = ""


@dataclass
class GateResult:
    gate_name: str
    checks: list = field(default_factory=list)
    verdict: str = "pass"  # pass / conditional_pass / fail / insufficient_evidence

    @property
    def blockers(self):
        return [c for c in self.checks if c.severity == "blocker" and not c.passed]

    @property
    def warnings(self):
        return [c for c in self.checks if c.severity == "warning" and not c.passed]

    @property
    def passed(self):
        return len(self.blockers) == 0


class GateEngine:
    """统一门禁引擎

    Optionally connected to a KillSwitch for global circuit-breaking.
    When a KillSwitch is provided, every add_check() call checks whether
    the kill switch is blocked — if so, the check is automatically
    marked as failed with blocker severity.
    """
    def __init__(self, kill_switch: Optional[KillSwitch] = None):
        self.results = []
        self.kill_switch = kill_switch

    def add_check(self, gate: str, name: str, passed: bool, severity: str = "warning",
                  message: str = "", evidence: str = ""):
        # If kill_switch is active, override the check to blocked
        if self.kill_switch and self.kill_switch.is_blocked():
            result = self.kill_switch.check_action(
                action_type="gate",
                action_name=f"{gate}/{name}",
                source="GateEngine",
                details={"gate": gate, "check_name": name},
            )
            passed = False
            severity = "blocker"
            message = f"KillSwitch blocking: {self.kill_switch.status.block_reason}"
            if result.get("reason"):
                message = f"KillSwitch blocking: {result['reason']}"

        result = self._find_or_create(gate)
        result.checks.append(GateCheck(name=name, passed=passed, severity=severity,
                                       message=message, evidence=evidence))

    def _find_or_create(self, gate: str) -> GateResult:
        for r in self.results:
            if r.gate_name == gate:
                return r
        gr = GateResult(gate_name=gate)
        self.results.append(gr)
        return gr

    def finalize(self):
        for r in self.results:
            blockers = r.blockers
            if blockers:
                r.verdict = "fail"
            elif r.warnings:
                r.verdict = "conditional_pass"
            else:
                r.verdict = "pass"

    def get_summary(self) -> dict:
        self.finalize()
        return {r.gate_name: {"verdict": r.verdict, "n_blockers": len(r.blockers),
                               "n_warnings": len(r.warnings)} for r in self.results}


# ═══════════════════════════════════════════════════════════════════════════
# V4.3 半导体同池等权 Gate
# ═══════════════════════════════════════════════════════════════════════════


class SemiconductorPoolGate:
    """V4.3 半导体同池等权 Gate

    因子晋级必须:
      - beats_semiconductor_peer = True  OR  beats_core_peer = True
      - 跑赢上证但跑输半导体同池 = 不得晋级

    用法:
        gate = SemiconductorPoolGate()
        result = gate.evaluate(v4_validation_result)
        if result.passed:
            promote_to_next_stage()
    """

    GATE_NAME = "semiconductor_pool_ew"

    def __init__(self):
        self.engine = GateEngine()

    def evaluate(self, v4_result: dict) -> GateResult:
        """评估因子是否通过半导体同池门禁

        Args:
            v4_result: validate_v4() 返回的结果 dict, 需包含
                       beats_semiconductor_peer, beats_core_peer,
                       beats_matched_control, excess_vs_semiconductor_ew,
                       excess_vs_etf_basket 等字段

        Returns:
            GateResult
        """
        # 清理之前的检查
        self.engine = GateEngine()

        beats_semi = v4_result.get("beats_semiconductor_peer", False)
        beats_core = v4_result.get("beats_core_peer", False)
        beats_matched = v4_result.get("beats_matched_control", False)
        excess_semi = v4_result.get("excess_vs_semiconductor_ew", 0)
        excess_etf = v4_result.get("excess_vs_etf_basket", 0)

        # ─── Check 1: 跑赢半导体核心等权 (晋级必要条件) ───
        passed_primary = beats_semi or beats_core
        if passed_primary:
            msg = (
                f"跑赢半导体核心等权 (beats_semiconductor={beats_semi}, "
                f"beats_core={beats_core})"
            )
        else:
            msg = (
                f"未跑赢半导体核心等权 (beats_semiconductor={beats_semi}, "
                f"beats_core={beats_core}) — 不得晋级"
            )

        self.engine.add_check(
            gate=self.GATE_NAME,
            name="beats_semiconductor_pool",
            passed=passed_primary,
            severity="blocker",
            message=msg,
            evidence=f"excess_vs_semiconductor_ew={excess_semi}%",
        )

        # ─── Check 2: 跑赢匹配对照池 (辅助验证, 非 blocker) ───
        self.engine.add_check(
            gate=self.GATE_NAME,
            name="beats_matched_control",
            passed=beats_matched,
            severity="warning",
            message=(
                f"跑赢匹配对照池 = {beats_matched}"
            ),
            evidence=f"excess_vs_matched_control={v4_result.get('excess_vs_matched_control', 0)}%",
        )

        # ─── Check 3: ETF 替代池对比 (信息) ───
        self.engine.add_check(
            gate=self.GATE_NAME,
            name="excess_vs_etf_basket",
            passed=True,
            severity="info",
            message=f"超额 vs ETF替代池 = {excess_etf}%",
            evidence="",
        )

        # ─── 汇总 ───
        self.engine.finalize()

        for r in self.engine.results:
            if r.gate_name == self.GATE_NAME:
                return r

        return GateResult(gate_name=self.GATE_NAME, verdict="fail")


def check_semiconductor_pool_gate(v4_result: dict) -> dict:
    """便捷函数: 执行半导体同池 Gate 并返回摘要

    Args:
        v4_result: validate_v4() 的结果

    Returns:
        {"passed": bool, "verdict": str, "checks": [...]}
    """
    gate = SemiconductorPoolGate()
    result = gate.evaluate(v4_result)
    return {
        "gate_name": result.gate_name,
        "verdict": result.verdict,
        "passed": result.passed,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "severity": c.severity,
                "message": c.message,
            }
            for c in result.checks
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# V4.4 半导体同池 Gate (严格版)
# ═══════════════════════════════════════════════════════════════════════════


class BeatsSemiconductorPeerGate:
    """V4.4 严格半导体同池 Gate

    因子晋级必须:
      - beats_semiconductor_peer = True  (必须跑赢半导体核心池等权)
      - beats_core_peer alone 不够 — 必须是 beats_semiconductor_peer
      - 同时跑赢匹配对照池 (matched_control) — 证明不是伪相关 (blocker)

    与 V4.3 的区别:
      V4.3: beats_semiconductor_peer OR beats_core_peer
      V4.4: beats_semiconductor_peer AND beats_matched_control
    """

    GATE_NAME = "beats_semiconductor_peer"

    def __init__(self):
        self.engine = GateEngine()

    def evaluate(self, v44_result: dict) -> GateResult:
        """评估因子是否通过严格半导体同池门禁

        Args:
            v44_result: validate_factor_v44() 或 validate_factor_v4() 的结果

        Returns:
            GateResult
        """
        self.engine = GateEngine()

        beats_semi = v44_result.get("beats_semiconductor_peer", False)
        beats_matched = v44_result.get("beats_matched_control", False)
        excess_semi = v44_result.get("excess_vs_semiconductor_ew", 0)
        excess_matched = v44_result.get("excess_vs_matched_control", 0)

        # ─── Check 1: 跑赢半导体核心等权 (必要条件) ───
        self.engine.add_check(
            gate=self.GATE_NAME,
            name="beats_semiconductor_peer",
            passed=beats_semi,
            severity="blocker",
            message=(
                f"跑赢半导体核心等权 = {beats_semi} "
                f"(excess={excess_semi}%)"
            ),
            evidence=f"excess_vs_semiconductor_ew={excess_semi}%",
        )

        # ─── Check 2: 跑赢匹配对照池 (必要条件) ───
        # 防止因子仅因半导体行业 Beta 而有效
        self.engine.add_check(
            gate=self.GATE_NAME,
            name="beats_matched_control",
            passed=beats_matched,
            severity="blocker",
            message=(
                f"跑赢匹配对照池 = {beats_matched} "
                f"(excess={excess_matched}%) — "
                f"需要跑赢匹配对照以证明不是行业Beta暴露"
            ),
            evidence=f"excess_vs_matched_control={excess_matched}%",
        )

        # ─── 汇总 ───
        self.engine.finalize()

        for r in self.engine.results:
            if r.gate_name == self.GATE_NAME:
                return r

        return GateResult(gate_name=self.GATE_NAME, verdict="fail")


# ═══════════════════════════════════════════════════════════════════════════
# V4.4 风险暴露 Gate
# ═══════════════════════════════════════════════════════════════════════════


class RiskExposureGate:
    """V4.4 风险暴露 Gate

    判断因子收益是否主要来自风险暴露 (市值/Beta/波动率/流动性/行业):
      - 若 exposure_type 为 "style_exposure_*" 或 "industry_bet" → blocker
      - 若 exposure_type 为 "concentrated" → blocker (极端个股依赖)
      - 若 exposure_type 为 "partial_exposure" → warning
      - 若 exposure_type 为 "pure_alpha" → pass

    用法:
        gate = RiskExposureGate()
        result = gate.evaluate(v44_validation_result)
        if result.passed:
            promote_as_pure_alpha()
        else:
            flag_as_risk_exposure()
    """

    GATE_NAME = "risk_exposure"

    def __init__(self):
        self.engine = GateEngine()

    def evaluate(self, v44_result: dict) -> GateResult:
        """评估因子收益是否来自风险暴露

        Args:
            v44_result: validate_factor_v44() 返回的结果 dict, 需包含
                       risk_exposure.exposure_type

        Returns:
            GateResult
        """
        self.engine = GateEngine()

        risk_exp = v44_result.get("risk_exposure", {})
        exposure_type = risk_exp.get("exposure_type", "no_data")
        error = risk_exp.get("error")

        # ─── Check 1: 风险暴露数据可用性 ───
        has_data = exposure_type != "no_data" and not error
        self.engine.add_check(
            gate=self.GATE_NAME,
            name="risk_data_available",
            passed=has_data,
            severity="info",
            message=f"风险暴露数据: {'可用' if has_data else '不可用'}",
            evidence=f"exposure_type={exposure_type}",
        )

        if not has_data:
            self.engine.finalize()
            for r in self.engine.results:
                if r.gate_name == self.GATE_NAME:
                    return r
            return GateResult(gate_name=self.GATE_NAME, verdict="insufficient_evidence")

        # ─── Check 2: 是否为纯 Alpha ───
        is_pure_alpha = exposure_type == "pure_alpha"

        # ─── Check 3: 暴露类型判断 ───
        if exposure_type.startswith("style_exposure"):
            # 收益主要来自风格暴露
            severity = "blocker"
            message = (
                f"收益主要来自风格暴露 ({exposure_type}) — "
                f"标记为暴露型收益, 不得晋级"
            )
        elif exposure_type == "industry_bet":
            severity = "blocker"
            message = (
                f"收益主要来自行业配置 ({exposure_type}) — "
                f"标记为暴露型收益, 不得晋级"
            )
        elif exposure_type == "concentrated":
            severity = "blocker"
            message = (
                f"收益高度依赖极端个股 (Jackknife max impact = "
                f"{risk_exp.get('jackknife_max_impact', 'N/A')}%) — "
                f"标记为暴露型收益, 不得晋级"
            )
        elif exposure_type == "mixed_style_industry":
            severity = "blocker"
            message = (
                f"收益来自多维度暴露 (风格+行业) — "
                f"标记为暴露型收益, 不得晋级"
            )
        elif exposure_type == "partial_exposure":
            severity = "warning"
            message = (
                f"存在部分风险暴露 ({exposure_type}) — "
                f"标记为暴露型收益, 需人工审查"
            )
        elif exposure_type == "pure_alpha":
            severity = "info"
            message = "收益来源无显著风险暴露, 认定为纯 Alpha"
        else:
            severity = "warning"
            message = f"未知暴露类型: {exposure_type}"

        self.engine.add_check(
            gate=self.GATE_NAME,
            name="exposure_type",
            passed=is_pure_alpha,
            severity=severity,
            message=message,
            evidence=(
                f"market_cap_r2={risk_exp.get('market_cap_r2', 'N/A')}, "
                f"beta_r2={risk_exp.get('beta_r2', 'N/A')}, "
                f"volatility_r2={risk_exp.get('volatility_r2', 'N/A')}, "
                f"industry_r2={risk_exp.get('industry_r2', 'N/A')}, "
                f"jackknife_max_impact={risk_exp.get('jackknife_max_impact', 'N/A')}"
            ),
        )

        # ─── 汇总 ───
        self.engine.finalize()

        for r in self.engine.results:
            if r.gate_name == self.GATE_NAME:
                return r

        return GateResult(gate_name=self.GATE_NAME, verdict="fail")


def check_risk_exposure_gate(v44_result: dict) -> dict:
    """便捷函数: 执行风险暴露 Gate 并返回摘要

    Args:
        v44_result: validate_factor_v44() 的结果

    Returns:
        {"gate_name": str, "verdict": str, "passed": bool,
         "exposure_type": str, "checks": [...]}
    """
    gate = RiskExposureGate()
    result = gate.evaluate(v44_result)
    risk_exp = v44_result.get("risk_exposure", {})
    return {
        "gate_name": result.gate_name,
        "verdict": result.verdict,
        "passed": result.passed,
        "exposure_type": risk_exp.get("exposure_type", "unknown"),
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "severity": c.severity,
                "message": c.message,
            }
            for c in result.checks
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# V4.4 组合 Gate (两阶段门禁)
# ═══════════════════════════════════════════════════════════════════════════


def check_v44_promotion_gate(v44_result: dict) -> dict:
    """V4.4 组合门禁: 半导体同池 Gate + 风险暴露 Gate

    因子晋级必须同时通过:
      1. BeatsSemiconductorPeerGate — 跑赢半导体核心等权 + 匹配对照池
      2. RiskExposureGate — 收益非主要来自风险暴露

    Returns:
        {
            "overall_passed": bool,
            "gates": {
                "semiconductor_peer": {...},
                "risk_exposure": {...},
            },
            "blockers": [...],
        }
    """
    # Gate 1: 半导体同池
    semi_gate = BeatsSemiconductorPeerGate()
    semi_result = semi_gate.evaluate(v44_result)

    # Gate 2: 风险暴露
    risk_gate = RiskExposureGate()
    risk_result = risk_gate.evaluate(v44_result)

    overall_passed = semi_result.passed and risk_result.passed
    blockers = semi_result.blockers + risk_result.blockers

    return {
        "overall_passed": overall_passed,
        "gates": {
            "semiconductor_peer": {
                "verdict": semi_result.verdict,
                "passed": semi_result.passed,
            },
            "risk_exposure": {
                "verdict": risk_result.verdict,
                "passed": risk_result.passed,
            },
        },
        "blockers": [
            {
                "name": c.name,
                "message": c.message,
                "severity": c.severity,
                "gate": "semiconductor_peer" if c in semi_result.blockers else "risk_exposure",
            }
            for c in blockers
        ],
    }
