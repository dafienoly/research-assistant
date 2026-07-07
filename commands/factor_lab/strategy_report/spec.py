"""Strategy Report Spec V6.5 — 策略报告数据结构

定义报告类型、格式、配置和结果的数据结构。
支持单策略分析报告、组合策略报告、多策略对比报告。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd


# ─── Enums ────────────────────────────────────────────────────────


class ReportType(str, Enum):
    """报告类型"""
    SINGLE_STRATEGY = "single_strategy"      # 单策略分析
    PORTFOLIO = "portfolio"                  # 组合策略
    COMPARISON = "comparison"                # 多策略对比
    BACKTEST = "backtest"                    # 回测报告


VALID_REPORT_TYPES = {e.value for e in ReportType}


class ReportFormat(str, Enum):
    """报告输出格式"""
    HTML = "html"
    JSON = "json"
    TEXT = "text"


VALID_REPORT_FORMATS = {e.value for e in ReportFormat}


class ReportSection(str, Enum):
    """报告板块"""
    OVERVIEW = "overview"                    # 概览
    METRICS = "metrics"                      # 核心指标
    EQUITY = "equity"                        # 净值曲线
    DRAWDOWN = "drawdown"                    # 回撤分析
    MONTHLY_RETURNS = "monthly_returns"      # 月度收益
    ANNUAL_RETURNS = "annual_returns"        # 年度收益
    BENCHMARK = "benchmark"                  # 基准对比
    ATTRIBUTION = "attribution"              # 归因分析
    CORRELATION = "correlation"              # 相关性
    RISK = "risk"                            # 风险分析
    DISTRIBUTION = "distribution"            # 收益率分布
    ROLLING = "rolling"                      # 滚动指标
    TRADE_ANALYSIS = "trade_analysis"        # 交易分析
    RAW_DATA = "raw_data"                    # 原始数据


# ─── Report Configuration ─────────────────────────────────────────


@dataclass
class StrategyReportConfig:
    """策略报告生成配置

    Attributes:
        include_sections: 要包含的板块列表 (默认全部)
        report_format: 输出格式 (默认 HTML)
        output_dir: 输出目录 (默认 auto)
        file_name: 文件名 (默认 auto)
        show_all_monthly: 月度收益表显示所有月份
        decimal_places: 指标小数位
        include_raw_data: 是否包含原始数据 (作为 JSON 嵌入)
        theme: 主题风格, "light" / "dark"
        title: 报告标题 (默认 auto)
        description: 报告描述
        author: 报告作者
        benchmark_name: 基准名称 (用于标题展示)
    """
    include_sections: list[str] | None = None
    report_format: str = ReportFormat.HTML.value
    output_dir: str | None = None
    file_name: str | None = None
    show_all_monthly: bool = False
    decimal_places: int = 2
    include_raw_data: bool = False
    theme: str = "light"
    title: str = ""
    description: str = ""
    author: str = ""
    benchmark_name: str = ""

    def validate(self) -> list[str]:
        """校验配置合法性"""
        errors: list[str] = []

        if self.report_format not in VALID_REPORT_FORMATS:
            errors.append(
                f"不支持的格式 '{self.report_format}', "
                f"可选: {sorted(VALID_REPORT_FORMATS)}"
            )

        if self.include_sections:
            for sec in self.include_sections:
                if sec not in {s.value for s in ReportSection}:
                    errors.append(f"未知板块 '{sec}'")
                    break

        if self.theme not in ("light", "dark"):
            errors.append(f"不支持的主题 '{self.theme}', 可选: light/dark")

        return errors

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyReportResult:
    """策略报告生成结果

    Attributes:
        report_type: 报告类型
        title: 报告标题
        description: 报告描述
        sections_generated: 已生成的板块列表
        output_path: 输出文件路径
        output_format: 输出格式
        html_content: HTML 内容 (仅 HTML 格式)
        json_content: JSON 内容 dict (仅 JSON 格式)
        n_strategies: 策略数量
        n_days: 交易日数
        errors: 生成过程中的错误
        warnings: 生成过程中的警告
        generated_at: 生成时间
        duration_ms: 生成耗时 (毫秒)
    """
    report_type: str = ReportType.SINGLE_STRATEGY.value
    title: str = ""
    description: str = ""
    sections_generated: list[str] = field(default_factory=list)
    output_path: str = ""
    output_format: str = ReportFormat.HTML.value
    html_content: str = ""
    json_content: dict = field(default_factory=dict)
    n_strategies: int = 0
    n_days: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "report_type": self.report_type,
            "title": self.title,
            "description": self.description,
            "sections_generated": self.sections_generated,
            "output_path": self.output_path,
            "output_format": self.output_format,
            "n_strategies": self.n_strategies,
            "n_days": self.n_days,
            "errors": self.errors,
            "warnings": self.warnings,
            "generated_at": self.generated_at,
            "duration_ms": self.duration_ms,
        }


# ─── Monthly Returns ──────────────────────────────────────────────


@dataclass
class MonthlyReturnsTable:
    """月度收益表"""
    year: int = 0
    data: dict[str, float] = field(default_factory=dict)  # month_str → return_pct
    annual_return_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "data": self.data,
            "annual_return_pct": self.annual_return_pct,
        }


@dataclass
class DrawdownAnalysis:
    """回撤分析

    Attributes:
        max_drawdown_pct: 最大回撤
        max_drawdown_duration_days: 最大回撤持续天数
        avg_drawdown_pct: 平均回撤
        avg_drawdown_duration_days: 平均回撤持续天数
        recovery_days: 恢复天数 (0 = 尚未恢复)
        underwater_days: 水下天数 (净值为负的天数占比)
        current_drawdown_pct: 当前回撤率
        drawdown_periods: 前 N 大回撤期列表
    """
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    avg_drawdown_pct: float = 0.0
    avg_drawdown_duration_days: float = 0.0
    recovery_days: int = 0
    underwater_days_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    drawdown_periods: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_drawdown_duration_days": self.max_drawdown_duration_days,
            "avg_drawdown_pct": self.avg_drawdown_pct,
            "avg_drawdown_duration_days": self.avg_drawdown_duration_days,
            "recovery_days": self.recovery_days,
            "underwater_days_pct": self.underwater_days_pct,
            "current_drawdown_pct": self.current_drawdown_pct,
            "drawdown_periods": self.drawdown_periods,
        }


@dataclass
class WinLossAnalysis:
    """盈亏分析"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_consecutive_wins: float = 0.0
    avg_consecutive_losses: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskMetrics:
    """风险指标"""
    var_95_pct: float = 0.0          # 95% VaR
    cvar_95_pct: float = 0.0         # 95% CVaR
    skewness: float = 0.0             # 偏度
    kurtosis: float = 0.0            # 峰度
    downside_deviation_pct: float = 0.0  # 下行波动率
    sortino_ratio: float = 0.0       # Sortino 比率
    ulcer_index: float = 0.0         # Ulcer 指数
    pain_index: float = 0.0          # Pain 指数
    tail_ratio: float = 0.0          # 尾部比率 (95/5)
    daily_value_at_risk_pct: float = 0.0  # 日 VaR

    def to_dict(self) -> dict:
        return asdict(self)
