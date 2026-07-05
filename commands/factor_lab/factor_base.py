"""因子基类与因子注册表 — Factor Lab"""

from dataclasses import dataclass, field
from typing import Callable
import numpy as np
import pandas as pd

@dataclass
class FactorDef:
    name: str
    category: str
    description: str
    params: dict = field(default_factory=dict)
    backtest_allowed: bool = True

# ─── 因子注册表 — 按类目组织 ─────────────────────────────────
# 每个因子是一个 dict：name, category, func, params, description
# func 签名: func(df: pd.DataFrame, **params) -> pd.Series

REGISTRY = []

def register(name, category, params=None, desc=""):
    """装饰器：注册因子到全局注册表"""
    def wrapper(func):
        REGISTRY.append({
            "name": name,
            "category": category,
            "func": func,
            "params": params or {},
            "description": desc,
        })
        return func
    return wrapper

# ═══════════════════════════════════════════════
# 一、动量因子 (Momentum)
# ═══════════════════════════════════════════════

@register("ret5", "momentum", {"window": 5}, "5日收益率动量")
@register("ret10", "momentum", {"window": 10}, "10日收益率动量")
@register("ret20", "momentum", {"window": 20}, "20日收益率动量")
@register("ret60", "momentum", {"window": 60}, "60日收益率动量")
def ret_n(df, window=20):
    return df.groupby("symbol")["close"].transform(lambda x: x.pct_change(window))

@register("ret_std20", "momentum", {"window": 20}, "20日收益率波动")
def ret_std_n(df, window=20):
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    return ret.groupby(df["symbol"]).transform(lambda x: x.rolling(window).std())

@register("max_high60", "momentum", {"window": 60}, "60日最高价距当前比例")
def max_high_n(df, window=60):
    high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    return df["close"] / high - 1

@register("min_low60", "momentum", {"window": 60}, "60日最低价距当前比例")
def min_low_n(df, window=60):
    low = df.groupby("symbol")["low"].transform(lambda x: x.rolling(window).min())
    return df["close"] / low - 1

# ═══════════════════════════════════════════════
# 二、趋势因子 (Trend)
# ═══════════════════════════════════════════════

@register("ma5_gt_ma10", "trend", {"fast": 5, "slow": 10}, "快慢均线关系")
@register("ma10_gt_ma20", "trend", {"fast": 10, "slow": 20}, "快慢均线关系(10/20)")
@register("ma20_gt_ma60", "trend", {"fast": 20, "slow": 60}, "快慢均线关系(20/60)")
def ma_gap(df, fast=5, slow=20):
    ma_f = df.groupby("symbol")["close"].transform(lambda x: x.rolling(fast).mean())
    ma_s = df.groupby("symbol")["close"].transform(lambda x: x.rolling(slow).mean())
    return (ma_f - ma_s) / ma_s

@register("close_gt_ma20", "trend", {"window": 20}, "收盘价在MA20上方幅度")
def close_gt_ma(df, window=20):
    ma = df.groupby("symbol")["close"].transform(lambda x: x.rolling(window).mean())
    return (df["close"] - ma) / ma

@register("ts_regression_slope20", "trend", {"window": 20}, "20日线性回归斜率")
def ts_slope(df, window=20):
    def _slope(s):
        if len(s) < window:
            return np.nan
        x = np.arange(window)
        y = s.values[-window:]
        return np.polyfit(x, y, 1)[0] / y.mean() if y.mean() != 0 else 0
    return df.groupby("symbol")["close"].transform(lambda x: x.rolling(window).apply(_slope, raw=False))

# ═══════════════════════════════════════════════
# 三、成交量因子 (Volume)
# ═══════════════════════════════════════════════

@register("vol_ratio5", "volume", {"window": 5}, "5日量比")
@register("vol_ratio20", "volume", {"window": 20}, "20日量比")
@register("vol_ratio60", "volume", {"window": 60}, "60日量比")
def vol_ratio(df, window=20):
    vol = df.groupby("symbol")["volume"].transform(lambda x: x.rolling(window).mean())
    return df["volume"] / vol

@register("vol_price_corr20", "volume", {"window": 20}, "量价相关性")
def vol_price_corr(df, window=20):
    def _corr(s):
        if len(s) < window: return np.nan
        v = s.values
        half = window // 2
        return np.corrcoef(v[:half], v[half:])[0, 1] if half >= 5 else 0
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    return ret.groupby(df["symbol"]).transform(lambda x: x.rolling(window).apply(_corr, raw=False))

@register("turnover20", "volume", {"window": 20}, "20日换手率均值")
def turnover(df, window=20):
    if "amount" not in df.columns:
        return pd.Series(0, index=df.index)
    turnover = df.groupby("symbol")["amount"].transform(lambda x: x.rolling(window).mean())
    return turnover

# ═══════════════════════════════════════════════
# 四、波动率因子 (Volatility)
# ═══════════════════════════════════════════════

@register("atr20", "volatility", {"window": 20}, "平均真实波幅")
def atr(df, window=20):
    high = df.groupby("symbol")["high"].transform(lambda x: x.diff())
    low = df.groupby("symbol")["low"].transform(lambda x: x.diff())
    tr = pd.concat([high.abs(), low.abs(), (df["high"] - df["low"])], axis=1).max(axis=1)
    return tr.groupby(df["symbol"]).transform(lambda x: x.rolling(window).mean()) / df["close"]

@register("volatility20", "volatility", {"window": 20}, "20日收益波动率")
def volatility(df, window=20):
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    return ret.groupby(df["symbol"]).transform(lambda x: x.rolling(window).std())

# ═══════════════════════════════════════════════
# 五、反转因子 (Reversal)
# ═══════════════════════════════════════════════

@register("reversal5", "reversal", {"window": 5}, "短期反转")
@register("reversal20", "reversal", {"window": 20}, "中期反转")
def reversal(df, window=5):
    return -df.groupby("symbol")["close"].transform(lambda x: x.pct_change(window))

# ═══════════════════════════════════════════════
# 六、流动性因子 (Liquidity)
# ═══════════════════════════════════════════════

@register("amihud_illiquidity20", "liquidity", {"window": 20}, "Amihud非流动性指标")
def amihud(df, window=20):
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1).abs())
    illiq = ret / df["amount"].replace(0, np.nan)
    return illiq.groupby(df["symbol"]).transform(lambda x: x.rolling(window).mean())

# ═══════════════════════════════════════════════
# 七、质量因子 (Quality) — 需基本面数据
# ═══════════════════════════════════════════════

@register("roe_q", "quality", {}, "ROE（净资产收益率）")
def roe_factor(df):
    """ROE 越高代表盈利能力越强"""
    if "roe" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["roe"].fillna(0)

@register("gross_margin_q", "quality", {}, "毛利率")
def gross_margin(df):
    """毛利率越高代表产品定价权越强"""
    if "gross_margin" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["gross_margin"].fillna(0)

@register("net_margin_q", "quality", {}, "净利率")
def net_margin_factor(df):
    """净利率越高代表盈利质量越好"""
    if "net_margin" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["net_margin"].fillna(0)

@register("debt_ratio_q", "quality", {}, "低负债率")
def debt_ratio(df):
    """负债率越低越好（取负值使方向统一：越高越好）"""
    if "debt_ratio" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return -df["debt_ratio"].fillna(0.5)  # 负值，低负债=高得分

@register("eps_q", "quality", {}, "每股收益")
def eps_factor(df):
    """EPS 越高代表每股价值越高"""
    if "eps" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return df["eps"].fillna(0)

@register("quality_composite", "quality", {}, "质量综合分(ROE+毛利+净利+低负债)")
def quality_composite(df):
    """等权组合：ROE + 毛利率 + 净利率 + (-负债率)"""
    score = pd.Series(0.0, index=df.index)
    n = 0
    for col, name in [("roe", "ROE"), ("gross_margin", "毛利率"),
                       ("net_margin", "净利率"), ("debt_ratio", "低负债")]:
        if col in df.columns:
            val = df[col].fillna(0)
            if col == "debt_ratio":
                val = -val  # 负债率越低越好
            # 截面 rank 归一化
            score += val.groupby(df["date"]).rank(pct=True)
            n += 1
    return score / n if n > 0 else pd.Series(np.nan, index=df.index)

# ═══════════════════════════════════════════════
# 八、资金流向因子 (Fund Flow) — 需 fund_flow_timeseries.csv
# ═══════════════════════════════════════════════
# 字段: net_main_force, net_super_large, net_large, net_medium, net_small

@register("net_inflow_1d", "fund_flow", {}, "主力净流入(今日)")
def net_inflow_1d(df):
    """主力净流入 = 超大单 + 大单。正值=机构买入"""
    if "net_main_force" in df.columns:
        return df["net_main_force"].fillna(0)
    return pd.Series(0.0, index=df.index)

@register("net_inflow_5d", "fund_flow", {}, "主力净流入(5日均)")
def net_inflow_5d(df):
    """5日主力净流入均值"""
    if "net_main_force" in df.columns:
        return df.groupby("symbol")["net_main_force"].transform(
            lambda x: x.rolling(5, min_periods=1).mean()).fillna(0)
    return pd.Series(0.0, index=df.index)

@register("super_large_net", "fund_flow", {}, "超大单净流入")
def super_large_net(df):
    """超大单（机构级）净流入"""
    if "net_super_large" in df.columns:
        return df["net_super_large"].fillna(0)
    return pd.Series(0.0, index=df.index)

@register("small_order_net", "fund_flow", {}, "小单净流入(散户)")
def small_order_net(df):
    """小单（散户）净流入。主力流入+散户流出=健康上涨"""
    if "net_small" in df.columns:
        return df["net_small"].fillna(0)
    return pd.Series(0.0, index=df.index)

@register("flow_divergence", "fund_flow", {}, "资金分化(主力-散户)")
def flow_divergence(df):
    """主力净流入 - 散户净流入。越正=机构买入散户卖出=健康"""
    has_main = "net_main_force" in df.columns
    has_small = "net_small" in df.columns
    if has_main and has_small:
        return (df["net_main_force"].fillna(0) - df["net_small"].fillna(0))
    return pd.Series(0.0, index=df.index)

@register("flow_momentum", "fund_flow", {}, "资金动量(主力×ret5)")
def flow_momentum(df):
    """资金流入+动量上涨确认。主力净流入×ret5"""
    has_flow = "net_main_force" in df.columns
    if has_flow:
        ret = df.get("ret5", df["close"].pct_change(5)) if "ret5" not in df.columns else df["ret5"]
        return df["net_main_force"].fillna(0) * ret.fillna(0)
    return pd.Series(0.0, index=df.index)


# ═══════════════════════════════════════════════
# 九、新闻情绪因子 (Sentiment) — 需 news_sentiment_timeseries.csv
# ═══════════════════════════════════════════════

@register("sentiment_1d", "sentiment", {}, "新闻情绪(今日)")
def sentiment_1d(df):
    """当日新闻情绪评分。正=利好，负=利空"""
    if "sentiment_score" in df.columns:
        return df["sentiment_score"].fillna(0)
    return pd.Series(0.0, index=df.index)

@register("sentiment_5d", "sentiment", {}, "新闻情绪(5日均)")
def sentiment_5d(df):
    """5日新闻情绪均值"""
    if "sentiment_score" in df.columns:
        return df.groupby("symbol")["sentiment_score"].transform(
            lambda x: x.rolling(5, min_periods=1).mean()).fillna(0)
    return pd.Series(0.0, index=df.index)

@register("sentiment_mom", "sentiment", {}, "情绪动量(情绪×ret5)")
def sentiment_mom(df):
    """正面情绪+动量上涨 = 强共振"""
    has_sent = "sentiment_score" in df.columns
    if has_sent:
        ret = df.get("ret5", df["close"].pct_change(5)) if "ret5" not in df.columns else df["ret5"]
        return df["sentiment_score"].fillna(0) * ret.fillna(0)
    return pd.Series(0.0, index=df.index)


def compute_factor(df: pd.DataFrame, factor_name: str) -> pd.Series:
    """计算单个因子"""
    for f in REGISTRY:
        if f["name"] == factor_name:
            return f["func"](df, **f["params"])
    raise ValueError(f"未知因子: {factor_name}")

def compute_all_factors(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有因子，返回 factor_name → Series"""
    results = {}
    for f in REGISTRY:
        try:
            s = f["func"](df, **f["params"])
            results[f["name"]] = s
        except Exception as e:
            results[f["name"]] = pd.Series(np.nan, index=df.index)
    return pd.DataFrame(results)

def list_factors(category: str = None) -> list:
    """列出因子，可按类目筛选"""
    # 加载已保存的进化因子
    _load_evolved()
    if category:
        return [f for f in REGISTRY if f["category"] == category]
    return REGISTRY.copy()

def _load_evolved():
    """从 JSON 文件加载进化因子到注册表"""
    import json
    from pathlib import Path
    evolved_path = Path("/mnt/d/HermesReports/factor_lab/evolved_candidates.json")
    if not evolved_path.exists():
        return
    try:
        with open(evolved_path) as f:
            candidates = json.load(f)
    except:
        return
    existing_names = {f["name"] for f in REGISTRY}
    for c in candidates:
        name = c.get("name", "")
        if name in existing_names:
            continue
        expr_str = c.get("expression", "")
        # 用表达式解析器编译
        from factor_lab.expression_parser import ExpressionParser
        _expr_cache = {}
        
        def _make_func(expr=expr_str, _name=name):
            def dyn_func(df):
                try:
                    parser = ExpressionParser()
                    return parser.eval(expr, df)
                except Exception:
                    return pd.Series(0.0, index=df.index)
            return dyn_func
        REGISTRY.append({
            "name": name,
            "category": "evolved",
            "func": _make_func(),
            "params": {},
            "description": c.get("hypothesis", f"LLM 进化因子: {expr_str}"),
        })
        existing_names.add(name)


# ═══════════════════════════════════════════════
# 九、波动率/风险因子 (Volatility)
# ═══════════════════════════════════════════════

@register("volatility60", "volatility", {"window": 60}, "60日收益波动率")
def volatility60(df, window=60):
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    return ret.groupby(df["symbol"]).transform(lambda x: x.rolling(window).std())

@register("downside_volatility20", "volatility", {"window": 20}, "下行波动率(仅负收益)")
def downside_vol(df, window=20):
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    neg = ret.where(ret < 0, 0)
    return neg.groupby(df["symbol"]).transform(lambda x: x.rolling(window).std())

@register("max_drawdown20", "volatility", {"window": 20}, "20日滚动最大回撤")
def rolling_dd(df, window=20):
    def _dd(s):
        if len(s) < window:
            return np.nan
        roll_max = s.rolling(window, min_periods=1).max()
        dd = (s - roll_max) / roll_max
        return dd.min()
    return df.groupby("symbol")["close"].transform(lambda x: x.rolling(window).apply(_dd, raw=False))

@register("intraday_range20", "volatility", {"window": 20}, "日内振幅(高-低)/收盘")
def intraday_range(df, window=20):
    rng = (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
    return rng.groupby(df["symbol"]).transform(lambda x: x.rolling(window).mean())

# ═══════════════════════════════════════════════
# 十、流动性/量因子 (Liquidity)
# ═══════════════════════════════════════════════

@register("amount_rank20", "liquidity", {"window": 20}, "成交额截面排名(20日均)")
def amount_rank(df, window=20):
    temp = df.copy()
    temp["amt_ma"] = df.groupby("symbol")["amount"].transform(lambda x: x.rolling(window).mean())
    temp["amt_rank"] = temp.groupby("date")["amt_ma"].rank(pct=True)
    return temp["amt_rank"]

@register("amount_stability20", "liquidity", {"window": 20}, "成交额稳定性(变异系数倒数)")
def amount_stability(df, window=20):
    def _cv(s):
        if len(s) < window:
            return np.nan
        return s.mean() / (s.std() + 1e-8)
    return df.groupby("symbol")["amount"].transform(lambda x: x.rolling(window).apply(_cv, raw=False))

@register("volume_stability20", "liquidity", {"window": 20}, "成交量稳定性")
def vol_stability(df, window=20):
    def _cv_vol(s):
        if len(s) < window:
            return np.nan
        return s.mean() / (s.std() + 1e-8)
    return df.groupby("symbol")["volume"].transform(lambda x: x.rolling(window).apply(_cv, raw=False))

@register("low_liquidity_penalty", "liquidity", {"window": 20}, "低流动性惩罚(成交额后20%为-1)")
def low_liq_penalty(df, window=20):
    temp = df.copy()
    temp["amt_ma"] = df.groupby("symbol")["amount"].transform(lambda x: x.rolling(window).mean())
    temp["amt_rank"] = temp.groupby("date")["amt_ma"].rank(pct=True)
    return (temp["amt_rank"] >= 0.2).astype(float) * (-1.0)

@register("high_turnover_penalty", "liquidity", {"window": 20}, "高换手惩罚(换手前20%为-1)")
def high_turn_penalty(df, window=20):
    temp = df.copy()
    temp["turn_ma"] = df.groupby("symbol")["amount"].transform(lambda x: x.rolling(window).mean())
    temp["turn_rank"] = temp.groupby("date")["turn_ma"].rank(pct=True)
    return (temp["turn_rank"] >= 0.8).astype(float) * (-1.0)

# ═══════════════════════════════════════════════
# 十一、突破因子 (Breakout)
# ═══════════════════════════════════════════════

@register("high_20_breakout", "breakout", {"window": 20}, "突破20日新高")
def breakout_20(df, window=20):
    max_high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    return (df["close"] >= max_high).astype(float)

@register("high_60_breakout", "breakout", {"window": 60}, "突破60日新高")
def breakout_60(df, window=60):
    max_high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(60).max())
    return (df["close"] >= max_high).astype(float)

@register("close_to_high20", "breakout", {"window": 20}, "收盘价/20日最高")
def close_to_high20(df, window=20):
    max_h = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    return df["close"] / max_h

@register("close_to_high60", "breakout", {"window": 60}, "收盘价/60日最高")
def close_to_high60(df, window=60):
    max_h = df.groupby("symbol")["high"].transform(lambda x: x.rolling(60).max())
    return df["close"] / max_h

@register("distance_to_high20", "breakout", {"window": 20}, "距20日高点距离")
def dist_high20(df, window=20):
    max_h = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    return (max_h - df["close"]) / df["close"]

@register("distance_to_high60", "breakout", {"window": 60}, "距60日高点距离")
def dist_high60(df, window=60):
    max_h = df.groupby("symbol")["high"].transform(lambda x: x.rolling(60).max())
    return (max_h - df["close"]) / df["close"]

# ═══════════════════════════════════════════════
# 十二、回调因子 (Pullback)
# ═══════════════════════════════════════════════

@register("pullback_5_in_ma20_uptrend", "pullback", {}, "MA20上升+5日回调")
def pullback_5(df):
    ma20 = df.groupby("symbol")["close"].transform(lambda x: x.rolling(20).mean())
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    ma20_slope = ma20.groupby(df["symbol"]).diff(5)
    cond = (ma20_slope > 0) & (ret5 < 0) & (df["close"] > ma20 * 0.95)
    return cond.astype(float)

@register("pullback_10_in_ma20_uptrend", "pullback", {}, "MA20上升+10日回调")
def pullback_10(df):
    ma20 = df.groupby("symbol")["close"].transform(lambda x: x.rolling(20).mean())
    ret10 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(10))
    ma20_slope = ma20.groupby(df["symbol"]).diff(10)
    cond = (ma20_slope > 0) & (ret10 < 0) & (df["close"] > ma20 * 0.95)
    return cond.astype(float)

@register("low_volume_pullback", "pullback", {"window": 20}, "缩量回调")
def low_vol_pullback(df, window=20):
    ma20 = df.groupby("symbol")["close"].transform(lambda x: x.rolling(20).mean())
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    vol_ratio = df["volume"] / df.groupby("symbol")["volume"].transform(lambda x: x.rolling(20).mean())
    cond = (ret5 < 0) & (vol_ratio < 0.8) & (df["close"] > ma20 * 0.95)
    return cond.astype(float)

@register("ma20_uptrend_pullback", "pullback", {}, "MA20上升趋势回调")
def ma20_uptrend_pb(df):
    ma20 = df.groupby("symbol")["close"].transform(lambda x: x.rolling(20).mean())
    ma60 = df.groupby("symbol")["close"].transform(lambda x: x.rolling(60).mean())
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    cond = (ma20 > ma60) & (ret5 < 0) & (df["close"] > ma20 * 0.95)
    return cond.astype(float)

# ═══════════════════════════════════════════════
# 十三、ret5惩罚因子 (Ret5 Filter)
# ═══════════════════════════════════════════════

@register("ret5_penalty_volatility20", "ret5_filter", {"window": 20}, "ret5经过高波动惩罚")
def ret5_penalty_vol(df, window=20):
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    vol = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1).rolling(window).std())
    vol_rank = vol.groupby(df["date"]).rank(pct=True)
    penalty = np.where(vol_rank > 0.8, 0.5, 1.0)
    return ret5 * penalty

@register("ret5_penalty_turnover20", "ret5_filter", {"window": 20}, "ret5经过高换手惩罚")
def ret5_penalty_turn(df, window=20):
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    amt_ma = df.groupby("symbol")["amount"].transform(lambda x: x.rolling(window).mean())
    turn_rank = amt_ma.groupby(df["date"]).rank(pct=True)
    penalty = np.where(turn_rank > 0.8, 0.5, 1.0)
    return ret5 * penalty

@register("ret5_penalty_vol_ratio20", "ret5_filter", {"window": 20}, "ret5经过异常放量惩罚")
def ret5_penalty_vr(df, window=20):
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    vr = df["volume"] / df.groupby("symbol")["volume"].transform(lambda x: x.rolling(window).mean())
    penalty = np.where(vr > 2.0, 0.3, 1.0)
    return ret5 * penalty

@register("ret5_penalty_gap", "ret5_filter", {"window": 5}, "ret5经过跳空惩罚")
def ret5_penalty_gap(df, window=5):
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    gap = (df["open"] - df["close"].shift(1)) / df["close"].shift(1)
    gap_penalty = gap.abs().groupby(df["symbol"]).transform(lambda x: x.rolling(window).max())
    penalty = np.where(gap_penalty > 0.03, 0.5, 1.0)
    return ret5 * penalty

@register("ret5_penalty_limit_up_recent", "ret5_filter", {"window": 10}, "ret5经过近期涨停惩罚")
def ret5_penalty_limit(df, window=10):
    ret5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    ret1 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    limit_up = (ret1 > 0.095).astype(float)
    recent_limit = limit_up.groupby(df["symbol"]).transform(lambda x: x.rolling(window).sum())
    penalty = np.where(recent_limit >= 2, 0.3, 1.0)
    return ret5 * penalty