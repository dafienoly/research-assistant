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
# 八-B、资金流增强因子 V3.3 (Enhanced Fund Flow)
# ═══════════════════════════════════════════════
# 字段: net_main_force, net_super_large, net_large, net_medium, net_small

@register("net_flow_composite", "fund_flow", {}, "资金流综合分(主力+超大+小单)")
def net_flow_composite(df):
    """多维度资金流综合得分: 主力净流入rank + 超大单rank - 小单rank

    正值=机构买入+散户卖出, 健康上涨结构。
    """
    has_main = "net_main_force" in df.columns
    has_super = "net_super_large" in df.columns
    has_small = "net_small" in df.columns
    if not (has_main or has_super):
        return pd.Series(0.0, index=df.index)

    score = pd.Series(0.0, index=df.index)
    n = 0
    if has_main:
        score += df.groupby("date")["net_main_force"].rank(pct=True).fillna(0.5)
        n += 1
    if has_super:
        score += df.groupby("date")["net_super_large"].rank(pct=True).fillna(0.5)
        n += 1
    if has_small:
        score -= df.groupby("date")["net_small"].rank(pct=True).fillna(0.5)
        n += 1
    return score / n if n > 0 else pd.Series(0.0, index=df.index)


@register("flow_divergence_5d", "fund_flow", {}, "5日资金分化均值(主力-散户)")
def flow_divergence_5d(df):
    """5日平均资金分化: 主力净流入 - 散户净流入, 取5日均值

    持续正值=机构持续买入, 散户持续卖出。
    """
    has_main = "net_main_force" in df.columns
    has_small = "net_small" in df.columns
    if has_main and has_small:
        div = df["net_main_force"].fillna(0) - df["net_small"].fillna(0)
        return div.groupby(df["symbol"]).transform(
            lambda x: x.rolling(5, min_periods=1).mean()).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("super_large_flow_mom", "fund_flow", {}, "超大单动量(超大单×ret5)")
def super_large_flow_mom(df):
    """超大单净流入 × 5日收益。机构级资金流入+上涨=强信号"""
    has_super = "net_super_large" in df.columns
    if has_super:
        ret = df.get("ret5", df["close"].pct_change(5)) if "ret5" not in df.columns else df["ret5"]
        return df["net_super_large"].fillna(0) * ret.fillna(0)
    return pd.Series(0.0, index=df.index)


@register("institutional_flow_ratio", "fund_flow", {}, "机构资金占比(主力/成交额)")
def institutional_flow_ratio(df):
    """机构资金占比 = net_main_force / (net_main_force.abs() + net_small.abs())

    >0.5 代表机构主导, <0.5 代表散户主导。
    """
    has_main = "net_main_force" in df.columns
    has_small = "net_small" in df.columns
    if has_main and has_small:
        denom = df["net_main_force"].abs().fillna(0) + df["net_small"].abs().fillna(0) + 1e-8
        return df["net_main_force"].fillna(0) / denom
    return pd.Series(0.5, index=df.index)


@register("consecutive_inflow", "fund_flow", {}, "连续净流入天数")
def consecutive_inflow(df):
    """连续主力净流入天数。>3天=资金持续关注"""
    if "days_inflow" in df.columns:
        return df["days_inflow"].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


# ═══════════════════════════════════════════════
# 八-C、北向资金因子 V3.3 (North-bound Capital)
# ═══════════════════════════════════════════════
# 字段: nb_net_flow, nb_total_buy, nb_total_sell, nb_holding_value, nb_holding_ratio

@register("nb_net_flow_1d", "north_bound", {}, "北向净流入(今日)")
def nb_net_flow_1d(df):
    """北向资金当日净流入。正值=外资买入"""
    if "nb_net_flow" in df.columns:
        return df["nb_net_flow"].fillna(0)
    return pd.Series(0.0, index=df.index)


@register("nb_net_flow_5d", "north_bound", {}, "北向净流入(5日均)")
def nb_net_flow_5d(df):
    """5日北向净流入均值"""
    if "nb_net_flow" in df.columns:
        return df.groupby("symbol")["nb_net_flow"].transform(
            lambda x: x.rolling(5, min_periods=1).mean()).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("nb_holding_change_5d", "north_bound", {}, "北向持仓变动(5日)")
def nb_holding_change_5d(df):
    """5日北向持仓市值变化率"""
    if "nb_holding_value" in df.columns:
        return df.groupby("symbol")["nb_holding_value"].transform(
            lambda x: x.pct_change(5)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("nb_flow_ratio", "north_bound", {}, "北向强度(净流入/绝对流入)")
def nb_flow_ratio(df):
    """北向净买入强度 = (buy - sell) / (buy + sell)

    >0 净买入, <0 净卖出, 绝对值越大强度越高。
    """
    has_buy = "nb_total_buy" in df.columns
    has_sell = "nb_total_sell" in df.columns
    if has_buy and has_sell:
        buy = df["nb_total_buy"].fillna(0)
        sell = df["nb_total_sell"].fillna(0)
        denom = buy.abs() + sell.abs() + 1e-8
        return (buy - sell) / denom
    return pd.Series(0.0, index=df.index)


@register("nb_holding_ratio_change", "north_bound", {}, "北向持股比例变动(5日)")
def nb_holding_ratio_change(df):
    """5日北向持股比例变化。正值=外资加仓"""
    if "nb_holding_ratio" in df.columns:
        return df.groupby("symbol")["nb_holding_ratio"].transform(
            lambda x: x.diff(5)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("nb_flow_momentum", "north_bound", {}, "北向动量(北向净流入×ret5)")
def nb_flow_momentum(df):
    """北向净流入 × 5日收益。外资流入+上涨=共振信号"""
    if "nb_net_flow" in df.columns:
        ret = df.get("ret5", df["close"].pct_change(5)) if "ret5" not in df.columns else df["ret5"]
        return df["nb_net_flow"].fillna(0) * ret.fillna(0)
    return pd.Series(0.0, index=df.index)


# ═══════════════════════════════════════════════
# 八-D、两融因子 V3.3 (Margin Trading & Securities Lending)
# ═══════════════════════════════════════════════
# 字段: margin_buy, margin_repay, margin_balance, sec_lending_volume, sec_lending_balance, margin_ratio

@register("margin_buy_ratio", "margin", {}, "融资买入强度(融资买入/成交额)")
def margin_buy_ratio(df):
    """融资买入额占成交额比例。越高=杠杆做多意愿强"""
    if "margin_buy" in df.columns and "amount" in df.columns:
        return df["margin_buy"].fillna(0) / (df["amount"].fillna(0) + 1e-8)
    return pd.Series(0.0, index=df.index)


@register("margin_balance_change_5d", "margin", {}, "融资余额变动(5日)")
def margin_balance_change_5d(df):
    """5日融资余额变化率。正值=杠杆资金加仓"""
    if "margin_balance" in df.columns:
        return df.groupby("symbol")["margin_balance"].transform(
            lambda x: x.pct_change(5)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("margin_balance_change_20d", "margin", {}, "融资余额变动(20日)")
def margin_balance_change_20d(df):
    """20日融资余额变化率。中长期杠杆资金趋势"""
    if "margin_balance" in df.columns:
        return df.groupby("symbol")["margin_balance"].transform(
            lambda x: x.pct_change(20)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("sec_lending_change_5d", "margin", {}, "融券余额变动(5日)")
def sec_lending_change_5d(df):
    """5日融券余额变化率。正值=做空力量增加"""
    if "sec_lending_balance" in df.columns:
        return df.groupby("symbol")["sec_lending_balance"].transform(
            lambda x: x.pct_change(5)).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("margin_sec_lending_ratio", "margin", {}, "融资融券比(融资余额/融券余额)")
def margin_sec_lending_ratio(df):
    """融资余额/融券余额。越高代表市场做多情绪越强"""
    has_margin = "margin_balance" in df.columns
    has_sec = "sec_lending_balance" in df.columns
    if has_margin and has_sec:
        return df["margin_balance"].fillna(0) / (df["sec_lending_balance"].abs().fillna(0) + 1e-8)
    return pd.Series(0.0, index=df.index)


@register("margin_net_buy", "margin", {}, "融资净买入(融资买入-偿还)")
def margin_net_buy(df):
    """融资净买入 = 融资买入 - 融资偿还。>0=净做多"""
    has_buy = "margin_buy" in df.columns
    has_repay = "margin_repay" in df.columns
    if has_buy and has_repay:
        return df["margin_buy"].fillna(0) - df["margin_repay"].fillna(0)
    return pd.Series(0.0, index=df.index)


@register("margin_net_buy_5d", "margin", {}, "融资净买入(5日均)")
def margin_net_buy_5d(df):
    """5日融资净买入均值"""
    if "margin_buy" in df.columns and "margin_repay" in df.columns:
        net = df["margin_buy"].fillna(0) - df["margin_repay"].fillna(0)
        return net.groupby(df["symbol"]).transform(
            lambda x: x.rolling(5, min_periods=1).mean()).fillna(0)
    return pd.Series(0.0, index=df.index)


@register("margin_flow_momentum", "margin", {}, "两融动量(融资净买入×ret5)")
def margin_flow_momentum(df):
    """融资净买入 × 5日收益。杠杆资金+上涨=强共振"""
    has_buy = "margin_buy" in df.columns
    has_repay = "margin_repay" in df.columns
    if has_buy and has_repay:
        ret = df.get("ret5", df["close"].pct_change(5)) if "ret5" not in df.columns else df["ret5"]
        net = df["margin_buy"].fillna(0) - df["margin_repay"].fillna(0)
        return net * ret.fillna(0)
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


# ═══════════════════════════════════════════════
# 十五、技术指标因子 V3.4 (Technical Pattern Control)
# ═══════════════════════════════════════════════
# 注意: MACD/KDJ/Bollinger 在 A 股作为单独的 alpha 信号
# 预测能力有限, 主要用作 control/baseline/redundancy 参考。
# 这些因子应优先作为低相关性参考, 而非主力 alpha 信号。


# ─── MACD (指数平滑异同平均) ─────────────────────

@register("macd_dif", "technical", {"fast": 12, "slow": 26, "signal": 9},
          "MACD DIF 线 (快线-慢线)")
def macd_dif(df, fast=12, slow=26, signal=9):
    """MACD DIF = EMA(fast) - EMA(slow)
    衡量短期动量减去长期动量。
    当 DIF > 0 代表短期动量强于长期, 反之亦然。
    """
    def _ema(s, period):
        return s.ewm(span=period, adjust=False).mean()

    close = df.groupby("symbol")["close"]
    ema_fast = close.transform(lambda x: _ema(x, fast))
    ema_slow = close.transform(lambda x: _ema(x, slow))
    return ema_fast - ema_slow


@register("macd_dea", "technical", {"fast": 12, "slow": 26, "signal": 9},
          "MACD DEA 线 (DIF 的 EMA)")
def macd_dea(df, fast=12, slow=26, signal=9):
    """MACD DEA = EMA(DIF, signal)
    DIF 的信号线, 用于识别 DIF 趋势。
    """
    def _ema(s, period):
        return s.ewm(span=period, adjust=False).mean()

    close = df.groupby("symbol")["close"]
    ema_fast = close.transform(lambda x: _ema(x, fast))
    ema_slow = close.transform(lambda x: _ema(x, slow))
    dif = ema_fast - ema_slow
    return dif.groupby(df["symbol"]).transform(lambda x: _ema(x, signal))


@register("macd_histogram", "technical", {"fast": 12, "slow": 26, "signal": 9},
          "MACD 柱状图 (DIF - DEA)")
def macd_histogram(df, fast=12, slow=26, signal=9):
    """MACD 柱状图 = DIF - DEA
    衡量动量的加速度。柱状图扩大=动量加速, 缩小=动量减速。
    DIF 上穿 DEA 时柱状图由负转正 (金叉), 反之死叉。
    """
    def _ema(s, period):
        return s.ewm(span=period, adjust=False).mean()

    close = df.groupby("symbol")["close"]
    ema_fast = close.transform(lambda x: _ema(x, fast))
    ema_slow = close.transform(lambda x: _ema(x, slow))
    dif = ema_fast - ema_slow
    dea = dif.groupby(df["symbol"]).transform(lambda x: _ema(x, signal))
    return dif - dea


@register("macd_cross", "technical", {"fast": 12, "slow": 26, "signal": 9},
          "MACD 交叉信号 (金叉/死叉)")
def macd_cross(df, fast=12, slow=26, signal=9):
    """MACD 交叉信号:
    +1 = 金叉 (DIF 上穿 DEA, 柱状图由负转正)
    -1 = 死叉 (DIF 下穿 DEA, 柱状图由正转负)
     0 = 无交叉
    """
    def _ema(s, period):
        return s.ewm(span=period, adjust=False).mean()

    close = df.groupby("symbol")["close"]
    ema_fast = close.transform(lambda x: _ema(x, fast))
    ema_slow = close.transform(lambda x: _ema(x, slow))
    dif = ema_fast - ema_slow
    dea = dif.groupby(df["symbol"]).transform(lambda x: _ema(x, signal))
    hist = dif - dea

    # 前一期的柱状图
    hist_prev = hist.groupby(df["symbol"]).shift(1)

    # 金叉: hist_prev < 0 且 hist >= 0
    golden = ((hist_prev < 0) & (hist >= 0)).astype(float)
    # 死叉: hist_prev > 0 且 hist <= 0
    death = ((hist_prev > 0) & (hist <= 0)).astype(float)

    return golden - death


# ─── KDJ (随机指标) ─────────────────────────────

@register("kdj_k", "technical", {"window": 9, "k_smooth": 3, "d_smooth": 3},
          "KDJ K 值 (快速随机线)")
def kdj_k(df, window=9, k_smooth=3, d_smooth=3):
    """KDJ K = 2/3 * prev_K + 1/3 * RSV
    RSV = (close - min_low) / (max_high - min_low) * 100
    K > 80 超买区, K < 20 超卖区。
    """
    high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    low = df.groupby("symbol")["low"].transform(lambda x: x.rolling(window).min())
    rsv = (df["close"] - low) / (high - low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)

    # K = EMA-like smoothing
    def _kdj_k(smooth_k):
        k = pd.Series(50.0, index=smooth_k.index)
        for i in range(1, len(smooth_k)):
            k.iloc[i] = 2/3 * k.iloc[i-1] + 1/3 * smooth_k.iloc[i]
        return k
    return rsv.groupby(df["symbol"]).transform(_kdj_k)


@register("kdj_d", "technical", {"window": 9, "k_smooth": 3, "d_smooth": 3},
          "KDJ D 值 (慢速随机线)")
def kdj_d(df, window=9, k_smooth=3, d_smooth=3):
    """KDJ D = 2/3 * prev_D + 1/3 * K
    D 是 K 的移动平均, 比 K 更平滑。
    """
    high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    low = df.groupby("symbol")["low"].transform(lambda x: x.rolling(window).min())
    rsv = (df["close"] - low) / (high - low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)

    def _calc_kd(smooth_k):
        k = pd.Series(50.0, index=smooth_k.index)
        for i in range(1, len(smooth_k)):
            k.iloc[i] = 2/3 * k.iloc[i-1] + 1/3 * smooth_k.iloc[i]
        d = pd.Series(50.0, index=k.index)
        for i in range(1, len(k)):
            d.iloc[i] = 2/3 * d.iloc[i-1] + 1/3 * k.iloc[i]
        return d
    return rsv.groupby(df["symbol"]).transform(_calc_kd)


@register("kdj_j", "technical", {"window": 9, "k_smooth": 3, "d_smooth": 3},
          "KDJ J 值 (方向敏感线)")
def kdj_j(df, window=9, k_smooth=3, d_smooth=3):
    """KDJ J = 3*K - 2*D
    J 对方向变化最敏感。J > 100 超买, J < 0 超卖。
    """
    high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    low = df.groupby("symbol")["low"].transform(lambda x: x.rolling(window).min())
    rsv = (df["close"] - low) / (high - low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)

    def _calc_j(smooth_k):
        k = pd.Series(50.0, index=smooth_k.index)
        for i in range(1, len(smooth_k)):
            k.iloc[i] = 2/3 * k.iloc[i-1] + 1/3 * smooth_k.iloc[i]
        d = pd.Series(50.0, index=k.index)
        for i in range(1, len(k)):
            d.iloc[i] = 2/3 * d.iloc[i-1] + 1/3 * k.iloc[i]
        return 3 * k - 2 * d
    return rsv.groupby(df["symbol"]).transform(_calc_j)


@register("kdj_cross", "technical", {"window": 9, "k_smooth": 3, "d_smooth": 3},
          "KDJ 交叉信号 (K 上穿/下穿 D)")
def kdj_cross(df, window=9, k_smooth=3, d_smooth=3):
    """KDJ 交叉信号:
    +1 = K 上穿 D (买入信号)
    -1 = K 下穿 D (卖出信号)
     0 = 无交叉
    """
    high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(window).max())
    low = df.groupby("symbol")["low"].transform(lambda x: x.rolling(window).min())
    rsv = (df["close"] - low) / (high - low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)

    def _k_series(smooth_k):
        k = pd.Series(50.0, index=smooth_k.index)
        for i in range(1, len(smooth_k)):
            k.iloc[i] = 2/3 * k.iloc[i-1] + 1/3 * smooth_k.iloc[i]
        return k

    def _d_series(smooth_k):
        k = pd.Series(50.0, index=smooth_k.index)
        for i in range(1, len(smooth_k)):
            k.iloc[i] = 2/3 * k.iloc[i-1] + 1/3 * smooth_k.iloc[i]
        d = pd.Series(50.0, index=k.index)
        for i in range(1, len(k)):
            d.iloc[i] = 2/3 * d.iloc[i-1] + 1/3 * k.iloc[i]
        return d

    k_val = rsv.groupby(df["symbol"]).transform(_k_series)
    d_val = rsv.groupby(df["symbol"]).transform(_d_series)

    k_prev = k_val.groupby(df["symbol"]).shift(1)
    d_prev = d_val.groupby(df["symbol"]).shift(1)

    golden = ((k_prev <= d_prev) & (k_val > d_val)).astype(float)
    death = ((k_prev >= d_prev) & (k_val < d_val)).astype(float)

    return golden - death


# ─── Bollinger Bands (布林带) ───────────────────

@register("boll_position", "technical", {"window": 20, "n_std": 2},
          "Bollinger %b 位置 (收盘价在布林带内位置)")
def boll_position(df, window=20, n_std=2):
    """Bollinger %b = (close - lower) / (upper - lower)
    %b = 0 在下轨, %b = 1 在上轨, %b = 0.5 在中轨。
    %b > 1 突破上轨 (超买), %b < 0 跌破下轨 (超卖)。
    """
    def _boll_pct(s):
        ma = s.rolling(window, min_periods=window).mean()
        std = s.rolling(window, min_periods=window).std()
        upper = ma + n_std * std
        lower = ma - n_std * std
        denom = (upper - lower).replace(0, np.nan)
        return (s - lower) / denom

    return df.groupby("symbol")["close"].transform(_boll_pct)


@register("boll_width", "technical", {"window": 20, "n_std": 2},
          "Bollinger 带宽 (上轨-下轨)/中轨")
def boll_width(df, window=20, n_std=2):
    """Bollinger 带宽 = (upper - lower) / middle
    带宽扩大 = 波动率上升, 带宽收窄 = 波动率下降。
    极窄带宽预示即将变盘 (squeeze)。
    """
    def _boll_width(s):
        ma = s.rolling(window).mean()
        std = s.rolling(window).std()
        upper = ma + n_std * std
        lower = ma - n_std * std
        return (upper - lower) / ma.replace(0, np.nan)

    return df.groupby("symbol")["close"].transform(_boll_width)


@register("boll_squeeze", "technical", {"window": 20, "n_std": 2, "lookback": 20},
          "Bollinger Squeeze (带宽处于历史低位)")
def boll_squeeze(df, window=20, n_std=2, lookback=20):
    """Bollinger Squeeze: 当前带宽处于过去 lookback 期最低的 20% 分位
    带宽极度收窄 = 即将变盘信号。
    1 = squeeze 状态, 0 = 正常。
    """
    def _boll_squeeze(s):
        ma = s.rolling(window).mean()
        std = s.rolling(window).std()
        upper = ma + n_std * std
        lower = ma - n_std * std
        bw = (upper - lower) / ma.replace(0, np.nan)
        bw_lookback = bw.rolling(lookback)
        bw_min = bw_lookback.min()
        bw_max = bw_lookback.max()
        # 带宽处于过去 lookback 最低的 20%
        pct_rank = (bw - bw_min) / (bw_max - bw_min + 1e-8)
        return (pct_rank < 0.2).astype(float)

    return df.groupby("symbol")["close"].transform(_boll_squeeze)


@register("boll_breakout", "technical", {"window": 20, "n_std": 2},
          "Bollinger 突破信号 (突破上轨=+1, 跌破下轨=-1)")
def boll_breakout(df, window=20, n_std=2):
    """Bollinger 突破信号:
    +1 = 突破上轨 (close > upper, 强势)
    -1 = 跌破下轨 (close < lower, 弱势)
     0 = 在轨道内
    """
    def _boll_signal(s):
        ma = s.rolling(window).mean()
        std = s.rolling(window).std()
        upper = ma + n_std * std
        lower = ma - n_std * std
        signal = pd.Series(0.0, index=s.index)
        signal[s > upper] = 1.0
        signal[s < lower] = -1.0
        return signal

    return df.groupby("symbol")["close"].transform(_boll_signal)


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


# ═══════════════════════════════════════════════
# 十四、行业相对因子 (Industry Relative) V3.1
# ═══════════════════════════════════════════════
# 这些因子需要 df 中的 "industry" 列。
# 如果缺失, 因子退化为原始值 (无行业调整)。

def _has_industry(df: pd.DataFrame) -> bool:
    """检查 DataFrame 是否包含 industry 列"""
    return "industry" in df.columns


def _industry_relative(df: pd.DataFrame, value: pd.Series) -> pd.Series:
    """截面行业中位数调整: value - median(value) by (date, industry)

    如果缺少 industry 列, 返回原始值。
    """
    if not _has_industry(df) or not df["industry"].nunique() > 1:
        return value
    key = df["date"].astype(str) + "_" + df["industry"]
    median = value.groupby(key).transform("median")
    return value - median


def _industry_rank(df: pd.DataFrame, value: pd.Series) -> pd.Series:
    """截面行业内分位数排名: rank(value) by (date, industry), 返回 [0, 1]

    如果缺少 industry 列, 返回全局分位数排名。
    """
    if not _has_industry(df):
        return value.groupby(df["date"]).rank(pct=True)
    key = df["date"].astype(str) + "_" + df["industry"]
    return value.groupby(key).rank(pct=True)


def _industry_zscore(df: pd.DataFrame, value: pd.Series) -> pd.Series:
    """截面行业内 Z-Score: (value - mean) / std by (date, industry)"""
    if not _has_industry(df) or not df["industry"].nunique() > 1:
        return value.groupby(df["date"]).transform(lambda x: (x - x.mean()) / (x.std() + 1e-8))
    key = df["date"].astype(str) + "_" + df["industry"]
    mean = value.groupby(key).transform("mean")
    std = value.groupby(key).transform("std").replace(0, np.nan)
    return (value - mean) / (std + 1e-8)


# ─── 行业相对动量 ──────────────────────────────

@register("ret5_industry_adj", "industry_relative", {"window": 5, "method": "median"},
          "5日收益行业中位数调整 (行业相对动量)")
@register("ret10_industry_adj", "industry_relative", {"window": 10, "method": "median"},
          "10日收益行业中位数调整 (行业相对动量)")
@register("ret20_industry_adj", "industry_relative", {"window": 20, "method": "median"},
          "20日收益行业中位数调整 (行业相对动量)")
def ret_n_industry_adj(df, window=5, method="median"):
    """计算收益率的行业相对值 (行业中位数调整)"""
    raw = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(window))
    if method == "rank":
        return _industry_rank(df, raw)
    elif method == "zscore":
        return _industry_zscore(df, raw)
    return _industry_relative(df, raw)


# ─── 行业相对波动率 ────────────────────────────

@register("volatility20_industry_adj", "industry_relative", {"window": 20, "method": "median"},
          "20日波动率行业中位数调整 (行业相对低波动)")
def volatility20_industry_adj(df, window=20, method="median"):
    raw = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1).rolling(window).std())
    if method == "rank":
        return _industry_rank(df, raw)
    elif method == "zscore":
        return _industry_zscore(df, raw)
    return _industry_relative(df, raw)


# ─── 行业相对量比 ──────────────────────────────

@register("vol_ratio20_industry_adj", "industry_relative", {"window": 20, "method": "median"},
          "20日量比行业中位数调整 (行业相对量比)")
def vol_ratio20_industry_adj(df, window=20, method="median"):
    vol = df.groupby("symbol")["volume"].transform(lambda x: x.rolling(window).mean())
    raw = df["volume"] / vol.replace(0, np.nan)
    return _industry_relative(df, raw)


# ─── 行业相对流动性 ────────────────────────────

@register("amihud_industry_adj", "industry_relative", {"window": 20, "method": "rank"},
          "Amihud非流动性行业内排名 (越高=越流动性好)")
def amihud_industry_adj(df, window=20, method="rank"):
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1).abs())
    raw = ret / df["amount"].replace(0, np.nan)
    illiq = raw.groupby(df["symbol"]).transform(lambda x: x.rolling(window).mean())
    # 行业内排名 (rank, 越高越流动)
    return _industry_rank(df, -illiq)


# ─── 行业相对质量组合 ──────────────────────────

@register("industry_neutral_quality", "industry_relative", {},
          "行业内中性化质量综合分 (ROE+毛利+净利 行业内rank)")
def industry_neutral_quality(df):
    """质量因子行业内排名组合: 对 ROE/毛利率/净利率 做行业 rank 后等权"""
    score = pd.Series(0.0, index=df.index)
    n = 0
    for col in ["roe", "gross_margin", "net_margin"]:
        if col in df.columns:
            raw = df[col].fillna(0)
            score += _industry_rank(df, raw)
            n += 1
    return score / n if n > 0 else pd.Series(0.0, index=df.index)


# ─── 行业相对资金流 ────────────────────────────

@register("fund_flow_industry_adj", "industry_relative", {},
          "主力净流入行业内排名 (行业相对资金流)")
def fund_flow_industry_adj(df):
    if "net_main_force" not in df.columns:
        return pd.Series(0.0, index=df.index)
    return _industry_rank(df, df["net_main_force"].fillna(0))


# ─── 行业中性复合因子 ──────────────────────────

@register("industry_neutral_composite", "industry_relative", {},
          "行业中性复合因子 (动量+波动+量比+资金 行业内rank等权)")
def industry_neutral_composite(df):
    """多因子行业中性复合: 对每个因子做行业rank, 等权组合

    成分:
    - ret5 行业内rank
    - volatility20 行业内rank (取负, 低波动=高分)
    - vol_ratio20 行业内rank
    - net_main_force 行业内rank (如有资金流数据)
    """
    score = pd.Series(0.0, index=df.index)
    n = 0

    # 动量 (ret5)
    raw_r5 = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    score += _industry_rank(df, raw_r5.fillna(0))
    n += 1

    # 波动 (取负, 低波动好)
    raw_vol = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1).rolling(20).std())
    score -= _industry_rank(df, raw_vol.fillna(0))
    n += 1

    # 量比
    vol_ma = df.groupby("symbol")["volume"].transform(lambda x: x.rolling(20).mean())
    raw_vr = df["volume"] / vol_ma.replace(0, np.nan)
    score += _industry_rank(df, raw_vr.fillna(0))
    n += 1

    # 资金流 (可选)
    if "net_main_force" in df.columns:
        score += _industry_rank(df, df["net_main_force"].fillna(0))
        n += 1

    return score / n


# ─── 跨行业相对强度 ────────────────────────────

@register("cross_sector_strength", "industry_relative", {},
          "跨行业相对强度 (ret5行业adj × ret20行业rank)")
def cross_sector_strength(df):
    """跨行业相对强度: 行业相对5日动量 × 行业rank的20日动量"""
    ret5_raw = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(5))
    ret20_raw = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(20))
    adj_5 = _industry_relative(df, ret5_raw)
    rank_20 = _industry_rank(df, ret20_raw.fillna(0))
    return adj_5.fillna(0) * rank_20.fillna(0)


# ═══════════════════════════════════════════════
# 十五、事件驱动因子 V3.5 (Event-driven Alpha Pack)
# ═══════════════════════════════════════════════
# 事件: 解禁(Lockup expiry), 回购(Buyback), 分红(Dividend), 业绩预告(Earnings Forecast)
# 数据来源: announcements_extracted.csv, adjust_factor.csv, forecast_report.csv
# 所有因子在缺少事件数据列时优雅降级, 返回零值。


# ─── 解禁因子 (Lockup Expiry) ────────────────────
# 字段: lockup_days_to_expiry, lockup_count_90d

@register("lockup_expiry_proximity", "event", {},
          "解禁倒计时: 接近解禁期 (距离越近值越大)")
def lockup_expiry_proximity(df):
    """解禁倒计时信号
    正值=解禁前N天, 负值=已解禁。
    值越接近0 (即将解禁) 信号越强, 但方向性取决于市场预期。
    作为反向指标: 解禁前承压, 解禁后压力释放。
    """
    if "lockup_days_to_expiry" not in df.columns:
        return pd.Series(0.0, index=df.index)
    days = df["lockup_days_to_expiry"].fillna(0)
    # 解禁前5天信号最强 (假设解禁后流通盘增加带来抛压)
    # -1 = 已解禁超过5天, 0 = 无信号, 1 = 即将解禁
    signal = pd.Series(0.0, index=df.index)
    signal[(days > 0) & (days <= 5)] = 1.0    # 5天内解禁 → 有抛压预期
    signal[(days > 5) & (days <= 30)] = 0.5   # 一个月内解禁
    signal[(days <= 0) & (days > -5)] = -0.3  # 刚解禁 → 压力释放
    return signal


@register("lockup_announcement_activity", "event", {},
          "解禁公告活跃度: 近90天解禁公告数")
def lockup_announcement_activity(df):
    """近90天解禁公告数。公告越多=解禁事件密集=潜在波动。"""
    if "lockup_count_90d" not in df.columns:
        return pd.Series(0.0, index=df.index)
    return df["lockup_count_90d"].fillna(0).astype(float)


# ─── 回购因子 (Share Buyback) ────────────────────
# 字段: buyback_count_30d, buyback_count_90d, buyback_active

@register("buyback_signal", "event", {},
          "回购公告信号: 近30日有回购公告")
def buyback_signal(df):
    """回购公告信号。公司回购=管理层认为股价低估, 正面信号。"""
    if "buyback_active" in df.columns:
        return df["buyback_active"].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


@register("buyback_intensity", "event", {},
          "回购公告强度: 近90天回购公告数")
def buyback_intensity(df):
    """回购强度: 90天内回购公告数量。多次回购=更强烈的信心信号。"""
    if "buyback_count_90d" in df.columns:
        return df["buyback_count_90d"].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


@register("buyback_recent_intensity", "event", {},
          "回购近期强度: 近30天回购公告数")
def buyback_recent_intensity(df):
    """近期回购强度: 30天内回购公告数量。近期回购=股价支撑。"""
    if "buyback_count_30d" in df.columns:
        return df["buyback_count_30d"].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


# ─── 分红因子 (Dividend) ─────────────────────────
# 字段: dividend_yield, dividend_days_since, dividend_amount

@register("dividend_yield_factor", "event", {},
          "股息率: 每股股息 / 股价 (近似)")
def dividend_yield_factor(df):
    """股息率信号。高股息率=防御性价值, 低波动+稳定收益。"""
    if "dividend_yield" in df.columns:
        return df["dividend_yield"].fillna(0)
    return pd.Series(0.0, index=df.index)


@register("ex_dividend_proximity", "event", {},
          "除权除息后窗口期: 除息后30天内 (填权行情)")
def ex_dividend_proximity(df):
    """除权除息后窗口期信号。
    除息后短期内可能发生填权行情 (股价回升至除息前水平)。
    除息后30天内为信号窗口。
    """
    if "dividend_days_since" not in df.columns:
        return pd.Series(0.0, index=df.index)
    days = df["dividend_days_since"].fillna(365)
    # 除息后30天内为填权窗口
    signal = pd.Series(0.0, index=df.index)
    signal[(days >= 0) & (days <= 30)] = 1.0
    signal[(days > 30) & (days <= 60)] = 0.5
    return signal


@register("dividend_amount_factor", "event", {},
          "每股股息金额: 绝对值越高=分红越慷慨")
def dividend_amount_factor(df):
    """每股派息金额。金额越高=公司现金流越好。"""
    if "dividend_amount" in df.columns:
        return df["dividend_amount"].fillna(0)
    return pd.Series(0.0, index=df.index)


# ─── 业绩预告因子 (Earnings Forecast) ────────────
# 字段: forecast_type_code, forecast_days_since, forecast_count_90d, forecast_momentum

@register("forecast_upgrade_signal", "event", {},
          "业绩预增信号: 预告类型为预增/略增/扭亏")
def forecast_upgrade_signal(df):
    """业绩预增信号。预增=公司基本面改善=正面催化剂。"""
    if "forecast_type_code" not in df.columns:
        return pd.Series(0.0, index=df.index)
    code = df["forecast_type_code"].fillna(0)
    # >0 利多信号, 值越大越正面
    return (code > 0).astype(float) * code.abs()


@register("forecast_downgrade_signal", "event", {},
          "业绩预减信号: 预告类型为预减/续亏/首亏")
def forecast_downgrade_signal(df):
    """业绩预减信号。预减=公司基本面恶化=负面催化剂。"""
    if "forecast_type_code" not in df.columns:
        return pd.Series(0.0, index=df.index)
    code = df["forecast_type_code"].fillna(0)
    # <0 利空信号, 取绝对值之后为负信号
    return (code < 0).astype(float) * code.abs()  # 负值=利空


@register("forecast_momentum_signal", "event", {},
          "业绩预告动量: 近90天预增数-预减数")
def forecast_momentum_signal(df):
    """业绩预告动量: 正面预告 vs 负面预告的净数量。
    越高=近期基本面趋势越好。
    """
    if "forecast_momentum" in df.columns:
        return df["forecast_momentum"].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


@register("forecast_recent_activity", "event", {},
          "业绩预告活跃度: 近90天预告总数")
def forecast_recent_activity(df):
    """近期预告活跃度: 90天内预告总数。
    活跃度高=公司处于业绩密集发布期=信息量增加。
    """
    if "forecast_count_90d" in df.columns:
        return df["forecast_count_90d"].fillna(0).astype(float)
    return pd.Series(0.0, index=df.index)


# ─── 事件复合因子 (Event Composite) ──────────────

@register("event_composite_score", "event", {},
          "事件复合得分: 回购+业绩预增+除息窗口+解禁反向")
def event_composite_score(df):
    """多事件复合得分: 正面事件信号 - 负面事件信号
    - 回购信号: +1 如果有回购
    - 业绩预增: +0.5 如果预增
    - 业绩预减: -0.5 如果预减
    - 除息窗口: +0.3 如果在除息30天内
    - 解禁预警: -0.3 如果5天内解禁
    """
    score = pd.Series(0.0, index=df.index)

    # 回购信号
    if "buyback_active" in df.columns:
        score += df["buyback_active"].fillna(0) * 1.0

    # 业绩预增
    if "forecast_type_code" in df.columns:
        code = df["forecast_type_code"].fillna(0)
        score += (code > 0).astype(float) * 0.5
        score += (code < 0).astype(float) * (-0.5)

    # 除息窗口
    if "dividend_days_since" in df.columns:
        days = df["dividend_days_since"].fillna(365)
        score += ((days >= 0) & (days <= 30)).astype(float) * 0.3

    # 解禁预警 (反向)
    if "lockup_days_to_expiry" in df.columns:
        lock_days = df["lockup_days_to_expiry"].fillna(0)
        score += ((lock_days > 0) & (lock_days <= 5)).astype(float) * (-0.3)

    return score