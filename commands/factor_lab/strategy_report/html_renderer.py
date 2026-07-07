"""Strategy Report HTML Renderer V6.5 — HTML 报告渲染器

使用 Hermes DESIGN.md 设计系统生成现代化、信息密度高的策略报告 HTML。
支持单策略、组合、对比报告的渲染。

设计系统核心色:
  - 主色: #0F172A (深色标题/文本)
  - 辅色: #64748B (辅助文字/标签)
  - 强调色: #2563EB (指标/标题/链接)
  - 浅强调: #DBEAFE
  - 底色: #FFFFFF / #F8FAFC / #F1F5F9
  - 边距: #E2E8F0
  - 成功: #059669 | 警告: #D97706 | 错误: #DC2626
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Optional

from factor_lab.strategy_report.spec import (
    StrategyReportResult,
    ReportType,
    ReportSection,
    MonthlyReturnsTable,
    DrawdownAnalysis,
    WinLossAnalysis,
    RiskMetrics,
    StrategyReportConfig,
)


# ─── 设计系统 CSS ─────────────────────────────────────────────────

DESIGN_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#F8FAFC;color:#0F172A;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:0.875rem;line-height:1.5;padding:0;min-height:100vh}
.container{max-width:1200px;margin:0 auto;padding:0 24px 40px}

/* Header */
.report-header{border-bottom:1px solid #E2E8F0;padding:32px 0 24px;margin-bottom:24px}
.report-header h1{font-size:1.5rem;font-weight:700;color:#0F172A;margin-bottom:4px;letter-spacing:-0.01em}
.report-header .subtitle{font-size:0.875rem;color:#64748B;margin-bottom:12px}
.report-header .meta-row{display:flex;gap:24px;flex-wrap:wrap;font-size:0.75rem;color:#94A3B8}
.report-header .meta-row span{display:flex;align-items:center;gap:4px}

/* Cards */
.card{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;margin-bottom:20px;box-shadow:0 1px 3px 0 rgb(0 0 0 / 0.04);overflow:hidden}
.card-header{padding:16px 20px;border-bottom:1px solid #E2E8F0;display:flex;justify-content:space-between;align-items:center}
.card-header h2{font-size:1.125rem;font-weight:600;color:#0F172A}
.card-body{padding:20px}

/* Stats Grid */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat-card{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:16px;border-left:4px solid #2563EB;box-shadow:0 1px 3px 0 rgb(0 0 0 / 0.04)}
.stat-card.success{border-left-color:#059669}
.stat-card.warning{border-left-color:#D97706}
.stat-card.error{border-left-color:#DC2626}
.stat-card .stat-label{font-size:0.75rem;font-weight:500;color:#64748B;text-transform:none;margin-bottom:4px}
.stat-card .stat-value{font-size:1.5rem;font-weight:700;color:#0F172A;line-height:1.2}
.stat-card .stat-value.pos{color:#059669}
.stat-card .stat-value.neg{color:#DC2626}

/* Metrics Grid - smaller */
.metrics-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.metric{padding:12px;background:#F1F5F9;border-radius:6px;text-align:center}
.metric .metric-value{font-size:1.25rem;font-weight:700;color:#0F172A}
.metric .metric-value.pos{color:#059669}
.metric .metric-value.neg{color:#DC2626}
.metric .metric-label{font-size:0.75rem;color:#64748B;margin-top:2px}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:0.8125rem}
th{text-align:left;padding:10px 12px;border-bottom:2px solid #E2E8F0;color:#64748B;font-weight:600;font-size:0.75rem;white-space:nowrap;background:#F1F5F9}
td{padding:8px 12px;border-bottom:1px solid #E2E8F0;font-feature-settings:"tnum"}
tr:hover{background:#F8FAFC}
.text-right{text-align:right}
.text-center{text-align:center}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:0.75rem}

/* Monthly Returns Table */
.monthly-table th:first-child{min-width:60px}
.monthly-table .pos{color:#059669;font-weight:600}
.monthly-table .neg{color:#DC2626;font-weight:600}

/* Badges */
.badge{display:inline-block;font-size:0.75rem;font-weight:600;padding:2px 10px;border-radius:9999px}
.badge-success{background:#D1FAE5;color:#059669}
.badge-warning{background:#FEF3C7;color:#D97706}
.badge-error{background:#FEE2E2;color:#DC2626}
.badge-info{background:#DBEAFE;color:#2563EB}

/* Progress-like indicators */
.progress-track{display:flex;gap:1px;height:16px;align-items:flex-end}
.progress-bar-segment{flex:1;border-radius:2px;transition:all 0.2s}
.progress-bar-segment:hover{opacity:0.8}

/* Footer */
.report-footer{text-align:center;padding:24px 0;color:#94A3B8;font-size:0.75rem;border-top:1px solid #E2E8F0;margin-top:24px}

/* Equity curve (text-based sparkline) */
.sparkline{display:flex;align-items:flex-end;height:40px;gap:1px;padding:4px 0}
.sparkline .bar{flex:1;background:#2563EB;border-radius:1px;min-height:2px;opacity:0.7}
.sparkline .bar.pos{background:#059669}
.sparkline .bar.neg{background:#DC2626}

/* Warning / Error boxes */
.msg-box{padding:12px 16px;border-radius:6px;margin:8px 0;font-size:0.8125rem}
.msg-box.warning{background:#FEF3C7;border:1px solid #FDE68A;color:#92400E}
.msg-box.error{background:#FEE2E2;border:1px solid #FECACA;color:#991B1B}
.msg-box.info{background:#DBEAFE;border:1px solid #BFDBFE;color:#1E40AF}

/* Responsive */
@media(max-width:768px){
  .stats-grid{grid-template-columns:repeat(2,1fr)}
  .metrics-grid{grid-template-columns:repeat(2,1fr)}
  .container{padding:0 12px 20px}
}
"""


class HTMLReportRenderer:
    """HTML 报告渲染器

    使用 Hermes 设计系统生成策略报告 HTML。
    支持渲染各报告板块的独立方法，便于测试和扩展。
    """

    def __init__(self, config: Optional[StrategyReportConfig] = None):
        self.config = config or StrategyReportConfig()
        self.dp = self.config.decimal_places

    # ─── 报告级方法 ───────────────────────────────────────────────

    def render_full_report(
        self,
        report_type: str,
        title: str,
        sections_html: dict[str, str],
        metadata: Optional[dict] = None,
    ) -> str:
        """组装完整 HTML 报告

        Args:
            report_type: 报告类型
            title: 报告标题
            sections_html: 板块名称 → HTML 内容
            metadata: 元信息 dict

        Returns:
            完整 HTML 字符串
        """
        meta = metadata or {}
        sections_rendered = "".join(
            f'<div class="card" id="section-{key}">'
            f'<div class="card-header"><h2>{self._section_title(key)}</h2></div>'
            f'<div class="card-body">{html}</div></div>\n'
            for key, html in sections_html.items()
            if html
        )

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{self._escape(title)}</title>
<style>{DESIGN_CSS}</style>
</head>
<body>
<div class="container">

<div class="report-header">
  <h1>{self._escape(title)}</h1>
  <div class="subtitle">{self._escape(meta.get("description", ""))}</div>
  <div class="meta-row">
    <span>📋 类型: {report_type}</span>
    <span>📅 生成时间: {meta.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))}</span>
    {f'<span>📊 策略数: {meta.get("n_strategies", "")}</span>' if meta.get("n_strategies") else ""}
    {f'<span>📆 交易日: {meta.get("n_days", "")}</span>' if meta.get("n_days") else ""}
    {f'<span>⏱ 耗时: {meta.get("duration_ms", "")}ms</span>' if meta.get("duration_ms") else ""}
  </div>
</div>

{sections_rendered}

<div class="report-footer">
  Generated by Hermes Strategy Report Generator V6.5 &mdash; {meta.get("generated_at", "")}
</div>

</div>
</body>
</html>"""
        return html

    def _section_title(self, key: str) -> str:
        """板块 key → 可读标题"""
        titles = {
            "overview": "📊 概览",
            "metrics": "📈 核心指标",
            "equity": "📉 净值曲线",
            "drawdown": "📉 回撤分析",
            "monthly_returns": "📅 月度收益",
            "annual_returns": "📅 年度收益",
            "benchmark": "🎯 基准对比",
            "attribution": "🔍 归因分析",
            "correlation": "🔗 相关性分析",
            "risk": "🛡️ 风险指标",
            "distribution": "📊 收益分布",
            "rolling": "📈 滚动指标",
            "trade_analysis": "📊 盈亏分析",
            "raw_data": "📋 原始数据",
        }
        return titles.get(key, key)

    # ─── 板块渲染方法 ─────────────────────────────────────────────

    def render_overview(
        self,
        strategy_name: str,
        report_type: str,
        n_strategies: int = 0,
        n_days: int = 0,
        benchmark: str = "",
        description: str = "",
    ) -> str:
        """渲染概览板块"""
        parts = []

        # 报表卡
        parts.append(f"""
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">策略名称</div>
            <div class="stat-value" style="font-size:1.25rem">{self._escape(strategy_name)}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">报告类型</div>
            <div class="stat-value" style="font-size:1.25rem">{report_type}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">交易日数</div>
            <div class="stat-value">{n_days}</div>
          </div>
        </div>
        """ if description else f"""
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">策略名称</div>
            <div class="stat-value" style="font-size:1.25rem">{self._escape(strategy_name)}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">报告类型</div>
            <div class="stat-value" style="font-size:1.25rem">{report_type}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">交易日数</div>
            <div class="stat-value">{n_days}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">基准</div>
            <div class="stat-value" style="font-size:1.25rem">{self._escape(benchmark) if benchmark else "无"}</div>
          </div>
        </div>
        """)

        return "".join(parts)

    def render_metrics_table(self, metrics: dict) -> str:
        """渲染指标表格 (key → value 对)

        Args:
            metrics: 指标 dict

        Returns:
            HTML 表格
        """
        if not metrics:
            return '<div class="msg-box info">无指标数据</div>'

        rows = []
        pos_keys = {
            "cumulative_return_pct", "annualized_return_pct", "sharpe",
            "calmar", "win_rate_pct", "information_ratio", "alpha",
            "active_return_pct", "sortino_ratio",
        }
        neg_keys = {
            "max_drawdown_pct", "annualized_volatility_pct",
            "tracking_error_pct",
        }

        for key, value in metrics.items():
            label = self._metric_label(key)
            if isinstance(value, float):
                display = f"{value:.{self.dp}f}"
                css_class = ""
                if key in pos_keys:
                    css_class = "pos" if value > 0 else ""
                elif key in neg_keys:
                    css_class = "neg" if value > 0 else ""
                elif key == "beta":
                    css_class = ""
            elif isinstance(value, int):
                display = str(value)
                css_class = ""
            else:
                display = str(value)
                css_class = ""

            rows.append(
                f'<tr><td>{self._escape(label)}</td>'
                f'<td class="text-right mono"><span class="{css_class}">{self._escape(display)}</span></td></tr>'
            )

        return f"""<table>
<thead><tr><th style="width:60%">指标</th><th class="text-right">值</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""

    def render_equity_curve(self, equity_values: list[float]) -> str:
        """渲染简易文本净值曲线

        由于无 Chart.js 依赖，使用条形迷你图 (sparkline) 展示。

        Args:
            equity_values: 净值序列

        Returns:
            HTML 迷你图
        """
        if not equity_values:
            return '<div class="msg-box info">无净值数据</div>'

        n = len(equity_values)
        max_val = max(equity_values)
        min_val = min(equity_values)
        range_val = max_val - min_val if max_val != min_val else 1

        # 等间隔采样最多 200 个点
        if n > 200:
            step = n // 200
            sampled = equity_values[::step]
        else:
            sampled = equity_values

        bars = []
        for val in sampled:
            height = max(2, int((val - min_val) / range_val * 36))
            cls = "pos" if val >= 1.0 else "neg"
            bars.append(f'<div class="bar {cls}" style="height:{height}px" title="{val:.4f}"></div>')

        # 基础统计
        start_val = equity_values[0]
        end_val = equity_values[-1]
        total_ret = (end_val / start_val - 1) * 100 if start_val != 0 else 0

        return f"""<div class="sparkline">{''.join(bars)}</div>
<div class="stats-grid" style="margin-top:12px">
  <div class="stat-card">
    <div class="stat-label">起始净值</div>
    <div class="stat-value" style="font-size:1rem">{start_val:.4f}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">最终净值</div>
    <div class="stat-value" style="font-size:1rem">{end_val:.4f}</div>
  </div>
  <div class="stat-card { 'success' if total_ret >= 0 else 'error' }">
    <div class="stat-label">总收益</div>
    <div class="stat-value {'pos' if total_ret >= 0 else 'neg'}" style="font-size:1rem">{total_ret:+.{self.dp}f}%</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">数据点</div>
    <div class="stat-value" style="font-size:1rem">{n}</div>
  </div>
</div>"""

    def render_monthly_returns(
        self, monthly_tables: list[MonthlyReturnsTable]
    ) -> str:
        """渲染月度收益表

        Args:
            monthly_tables: MonthlyReturnsTable 列表

        Returns:
            HTML 表格
        """
        if not monthly_tables:
            return '<div class="msg-box info">无月度数据</div>'

        all_months = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]

        # 表头
        header_cells = "".join(
            f'<th class="text-center">{m}</th>' for m in all_months
        )
        header = (
            f"<thead><tr><th>年份</th>{header_cells}"
            f'<th class="text-right">年收益</th></tr></thead>'
        )

        # 表体
        body_rows = []
        for table in monthly_tables:
            cells = []
            for m in all_months:
                val = table.data.get(m)
                if val is not None:
                    cls = "pos" if val >= 0 else "neg"
                    cells.append(f'<td class="text-center {cls}">{val:+.1f}%</td>')
                else:
                    cells.append('<td class="text-center" style="color:#CBD5E1">—</td>')

            ann_cls = "pos" if table.annual_return_pct >= 0 else "neg"
            body_rows.append(
                f"<tr><td><strong>{table.year}</strong></td>"
                f"{''.join(cells)}"
                f'<td class="text-right {ann_cls}"><strong>{table.annual_return_pct:+.1f}%</strong></td></tr>'
            )

        return f"""<table class="monthly-table">{header}<tbody>{''.join(body_rows)}</tbody></table>"""

    def render_drawdown_analysis(self, analysis: DrawdownAnalysis) -> str:
        """渲染回撤分析

        Args:
            analysis: DrawdownAnalysis 对象

        Returns:
            HTML
        """
        if analysis.max_drawdown_pct == 0:
            return '<div class="msg-box info">无回撤数据</div>'

        parts = []

        # 指标网格
        dd_cls = "error" if analysis.max_drawdown_pct < -5 else "warning"
        parts.append(f"""
        <div class="stats-grid">
          <div class="stat-card {dd_cls}">
            <div class="stat-label">最大回撤</div>
            <div class="stat-value neg" style="font-size:1rem">{analysis.max_drawdown_pct:.{self.dp}f}%</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">最大回撤持续天数</div>
            <div class="stat-value" style="font-size:1rem">{analysis.max_drawdown_duration_days} 天</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">平均回撤</div>
            <div class="stat-value" style="font-size:1rem">{analysis.avg_drawdown_pct:.{self.dp}f}%</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">水下时间占比</div>
            <div class="stat-value" style="font-size:1rem">{analysis.underwater_days_pct:.1f}%</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">当前回撤</div>
            <div class="stat-value {'neg' if analysis.current_drawdown_pct < 0 else 'pos'}" style="font-size:1rem">{analysis.current_drawdown_pct:.{self.dp}f}%</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">恢复天数</div>
            <div class="stat-value" style="font-size:1rem">{analysis.recovery_days if analysis.recovery_days > 0 else '未恢复'}</div>
          </div>
        </div>
        """)

        # 前 N 大回撤期
        if analysis.drawdown_periods:
            period_rows = []
            for i, dp in enumerate(analysis.drawdown_periods, 1):
                period_rows.append(f"""
                <tr>
                  <td>{i}</td>
                  <td class="mono">{dp.get("peak_date", "?")}</td>
                  <td class="mono">{dp.get("trough_date", "?")}</td>
                  <td class="text-right neg">{dp.get("max_drawdown_pct", 0):.{self.dp}f}%</td>
                  <td class="text-right">{dp.get("duration_days", 0)} 天</td>
                </tr>
                """)

            parts.append(f"""
            <h3 style="font-size:0.875rem;font-weight:600;margin:16px 0 8px;color:#64748B">前 {len(analysis.drawdown_periods)} 大回撤期</h3>
            <table>
              <thead><tr><th>#</th><th>峰值日期</th><th>谷值日期</th><th class="text-right">回撤</th><th class="text-right">持续期</th></tr></thead>
              <tbody>{''.join(period_rows)}</tbody>
            </table>
            """)

        return "".join(parts)

    def render_win_loss_analysis(self, analysis: WinLossAnalysis) -> str:
        """渲染盈亏分析

        Args:
            analysis: WinLossAnalysis 对象

        Returns:
            HTML
        """
        if analysis.total_trades == 0:
            return '<div class="msg-box info">无交易数据</div>'

        return f"""
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">总交易天数</div>
            <div class="stat-value" style="font-size:1rem">{analysis.total_trades}</div>
          </div>
          <div class="stat-card success">
            <div class="stat-label">盈利天数</div>
            <div class="stat-value pos" style="font-size:1rem">{analysis.winning_trades}</div>
          </div>
          <div class="stat-card error">
            <div class="stat-label">亏损天数</div>
            <div class="stat-value neg" style="font-size:1rem">{analysis.losing_trades}</div>
          </div>
          <div class="stat-card { 'success' if analysis.win_rate_pct >= 50 else 'warning' }">
            <div class="stat-label">胜率</div>
            <div class="stat-value {'pos' if analysis.win_rate_pct >= 50 else ''}" style="font-size:1rem">{analysis.win_rate_pct:.1f}%</div>
          </div>
          <div class="stat-card success">
            <div class="stat-label">平均盈利</div>
            <div class="stat-value pos" style="font-size:1rem">{analysis.avg_win_pct:.{self.dp}f}%</div>
          </div>
          <div class="stat-card error">
            <div class="stat-label">平均亏损</div>
            <div class="stat-value neg" style="font-size:1rem">{analysis.avg_loss_pct:.{self.dp}f}%</div>
          </div>
          <div class="stat-card { 'success' if analysis.profit_factor >= 1.5 else 'warning' }">
            <div class="stat-label">盈亏比</div>
            <div class="stat-value" style="font-size:1rem">{analysis.profit_factor:.2f}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">最大连盈</div>
            <div class="stat-value pos" style="font-size:1rem">{analysis.max_consecutive_wins} 天</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">最大连亏</div>
            <div class="stat-value neg" style="font-size:1rem">{analysis.max_consecutive_losses} 天</div>
          </div>
        </div>
        """

    def render_risk_metrics(self, risk: RiskMetrics) -> str:
        """渲染风险指标

        Args:
            risk: RiskMetrics 对象

        Returns:
            HTML
        """
        if risk.var_95_pct == 0 and risk.sortino_ratio == 0:
            return '<div class="msg-box info">无风险数据</div>'

        return f"""
        <div class="metrics-grid">
          <div class="metric">
            <div class="metric-value neg">-{abs(risk.var_95_pct):.{self.dp}f}%</div>
            <div class="metric-label">95% VaR (日)</div>
          </div>
          <div class="metric">
            <div class="metric-value neg">-{abs(risk.cvar_95_pct):.{self.dp}f}%</div>
            <div class="metric-label">95% CVaR (日)</div>
          </div>
          <div class="metric">
            <div class="metric-value">{risk.skewness:.{self.dp}f}</div>
            <div class="metric-label">偏度 (Skewness)</div>
          </div>
          <div class="metric">
            <div class="metric-value">{risk.kurtosis:.{self.dp}f}</div>
            <div class="metric-label">峰度 (Kurtosis)</div>
          </div>
          <div class="metric">
            <div class="metric-value">{risk.downside_deviation_pct:.{self.dp}f}%</div>
            <div class="metric-label">下行波动率</div>
          </div>
          <div class="metric">
            <div class="metric-value {'pos' if risk.sortino_ratio > 0 else 'neg'}">{risk.sortino_ratio:.{self.dp}f}</div>
            <div class="metric-label">Sortino 比率</div>
          </div>
          <div class="metric">
            <div class="metric-value">{risk.ulcer_index:.{self.dp}f}</div>
            <div class="metric-label">Ulcer 指数</div>
          </div>
          <div class="metric">
            <div class="metric-value">{risk.tail_ratio:.{self.dp}f}</div>
            <div class="metric-label">尾部比率</div>
          </div>
        </div>
        """

    def render_benchmark_comparison(self, metrics: dict) -> str:
        """渲染基准对比

        Args:
            metrics: 包含 benchmark_ 和 active_ 前缀的指标 dict

        Returns:
            HTML
        """
        if not metrics:
            return '<div class="msg-box info">无基准数据</div>'

        bm_keys = {
            "benchmark_cumulative_return_pct": "基准累计收益",
            "benchmark_annualized_return_pct": "基准年化收益",
            "benchmark_volatility_pct": "基准年化波动",
            "benchmark_sharpe": "基准 Sharpe",
            "benchmark_max_drawdown_pct": "基准最大回撤",
            "active_return_pct": "主动收益 (超额)",
            "tracking_error_pct": "跟踪误差",
            "information_ratio": "信息比率",
            "alpha": "Alpha",
            "beta": "Beta",
            "r_squared": "R²",
        }

        rows = []
        for key, label in bm_keys.items():
            if key not in metrics:
                continue
            value = metrics[key]

            if isinstance(value, float):
                if key in ("benchmark_sharpe", "information_ratio", "alpha", "beta", "r_squared"):
                    display = f"{value:.{self.dp}f}"
                else:
                    display = f"{value:.{self.dp}f}%"
            else:
                display = str(value)

            css_class = ""
            if key in ("active_return_pct", "information_ratio", "alpha"):
                css_class = "pos" if value > 0 else "neg"
            elif key in ("benchmark_sharpe",):
                css_class = "pos" if value > 0 else ""

            rows.append(
                f'<tr><td>{label}</td>'
                f'<td class="text-right mono"><span class="{css_class}">{display}</span></td></tr>'
            )

        return f"""<table>
<thead><tr><th style="width:60%">指标</th><th class="text-right">值</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""

    def render_attribution(self, attribution: list[dict]) -> str:
        """渲染归因分析

        Args:
            attribution: 归因列表 [{strategy_name, weight, contribution_pct, ...}]

        Returns:
            HTML 表格
        """
        if not attribution:
            return '<div class="msg-box info">无归因数据</div>'

        rows = []
        for a in attribution:
            contrib_cls = "pos" if a.get("contribution_pct", 0) >= 0 else "neg"
            rows.append(f"""<tr>
<td>{self._escape(a.get("strategy_name", "?"))}</td>
<td class="text-right">{a.get("weight", 0):.2f}</td>
<td class="text-right {contrib_cls}">{a.get("contribution_pct", 0):.1f}%</td>
<td class="text-right">{a.get("standalone_return_pct", 0):.2f}%</td>
<td class="text-right">{a.get("sharpe", 0):.4f}</td>
<td class="text-right">{a.get("correlation_to_portfolio", 0):.4f}</td>
</tr>""")

        return f"""<table>
<thead><tr>
<th>策略</th><th class="text-right">权重</th><th class="text-right">贡献%</th>
<th class="text-right">独自收益</th><th class="text-right">Sharpe</th><th class="text-right">与组合相关</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""

    def render_correlation(self, correlation: list[dict]) -> str:
        """渲染交叉相关性

        Args:
            correlation: [{strategy_i, strategy_j, correlation}, ...]

        Returns:
            HTML 表格
        """
        if not correlation:
            return '<div class="msg-box info">无相关性数据</div>'

        # 只显示 i < j 的记录以去重
        filtered = [c for c in correlation if c["strategy_i"] < c["strategy_j"]]
        if not filtered:
            filtered = correlation

        rows = []
        for c in filtered:
            corr = c.get("correlation", 0)
            cls = ""
            if abs(corr) > 0.7:
                cls = "neg" if corr > 0 else "pos"
            rows.append(f"""<tr>
<td>{self._escape(c.get("strategy_i", "?"))}</td>
<td>{self._escape(c.get("strategy_j", "?"))}</td>
<td class="text-right mono"><span class="{cls}">{corr:.4f}</span></td>
</tr>""")

        return f"""<table>
<thead><tr><th>策略 A</th><th>策略 B</th><th class="text-right">相关系数</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""

    def render_distribution(self, dist: dict) -> str:
        """渲染收益分布

        Args:
            dist: return_distribution() 的输出

        Returns:
            HTML
        """
        if not dist:
            return '<div class="msg-box info">无分布数据</div>'

        # 统计指标
        stat_rows = f"""
        <div class="stats-grid" style="margin-bottom:16px">
          <div class="stat-card"><div class="stat-label">平均</div><div class="stat-value" style="font-size:1rem">{dist.get("mean", 0):.{self.dp}f}%</div></div>
          <div class="stat-card"><div class="stat-label">中位数</div><div class="stat-value" style="font-size:1rem">{dist.get("median", 0):.{self.dp}f}%</div></div>
          <div class="stat-card"><div class="stat-label">标准差</div><div class="stat-value" style="font-size:1rem">{dist.get("std", 0):.{self.dp}f}%</div></div>
          <div class="stat-card success"><div class="stat-label">正收益占比</div><div class="stat-value pos" style="font-size:1rem">{dist.get("positive_pct", 0):.1f}%</div></div>
          <div class="stat-card error"><div class="stat-label">负收益占比</div><div class="stat-value neg" style="font-size:1rem">{dist.get("negative_pct", 0):.1f}%</div></div>
        </div>
        """

        # 频率条 (作为进度条展示)
        max_freq = max(dist.get("frequencies", [0.01]))
        bar_rows = []
        bins = dist.get("bins", [])
        freqs = dist.get("frequencies", [])
        counts = dist.get("counts", [])

        for i in range(len(bins)):
            pct = (freqs[i] / max_freq) * 100 if max_freq > 0 else 0
            is_pos = "pos" if "~" not in bins[i] and float(bins[i].split("~")[0]) >= 0 else "neg"
            bar_rows.append(f"""
            <tr>
              <td class="mono">{bins[i]}</td>
              <td>
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="flex:1;height:16px;background:#F1F5F9;border-radius:4px;overflow:hidden">
                    <div style="height:100%;width:{pct:.1f}%;background:#2563EB;border-radius:4px;transition:width 0.3s"></div>
                  </div>
                  <span class="mono" style="color:#64748B;min-width:40px;text-align:right">{counts[i]}</span>
                </div>
              </td>
            </tr>
            """)

        dist_table = f"""<table>
<thead><tr><th style="width:30%">区间</th><th>频数</th></tr></thead>
<tbody>{''.join(bar_rows)}</tbody>
</table>"""

        return stat_rows + dist_table

    def render_rolling_metrics(self, rolling_data: dict) -> str:
        """渲染滚动指标

        Args:
            rolling_data: compute_rolling_metrics() 的输出
                         {series_name: [values, ...]}

        Returns:
            HTML 展示
        """
        if not rolling_data:
            return '<div class="msg-box info">无滚动指标数据</div>'

        parts = []
        for name, series in rolling_data.items():
            if not isinstance(series, list) or not series:
                continue

            n = len(series)
            recent = series[-min(5, n):]

            label = {
                "rolling_sharpe": "滚动 Sharpe (60日)",
                "rolling_volatility": "滚动波动率 (60日)",
                "rolling_return": "滚动收益 (60日)",
            }.get(name, name)

            # 简单文字统计
            max_val = max(series)
            min_val = min(series)
            avg_val = sum(series) / n if n > 0 else 0

            parts.append(f"""
            <h3 style="font-size:0.875rem;font-weight:600;margin:12px 0 8px;color:#64748B">{label}</h3>
            <div class="metrics-grid">
              <div class="metric"><div class="metric-value">{avg_val:.{self.dp}f}</div><div class="metric-label">平均</div></div>
              <div class="metric"><div class="metric-value">{max_val:.{self.dp}f}</div><div class="metric-label">最大</div></div>
              <div class="metric"><div class="metric-value">{min_val:.{self.dp}f}</div><div class="metric-label">最小</div></div>
              <div class="metric"><div class="metric-value" style="font-size:0.9rem">{recent[-1]:.{self.dp}f}</div><div class="metric-label">当前值</div></div>
            </div>
            """)

        return "".join(parts)

    def render_warnings(self, warnings: list[str]) -> str:
        """渲染警告信息

        Args:
            warnings: 警告字符串列表

        Returns:
            HTML 警告框
        """
        if not warnings:
            return ""
        items = "".join(f"<li>{self._escape(w)}</li>" for w in warnings)
        return f'<div class="msg-box warning"><strong>⚠ 警告 ({len(warnings)})</strong><ul style="margin:4px 0 0 16px">{items}</ul></div>'

    # ─── 辅助方法 ──────────────────────────────────────────────────

    def _metric_label(self, key: str) -> str:
        """指标 key → 可读中文标签"""
        labels = {
            "cumulative_return_pct": "累计收益率",
            "annualized_return_pct": "年化收益率",
            "annualized_volatility_pct": "年化波动率",
            "sharpe": "Sharpe Ratio",
            "max_drawdown_pct": "最大回撤",
            "calmar": "Calmar Ratio",
            "win_rate_pct": "日胜率",
            "n_trading_days": "交易日数",
            "benchmark_cumulative_return_pct": "基准累计收益",
            "benchmark_annualized_return_pct": "基准年化收益",
            "benchmark_volatility_pct": "基准年化波动",
            "benchmark_sharpe": "基准 Sharpe",
            "benchmark_max_drawdown_pct": "基准最大回撤",
            "active_return_pct": "主动收益 (超额)",
            "tracking_error_pct": "跟踪误差",
            "information_ratio": "信息比率",
            "alpha": "Alpha",
            "beta": "Beta",
            "r_squared": "R²",
            "avg_cross_correlation": "平均交叉相关性",
            "n_strategies": "策略数量",
            "sortino_ratio": "Sortino 比率",
            "downside_deviation_pct": "下行波动率",
        }
        return labels.get(key, key)

    @staticmethod
    def _escape(text: str) -> str:
        """HTML 转义"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
