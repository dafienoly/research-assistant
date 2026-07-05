"""回测结果标准化数据结构"""
from dataclasses import dataclass, field
from typing import Optional, List
import pandas as pd
import numpy as np
from datetime import datetime

@dataclass
class BacktestResult:
    """标准化回测结果，作为报告生成的输入"""
    strategy_returns: pd.Series       # 策略每日收益率，index=date
    benchmark_returns: pd.Series      # 基准每日收益率，index=date
    equity_curve: pd.Series           # 策略净值
    benchmark_curve: pd.Series        # 基准净值
    positions: Optional[pd.DataFrame] = None  # 每日持仓
    trades: Optional[pd.DataFrame] = None     # 交易流水
    factor_name: str = ""             # 因子名称
    factor_expression: str = ""       # 因子表达式
    strategy_name: str = "Strategy"   # 策略名称
    universe: str = ""                # 股票池
    benchmark_name: str = "沪深300"   # 基准名称
    start_date: str = ""              # 回测开始
    end_date: str = ""                # 回测结束
    rebalance_freq: str = "daily"     # 调仓频率
    cost_config: dict = field(default_factory=lambda: {
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.0005,
        "slippage_bps": 10,
        "min_commission": 5.0,
    })
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    _extras: dict = field(default_factory=dict)  # 扩展字段（universe_ew等）
    
    def validate(self):
        """验证数据完整性"""
        if self.strategy_returns is None or len(self.strategy_returns) == 0:
            raise ValueError("strategy_returns 为空")
        if self.benchmark_returns is None or len(self.benchmark_returns) == 0:
            raise ValueError("benchmark_returns 为空")
        if self.equity_curve is None or len(self.equity_curve) == 0:
            raise ValueError("equity_curve 为空")
        
        # 日期对齐检查
        common = self.strategy_returns.index.intersection(self.benchmark_returns.index)
        if len(common) < 20:
            raise ValueError(f"策略与基准的日期对齐后不足20个交易日 (共{len(common)}天)")
        
        # 检查未来函数
        if self.start_date and self.end_date:
            start = pd.Timestamp(self.start_date)
            end = pd.Timestamp(self.end_date)
            if self.strategy_returns.index.min() < start:
                raise ValueError(f"策略收益率包含回测开始日期({start})之前的数据")
            if self.strategy_returns.index.max() > end:
                raise ValueError(f"策略收益率包含回测结束日期({end})之后的数据")


def compute_equity_curve(returns: pd.Series, initial_capital: float = 1.0) -> pd.Series:
    """从收益率序列计算净值曲线"""
    return (1 + returns).cumprod() * initial_capital


def compute_drawdown(equity: pd.Series) -> pd.Series:
    """计算回撤序列"""
    rolling_max = equity.cummax()
    return (equity - rolling_max) / rolling_max


def align_returns(strategy: pd.Series, benchmark: pd.Series) -> tuple:
    """对齐策略和基准的日期"""
    common = strategy.index.intersection(benchmark.index)
    return strategy.loc[common].sort_index(), benchmark.loc[common].sort_index()