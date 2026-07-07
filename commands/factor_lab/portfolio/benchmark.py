"""Benchmark Data V6.4 — 基准指数收益率

提供 A 股主要指数的收益率数据加载:
  - CSI300  (沪深 300)
  - CSI500  (中证 500)
  - CSI1000 (中证 1000)
  - CSI_ALL (中证全指)

支持:
  1) get_benchmark_returns() — 通用接口, 按名称获取
  2) 自定义 benchmark (通过 BenchmarkSpec(returns=...))
  3) 指数 ETF 收益率代理 (通过 get_etf_proxy_returns)

当前实现:
  由于无实时指数数据库, 提供两种模式:
  A. SyntheticReturns — 根据日期长度生成模拟基准 (用于测试/开发)
  B. ETF proxy — 通过指数 ETF 行情模拟基准 (需数据源)

注意:
  所有缺失数据标记为 partial, 不允许 silent fallback。
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.portfolio.spec import BenchmarkSpec

CST = timezone(timedelta(hours=8))

# ─── 标准指数定义 ─────────────────────────────────────────────

BENCHMARK_META = {
    "CSI300": {
        "name": "沪深300",
        "code": "000300.SH",
        "etf_symbol": "510300",
        "description": "沪深300指数 — 大盘蓝筹",
    },
    "CSI500": {
        "name": "中证500",
        "code": "000905.SH",
        "etf_symbol": "510500",
        "description": "中证500指数 — 中盘",
    },
    "CSI1000": {
        "name": "中证1000",
        "code": "000852.SH",
        "etf_symbol": "512100",
        "description": "中证1000指数 — 小盘",
    },
    "CSI_ALL": {
        "name": "中证全指",
        "code": "000985.SH",
        "etf_symbol": None,
        "description": "中证全指 — A股全市场",
    },
}

VALID_BENCHMARK_NAMES = set(BENCHMARK_META.keys())


def get_benchmark_meta(name: str) -> dict:
    """获取基准指数元信息

    Args:
        name: 基准名称, 如 "CSI300", "CSI500", "CSI1000", "CSI_ALL"

    Returns:
        元信息 dict

    Raises:
        ValueError: 不支持的基准名称
    """
    name_upper = name.upper().strip()
    if name_upper in BENCHMARK_META:
        return BENCHMARK_META[name_upper]
    raise ValueError(
        f"不支持的基准 '{name}', 可选: {sorted(VALID_BENCHMARK_NAMES)}"
    )


def get_benchmark_returns(
    benchmark_spec: BenchmarkSpec,
    index_dates: Optional[pd.DatetimeIndex] = None,
    method: str = "synthetic",
    seed: int = 42,
) -> pd.Series:
    """获取基准指数收益率序列

    Args:
        benchmark_spec: 基准规格
        index_dates: 对齐日期 (仅 synthetic 模式需要)
        method: 数据获取方法
            - "synthetic": 生成模拟基准收益 (用于测试)
            - "etf_proxy": 通过指数 ETF 行情获取 (需数据源)
        seed: 随机种子 (synthetic 模式)

    Returns:
        日收益率 Series, index=index_dates (synthetic) 或实际日期

    Raises:
        ValueError: 参数无效
    """
    if benchmark_spec is None:
        raise ValueError("benchmark_spec 不能为 None")

    name = benchmark_spec.name

    # 自定义 benchmark: 直接返回用户提供的 returns
    if name == "custom":
        if benchmark_spec.returns is not None and len(benchmark_spec.returns) > 0:
            result = benchmark_spec.returns.sort_index()
            result.name = "custom"
            return result
        raise ValueError("自定义基准 (name='custom') 必须提供 returns 序列")

    # 标准指数
    name_upper = name.upper().strip()
    if name_upper not in VALID_BENCHMARK_NAMES:
        raise ValueError(
            f"不支持的基准 '{name}', 可选: {sorted(VALID_BENCHMARK_NAMES)}"
        )

    if method == "synthetic":
        return _synthetic_benchmark_returns(
            name_upper, index_dates, seed
        )
    elif method == "etf_proxy":
        return _etf_proxy_benchmark_returns(name_upper, index_dates)
    else:
        raise ValueError(f"不支持的数据获取方法: {method}")


def _synthetic_benchmark_returns(
    name: str,
    index_dates: Optional[pd.DatetimeIndex],
    seed: int = 42,
) -> pd.Series:
    """生成模拟基准收益 (用于测试/开发环境)

    生成年化 8-12% 收益、15-20% 年化波动率的市场指数走势。

    Args:
        name: 基准名称 (仅用于命名)
        index_dates: 日期序列
        seed: 随机种子

    Returns:
        日收益率 Series
    """
    if index_dates is None or len(index_dates) < 2:
        # 生成默认日期 (过去 2 年)
        end = pd.Timestamp.now()
        start = end - pd.DateOffset(years=2)
        dates = pd.date_range(start, end, freq="B")
    else:
        dates = sorted(pd.DatetimeIndex(index_dates))

    n = len(dates)
    rng = np.random.default_rng(seed)

    # 各指数设定不同的收益/波动特征
    profiles = {
        "CSI300": {"mu": 0.08, "sigma": 0.18},    # 大盘: 低收益低波动
        "CSI500": {"mu": 0.10, "sigma": 0.22},    # 中盘: 中收益中波动
        "CSI1000": {"mu": 0.12, "sigma": 0.25},   # 小盘: 高收益高波动
        "CSI_ALL": {"mu": 0.09, "sigma": 0.20},   # 全市场: 中收益中波动
    }
    prof = profiles.get(name, profiles["CSI_ALL"])
    daily_mu = prof["mu"] / 252
    daily_sigma = prof["sigma"] / np.sqrt(252)

    # 生成带轻微自相关的收益率
    eps = rng.normal(daily_mu, daily_sigma, n)
    returns = pd.Series(eps, index=pd.DatetimeIndex(dates), name=name)

    return returns


def _etf_proxy_benchmark_returns(
    name: str,
    index_dates: Optional[pd.DatetimeIndex] = None,
) -> pd.Series:
    """通过指数 ETF 行情获取基准收益

    需要 RealtimeQuoteEngine 提供数据源。
    当数据不可用时, 降级为 synthetic 并记录 partial 标记。

    Args:
        name: 基准名称
        index_dates: 日期序列 (用于降级)

    Returns:
        日收益率 Series
    """
    # TODO(V6.4+): 接入 DataSource 获取指数 ETF 历史行情
    # 当前实现: synthetic 替代并发出警告
    warnings.warn(
        f"partial: 指数 ETF 数据源未接入, 使用 synthetic 替代 {name}"
    )

    returns = _synthetic_benchmark_returns(name, index_dates)
    returns.name = name
    return returns


def list_benchmarks() -> list[dict]:
    """列出所有可用的基准指数

    Returns:
        [{name, code, description}, ...]
    """
    return [
        {
            "name": k,
            "code": v["code"],
            "etf_symbol": v["etf_symbol"],
            "description": v["description"],
        }
        for k, v in BENCHMARK_META.items()
    ]


# ─── 便捷工厂函数 ──────────────────────────────────────────────

def make_benchmark_spec(name: str = "CSI300") -> BenchmarkSpec:
    """快速创建 BenchmarkSpec

    Args:
        name: 基准名称, "CSI300" / "CSI500" / "CSI1000" / "CSI_ALL"

    Returns:
        BenchmarkSpec 实例
    """
    name_upper = name.upper().strip()
    if name_upper not in VALID_BENCHMARK_NAMES:
        raise ValueError(
            f"不支持的基准 '{name}', 可选: {sorted(VALID_BENCHMARK_NAMES)}"
        )
    meta = BENCHMARK_META[name_upper]
    return BenchmarkSpec(
        name=name_upper,
        description=meta["description"],
    )
