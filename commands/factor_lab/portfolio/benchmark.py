"""Benchmark Data V6.5 — 基准指数收益率

提供 A 股主要指数的真实收益率数据加载:
  - CSI300  (沪深 300)
  - CSI500  (中证 500)
  - CSI1000 (中证 1000)
  - CSI_ALL (中证全指)

数据源:
  1) canonical DataHub market_series/index
  2) synthetic — 仅允许测试显式调用 (标记 deprecation)

变更记录:
  V6.5 — 从合成随机数据改为真实 A 股指数行情数据
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.portfolio.spec import BenchmarkSpec
from factor_lab.datahub_access import DATAHUB_ROOT

logger = logging.getLogger(__name__)

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

# 标准指数代码 → canonical DataHub 文件代码映射
_INDEX_DATAHUB_MAP = {
    "000300.SH": "000300.SH",
    "000905.SH": "000905.SH",
    "000852.SH": "000852.SH",
    "000985.SH": "000985.CSI",
}

# ─── 数据获取 ──────────────────────────────────────────────────


def fetch_index_kline(
    index_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """获取 A 股指数日行情数据

    只读 canonical DataHub 指数序列，禁止研究和回测模块自行联网。

    Args:
        index_code: 标准指数代码, 如 "000300.SH", "000905.SH"
        start_date: 开始日期 "YYYYMMDD", 默认 3 年前
        end_date: 结束日期 "YYYYMMDD", 默认今天

    Returns:
        DataFrame 列: date, open, close, high, low, volume

    Raises:
        ValueError: 不支持的指数代码
        RuntimeError: 数据获取失败
    """
    if index_code not in _INDEX_DATAHUB_MAP:
        raise ValueError(
            f"不支持的指数代码 '{index_code}', "
            f"可选: {list(_INDEX_DATAHUB_MAP.keys())}"
        )

    # 默认日期范围: 最近 3 年
    if end_date is None:
        end_date = datetime.now(CST).strftime("%Y%m%d")
    if start_date is None:
        dt = datetime.now(CST) - timedelta(days=3 * 365)
        start_date = dt.strftime("%Y%m%d")

    source_code = _INDEX_DATAHUB_MAP[index_code]
    source_path = DATAHUB_ROOT / "market_series" / "index" / f"{source_code}.csv"
    if not source_path.exists():
        raise RuntimeError(f"canonical DataHub 指数行情缺失: {source_path}")
    try:
        df = pd.read_csv(source_path, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise RuntimeError(f"canonical DataHub 指数行情不可读: {source_path}: {exc}") from exc

    if df is None or df.empty:
        raise RuntimeError(
            f"canonical DataHub 指数行情为空: {index_code}, "
            f"日期范围 {start_date}~{end_date}"
        )

    df = df.copy()
    required = {"trade_date", "open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"canonical DataHub 指数行情字段缺失: {sorted(required - set(df.columns))}")
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})

    df["date"] = pd.to_datetime(df["date"].astype("string").str.replace(r"\.0$", "", regex=True), format="%Y%m%d", errors="coerce")
    start = pd.to_datetime(start_date, format="%Y%m%d")
    end = pd.to_datetime(end_date, format="%Y%m%d")
    df = df[df["date"].between(start, end)].dropna(subset=["date", "close"])

    # 数值列转为 float
    for col in ["open", "close", "high", "low", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.sort_values("date").reset_index(drop=True)


# ─── 数据验证 ──────────────────────────────────────────────────


def _validate_benchmark_returns(returns: pd.Series) -> bool:
    """检查基准收益率序列是否合理

    验证项:
    - 非空、非全零
    - 非 NaN 比例 > 90%
    - 年化波动率在 5%-50% 之间

    Args:
        returns: 日收益率 Series

    Returns:
        True 如果通过验证, False 否则
    """
    if returns is None or len(returns) == 0:
        logger.warning("基准收益率序列为空")
        return False

    if (returns == 0).all():
        logger.warning("基准收益率序列全为零")
        return False

    valid_ratio = returns.notna().sum() / len(returns)
    if valid_ratio < 0.9:
        logger.warning(
            f"基准收益率序列 NaN 过多: {1 - valid_ratio:.1%} NaN"
        )
        return False

    # 年化波动率
    ann_vol = returns.std() * np.sqrt(252)
    if ann_vol < 0.05 or ann_vol > 0.50:
        logger.warning(
            f"基准收益率年化波动率 {ann_vol:.2%} 不在合理范围 [5%, 50%]"
        )
        return False

    return True


# ─── 核心函数 ──────────────────────────────────────────────────


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
    method: str = "api",
    seed: int = 42,
) -> pd.Series:
    """获取基准指数收益率序列

    Args:
        benchmark_spec: 基准规格
        index_dates: 可选, 用于对齐日期的序列 (api 模式取其 min/max 做时间范围)
        method: 数据获取方法
            - "api" (默认): 通过 akshare / baostock 获取真实指数行情
            - "synthetic": 生成模拟基准收益 (已弃用, 仅作降级 fallback)
            - "etf_proxy": 已废弃, 请使用 "api"
        seed: 随机种子 (仅 synthetic 模式)

    Returns:
        日收益率 Series, index=实际交易日日期

    Raises:
        ValueError: 参数无效或数据获取失败
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

    meta = BENCHMARK_META[name_upper]
    index_code = meta["code"]

    if method == "api":
        return _api_benchmark_returns(name_upper, index_code, index_dates)
    elif method == "synthetic":
        warnings.warn(
            "method='synthetic' 已弃用, 请使用 method='api' 获取真实指数数据。"
            "合成数据将在未来版本中移除。",
            DeprecationWarning,
            stacklevel=2,
        )
        return _synthetic_benchmark_returns(name_upper, index_dates, seed)
    elif method == "etf_proxy":
        raise ValueError(
            "method='etf_proxy' 已废弃, 请使用 method='api' 获取真实指数行情。"
        )
    else:
        raise ValueError(f"不支持的数据获取方法: {method}")


def _api_benchmark_returns(
    name: str,
    index_code: str,
    index_dates: Optional[pd.DatetimeIndex] = None,
) -> pd.Series:
    """通过真实指数行情获取基准日收益率

    流程:
      1. 确定日期范围 (index_dates 或过去 3 年)
      2. fetch_index_kline() 获取指数日行情
      3. 计算日收益率 (close 的 pct_change)
      4. 日期对齐 (如果提供了 index_dates)
      5. 数据验证

    Args:
        name: 基准名称 (用于命名)
        index_code: 标准指数代码, 如 "000300.SH"
        index_dates: 可选日期序列, 用于对齐和确定时间范围

    Returns:
        日收益率 Series

    Raises:
        RuntimeError: 数据获取/验证失败
    """
    # 确定日期范围
    if index_dates is not None and len(index_dates) > 0:
        dt_idx = pd.DatetimeIndex(index_dates)
        start_date = dt_idx.min().strftime("%Y%m%d")
        end_date = dt_idx.max().strftime("%Y%m%d")
    else:
        end_dt = datetime.now(CST)
        start_dt = end_dt - timedelta(days=3 * 365)
        start_date = start_dt.strftime("%Y%m%d")
        end_date = end_dt.strftime("%Y%m%d")

    # 获取数据
    df = fetch_index_kline(index_code, start_date, end_date)

    if df.empty:
        raise RuntimeError(
            f"获取 {name} ({index_code}) 行情失败: 空数据"
        )

    # 计算日收益率
    returns = df.set_index("date")["close"].pct_change().dropna()
    returns.name = name

    # 数据验证
    if not _validate_benchmark_returns(returns):
        raise RuntimeError(
            f"{name} ({index_code}) 收益率数据验证未通过。"
            f"len={len(returns)}, mean={returns.mean():.6f}, std={returns.std():.6f}"
        )

    # 日期对齐 (如果提供了 index_dates)
    if index_dates is not None and len(index_dates) > 0:
        common = returns.index.intersection(pd.DatetimeIndex(index_dates))
        if len(common) < 5:
            raise RuntimeError(
                f"{name} 与 index_dates 日期重叠不足 5 个交易日"
            )
        returns = returns.loc[common].sort_index()

    logger.info(
        f"基准 {name}: {len(returns)} 个交易日, "
        f"日期 {returns.index[0].date()} ~ {returns.index[-1].date()}"
    )

    return returns


def _synthetic_benchmark_returns(
    name: str,
    index_dates: Optional[pd.DatetimeIndex],
    seed: int = 42,
) -> pd.Series:
    """生成模拟基准收益 (仅用于测试/降级)

    Args:
        name: 基准名称
        index_dates: 日期序列
        seed: 随机种子

    Returns:
        日收益率 Series
    """
    if index_dates is None or len(index_dates) < 2:
        end = pd.Timestamp.now()
        start = end - pd.DateOffset(years=2)
        dates = pd.date_range(start, end, freq="B")
    else:
        dates = sorted(pd.DatetimeIndex(index_dates))

    n = len(dates)
    rng = np.random.default_rng(seed)

    profiles = {
        "CSI300": {"mu": 0.08, "sigma": 0.18},
        "CSI500": {"mu": 0.10, "sigma": 0.22},
        "CSI1000": {"mu": 0.12, "sigma": 0.25},
        "CSI_ALL": {"mu": 0.09, "sigma": 0.20},
    }
    prof = profiles.get(name, profiles["CSI_ALL"])
    daily_mu = prof["mu"] / 252
    daily_sigma = prof["sigma"] / np.sqrt(252)

    eps = rng.normal(daily_mu, daily_sigma, n)
    returns = pd.Series(eps, index=pd.DatetimeIndex(dates), name=name)

    return returns


def _etf_proxy_benchmark_returns(
    name: str,
    index_dates: Optional[pd.DatetimeIndex] = None,
) -> pd.Series:
    """已废弃 — 请使用 get_benchmark_returns(method='api')"""
    raise ValueError(
        "_etf_proxy_benchmark_returns 已废弃。"
        "请使用 get_benchmark_returns(benchmark_spec, method='api') 获取真实指数行情。"
    )


def list_benchmarks() -> list[dict]:
    """列出所有可用的基准指数及其数据状态

    通过尝试获取近 5 个交易日的收益率来判断数据源状态。

    Returns:
        [{name, code, etf_symbol, description, data_status}, ...]
    """
    results = []
    for k, v in BENCHMARK_META.items():
        status = _check_benchmark_status(k)
        results.append(
            {
                "name": k,
                "code": v["code"],
                "etf_symbol": v["etf_symbol"],
                "description": v["description"],
                "data_status": status,
            }
        )
    return results


def _check_benchmark_status(name: str) -> str:
    """检查指定基准的数据源可用状态"""
    try:
        spec = make_benchmark_spec(name)
        returns = get_benchmark_returns(spec, method="api")
        if returns is not None and len(returns) > 20:
            vol = returns.std() * np.sqrt(252)
            if 0.05 <= vol <= 0.50:
                return "real"
            return "real(invalid_vol)"
        return "unavailable"
    except Exception as e:
        logger.debug(f"基准 {name} 状态检查失败: {e}")
        return "unavailable"


# ─── 便捷工厂函数 ──────────────────────────────────────────────


def make_benchmark_spec(name: str = "CSI300") -> BenchmarkSpec:
    """快速创建 BenchmarkSpec

    默认使用 method="api" 获取真实指数数据, 无需额外配置。

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
