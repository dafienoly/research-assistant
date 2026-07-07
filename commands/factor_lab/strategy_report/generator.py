"""Strategy Report Generator V6.5 — 策略报告生成引擎

核心生成器，负责：
  1. 接收策略/组合数据和配置
  2. 计算分析指标
  3. 渲染 HTML/JSON/TEXT 报告
  4. 保存到磁盘
  5. 管理报告元信息

支持输入源:
  - PortfolioResult (V6.4) — 从组合回测结果生成
  - 原始收益率 Series — 从策略收益率直接生成
  - dict 格式 — 从 JSON 可序列化数据生成
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from factor_lab.strategy_report.spec import (
    StrategyReportConfig,
    StrategyReportResult,
    ReportType,
    ReportSection,
    ReportFormat,
    DrawdownAnalysis,
    WinLossAnalysis,
    RiskMetrics,
)
from factor_lab.strategy_report.metrics import (
    compute_monthly_returns,
    compute_annual_returns,
    compute_drawdown_analysis,
    compute_win_loss_analysis,
    compute_risk_metrics,
    compute_rolling_metrics,
    compute_return_distribution,
)
from factor_lab.strategy_report.html_renderer import HTMLReportRenderer


CST = timezone(timedelta(hours=8))
DEFAULT_OUTPUT_ROOT = Path(
    os.environ.get(
        "HERMES_REPORTS_DIR",
        "/mnt/d/HermesReports/strategies",
    )
)


class StrategyReportGenerator:
    """策略报告生成器

    使用方法:
        from factor_lab.portfolio import PortfolioBacktestEngine, PortfolioSpec
        from factor_lab.strategy_report import StrategyReportGenerator

        # 场景 1: 从组合回测结果生成
        engine = PortfolioBacktestEngine(spec)
        result = engine.run_with_benchmark("CSI300")
        gen = StrategyReportGenerator()
        report = gen.from_portfolio_result(result)

        # 场景 2: 从策略收益率直接生成
        report = gen.from_strategy_returns(
            strategy_returns=momentum_series,
            strategy_name="动量策略",
            benchmark_name="CSI300",
        )

        # 场景 3: 设置输出目录
        gen = StrategyReportGenerator(output_dir="/tmp/reports")
        report = gen.from_portfolio_result(result)

    Reports are auto-saved to output_dir/{report_type}/{title}_{timestamp}.html
    """

    def __init__(
        self,
        config: Optional[StrategyReportConfig] = None,
        output_dir: Optional[str] = None,
    ):
        self.config = config or StrategyReportConfig()
        if output_dir:
            self.config.output_dir = output_dir
        self.renderer = HTMLReportRenderer(self.config)

    # ─── 主入口方法 ────────────────────────────────────────────────

    def from_portfolio_result(
        self,
        portfolio_result,
    ) -> StrategyReportResult:
        """从 PortfolioResult (V6.4) 生成策略报告

        自动检测报告类型：根据策略数量决定 single 或 portfolio。

        Args:
            portfolio_result: V6.4 PortfolioResult 对象

        Returns:
            StrategyReportResult
        """
        start = time.monotonic()
        title = self.config.title or (
            portfolio_result.portfolio_spec.name
            if portfolio_result and portfolio_result.portfolio_spec
            else "策略报告"
        )

        # 提取数据
        portfolio_ret = portfolio_result.portfolio_returns
        portfolio_equity = portfolio_result.portfolio_equity
        individual_returns = portfolio_result.individual_returns
        benchmark_ret = portfolio_result.benchmark_returns
        metrics = portfolio_result.metrics
        attribution = portfolio_result.attribution
        warnings = portfolio_result.warnings or []

        # 确定报告类型
        n_strategies = metrics.n_strategies if metrics else len(individual_returns)
        report_type = (
            ReportType.PORTFOLIO.value
            if n_strategies > 1
            else ReportType.SINGLE_STRATEGY.value
        )

        # 准备基准名称
        bm_name = (
            self.config.benchmark_name
            or (
                portfolio_result.benchmark_spec.name
                if portfolio_result and portfolio_result.benchmark_spec
                else ""
            )
        )

        # 构建板块
        sections = self._build_sections(
            portfolio_ret=portfolio_ret,
            portfolio_equity=portfolio_equity,
            individual_returns=individual_returns,
            benchmark_ret=benchmark_ret,
            metrics_dict=metrics.to_dict() if metrics else {},
            attribution=attribution,
            warnings=warnings,
            strategy_name=title,
            report_type=report_type,
            n_strategies=n_strategies,
            n_days=len(portfolio_ret) if portfolio_ret is not None else 0,
            benchmark_name=bm_name,
            correlation_data=(
                portfolio_result.cross_correlation
                if hasattr(portfolio_result, "cross_correlation")
                else None
            ),
        )

        # 渲染
        elapsed = time.monotonic() - start
        return self._finalize(
            report_type=report_type,
            title=title,
            sections=sections,
            n_strategies=n_strategies,
            n_days=len(portfolio_ret) if portfolio_ret is not None else 0,
            duration_ms=round(elapsed * 1000, 1),
            warnings=warnings,
            description=self.config.description or "",
            benchmark_name=bm_name,
        )

    def from_strategy_returns(
        self,
        strategy_returns: pd.Series,
        strategy_name: str = "策略",
        benchmark_returns: Optional[pd.Series] = None,
        benchmark_name: str = "",
    ) -> StrategyReportResult:
        """从策略收益率序列生成报告

        Args:
            strategy_returns: 策略日收益率 Series
            strategy_name: 策略名称
            benchmark_returns: 基准收益率 (可选)
            benchmark_name: 基准名称

        Returns:
            StrategyReportResult
        """
        start = time.monotonic()

        if strategy_returns.empty:
            return StrategyReportResult(
                report_type=ReportType.SINGLE_STRATEGY.value,
                title=strategy_name,
                errors=["收益率为空"],
            )

        title = self.config.title or strategy_name
        n_days = len(strategy_returns)

        # 计算净值
        equity = (1 + strategy_returns).cumprod()

        # 基本指标
        cum_ret = float(equity.iloc[-1]) - 1
        ann_ret = (
            (1 + cum_ret) ** (252 / n_days) - 1
            if n_days > 20
            else 0.0
        )
        ann_vol = float(strategy_returns.std() * (252 ** 0.5))
        from factor_lab.metrics import calc_sharpe, calc_max_drawdown, calc_calmar

        sharpe = calc_sharpe(strategy_returns)
        max_dd = calc_max_drawdown(equity)
        calmar = calc_calmar(ann_ret, max_dd)
        win_rate = float((strategy_returns > 0).mean())

        metrics_dict = {
            "cumulative_return_pct": round(cum_ret * 100, 2),
            "annualized_return_pct": round(ann_ret * 100, 2),
            "annualized_volatility_pct": round(ann_vol * 100, 2),
            "sharpe": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "calmar": round(calmar, 4),
            "win_rate_pct": round(win_rate * 100, 2),
            "n_trading_days": n_days,
        }

        # 如果有基准，计算对比指标
        if benchmark_returns is not None and len(benchmark_returns) > 0:
            from factor_lab.portfolio.metrics import compute_benchmark_relative_metrics
            bm_metrics = compute_benchmark_relative_metrics(
                strategy_returns, benchmark_returns
            )
            metrics_dict.update(bm_metrics)

        # 构建板块
        sections = self._build_sections(
            portfolio_ret=strategy_returns,
            portfolio_equity=equity,
            individual_returns={"single": strategy_returns},
            benchmark_ret=benchmark_returns,
            metrics_dict=metrics_dict,
            attribution=[],
            warnings=[],
            strategy_name=strategy_name,
            report_type=ReportType.SINGLE_STRATEGY.value,
            n_strategies=1,
            n_days=n_days,
            benchmark_name=benchmark_name,
        )

        elapsed = time.monotonic() - start
        return self._finalize(
            report_type=ReportType.SINGLE_STRATEGY.value,
            title=title,
            sections=sections,
            n_strategies=1,
            n_days=n_days,
            duration_ms=round(elapsed * 1000, 1),
            warnings=[],
            description=self.config.description or strategy_name,
            benchmark_name=benchmark_name,
        )

    # ─── 板块构建 ──────────────────────────────────────────────────

    def _build_sections(
        self,
        portfolio_ret,
        portfolio_equity,
        individual_returns,
        benchmark_ret,
        metrics_dict: dict,
        attribution,
        warnings: list[str],
        strategy_name: str,
        report_type: str,
        n_strategies: int,
        n_days: int,
        benchmark_name: str = "",
        correlation_data=None,
    ) -> dict[str, str]:
        """构建所有请求的板块 HTML

        Returns:
            板块名 → HTML 字符串
        """
        include = self.config.include_sections
        all_sections = [s.value for s in ReportSection]

        sections = {}

        # ── Overview ──
        if not include or ReportSection.OVERVIEW.value in include:
            sections["overview"] = self.renderer.render_overview(
                strategy_name=strategy_name,
                report_type=report_type,
                n_strategies=n_strategies,
                n_days=n_days,
                benchmark=benchmark_name,
            )

        # ── Metrics ──
        if not include or ReportSection.METRICS.value in include:
            if metrics_dict:
                sections["metrics"] = self.renderer.render_metrics_table(metrics_dict)

        # ── Equity ──
        if not include or ReportSection.EQUITY.value in include:
            if portfolio_equity is not None and len(portfolio_equity) > 0:
                equity_values = portfolio_equity.tolist()
                sections["equity"] = self.renderer.render_equity_curve(equity_values)

        # ── Drawdown ──
        if not include or ReportSection.DRAWDOWN.value in include:
            if portfolio_equity is not None and len(portfolio_equity) > 0:
                dd = compute_drawdown_analysis(portfolio_equity)
                sections["drawdown"] = self.renderer.render_drawdown_analysis(dd)

        # ── Monthly Returns ──
        if not include or ReportSection.MONTHLY_RETURNS.value in include:
            if portfolio_ret is not None and len(portfolio_ret) > 0:
                monthly = compute_monthly_returns(
                    portfolio_ret, self.config.show_all_monthly
                )
                sections["monthly_returns"] = self.renderer.render_monthly_returns(monthly)

        # ── Annual Returns ──
        if not include or ReportSection.ANNUAL_RETURNS.value in include:
            if portfolio_ret is not None and len(portfolio_ret) > 0:
                annual = compute_annual_returns(portfolio_ret)
                if annual:
                    annual_items = "".join(
                        f'<tr><td>{year}</td><td class="text-right mono {"pos" if ret >= 0 else "neg"}">{ret:+.{self.config.decimal_places}f}%</td></tr>'
                        for year, ret in sorted(annual.items())
                    )
                    sections["annual_returns"] = f"""<table>
<thead><tr><th>年份</th><th class="text-right">年收益</th></tr></thead>
<tbody>{annual_items}</tbody>
</table>"""

        # ── Benchmark ──
        if not include or ReportSection.BENCHMARK.value in include:
            if benchmark_ret is not None and len(benchmark_ret) > 0:
                benchmark_metrics = {
                    k: v for k, v in metrics_dict.items()
                    if k.startswith("benchmark_") or k.startswith("active_")
                       or k in ("tracking_error_pct", "information_ratio", "alpha", "beta", "r_squared")
                }
                if benchmark_metrics:
                    sections["benchmark"] = self.renderer.render_benchmark_comparison(
                        benchmark_metrics
                    )

        # ── Attribution ──
        if not include or ReportSection.ATTRIBUTION.value in include:
            if attribution:
                attr_list = [
                    {
                        "strategy_name": a.strategy_name if hasattr(a, "strategy_name") else getattr(a, "get", lambda k, d=None: d)("strategy_name", "?"),
                        "weight": a.weight if hasattr(a, "weight") else getattr(a, "get", lambda k, d=None: d)("weight", 0),
                        "contribution_pct": a.contribution_pct if hasattr(a, "contribution_pct") else getattr(a, "get", lambda k, d=None: d)("contribution_pct", 0),
                        "standalone_return_pct": a.standalone_return_pct if hasattr(a, "standalone_return_pct") else getattr(a, "get", lambda k, d=None: d)("standalone_return_pct", 0),
                        "sharpe": a.sharpe if hasattr(a, "sharpe") else getattr(a, "get", lambda k, d=None: d)("sharpe", 0),
                        "correlation_to_portfolio": a.correlation_to_portfolio if hasattr(a, "correlation_to_portfolio") else getattr(a, "get", lambda k, d=None: d)("correlation_to_portfolio", 0),
                    }
                    for a in attribution
                ]
                sections["attribution"] = self.renderer.render_attribution(attr_list)

        # ── Correlation ──
        if not include or ReportSection.CORRELATION.value in include:
            if correlation_data is not None:
                if isinstance(correlation_data, pd.DataFrame) and not correlation_data.empty:
                    corr_items = _correlation_to_list(correlation_data)
                    sections["correlation"] = self.renderer.render_correlation(corr_items)

        # ── Risk ──
        if not include or ReportSection.RISK.value in include:
            if portfolio_ret is not None and len(portfolio_ret) > 0:
                risk = compute_risk_metrics(portfolio_ret)
                sections["risk"] = self.renderer.render_risk_metrics(risk)

        # ── Distribution ──
        if not include or ReportSection.DISTRIBUTION.value in include:
            if portfolio_ret is not None and len(portfolio_ret) > 0:
                dist = compute_return_distribution(portfolio_ret)
                sections["distribution"] = self.renderer.render_distribution(dist)

        # ── Trade Analysis ──
        if not include or ReportSection.TRADE_ANALYSIS.value in include:
            if portfolio_ret is not None and len(portfolio_ret) > 0:
                wl = compute_win_loss_analysis(portfolio_ret)
                sections["trade_analysis"] = self.renderer.render_win_loss_analysis(wl)

        # ── Warnings ──
        if warnings:
            sections.setdefault("overview", "")
            sections["overview"] += self.renderer.render_warnings(warnings)

        return sections

    # ─── 终处理 ────────────────────────────────────────────────────

    def _finalize(
        self,
        report_type: str,
        title: str,
        sections: dict[str, str],
        n_strategies: int,
        n_days: int,
        duration_ms: float,
        warnings: list[str],
        description: str = "",
        benchmark_name: str = "",
    ) -> StrategyReportResult:
        """组装最终报告结果

        - 渲染 HTML
        - 保存到磁盘
        - 构建 StrategyReportResult
        """
        now = datetime.now(CST)
        generated_at = now.isoformat()
        displayed_at = now.strftime("%Y-%m-%d %H:%M")

        metadata = {
            "description": description,
            "generated_at": displayed_at,
            "n_strategies": n_strategies,
            "n_days": n_days,
            "duration_ms": duration_ms,
        }

        html = self.renderer.render_full_report(
            report_type=report_type,
            title=title,
            sections_html=sections,
            metadata=metadata,
        )

        # 保存到磁盘
        output_path = self._save_report(
            html=html,
            report_type=report_type,
            title=title,
            generated_at=generated_at,
        )

        result = StrategyReportResult(
            report_type=report_type,
            title=title,
            description=description,
            sections_generated=list(sections.keys()),
            output_path=output_path,
            output_format=self.config.report_format,
            html_content=html,
            n_strategies=n_strategies,
            n_days=n_days,
            warnings=warnings,
            generated_at=generated_at,
            duration_ms=duration_ms,
        )

        return result

    # ─── 持久化 ────────────────────────────────────────────────────

    def _save_report(
        self,
        html: str,
        report_type: str,
        title: str,
        generated_at: str,
    ) -> str:
        """将 HTML 报告保存到磁盘

        路径: {output_dir}/{report_type}/{sanitized_title}_{timestamp}.html
        """
        output_dir = Path(self.config.output_dir or DEFAULT_OUTPUT_ROOT)
        type_dir = output_dir / report_type
        os.makedirs(type_dir, exist_ok=True)

        safe_title = "".join(
            c if c.isalnum() or c in ("-", "_") else "_"
            for c in title
        ).strip("_") or "report"

        ts = generated_at.replace(":", "-").split(".")[0]
        file_name = self.config.file_name or f"{safe_title}_{ts}.html"
        out_path = type_dir / file_name

        if self.config.report_format == ReportFormat.HTML.value:
            out_path.write_text(html, encoding="utf-8")
        elif self.config.report_format == ReportFormat.JSON.value:
            json_content = {"title": title, "html": html, "generated_at": generated_at}
            out_path = out_path.with_suffix(".json")
            out_path.write_text(
                json.dumps(json_content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif self.config.report_format == ReportFormat.TEXT.value:
            out_path = out_path.with_suffix(".txt")
            # 提取纯文本概览
            text = f"=== {title} ===\nGenerated: {generated_at}\nType: {report_type}\n"
            out_path.write_text(text, encoding="utf-8")

        return str(out_path)

    # ─── 列表 / 发现 ──────────────────────────────────────────────

    def list_reports(
        self,
        report_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """列出已生成的报告文件

        Args:
            report_type: 按类型筛选 (可选)
            limit: 最大返回数

        Returns:
            [{"path", "type", "title", "generated_at", "size"}, ...]
        """
        output_dir = Path(self.config.output_dir or DEFAULT_OUTPUT_ROOT)
        if not output_dir.exists():
            return []

        reports = []
        glob_pattern = "**/*.html" if not report_type else f"{report_type}/*.html"

        for path in sorted(output_dir.glob(glob_pattern), reverse=True):
            if not path.is_file():
                continue

            # 从文件名提取信息
            fname = path.stem
            size_kb = round(path.stat().st_size / 1024, 1)
            reports.append({
                "path": str(path),
                "file_name": path.name,
                "type": path.parent.name if path.parent != output_dir else "unknown",
                "title": fname,
                "size_kb": size_kb,
            })
            if len(reports) >= limit:
                break

        return reports

    def get_report_count(self) -> dict[str, int]:
        """按类型统计报告数量"""
        output_dir = Path(self.config.output_dir or DEFAULT_OUTPUT_ROOT)
        if not output_dir.exists():
            return {}

        counts: dict[str, int] = {}
        for path in output_dir.glob("*/*.html"):
            t = path.parent.name
            counts[t] = counts.get(t, 0) + 1
        return dict(sorted(counts.items()))


# ─── 辅助函数 ─────────────────────────────────────────────────────


def _correlation_to_list(corr_df: pd.DataFrame) -> list[dict]:
    """将相关性 DataFrame 转为 list[dict]"""
    items = []
    for i in corr_df.index:
        for j in corr_df.columns:
            val = corr_df.loc[i, j]
            if not pd.isna(val):
                items.append({
                    "strategy_i": str(i),
                    "strategy_j": str(j),
                    "correlation": round(val, 4),
                })
    return items
