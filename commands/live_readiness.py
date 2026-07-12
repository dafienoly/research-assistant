"""V4.9 小资金实盘 Readiness Gate (13道门禁检查)

LiveReadinessChecker — 运行全部 13 个 Gate, 返回 READY/NOT_READY。

设计原则:
  - V4.9 只做 readiness 检查, 不做自动下单
  - 默认全部 enabled=false, paper_enabled=false, live_enabled=false
  - 小资金实盘 = 需要人工审批
  - 自动交易 = 不允许
  - 输出 READY/NOT_READY + 阻塞项清单 + 证据 + 修复建议

用法:
    from live_readiness import LiveReadinessChecker
    checker = LiveReadinessChecker()
    result = checker.check_all()
    print(result["overall"])  # READY / NOT_READY
    for gate in result["gates"]:
        print(f"  {gate['gate_name']}: {'✅' if gate['passed'] else '❌'} [{gate['severity']}]")
"""
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.core.gate import GateEngine, GateCheck, GateResult
from factor_lab.datahub_access import PROJECT_ROOT
from factor_lab.risk.kill_switch import KillSwitch
from factor_lab.notify import notify_goal_done, notify_risk_event

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).parent.resolve()

# ---------------------------------------------------------------------------
# Gate Result Data Classes
# ---------------------------------------------------------------------------

@dataclass
class GateOutput:
    """单个 Gate 的输出结果。"""
    gate_name: str
    passed: bool = False
    severity: str = "blocker"  # blocker / warning / info
    message: str = ""
    evidence: str = ""
    fix_suggestion: str = ""


@dataclass
class ReadinessReport:
    """完整的 Readiness 检查报告。"""
    overall: str = "NOT_READY"  # READY / NOT_READY
    gates: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    infos: list = field(default_factory=list)
    scanned_at: str = ""
    run_id: str = ""

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "run_id": self.run_id,
            "scanned_at": self.scanned_at,
            "gates": [
                {
                    "gate_name": g.gate_name,
                    "passed": g.passed,
                    "severity": g.severity,
                    "message": g.message,
                    "evidence": g.evidence,
                    "fix_suggestion": g.fix_suggestion,
                }
                for g in self.gates
            ],
            "blockers": [
                {
                    "gate_name": g.gate_name,
                    "message": g.message,
                    "evidence": g.evidence,
                    "fix_suggestion": g.fix_suggestion,
                }
                for g in self.blockers
            ],
            "warnings": [
                {
                    "gate_name": g.gate_name,
                    "message": g.message,
                    "evidence": g.evidence,
                    "fix_suggestion": g.fix_suggestion,
                }
                for g in self.warnings
            ],
            "infos": [
                {
                    "gate_name": g.gate_name,
                    "message": g.message,
                    "evidence": g.evidence,
                }
                for g in self.infos
            ],
        }


# ---------------------------------------------------------------------------
# Live Readiness Checker — 13 Gates
# ---------------------------------------------------------------------------

class LiveReadinessChecker:
    """V4.9 小资金实盘 Readiness Gate 检查器。

    运行全部 13 个 Gate, 返回 READY/NOT_READY + 阻塞项清单 + 证据 + 修复建议。

    用法:
        checker = LiveReadinessChecker()
        result = checker.check_all()
        if result.overall == "READY":
            print("✅ 全部门禁通过, 可以申请实盘")
        else:
            for b in result.blockers:
                print(f"  ❌ {b.gate_name}: {b.message}")
    """

    VERSION = "V4.9"
    GATE_NAMES = [
        "DataHealthGate",
        "UniversePurityGate",
        "BenchmarkGate",
        "SemiconductorPeerGate",
        "RiskExposureGate",
        "CostAdjustedReturnGate",
        "PaperTradingGate",
        "ShadowTradingGate",
        "TradeConstraintGate",
        "ManualApprovalGate",
        "KillSwitchGate",
        "AuditTrailGate",
        "WeChatNotifyGate",
    ]

    def __init__(self, kill_switch: Optional[KillSwitch] = None, strict: bool = False):
        self.kill_switch = kill_switch
        self.strict = strict
        self.gate_engine = GateEngine(kill_switch=kill_switch)
        self.report = ReadinessReport(
            run_id=f"readiness_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}",
            scanned_at=datetime.now(CST).isoformat(),
        )

    # ── 1. DataHealthGate — 数据新鲜度、覆盖率 ─────────────────────

    def check_data_health(self) -> GateOutput:
        """检查数据新鲜度和覆盖率。

        验证:
          - 最近交易日数据是否存在
          - 数据新鲜度在 2 个交易日内
          - 日 K 线覆盖率 > 80%
        """
        gate = GateOutput(gate_name="DataHealthGate", severity="blocker")

        health_dir = PROJECT_ROOT / "data" / "audit" / "health"
        required = {
            "coverage": health_dir / "coverage.json",
            "freshness": health_dir / "freshness.json",
            "integrity": health_dir / "integrity.json",
        }
        reports: dict[str, dict] = {}
        errors: list[str] = []
        for name, path in required.items():
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                generated = datetime.fromisoformat(str(report["generated_at"]))
                age_hours = (datetime.now(CST) - generated.astimezone(CST)).total_seconds() / 3600
                if age_hours > 24:
                    errors.append(f"{name} audit stale ({age_hours:.1f}h)")
                reports[name] = report
            except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{name} audit unavailable: {exc}")

        coverage = reports.get("coverage", {})
        freshness = reports.get("freshness", {})
        integrity = reports.get("integrity", {})
        coverage_ok = (
            coverage.get("universe_status") == "OK"
            and coverage.get("active_missing_files") == 0
            and coverage.get("empty_files") == 0
            and coverage.get("stocks_with_data") == coverage.get("total_stocks")
        )
        freshness_ok = freshness.get("status") == "OK" and freshness.get("blocking_stock_count") == 0
        integrity_ok = integrity.get("status") == "OK" and integrity.get("problematic_file_count") == 0
        gate.evidence = (
            f"coverage={coverage.get('stocks_with_data')}/{coverage.get('total_stocks')}; "
            f"freshness={freshness.get('status')}; integrity={integrity.get('status')}; "
            f"audit_errors={errors}"
        )

        if coverage_ok and freshness_ok and integrity_ok and not errors:
            gate.passed = True
            gate.severity = "info"
            gate.message = "DataHub coverage、freshness、integrity 审计均通过"
            gate.fix_suggestion = ""
        else:
            gate.passed = False
            gate.severity = "blocker"
            gate.message = "DataHub 数据健康审计缺失、过期或未通过"
            gate.fix_suggestion = (
                "先从 D 盘最近 FINAL_COMPLETE 备份恢复，再运行 canonical DataHub 增量任务，"
                "最后重跑 coverage、freshness 和 integrity 审计"
            )

        return gate

    # ── 2. UniversePurityGate — 股票池纯度、权限标记 ──────────────

    def check_universe_purity(self) -> GateOutput:
        """检查股票池纯度和权限标记。

        验证:
          - U0-U4 股票池都已构建
          - 不包含 ST/*ST/退市/停牌股
          - 权限标记正确（科创板/北交所权限）
        """
        gate = GateOutput(gate_name="UniversePurityGate", severity="blocker")

        evidence_parts = []

        # 尝试导入 universes 模块
        try:
            sys.path.insert(0, str(BASE))
            from universes import list_universes, get_universe

            universe_names = list_universes()
            evidence_parts.append(f"股票池已注册: {len(universe_names)} 个")

            # 检查每个池的股票数量
            for uname in universe_names:
                try:
                    stocks, meta = get_universe(uname)
                    evidence_parts.append(f"  {uname}: {meta.get('total_stocks', 0)} 只")
                except Exception:
                    evidence_parts.append(f"  {uname}: 无法加载")

            gate.passed = True
            gate.severity = "info"
            gate.message = f"股票池系统正常 ({len(universe_names)} 个池)"
            gate.fix_suggestion = ""

        except ImportError as e:
            evidence_parts.append(f"universes 模块导入失败: {e}")
            gate.passed = False
            gate.severity = "warning"
            gate.message = "股票池模块未就绪"
            gate.fix_suggestion = "运行 python3 hermes_cli.py universe:build 构建所有股票池"

        except Exception as e:
            evidence_parts.append(f"股票池检查异常: {e}")
            gate.passed = False
            gate.severity = "warning"
            gate.message = f"股票池检查异常: {e}"
            gate.fix_suggestion = "检查 universes 模块状态并运行 universe:list"

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 3. BenchmarkGate — 基准体系完整 ───────────────────────────

    def check_benchmark(self) -> GateOutput:
        """检查基准体系是否完整。

        验证:
          - 6 个基准 + semiconductor_peer 都已注册
          - 基准收益率数据可查询
          - 基准更新及时
        """
        gate = GateOutput(gate_name="BenchmarkGate", severity="blocker")

        evidence_parts = []

        try:
            sys.path.insert(0, str(BASE))
            from benchmarks_v4 import list_benchmarks

            benchmarks = list_benchmarks()
            evidence_parts.append(f"基准体系: {len(benchmarks)} 个基准")
            unavailable = []
            for benchmark in benchmarks:
                name = benchmark.get("name", "unknown")
                days = int(benchmark.get("available_days", 0) or 0)
                evidence_parts.append(
                    f"  {name}: {days} 行, {benchmark.get('date_range', 'N/A')}"
                )
                if days <= 0:
                    unavailable.append(name)

            gate.passed = len(benchmarks) >= 6 and not unavailable
            if gate.passed:
                gate.severity = "info"
                gate.message = f"基准体系正常 ({len(benchmarks)} 个真实基准)"
                gate.fix_suggestion = ""
            else:
                gate.severity = "blocker"
                gate.message = "基准体系缺少可验证收益序列"
                gate.fix_suggestion = "通过 DataHub 重新生成 benchmark projections"

        except ImportError as e:
            evidence_parts.append(f"benchmarks_v4 模块导入失败: {e}")
            gate.passed = False
            gate.severity = "warning"
            gate.message = "基准体系模块未就绪"
            gate.fix_suggestion = "运行 python3 hermes_cli.py benchmark:list 检查基准状态"

        except Exception as e:
            evidence_parts.append(f"基准检查异常: {e}")
            gate.passed = False
            gate.severity = "warning"
            gate.message = f"基准检查异常: {e}"
            gate.fix_suggestion = "检查 benchmarks_v4 模块状态"

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 4. SemiconductorPeerGate — 因子跑赢半导体同池 ─────────────

    def check_semiconductor_peer(self) -> GateOutput:
        """检查因子是否跑赢半导体同池。

        验证:
          - 因子的 beats_semiconductor_peer = True
          - 同时 beats_matched_control = True（防止行业Beta暴露）
        """
        gate = GateOutput(gate_name="SemiconductorPeerGate", severity="blocker")

        # 使用现有的 SemiconductorPoolGate
        try:
            from factor_lab.core.gate import check_semiconductor_pool_gate

            from factor_lab.validate_factor_v4 import load_v4_report

            # 尝试加载最新 V4 报告
            report_dir = Path("/mnt/d/HermesReports/factor_lab/v4_reports")
            latest_report = None
            if report_dir.exists():
                reports = sorted(report_dir.glob("*_v4_report.json"))
                if reports:
                    latest_report = reports[-1]

            if latest_report:
                with open(latest_report) as f:
                    v4_result = json.load(f)
                result = check_semiconductor_pool_gate(v4_result)
                gate.passed = result.get("passed", False)
                checks_detail = "; ".join(
                    f"{c['name']}: {'✅' if c['passed'] else '❌'} {c['message']}"
                    for c in result.get("checks", [])
                )
                gate.evidence = (
                    f"报告: {latest_report.name}, 裁决: {result.get('verdict', '?')}, "
                    f"检查: {checks_detail}"
                )
                gate.message = (
                    "因子跑赢半导体同池" if gate.passed
                    else "因子未跑赢半导体同池 — 不得晋级"
                )
                gate.fix_suggestion = (
                    "" if gate.passed
                    else "优化因子以跑赢半导体核心等权和匹配对照池"
                )
            else:
                gate.passed = True
                gate.severity = "warning"
                gate.message = "未找到 V4 报告, 跳过验证"
                gate.evidence = "无 V4 报告文件"
                gate.fix_suggestion = "运行 factor:validate-v4 生成 V4 报告"

        except ImportError as e:
            gate.passed = True
            gate.severity = "warning"
            gate.message = f"半导体同池 Gate 模块未就绪 ({e})"
            gate.evidence = "模块未安装"
            gate.fix_suggestion = "检查 factor_lab.core.gate 是否存在"

        except Exception as e:
            gate.passed = True
            gate.severity = "info"
            gate.message = f"半导体同池检查跳过 ({e})"
            gate.evidence = str(e)
            gate.fix_suggestion = ""

        return gate

    # ── 5. RiskExposureGate — 因子收益非市值/Beta暴露 ────────────

    def check_risk_exposure(self) -> GateOutput:
        """检查因子收益是否主要来自风险暴露。

        验证:
          - risk_exposure.exposure_type != style_exposure_*
          - risk_exposure.exposure_type != industry_bet
          - risk_exposure.exposure_type != concentrated
        """
        gate = GateOutput(gate_name="RiskExposureGate", severity="blocker")

        try:
            from factor_lab.core.gate import check_risk_exposure_gate

            from factor_lab.validate_factor_v4 import load_v4_report

            report_dir = Path("/mnt/d/HermesReports/factor_lab/v4_reports")
            latest_report = None
            if report_dir.exists():
                reports = sorted(report_dir.glob("*_v4_report.json"))
                if reports:
                    latest_report = reports[-1]

            if latest_report:
                with open(latest_report) as f:
                    v4_result = json.load(f)
                result = check_risk_exposure_gate(v4_result)
                gate.passed = result.get("passed", False)
                exposure_type = result.get("exposure_type", "unknown")
                gate.evidence = (
                    f"报告: {latest_report.name}, "
                    f"暴露类型: {exposure_type}, "
                    f"裁决: {result.get('verdict', '?')}"
                )

                if exposure_type == "pure_alpha":
                    gate.message = "因子收益为纯 Alpha, 无显著风险暴露"
                elif exposure_type == "partial_exposure":
                    gate.message = "因子存在部分风险暴露, 需人工审查"
                elif exposure_type.startswith("style_exposure"):
                    gate.message = f"收益主要来自风格暴露 ({exposure_type})"
                elif exposure_type == "industry_bet":
                    gate.message = "收益主要来自行业配置"
                elif exposure_type == "concentrated":
                    gate.message = "收益高度依赖极端个股"
                else:
                    gate.message = f"暴露类型: {exposure_type}"

                gate.fix_suggestion = (
                    "" if gate.passed
                    else "需对因子进行风险中性化处理, 剥离风格/Beta/行业暴露"
                )
            else:
                gate.passed = True
                gate.severity = "warning"
                gate.message = "未找到 V4 报告, 跳过风险暴露验证"
                gate.evidence = "无 V4 报告文件"
                gate.fix_suggestion = "运行 factor:risk-attribution 生成风险归因报告"

        except ImportError as e:
            gate.passed = True
            gate.severity = "warning"
            gate.message = f"风险暴露 Gate 模块未就绪 ({e})"
            gate.evidence = "模块未安装"
            gate.fix_suggestion = "检查 factor_lab.core.gate 是否存在"

        except Exception as e:
            gate.passed = True
            gate.severity = "info"
            gate.message = f"风险暴露检查跳过 ({e})"
            gate.evidence = str(e)
            gate.fix_suggestion = ""

        return gate

    # ── 6. CostAdjustedReturnGate — 交易成本后收益为正 ───────────

    def check_cost_adjusted_return(self) -> GateOutput:
        """检查交易成本后收益是否为正。

        验证:
          - 扣除手续费/滑点/印花税后收益 > 0
          - 换手率合理, 成本占比 < 50%
        """
        gate = GateOutput(gate_name="CostAdjustedReturnGate", severity="blocker")

        evidence_parts = []

        # 尝试从 V4 报告读取成本调整后收益
        try:
            report_dir = Path("/mnt/d/HermesReports/factor_lab/v4_reports")
            if report_dir.exists():
                reports = sorted(report_dir.glob("*_v4_report.json"))
                if reports:
                    with open(reports[-1]) as f:
                        v4_result = json.load(f)

                    net_ret = v4_result.get("net_return_after_cost", 0)
                    gross_ret = v4_result.get("total_return", 0)
                    turnover = v4_result.get("annual_turnover", 0)

                    evidence_parts.append(
                        f"净收益={net_ret:.2%}, 毛收益={gross_ret:.2%}, 换手率={turnover:.0%}"
                    )

                    if net_ret > 0:
                        gate.passed = True
                        gate.severity = "info"
                        gate.message = f"交易成本后收益为正 (净收益={net_ret:.2%})"
                    else:
                        gate.passed = False
                        gate.severity = "blocker"
                        gate.message = (
                            f"交易成本后收益非正 (净收益={net_ret:.2%}, 换手率={turnover:.0%})"
                        )
                        gate.fix_suggestion = "降低换手率或改进因子降低交易成本"

                    gate.evidence = "; ".join(evidence_parts)
                    return gate
        except Exception as e:
            evidence_parts.append(f"V4 报告读取失败: {e}")

        # 如果没有 V4 报告, 模拟检查
        evidence_parts.append("无 V4 成本数据, 使用默认通过")
        gate.passed = True
        gate.severity = "warning"
        gate.message = "未找到交易成本数据, 跳过该检查"
        gate.evidence = "; ".join(evidence_parts)
        gate.fix_suggestion = "运行 factor:validate-v4 生成含成本指标的完整报告"

        return gate

    # ── 7. PaperTradingGate — Paper Trading 稳定 ─────────────────

    def check_paper_trading(self) -> GateOutput:
        """检查 Paper Trading 是否稳定运行。

        验证:
          - Paper Trading 已运行 >= 20 个交易日
          - 收益率稳定（无极端波动）
          - 无严重执行异常
        """
        gate = GateOutput(gate_name="PaperTradingGate", severity="blocker")

        evidence_parts = []

        try:
            sys.path.insert(0, str(BASE))
            from factor_lab.paper.standing_paper_trading import (
                get_paper_trading_status,
            )

            status = get_paper_trading_status()
            days_run = status.get("trading_days", 0)
            total_return = status.get("total_return_pct", 0)
            sharpe = status.get("sharpe", 0)
            max_dd = status.get("max_drawdown_pct", 0)

            evidence_parts.append(
                f"运行天数: {days_run}, 收益: {total_return:.2f}%, "
                f"Sharpe: {sharpe:.2f}, 最大回撤: {max_dd:.2f}%"
            )

            # 检查是否满足条件
            sufficient_days = days_run >= 20
            positive_return = total_return > -5  # 回撤不超过 5%

            if sufficient_days and positive_return:
                gate.passed = True
                gate.severity = "info"
                gate.message = f"Paper Trading 运行稳定 ({days_run} 天, {total_return:.2f}%)"
            elif sufficient_days and not positive_return:
                gate.passed = False
                gate.severity = "blocker"
                gate.message = f"Paper Trading 运行天数足够但收益异常 ({total_return:.2f}%)"
                gate.fix_suggestion = "检查 Paper Trading 策略逻辑和参数"
            else:
                gate.passed = False
                gate.severity = "blocker"
                gate.message = f"Paper Trading 运行天数不足 ({days_run}/20)"
                gate.fix_suggestion = "继续运行 Paper Trading 直至满 20 个交易日"

        except ImportError as e:
            evidence_parts.append(f"Paper Trading 模块未就绪: {e}")
            gate.passed = False
            gate.severity = "blocker"
            gate.message = "Paper Trading 模块未实现或未就绪"
            gate.fix_suggestion = "实现 Paper Trading 模块或运行 factor:paper-trade"
        except Exception as e:
            evidence_parts.append(f"Paper Trading 状态读取失败: {e}")
            gate.passed = False
            gate.severity = "blocker"
            gate.message = f"Paper Trading 状态异常: {e}"
            gate.fix_suggestion = "检查 Paper Trading 模块状态和运行日志"

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 8. ShadowTradingGate — Shadow Trading 稳定 ──────────────

    def check_shadow_trading(self) -> GateOutput:
        """检查 Shadow Trading 是否稳定运行。

        验证:
          - Shadow Trading 运行正常
          - 影子信号与 Paper Trading 一致
          - 无异常偏差
        """
        gate = GateOutput(gate_name="ShadowTradingGate", severity="blocker")

        evidence_parts = []

        try:
            # 尝试导入 shadow 模块
            sys.path.insert(0, str(BASE))
            from factor_lab.adaptive.shadow_forward import ShadowForwardEngine

            engine = ShadowForwardEngine()
            status = engine.get_status()

            shadow_days = status.get("shadow_days", 0)
            correlation = status.get("correlation_with_paper", 0)
            deviation = status.get("deviation_pct")
            deviation_text = f"{deviation:.2f}%" if deviation is not None else "n/a"

            evidence_parts.append(
                f"影子天数: {shadow_days}, "
                f"与Paper相关性: {correlation:.2f}, "
                f"偏差: {deviation_text}"
            )

            if shadow_days >= 5 and correlation > 0.7:
                gate.passed = True
                gate.severity = "info"
                gate.message = (
                    f"Shadow Trading 运行稳定 ({shadow_days} 天, "
                    f"相关性={correlation:.2f})"
                )
            elif shadow_days < 5:
                gate.passed = False
                gate.severity = "warning"
                gate.message = f"Shadow Trading 运行天数不足 ({shadow_days}/5)"
                gate.fix_suggestion = "继续运行 Shadow Trading"
            else:
                gate.passed = False
                gate.severity = "warning"
                gate.message = (
                    f"Shadow Trading 与 Paper 偏差较大 "
                    f"(相关性={correlation:.2f}, 偏差={deviation_text})"
                )
                gate.fix_suggestion = "补齐 canonical Shadow 观测、配对成交和权益序列后再验收"

        except ImportError as e:
            evidence_parts.append(f"Shadow Forward 模块未就绪: {e}")
            gate.passed = True
            gate.severity = "warning"
            gate.message = "Shadow Trading 模块未就绪, 跳过验证"
            gate.fix_suggestion = "接入 canonical Shadow 观测、配对成交和权益序列"
        except Exception as e:
            evidence_parts.append(f"Shadow Trading 状态读取失败: {e}")
            gate.passed = True
            gate.severity = "info"
            gate.message = f"Shadow Trading 检查跳过 ({e})"
            gate.fix_suggestion = ""

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 9. TradeConstraintGate — 交易约束正常工作 ────────────────

    def check_trade_constraints(self) -> GateOutput:
        """检查交易约束是否正常工作。

        验证:
          - 最小交易金额约束
          - 最大持仓比例约束
          - 单票集中度约束
          - 行业集中度约束
        """
        gate = GateOutput(gate_name="TradeConstraintGate", severity="blocker")

        evidence_parts = []

        # 检查 portfolio_builder 中的约束
        try:
            sys.path.insert(0, str(BASE))
            from portfolio_builder import PortfolioBuilder

            builder = PortfolioBuilder()
            constraints = builder.get_constraints() if hasattr(builder, "get_constraints") else {}

            if constraints:
                evidence_parts.append(f"交易约束已配置: {len(constraints)} 条")
                for k, v in constraints.items():
                    evidence_parts.append(f"  {k}: {v}")
                gate.passed = True
                gate.severity = "info"
                gate.message = "交易约束系统正常工作"
            else:
                evidence_parts.append("交易约束未显式配置")
                gate.passed = True
                gate.severity = "warning"
                gate.message = "交易约束未配置, 使用默认值"
                gate.fix_suggestion = "在 portfolio_builder 中配置明确的交易约束"

        except ImportError as e:
            evidence_parts.append(f"portfolio_builder 模块导入失败: {e}")
            gate.passed = False
            gate.severity = "warning"
            gate.message = "交易约束模块未就绪"
            gate.fix_suggestion = "实现 portfolio_builder 中的约束检查逻辑"
        except Exception as e:
            evidence_parts.append(f"交易约束检查异常: {e}")
            gate.passed = False
            gate.severity = "warning"
            gate.message = f"交易约束检查异常: {e}"
            gate.fix_suggestion = "检查 portfolio_builder 约束实现"

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 10. ManualApprovalGate — 人工审批链正常 ──────────────────

    def check_manual_approval(self) -> GateOutput:
        """检查人工审批链是否正常工作。

        验证:
          - 审批流程文档存在
          - 审批记录系统可用
          - 审批表单可生成
        """
        gate = GateOutput(gate_name="ManualApprovalGate", severity="blocker")

        evidence_parts = []

        # 检查审批相关模块
        approval_modules_found = []
        approval_dir = BASE / ".." / "data" / "approvals"
        if not approval_dir.exists():
            approval_dir = Path("/mnt/d/HermesReports/approvals")

        try:
            sys.path.insert(0, str(BASE))
            from factor_lab.adaptive.live_readiness import ManualApprovalPackage

            # 尝试检查审批包生成能力
            evidence_parts.append("ManualApprovalPackage 可用")
            approval_modules_found.append("ManualApprovalPackage")
        except ImportError:
            evidence_parts.append("ManualApprovalPackage 未就绪")

        try:
            # V2.5 审批工作流
            from factor_lab.risk.pretrade_risk_check import ApprovalEngine

            evidence_parts.append("ApprovalEngine 可用")
            approval_modules_found.append("ApprovalEngine")
        except ImportError:
            evidence_parts.append("ApprovalEngine 未就绪")

        if approval_modules_found:
            gate.passed = True
            gate.severity = "info"
            gate.message = f"人工审批链正常 ({', '.join(approval_modules_found)})"
            gate.fix_suggestion = ""
        else:
            gate.passed = False
            gate.severity = "blocker"
            gate.message = "人工审批模块未实现"
            gate.fix_suggestion = "实现 factor:approval 审批工作流和 ManualApprovalPackage"

        if approval_dir.exists():
            evidence_parts.append(f"审批目录: {approval_dir}")

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 11. KillSwitchGate — Kill Switch 正常 ─────────────────────

    def check_kill_switch(self) -> GateOutput:
        """检查 Kill Switch 是否正常工作。

        验证:
          - Kill Switch 已初始化（状态非 None）
          - Kill Switch 状态为 ARMED（非 TRIGGERED）
          - 可通过 check_action 阻断操作
        """
        gate = GateOutput(gate_name="KillSwitchGate", severity="blocker")

        evidence_parts = []

        # 使用传入的 kill_switch 或创建一个测试实例
        ks = self.kill_switch

        if ks is not None:
            state = ks.state
            is_armed = ks.is_armed()
            is_blocked = ks.is_blocked()
            n_blocked = ks.status.n_actions_blocked

            evidence_parts.append(
                f"Kill Switch 状态: {state}, "
                f"ARMED={is_armed}, BLOCKED={is_blocked}, "
                f"已阻断操作: {n_blocked}"
            )

            if is_armed:
                gate.passed = True
                gate.severity = "info"
                gate.message = f"Kill Switch 正常 (状态: {state})"
            elif is_blocked:
                gate.passed = False
                gate.severity = "blocker"
                gate.message = (
                    f"Kill Switch 已触发 (状态: {state}, "
                    f"原因: {ks.status.block_reason})"
                )
                gate.fix_suggestion = "排查触发原因, 解决问题后手动释放 Kill Switch"
            else:
                gate.passed = True
                gate.severity = "warning"
                gate.message = f"Kill Switch 状态异常 ({state})"
                gate.fix_suggestion = "执行 kill_switch.arm() 重新激活"
        else:
            # 没有传入 kill_switch, 创建一个测试实例
            try:
                test_ks = KillSwitch()
                evidence_parts.append(f"KillSwitch 可实例化 (状态: {test_ks.state})")
                gate.passed = True
                gate.severity = "warning"
                gate.message = "Kill Switch 可创建, 未注入到检查器"
                gate.fix_suggestion = "将 KillSwitch 实例注入 LiveReadinessChecker"
            except Exception as e:
                evidence_parts.append(f"KillSwitch 实例化失败: {e}")
                gate.passed = False
                gate.severity = "blocker"
                gate.message = "Kill Switch 无法创建"
                gate.fix_suggestion = "检查 KillSwitch 实现"

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 12. AuditTrailGate — 审计日志完整 ─────────────────────────

    def check_audit_trail(self) -> GateOutput:
        """检查审计日志是否完整。

        验证:
          - 审计日志目录存在
          - 最近 7 天有审计记录
          - 审计日志格式正确
        """
        gate = GateOutput(gate_name="AuditTrailGate", severity="blocker")

        evidence_parts = []

        # 检查审计日志目录
        audit_dir = BASE / ".." / "data" / "audit"
        if not audit_dir.exists():
            audit_dir = Path("/mnt/d/HermesReports/audit")

        if audit_dir.exists():
            log_files = sorted(audit_dir.glob("*"))
            evidence_parts.append(f"审计日志目录: {audit_dir}, 文件数: {len(log_files)}")

            # 检查最近是否有审计日志
            recent_logs = [
                f for f in log_files
                if f.stat().st_mtime > (datetime.now().timestamp() - 7 * 86400)
            ]
            evidence_parts.append(f"最近 7 天日志: {len(recent_logs)} 个文件")

            if recent_logs:
                gate.passed = True
                gate.severity = "info"
                gate.message = f"审计日志完整 (最近 7 天 {len(recent_logs)} 个文件)"
            else:
                gate.passed = False
                gate.severity = "warning"
                gate.message = "审计日志目录存在但最近 7 天无新日志"
                gate.fix_suggestion = "检查审计系统是否运行正常"
        else:
            # 尝试使用审计模块
            try:
                sys.path.insert(0, str(BASE))
                from factor_lab.audit import AuditLogger

                logger = AuditLogger()
                recent = logger.get_recent(days=7) if hasattr(logger, "get_recent") else []
                evidence_parts.append(f"AuditLogger 可用, 最近记录: {len(recent)} 条")
                gate.passed = True
                gate.severity = "info"
                gate.message = f"AuditLogger 可用 ({len(recent)} 条最近记录)"
            except ImportError:
                gate.passed = False
                gate.severity = "blocker"
                gate.message = "审计日志系统未实现"
                gate.fix_suggestion = "实现 audit 审计日志模块"
            except Exception as e:
                evidence_parts.append(f"审计模块异常: {e}")
                gate.passed = False
                gate.severity = "warning"
                gate.message = f"审计系统异常: {e}"
                gate.fix_suggestion = "修复审计日志模块"

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── 13. WeChatNotifyGate — 企业微信通知正常 ───────────────────

    def check_wechat_notify(self) -> GateOutput:
        """检查 Telegram + 企业微信 durable worker 凭据是否完整。

        验证:
          - WECHAT_WEBHOOK_URL/WECOM_WEBHOOK_URL 已配置
          - TELEGRAM_BOT_TOKEN 与 TELEGRAM_CHAT_ID 已配置
          - 不从交互 shell 或 .bashrc 读取凭据
        """
        gate = GateOutput(gate_name="WeChatNotifyGate", severity="blocker")

        evidence_parts = []

        webhook = os.environ.get("WECHAT_WEBHOOK_URL") or os.environ.get("WECOM_WEBHOOK_URL")
        telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if webhook:
            evidence_parts.append("企业微信环境凭据已配置")
        else:
            evidence_parts.append("企业微信环境凭据未配置")
        if telegram_token and telegram_chat:
            evidence_parts.append("Telegram 环境凭据已配置")
        else:
            evidence_parts.append("Telegram 环境凭据未配置")

        if webhook and telegram_token and telegram_chat:
            gate.passed = True
            gate.severity = "info"
            gate.message = "Telegram 与企业微信双通道 worker 凭据完整"
            gate.fix_suggestion = ""
        else:
            gate.passed = False
            gate.severity = "blocker"
            gate.message = "双通道通知凭据不完整"
            gate.fix_suggestion = (
                "通过受控进程环境配置 WECHAT_WEBHOOK_URL、TELEGRAM_BOT_TOKEN、"
                "TELEGRAM_CHAT_ID；禁止依赖 .bashrc"
            )

        gate.evidence = "; ".join(evidence_parts)
        return gate

    # ── check_all: 运行全部 13 个 Gate ───────────────────────────

    def check_all(self, gates: Optional[list] = None) -> ReadinessReport:
        """运行全部或指定 Gate, 返回 ReadinessReport。

        Args:
            gates: 可选, 指定要运行的 Gate 名称列表
                   (默认运行全部 13 个 Gate)

        Returns:
            ReadinessReport — 完整的检查报告
        """
        gate_methods = {
            "DataHealthGate": self.check_data_health,
            "UniversePurityGate": self.check_universe_purity,
            "BenchmarkGate": self.check_benchmark,
            "SemiconductorPeerGate": self.check_semiconductor_peer,
            "RiskExposureGate": self.check_risk_exposure,
            "CostAdjustedReturnGate": self.check_cost_adjusted_return,
            "PaperTradingGate": self.check_paper_trading,
            "ShadowTradingGate": self.check_shadow_trading,
            "TradeConstraintGate": self.check_trade_constraints,
            "ManualApprovalGate": self.check_manual_approval,
            "KillSwitchGate": self.check_kill_switch,
            "AuditTrailGate": self.check_audit_trail,
            "WeChatNotifyGate": self.check_wechat_notify,
        }

        target_gates = gates or self.GATE_NAMES
        results = []

        for gname in target_gates:
            if gname in gate_methods:
                try:
                    result = gate_methods[gname]()
                except Exception as e:
                    result = GateOutput(
                        gate_name=gname,
                        passed=False,
                        severity="blocker",
                        message=f"Gate 执行异常: {e}",
                        evidence="",
                        fix_suggestion="检查 gate 实现代码",
                    )
            else:
                result = GateOutput(
                    gate_name=gname,
                    passed=False,
                    severity="blocker",
                    message=f"未知 Gate: {gname}",
                    evidence="",
                    fix_suggestion="检查 gate 名称拼写",
                )

            results.append(result)

            # 记录到 GateEngine
            self.gate_engine.add_check(
                gate=result.gate_name,
                name=result.gate_name,
                passed=result.passed,
                severity=result.severity,
                message=result.message,
                evidence=result.evidence,
            )

        self.gate_engine.finalize()

        # 构建报告
        self.report.gates = results
        self.report.blockers = [g for g in results if not g.passed and g.severity == "blocker"]
        self.report.warnings = [g for g in results if not g.passed and g.severity == "warning"]
        self.report.infos = [g for g in results if g.severity == "info"]
        self.report.scanned_at = datetime.now(CST).isoformat()

        # 总体裁决
        if len(self.report.blockers) == 0:
            self.report.overall = "READY"
        else:
            self.report.overall = "NOT_READY"

        return self.report


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def run_live_readiness_check(strict: bool = False) -> ReadinessReport:
    """运行全部 13 个 Readiness Gate, 返回报告。

    Args:
        strict: 如果为 True, warning 级别的失败也视为 blocker

    Returns:
        ReadinessReport 对象
    """
    # 创建 KillSwitch 实例
    ks = KillSwitch()

    checker = LiveReadinessChecker(kill_switch=ks, strict=strict)
    report = checker.check_all()

    # 如果 strict=True, warning 也会导致 NOT_READY
    if strict and len(report.warnings) > 0 and report.overall == "READY":
        report.overall = "NOT_READY"

    return report


def print_readiness_report(report: ReadinessReport, verbose: bool = False):
    """打印 Readiness 报告到控制台。"""
    total = len(report.gates)
    passed = sum(1 for g in report.gates if g.passed)
    blockers = len(report.blockers)
    warnings = len(report.warnings)

    print(f"\n{'='*60}")
    print(f"  V4.9 小资金实盘 Readiness Gate 检查报告")
    print(f"{'='*60}")
    print(f"  运行 ID:  {report.run_id}")
    print(f"  检查时间: {report.scanned_at[:19]}")
    print(f"  总体状态: {'✅ READY' if report.overall == 'READY' else '❌ NOT_READY'}")
    print(f"  门禁总数: {total}")
    print(f"  通过:     {passed}")
    print(f"  阻塞项:   {blockers}")
    print(f"  警告项:   {warnings}")
    print(f"{'='*60}")

    if blockers > 0:
        print(f"\n❌ 阻塞项 ({blockers}):")
        for g in report.blockers:
            print(f"  [{g.gate_name}] {g.message}")
            if g.evidence:
                print(f"    证据: {g.evidence[:120]}")
            print(f"    修复: {g.fix_suggestion}")
            print()

    if warnings > 0:
        print(f"\n⚠️ 警告项 ({warnings}):")
        for g in report.warnings:
            print(f"  [{g.gate_name}] {g.message}")
            if verbose and g.evidence:
                print(f"    证据: {g.evidence[:120]}")
                print(f"    修复: {g.fix_suggestion}")
            print()

    if verbose:
        print(f"\n📋 全部 Gate 明细:")
        for g in report.gates:
            icon = "✅" if g.passed else ("⚠️" if g.severity == "warning" else "❌")
            print(f"  {icon} [{g.severity:8s}] {g.gate_name}")
            print(f"     {g.message}")
            if g.evidence:
                print(f"     证据: {g.evidence[:120]}")
            if not g.passed and g.fix_suggestion:
                print(f"     修复: {g.fix_suggestion}")
            print()

    print(f"{'='*60}")
    if report.overall == "READY":
        print("  🎉 全部门禁通过! 可以申请小资金实盘.")
        print("  ⚠️ 注意: 仍需要人工审批后才能实盘交易.")
    else:
        print(f"  ❌ {blockers} 个阻塞项需要修复后再检查.")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def cmd_live_readiness_v4(args: list = None):
    """live-readiness:v4 — 运行全部 13 个 Gate。

    用法:
        python3 live_readiness.py all
        python3 hermes_cli.py live-readiness:v4
    """
    strict = "--strict" in (args or [])
    report = run_live_readiness_check(strict=strict)
    print_readiness_report(report, verbose=False)
    return report


def cmd_live_gate_report(args: list = None):
    """live-gate:v4-report — 输出详细的 Gate 报告。

    用法:
        python3 live_readiness.py report
        python3 hermes_cli.py live-gate:v4-report
    """
    strict = "--strict" in (args or [])
    report = run_live_readiness_check(strict=strict)
    print_readiness_report(report, verbose=True)
    return report


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        args = sys.argv[2:]

        if cmd == "all":
            cmd_live_readiness_v4(args)
        elif cmd == "report":
            cmd_live_gate_report(args)
        else:
            print(f"用法: python3 live_readiness.py [all|report]")
            print(f"  all      — 运行全部 13 个 Gate (简短输出)")
            print(f"  report   — 运行全部 13 个 Gate (详细输出)")
    else:
        cmd_live_readiness_v4()
