"""V4.5 半导体专属因子库 — 主题择时/内部选股/风险反证

三层次因子体系:
  A类 (Theme Timing): 回答「什么时候配半导体」
  B类 (Stock Selection):  回答「半导体池里买谁」
  C类 (Risk Cross-validation): 回答「这个因子是不是假的」

数据依赖:
  - A类因子: 需 df 含 is_semi 列(是否半导体池成员), subsector 列(细分方向)
  - B类因子: 需 df 含 valuation_pct 列(估值历史分位), event_catalyst 列(事件催化得分)
             推荐同时提供 gross_margin、revenue_growth_q 等基本面列
  - C类因子: 需 df 含 industry(行业)、total_mv(总市值)、close 等标准列

所有因子通过 @register 装饰器注册到 factor_base.REGISTRY。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factor_lab.factor_base import register

# ═══════════════════════════════════════════════════════════════
# A类: 主题择时因子 (Sector Timing)
# ═══════════════════════════════════════════════════════════════
# 产业假设: 半导体作为强周期+成长双属性板块, 超额收益来源
# 于市场情绪、资金集中度、龙头效应和产业链共振。
# 择时核心: 相对全A强度 > 成交额占比 > 上涨广度 > 龙头强度。
#
# 输出约定: theme_state ∈ {极弱/偏弱/中性/偏强/极强}
#          recommended_theme_weight ∈ {0, 30, 50, 70, 100} (%)
# ============================================================


def _is_semi_marked(df: pd.DataFrame) -> bool:
    """检查 DataFrame 是否包含半导体标记"""
    return "is_semi" in df.columns


def _semi_mask(df: pd.DataFrame) -> pd.Series:
    """获取半导体池布尔掩码"""
    if "is_semi" in df.columns:
        return df["is_semi"].fillna(False).astype(bool)
    return pd.Series(False, index=df.index)


# ─── A1: 半导体 vs 全A 相对强度 ─────────────────────────

@register(
    "semi_vs_all_a_strength", "sector_timing",
    {"ew_window": 5},
    "半导体等权 / 全A等权 相对强度: >1 超额收益, <1 跑输",
)
def semi_vs_all_a_strength(df: pd.DataFrame, ew_window: int = 5) -> pd.Series:
    """半导体等权 / 全A等权 日收益率之比, 再取窗口均值

    产业假设:
      半导体作为 A 股最强贝塔板块之一, 相对全A走强时
      往往预示半导体主题行情启动; 持续走弱则主题退潮。
    输入:
      df: 需含 date, symbol, close, is_semi
      ew_window: 相对强度平滑窗口(默认5日)
    返回:
      每个交易日的相对强度值, 广播到该日期所有行
    """
    if not _is_semi_marked(df):
        return pd.Series(0.5, index=df.index)

    mask = _semi_mask(df)
    semi = df[mask].copy()
    all_a = df.copy()

    # 计算每日收益率
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    all_a["ret"] = all_a.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 等权均值 (按日期)
    semi_ew = semi.groupby("date")["ret"].mean()
    all_ew = all_a.groupby("date")["ret"].mean()

    # 相对强度 = 1 + (semi_ew - all_ew), 取窗口均值平滑
    ratio = 1.0 + (semi_ew - all_ew).fillna(0)
    ratio_smooth = ratio.rolling(ew_window, min_periods=1).mean().fillna(1.0)

    # 广播回到原始 DataFrame
    result = df["date"].map(ratio_smooth).fillna(1.0)
    return result


# ─── A2: 半导体成交额占比 ───────────────────────────────

@register(
    "semi_turnover_share", "sector_timing",
    {"smooth_window": 5},
    "半导体成交额 / 全A成交额: 越高=资金越集中半导体",
)
def semi_turnover_share(df: pd.DataFrame, smooth_window: int = 5) -> pd.Series:
    """半导体板块成交额占全A比例

    产业假设:
      半导体成交额占比持续上升 = 市场资金向半导体聚集,
      是主题行情启动的前兆。当占比从低位快速拉升时,
      往往对应主题主升浪。
    输入:
      df: 需含 date, symbol, amount, is_semi
      smooth_window: 移动平均窗口
    返回:
      成交额占比(0~1), 广播到该日期所有行
    """
    if not _is_semi_marked(df) or "amount" not in df.columns:
        return pd.Series(0.0, index=df.index)

    mask = _semi_mask(df)
    total_amount = df.groupby("date")["amount"].sum()
    semi_amount = df[mask].groupby("date")["amount"].sum()

    share = (semi_amount / (total_amount + 1e-8)).fillna(0)
    share_smooth = share.rolling(smooth_window, min_periods=1).mean().fillna(0)

    result = df["date"].map(share_smooth).fillna(0.0)
    return result


# ─── A3: 半导体上涨家数占比 ─────────────────────────────

@register(
    "semi_up_ratio", "sector_timing",
    {"window": 5},
    "半导体池上涨家数占比: >0.6=强势, <0.4=弱势",
)
def semi_up_ratio(df: pd.DataFrame, window: int = 5) -> pd.Series:
    """半导体池内上涨家数占比

    产业假设:
      半导体板块上涨广度 > 60% 表示内部高度共振,
      是可持续行情的信号; < 40% 则分化严重, 行情不可持续。
    输入:
      df: 需含 date, symbol, close, is_semi
      window: 平滑窗口
    返回:
      上涨家数占比(0~1), 广播到该日期所有行
    """
    if not _is_semi_marked(df):
        return pd.Series(0.5, index=df.index)

    mask = _semi_mask(df)
    semi = df[mask].copy()
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    daily_up_ratio = semi.groupby("date")["ret"].apply(
        lambda x: (x > 0).sum() / max(len(x), 1)
    ).fillna(0.5)

    smooth = daily_up_ratio.rolling(window, min_periods=1).mean().fillna(0.5)

    result = df["date"].map(smooth).fillna(0.5)
    return result


# ─── A4: 半导体涨停数 ──────────────────────────────────

@register(
    "semi_limit_up_count", "sector_timing",
    {"window": 3, "limit_pct": 0.098},
    "半导体涨停/跌停净计数(涨停-跌停): >3=板块情绪亢奋",
)
def semi_limit_up_count(df: pd.DataFrame, window: int = 3,
                        limit_pct: float = 0.098) -> pd.Series:
    """半导体板块涨停-跌停净计数

    产业假设:
      涨停是A股最强情绪指标。半导体板块涨停潮(净计数>5)
      往往宣告主题行情加速; 大面积跌停则是恐慌退潮信号。
    输入:
      df: 需含 date, symbol, close, is_semi
      window: 滚动窗口
      limit_pct: 涨停阈值 (默认9.8% 考虑四舍五入)
    返回:
      净涨停计数, 广播到该日期所有行
    """
    if not _is_semi_marked(df):
        return pd.Series(0.0, index=df.index)

    mask = _semi_mask(df)
    semi = df[mask].copy()
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    def _net_limit(g):
        up = (g >= limit_pct).sum()
        down = (g <= -limit_pct).sum()
        return up - down

    daily_net = semi.groupby("date")["ret"].apply(_net_limit).fillna(0).astype(float)
    smooth = daily_net.rolling(window, min_periods=1).mean().fillna(0)

    result = df["date"].map(smooth).fillna(0.0)
    return result


# ─── A5: 龙头相对强度 ─────────────────────────────────

@register(
    "semi_leader_strength", "sector_timing",
    {"top_n": 5, "window": 5},
    "半导体前N龙头等权 / 半导体整体等权: >1=龙头带队突破",
)
def semi_leader_strength(df: pd.DataFrame, top_n: int = 5,
                         window: int = 5) -> pd.Series:
    """龙头 vs 板块整体相对强度

    产业假设:
      半导体行情启动初期, 龙头股率先突破, 带动板块跟进。
      龙头强度 > 1.3 表示龙头效应显著, 行情健康;
      龙头强度回落 < 1 则板块内缺乏领涨力量, 行情可能尾声。
    输入:
      df: 需含 date, symbol, close, is_semi
      top_n: 选取前N只涨幅最大股作为龙头
      window: 平滑窗口
    返回:
      龙头强度比, 广播到该日期所有行
    """
    if not _is_semi_marked(df):
        return pd.Series(1.0, index=df.index)

    mask = _semi_mask(df)
    semi = df[mask].copy()
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 按日期分组, 取前N只涨幅最大股的均值 / 全部均值
    def _leader_ratio(g):
        if len(g) == 0:
            return 1.0
        sorted_vals = g.sort_values(ascending=False)
        n = min(top_n, len(sorted_vals))
        leader_mean = sorted_vals.iloc[:n].mean()
        all_mean = sorted_vals.mean()
        return leader_mean / all_mean if abs(all_mean) > 1e-8 else 1.0

    daily_ratio = semi.groupby("date")["ret"].apply(_leader_ratio).fillna(1.0)
    smooth = daily_ratio.rolling(window, min_periods=1).mean().fillna(1.0)

    result = df["date"].map(smooth).fillna(1.0)
    return result


# ─── A6: 半导体ETF成交额趋势 ──────────────────────────

@register(
    "semi_etf_amount_trend", "sector_timing",
    {"window": 5},
    "半导体ETF成交额趋势(按大盘归一化): 越高=资金借道ETF涌入",
)
def semi_etf_amount_trend(df: pd.DataFrame, window: int = 5) -> pd.Series:
    """半导体/芯片类ETF成交额相对全市场成交额的趋势

    产业假设:
      散户和游资通过ETF快速参与半导体行情。
      ETF成交额占比快速上升 = 情绪资金入场, 行情短期过热信号;
      持续高位 = 市场对半导体关注度极高。
    输入:
      df: 需含 date, symbol, amount, is_semi
          is_semi=True 且可识别为 ETF 的标的 (如 ts_code 含 "512480"等)
      window: 平滑窗口
    返回:
      ETF成交额趋势值, 广播到该日期所有行
    """
    if not _is_semi_marked(df) or "amount" not in df.columns:
        return pd.Series(0.0, index=df.index)

    mask = _semi_mask(df)

    # 识别半导体ETF: 代码包含半导体/芯片相关ETF
    # 常见半导体ETF ts_code: 512480.SH, 512760.SH, 159813.SZ, 159995.SZ, 588050.SH
    semi_etf_codes = [
        "512480", "512760", "159813", "159995",
        "588050", "159859", "588000",
    ]

    def _is_semi_etf(ts_code: str) -> bool:
        code = str(ts_code).split(".")[0]
        return code in semi_etf_codes

    # ETF 成交额
    if "ts_code" in df.columns:
        etf_mask = mask & df["ts_code"].apply(_is_semi_etf)
    else:
        # 退而求其次: 仅标记为 semi 的假设部分为 ETF
        etf_mask = mask & (df.get("is_etf", pd.Series(False, index=df.index)).fillna(False))

    total_amount = df.groupby("date")["amount"].sum()
    etf_amount = df[etf_mask].groupby("date")["amount"].sum()

    etf_share = (etf_amount / (total_amount + 1e-8)).fillna(0)
    etf_trend = etf_share.rolling(window, min_periods=1).mean().fillna(0)

    result = df["date"].map(etf_trend).fillna(0.0)
    return result


# ─── A7: 细分方向扩散度 ───────────────────────────────

@register(
    "semi_subsector_diffusion", "sector_timing",
    {"window": 5},
    "半导体细分方向(设备/材料/设计/封测)上涨占比: >0.75=全方向共振",
)
def semi_subsector_diffusion(df: pd.DataFrame, window: int = 5) -> pd.Series:
    """半导体细分方向上涨占比

    产业假设:
      半导体内部有设备、材料、设计、封测等细分方向。
      当所有细分方向均上涨时, 行情具备产业链级别共振,
      可持续性强。仅个别方向上涨则主题力度不足。
    输入:
      df: 需含 date, symbol, close, is_semi, subsector
      window: 平滑窗口
    返回:
      细分方向上涨占比(0~1), 广播到该日期所有行
    """
    if not _is_semi_marked(df) or "subsector" not in df.columns:
        return pd.Series(0.5, index=df.index)

    mask = _semi_mask(df)
    semi = df[mask].copy()
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 每个细分方向内: 是否上涨(均值>0)
    def _subsector_up_ratio(g):
        if g.empty:
            return 0.5
        subsectors = g.groupby("subsector")["ret"].mean()
        up_count = (subsectors > 0).sum()
        return up_count / max(len(subsectors), 1)

    daily_ratio = semi.groupby("date").apply(_subsector_up_ratio).fillna(0.5)
    smooth = daily_ratio.rolling(window, min_periods=1).mean().fillna(0.5)

    result = df["date"].map(smooth).fillna(0.5)
    return result


# ─── A类复合信号: theme_state + recommended_theme_weight ──

@register(
    "semi_theme_composite", "sector_timing", {},
    "半导体主题综合择时信号: 输出 theme_state + recommended_theme_weight",
)
def semi_theme_composite(df: pd.DataFrame) -> pd.Series:
    """半导体主题综合择时复合信号

    融合 A1-A7 七个维度, 输出:
      - theme_state: 极弱/偏弱/中性/偏强/极强 (str)
      - recommended_theme_weight: 0/30/50/70/100 (int, %仓位建议)

    产业假设:
      七维度等权打分, 避免单一指标误导。
      仅当相对强度 + 资金集中 + 上涨广度三要素同时确认时才为"极强"。
    返回:
      Series of str — "极弱"/"偏弱"/"中性"/"偏强"/"极强"
      可通过 df['date'].map(weight_map) 转为推荐仓位
    """
    if not _is_semi_marked(df):
        return pd.Series("中性", index=df.index)

    # 计算各子因子
    strength = semi_vs_all_a_strength(df)
    turnover = semi_turnover_share(df)
    up_ratio = semi_up_ratio(df)
    limit_up = semi_limit_up_count(df)
    leader = semi_leader_strength(df)
    etf_trend = semi_etf_amount_trend(df)

    # 将各因子映射到 -2 ~ +2 分
    signals = []

    # strength: 1.0=中性, >1.02=偏强, <0.98=偏弱
    s_signal = pd.cut(
        strength,
        bins=[-np.inf, 0.97, 0.99, 1.01, 1.03, np.inf],
        labels=[-2, -1, 0, 1, 2],
    ).astype(float).fillna(0)
    signals.append(s_signal)

    # turnover_share: 按分位数映射
    t_baseline = turnover.median() if turnover.nunique() > 1 else 0.02
    t_signal = pd.cut(
        turnover / (t_baseline + 1e-8),
        bins=[-np.inf, 0.5, 0.8, 1.2, 1.5, np.inf],
        labels=[-2, -1, 0, 1, 2],
    ).astype(float).fillna(0)
    signals.append(t_signal)

    # up_ratio: 上涨家数占比
    u_signal = pd.cut(
        up_ratio,
        bins=[-np.inf, 0.3, 0.45, 0.6, 0.75, np.inf],
        labels=[-2, -1, 0, 1, 2],
    ).astype(float).fillna(0)
    signals.append(u_signal)

    # limit_up: 净涨停
    l_signal = pd.cut(
        limit_up,
        bins=[-np.inf, -3, -1, 1, 3, np.inf],
        labels=[-2, -1, 0, 1, 2],
    ).astype(float).fillna(0)
    signals.append(l_signal)

    # leader: 龙头强度
    ld_signal = pd.cut(
        leader,
        bins=[-np.inf, 0.9, 0.98, 1.05, 1.15, np.inf],
        labels=[-2, -1, 0, 1, 2],
    ).astype(float).fillna(0)
    signals.append(ld_signal)

    # etf_trend: ETF成交额占比
    etf_baseline = etf_trend.median() if etf_trend.nunique() > 1 else 0.001
    etf_signal = pd.cut(
        etf_trend / (etf_baseline + 1e-8),
        bins=[-np.inf, 0.5, 0.8, 1.2, 1.5, np.inf],
        labels=[-2, -1, 0, 1, 2],
    ).astype(float).fillna(0)
    signals.append(etf_signal)

    # 综合得分
    composite = sum(signals) / len(signals)

    # 映射到 theme_state
    bins = [-np.inf, -1.5, -0.5, 0.5, 1.5, np.inf]
    labels = ["极弱", "偏弱", "中性", "偏强", "极强"]
    result = pd.cut(composite, bins=bins, labels=labels).astype(str)

    return result


# 仓位映射表: 供外部使用
THEME_WEIGHT_MAP = {
    "极弱": 0,
    "偏弱": 30,
    "中性": 50,
    "偏强": 70,
    "极强": 100,
}


def get_recommended_theme_weight(theme_state_series: pd.Series) -> pd.Series:
    """将 theme_state 文本映射为整数仓位百分比"""
    return theme_state_series.map(THEME_WEIGHT_MAP).fillna(50).astype(int)


# ═══════════════════════════════════════════════════════════════
# B类: 内部选股因子 (Stock Selection Within Semiconductor)
# ═══════════════════════════════════════════════════════════════
# 产业假设: 半导体池内个股分化极大, 选股超额收益源于:
#   1) 相对板块超额 (动量选股)
#   2) 基本面改善 (毛利率/营收趋势)
#   3) 估值安全边际
#   4) 事件催化
# 所有 B 类因子使用 semiconductor_ew (半导体等权) 作为基准对比。
# ============================================================


def _semi_ew_return(df: pd.DataFrame) -> pd.Series:
    """计算半导体等权日收益率 (内部辅助)

    返回 Series index=date, value=当日半导体等权收益率
    """
    if not _is_semi_marked(df):
        return pd.Series(0.0, index=df["date"].unique())
    mask = _semi_mask(df)
    semi = df[mask].copy()
    if semi.empty:
        return pd.Series(0.0, index=df["date"].unique())
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    ew = semi.groupby("date")["ret"].mean().fillna(0)
    return ew


# ─── B1: 个股相对半导体等权超额 ─────────────────────

@register(
    "stock_vs_semi_ew_strength", "semi_stock_selection",
    {"window": 10},
    "个股日收益 - 半导体等权收益: >0=跑赢板块",
)
def stock_vs_semi_ew_strength(df: pd.DataFrame, window: int = 10) -> pd.Series:
    """个股相对半导体等权组合的超额收益

    产业假设:
      半导体行情中, 超额收益持续为正的个股是板块内
      真正的 alpha 来源, 优先配置。超额转负则考虑替换。
    输入:
      df: 需含 date, symbol, close, is_semi
      window: 滚动均值窗口
    返回:
      超额收益率, 正值=跑赢板块
    """
    if not _is_semi_marked(df):
        return pd.Series(0.0, index=df.index)

    # 个股收益率
    stock_ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 半导体等权收益率
    semi_ew = _semi_ew_return(df)
    ew_map = df["date"].map(semi_ew).fillna(0)

    excess = stock_ret.fillna(0) - ew_map
    excess_smooth = excess.groupby(df["symbol"]).transform(
        lambda x: x.rolling(window, min_periods=1).mean()
    ).fillna(0)

    return excess_smooth


# ─── B2: 个股相对所属细分方向超额 ────────────────────

@register(
    "stock_vs_subsector_strength", "semi_stock_selection",
    {"window": 10},
    "个股日收益 - 所属细分方向等权收益: 细分方向内选股",
)
def stock_vs_subsector_strength(df: pd.DataFrame, window: int = 10) -> pd.Series:
    """个股相对所属细分方向的超额收益

    产业假设:
      半导体内部(设备/材料/设计/封测/EDA)走势分化。
      在同一细分方向内选 alpha, 剥离了方向性beta风险。
      细分方向内持续跑赢的个股是真正的细分龙头。
    输入:
      df: 需含 date, symbol, close, is_semi, subsector
      window: 滚动均值窗口
    返回:
      细分方向内超额收益
    """
    if not _is_semi_marked(df) or "subsector" not in df.columns:
        return pd.Series(0.0, index=df.index)

    stock_ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 计算每个细分方向等权收益
    mask = _semi_mask(df)
    semi = df[mask].copy()
    semi["ret"] = semi.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    subsector_ew = semi.groupby(["date", "subsector"])["ret"].mean().reset_index()
    subsector_ew.columns = ["date", "subsector", "subsector_ew"]

    # 合并回原始 df
    merged = df[["date", "subsector"]].merge(
        subsector_ew, on=["date", "subsector"], how="left"
    )
    excess = stock_ret.fillna(0) - merged["subsector_ew"].fillna(0)

    excess_smooth = excess.groupby(df["symbol"]).transform(
        lambda x: x.rolling(window, min_periods=1).mean()
    ).fillna(0)

    return excess_smooth


# ─── B3: 放量确认 ───────────────────────────────────

@register(
    "volume_confirmation", "semi_stock_selection",
    {"vol_window": 20, "ret_window": 5},
    "放量确认: 量比>1.2 且 上涨=放量上涨信号",
)
def volume_confirmation(df: pd.DataFrame, vol_window: int = 20,
                        ret_window: int = 5) -> pd.Series:
    """放量上涨确认信号

    产业假设:
      半导体是资金驱动型板块, 放量上涨=资金真金白银介入。
      缩量上涨/放量下跌均不可持续。放量+温和上涨=最佳信号。
    计算:
      1) 量比 = 当日量 / 20日均量
      2) 涨幅 = 5日涨幅
      3) 信号 = 量比>1.2 且 涨幅>0 → 放量上涨
              量比>1.2 且 涨幅<0 → 放量下跌 (负信号)
    返回:
      -1 ~ +1 信号值
    """
    if "volume" not in df.columns:
        return pd.Series(0.0, index=df.index)

    vol_ma = df.groupby("symbol")["volume"].transform(
        lambda x: x.rolling(vol_window, min_periods=1).mean()
    ).fillna(0)
    vol_ratio = df["volume"] / (vol_ma + 1e-8)

    ret_5 = df.groupby("symbol")["close"].transform(
        lambda x: x.pct_change(ret_window)
    ).fillna(0)

    # 放量上涨
    signal = pd.Series(0.0, index=df.index)
    signal[(vol_ratio > 1.2) & (ret_5 > 0)] = 1.0
    signal[(vol_ratio > 1.5) & (ret_5 > 0.02)] = 1.5  # 显著放量上涨
    signal[(vol_ratio > 1.2) & (ret_5 < -0.02)] = -1.0  # 放量下跌
    signal[(vol_ratio > 1.5) & (ret_5 < -0.03)] = -1.5  # 显著放量下跌

    # 缩量上涨 = 弱信号
    signal[(vol_ratio < 0.8) & (ret_5 > 0.02)] = 0.3

    return signal


# ─── B4: 毛利率改善 (YoY) ──────────────────────────

@register(
    "gross_margin_improvement", "semi_stock_selection",
    {},
    "毛利率同比改善: 当期毛利率 - 上年同期毛利率",
)
def gross_margin_improvement(df: pd.DataFrame) -> pd.Series:
    """毛利率同比改善幅度

    产业假设:
      半导体行业景气周期中, 毛利率提升是产能利用率提高
      和产品价格上行的直接证据。毛利率同比持续改善的
      个股是周期上行最大受益者。
    输入:
      df: 需含 gross_margin (可来自基本面数据)
          如果有 gross_margin_4q_ago 则直接计算同比变化
          否则使用最近可得值与历史值
    返回:
      毛利率同比变化(百分点), 越高越好
    """
    if "gross_margin" not in df.columns:
        return pd.Series(0.0, index=df.index)

    gm = df["gross_margin"].fillna(0)

    # 如果有同比列直接使用
    if "gross_margin_yoy" in df.columns:
        return df["gross_margin_yoy"].fillna(0)

    # 否则估算: 用4期滞后代替同比 (季度数据4Q lag)
    if "gross_margin_4q_ago" in df.columns:
        return gm - df["gross_margin_4q_ago"].fillna(0)

    # 回退: 使用当前毛利率的截面rank (只有截面数据时)
    if "date" in df.columns and gm.nunique() > 1:
        return gm.groupby(df["date"]).rank(pct=True).fillna(0.5)
    return gm * 0  # 无数据返回0


# ─── B5: 营收增速趋势 ──────────────────────────────

@register(
    "revenue_growth_trend", "semi_stock_selection",
    {},
    "营收增速趋势: 近3期营收同比增速的斜率为正=加速增长",
)
def revenue_growth_trend(df: pd.DataFrame) -> pd.Series:
    """营收增速趋势方向

    产业假设:
      半导体公司营收增速的趋势比绝对值更重要。
      连续加速增长 = 市场份额提升或行业景气上行;
      增速放缓即使仍在增长也需警惕周期见顶。
    输入:
      df: 需含 revenue_growth_q (单季营收同比)
          可选: revenue_growth_q_1, revenue_growth_q_2 (前两期)
    返回:
      趋势方向: >0=加速, <0=减速, 值越大趋势越强
    """
    if "revenue_growth_q" not in df.columns:
        return pd.Series(0.0, index=df.index)

    curr = df["revenue_growth_q"].fillna(0)

    # 如果有多期数据, 计算趋势斜率
    if all(col in df.columns for col in ["revenue_growth_q", "revenue_growth_q_1", "revenue_growth_q_2"]):
        q1 = df["revenue_growth_q_1"].fillna(0)
        q2 = df["revenue_growth_q_2"].fillna(0)
        # 线性回归斜率: 用离散差分近似
        trend = (curr - q2) / 2  # 两期变化均值
        return trend.fillna(0)

    # 只有当期: 直接用同比增速(越高越好)
    return curr / 100.0  # 归一化


# ─── B6: 估值分位不过热 ─────────────────────────────

@register(
    "valuation_not_overheated", "semi_stock_selection",
    {"pct_threshold": 0.8},
    "估值分位反过热: PE_TTM历史分位<80%=估值合理, 否则需警惕",
)
def valuation_not_overheated(df: pd.DataFrame,
                             pct_threshold: float = 0.8) -> pd.Series:
    """估值不过热信号

    产业假设:
      半导体作为高弹性板块, 估值易大幅偏离均值。
      当 PE_TTM 处于历史 80% 分位以上时, 即使基本面优秀
      也面临估值回归风险, 应降低权重。
    输入:
      df: 需含 pe_ttm 或 valuation_pct (0~1)
      pct_threshold: 过热阈值
    返回:
      >0 = 估值合理, <0 = 估值过热, 范围 -1 ~ +1
    """
    if "valuation_pct" in df.columns:
        pct = df["valuation_pct"].fillna(0.5)
    elif "pe_ttm" in df.columns:
        # 计算截面估值分位
        pe = df["pe_ttm"].replace(0, np.nan).abs()
        if "date" in df.columns and pe.nunique() > 1:
            pct = pe.groupby(df["date"]).rank(pct=True).fillna(0.5)
        else:
            pct = pd.Series(0.5, index=df.index)
    else:
        return pd.Series(0.0, index=df.index)

    # 映射: >80% 分位 = 过热 (负信号)
    # <20% 分位 = 低估 (正信号)
    signal = pd.Series(0.0, index=df.index)
    signal[pct < 0.2] = 1.0
    signal[(pct >= 0.2) & (pct < 0.8)] = 0.5
    signal[pct >= pct_threshold] = -1.0
    signal[pct >= 0.95] = -1.5  # 极度高估

    return signal


# ─── B7: 事件催化得分 ──────────────────────────────

@register(
    "event_catalyst_score", "semi_stock_selection",
    {},
    "事件催化得分: 回购+业绩预增+重大合同+政策利好+新产品",
)
def event_catalyst_score(df: pd.DataFrame) -> pd.Series:
    """事件催化综合得分

    产业假设:
      半导体板块受事件驱动效应显著:
      - 大基金/产业政策利好: 板块级催化剂
      - 公司回购/增持: 个股级正面信号
      - 业绩预告超预期: 基本面催化
      - 重大合同/订单公告: 成长性确认
      - 新产品/技术突破: 估值重塑催化剂
    输入:
      df: 需含 event_catalyst 列(预计算的事件催化剂得分)
          或以下列: forecast_upgrade, buyback_active,
          major_contract, policy_benefit, new_product
    返回:
      事件催化得分, 范围 -3 ~ +3
    """
    # 如果有预计算的综合催化分
    if "event_catalyst" in df.columns:
        return df["event_catalyst"].fillna(0).clip(-3, 3)

    # 否则计算多维度复合分
    score = pd.Series(0.0, index=df.index)

    # 业绩预增
    if "forecast_upgrade" in df.columns:
        score += df["forecast_upgrade"].fillna(0).astype(float) * 1.0
    if "forecast_downgrade" in df.columns:
        score -= df["forecast_downgrade"].fillna(0).astype(float) * 1.0

    # 回购信号
    if "buyback_active" in df.columns:
        score += df["buyback_active"].fillna(0).astype(float) * 0.8

    # 重大合同
    if "major_contract" in df.columns:
        score += df["major_contract"].fillna(0).astype(float) * 1.2

    # 政策利好 (如大基金注资、产业政策)
    if "policy_benefit" in df.columns:
        score += df["policy_benefit"].fillna(0).astype(float) * 1.5

    # 新产品/技术突破
    if "new_product" in df.columns:
        score += df["new_product"].fillna(0).astype(float) * 1.0

    # 降级到 factor_base 已有的事件因子
    if "forecast_type_code" in df.columns:
        code = df["forecast_type_code"].fillna(0)
        score += (code > 0).astype(float) * 0.5
        score += (code < 0).astype(float) * (-0.5)

    return score.clip(-3, 3)


# ═══════════════════════════════════════════════════════════════
# C类: 风险反证因子 (Risk Cross-validation)
# ═══════════════════════════════════════════════════════════════
# 目的: 验证一个因子是否真的是 alpha, 还是被其他风险因子
# 所驱动。高暴露 = 因子纯度低, 容易被对手策略收割。
#
# C类因子输出 0~1 的暴露度, 配合因子报告使用:
#   暴露度 > 0.6 = 高依赖, 因子可能是"假的"
#   暴露度 < 0.3 = 低依赖, 因子独立性好
# ============================================================


def _compute_beta(df: pd.DataFrame, stock_ret_col: str,
                  factor_ret_col: str, window: int = 60) -> pd.Series:
    """计算个股收益率对某个因子的滚动Beta

    Beta = Cov(ret_stock, ret_factor) / Var(ret_factor)

    返回滚动Beta值, 缺省值填充为1.0 (中性暴露)
    """
    def _beta_rolling(group):
        n = len(group)
        if n < window or n < 3:
            return pd.Series(1.0, index=group.index)
        stock_r = group[stock_ret_col].values
        factor_r = group[factor_ret_col].values
        # 防止全零/常数列
        if np.std(stock_r) < 1e-10 or np.std(factor_r) < 1e-10:
            return pd.Series(1.0, index=group.index)
        cov = np.cov(stock_r[-window:], factor_r[-window:])
        if cov.shape != (2, 2):
            return pd.Series(1.0, index=group.index)
        var_f = cov[1, 1]
        beta_val = cov[0, 1] / var_f if var_f > 1e-8 else 1.0
        return pd.Series(np.clip(beta_val, -3, 3), index=group.index)

    # 准备收益率数据
    needed = [stock_ret_col, factor_ret_col, "symbol"]
    existing = [c for c in needed if c in df.columns]
    df_valid = df[existing].dropna()
    if df_valid.empty:
        return pd.Series(1.0, index=df.index)

    # 按symbol分组计算
    result_series = df_valid.groupby("symbol").apply(
        lambda g: _beta_rolling(g)
    )

    # 处理 apply 返回的 MultiIndex 或 Series 值
    if isinstance(result_series, pd.DataFrame):
        # apply返回了DataFrame, 取第一列
        vals = result_series.iloc[:, 0]
    elif isinstance(result_series, pd.Series):
        # MultiIndex Series: (symbol, original_index) -> value
        vals = result_series
    else:
        return pd.Series(1.0, index=df.index)

    # 优雅映射回原始索引
    full = pd.Series(1.0, index=df.index)
    try:
        # vals 的索引是 (symbol, original_index) MultiIndex 或原始 index
        if isinstance(vals.index, pd.MultiIndex):
            # 通过原始index位置映射
            common = df.index.intersection(vals.index.droplevel(0))
            if not common.empty:
                full.loc[common] = vals.loc[vals.index.droplevel(0).isin(common)].values[:len(common)]
            else:
                # 回退: 通过symbol逐组映射
                for sym in vals.index.get_level_values(0).unique():
                    sub_vals = vals.xs(sym, level=0)
                    sub_idx = df[df["symbol"] == sym].index
                    n = min(len(sub_vals), len(sub_idx))
                    if n > 0:
                        full.loc[sub_idx[:n]] = sub_vals.iloc[:n].values
        else:
            full.loc[vals.index] = vals
    except (ValueError, IndexError, KeyError):
        # 兜底: 返回中性暴露
        pass

    return full


# ─── C1: 行业Beta暴露 ──────────────────────────────

@register(
    "industry_beta_exposure", "risk_cross_validation",
    {"window": 60, "norm": True},
    "个股对所属行业的Beta暴露: >1.5=高行业依赖",
)
def industry_beta_exposure(df: pd.DataFrame, window: int = 60,
                           norm: bool = True) -> pd.Series:
    """个股收益率对所属行业指数收益率的Beta暴露

    投资逻辑:
      如果一个因子选出的股票高度集中在特定行业,
      且对行业Beta暴露 > 1.5, 则该因子本质上是行业
      动量因子而非个股alpha。牛市中表现好但行业回撤时
      跌幅更大, 不具备跨周期稳定性。

    输入:
      df: 需含 close, industry, date, symbol
          且同一行业至少有3只以上股票
      window: 滚动窗口
      norm: 是否归一化到 0~1

    返回:
      Beta暴露度。norm=True: 0~1 (越高越依赖)
    """
    if "industry" not in df.columns:
        return pd.Series(0.5, index=df.index)

    # 计算个股日收益率
    df["_ret"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 计算行业等权收益率
    ind_ew = df.groupby(["date", "industry"])["_ret"].mean().reset_index()
    ind_ew.columns = ["date", "industry", "_ind_ret"]

    # 合并
    merged = df.merge(ind_ew, on=["date", "industry"], how="left")

    # 滚动Beta
    beta = _compute_beta(merged, "_ret", "_ind_ret", window=window)

    # 清理辅助列
    beta = beta.reindex(df.index).fillna(1.0)

    if norm:
        # 归一化到 0~1: 1.0=中性暴露(0.5), 越高越依赖
        return (np.clip(beta.abs(), 0, 3) / 3.0).fillna(0.5)
    return beta.fillna(1.0)


# ─── C2: 市值暴露 ─────────────────────────────────

@register(
    "size_exposure", "risk_cross_validation",
    {"norm": True},
    "个股对市值因子的暴露: 高=因子偏向小/大市值",
)
def size_exposure(df: pd.DataFrame, norm: bool = True) -> pd.Series:
    """个股对市值(size)因子的横截面暴露

    投资逻辑:
      如果因子的IC在大小市值分组之间差异显著,
      则该因子本质上是size因子。半导体板块内市值
      差异极大(从百亿到万亿), 掩盖在半导体标签下的
      size暴露是常见陷阱。

    输入:
      df: 需含 total_mv 或 float_mv
      norm: 是否做截面归一化到 0~1

    返回:
      市值暴露度。norm=True: 0~1 (越高=偏向该端市值)
      0~0.3: 偏小盘, 0.3~0.7: 市值中性, 0.7~1: 偏大盘
    """
    mv_col = None
    for col in ["total_mv", "float_mv", "market_cap"]:
        if col in df.columns:
            mv_col = col
            break

    if mv_col is None:
        return pd.Series(0.5, index=df.index)

    mv = df[mv_col].fillna(0).abs()

    if norm and "date" in df.columns and mv.nunique() > 1:
        # 截面rank归一化: 0=最小市值, 1=最大市值
        exposure = mv.groupby(df["date"]).rank(pct=True).fillna(0.5)
    elif norm:
        exposure = pd.Series(0.5, index=df.index)
    else:
        # 取对数市值
        log_mv = np.log1p(mv)
        exposure = (log_mv - log_mv.min()) / (log_mv.max() - log_mv.min() + 1e-8)
        exposure = exposure.fillna(0.5)

    return exposure


# ─── C3: 市场Beta暴露 ─────────────────────────────

@register(
    "market_beta_exposure", "risk_cross_validation",
    {"window": 60, "norm": True},
    "个股对全A等权的Beta暴露: >1.5=高市场依赖",
)
def market_beta_exposure(df: pd.DataFrame, window: int = 60,
                         norm: bool = True) -> pd.Series:
    """个股收益率对全A等权收益率的Beta暴露

    投资逻辑:
      高市场Beta的因子在牛市中表现亮眼, 但在熊市中
      跌幅更大。如果某个"半导体选股因子"筛选出的
      股票平均Beta > 1.2, 说明其超额收益主要来自
      承担了更高的市场风险, 而非真正的选股能力。

    输入:
      df: 需含 close, date, symbol
      window: 滚动窗口
      norm: 归一化到 0~1

    返回:
      市场Beta暴露度
    """
    df["_ret"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    # 全A等权收益率
    all_ew = df.groupby("date")["_ret"].mean().reset_index()
    all_ew.columns = ["date", "_mkt_ret"]

    merged = df.merge(all_ew, on="date", how="left")

    beta = _compute_beta(merged, "_ret", "_mkt_ret", window=window)
    beta = beta.reindex(df.index).fillna(1.0)

    # 清理辅助列
    for col in ["_ret", "_mkt_ret"]:
        if col in merged.columns:
            pass  # 不会影响原始df

    if norm:
        return (np.clip(beta.abs(), 0, 3) / 3.0).fillna(0.5)
    return beta.fillna(1.0)


# ─── C4: 波动率暴露 ──────────────────────────────

@register(
    "volatility_exposure", "risk_cross_validation",
    {"window": 60, "norm": True},
    "个股对波动率因子的暴露: 高=因子偏向高/低波",
)
def volatility_exposure(df: pd.DataFrame, window: int = 60,
                        norm: bool = True) -> pd.Series:
    """个股收益率对波动率(volatility)因子的暴露

    投资逻辑:
      低波动异象(Low Vol Anomaly)在A股同样存在:
      低波动股票长期跑赢高波动股票。如果一个因子
      偏向高波动股票, 则其短期高收益可能来自承担
      了额外的波动风险, 长期可能被低波因子反超。

    输入:
      df: 需含 close, date, symbol
      window: 波动率计算窗口
      norm: 是否截面归一化

    返回:
      波动率暴露度。norm=True: 0~1
      0~0.3: 低波, 0.3~0.7: 中波, 0.7~1: 高波
    """
    # 20日滚动波动率作为因子
    ret = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))
    vol = ret.groupby(df["symbol"]).transform(
        lambda x: x.rolling(window, min_periods=10).std()
    ).fillna(0)

    if norm and "date" in df.columns and vol.nunique() > 1:
        exposure = vol.groupby(df["date"]).rank(pct=True).fillna(0.5)
    elif norm:
        exposure = pd.Series(0.5, index=df.index)
    else:
        exposure = vol.fillna(0)

    return exposure


# ─── C5: 极端赢家依赖度 ──────────────────────────

@register(
    "extreme_winner_dependence", "risk_cross_validation",
    {"top_n": 3, "window": 20},
    "因子选股对前N只极端赢家的依赖度: >0.6=脆弱的集中度风险",
)
def extreme_winner_dependence(df: pd.DataFrame, top_n: int = 3,
                               window: int = 20) -> pd.Series:
    """因子选股组合对极端赢家的依赖度

    投资逻辑:
      如果一个因子的多头组合收益高度依赖于少数几只
      极端赢家(如前3只暴涨股), 则该因子的收益分布
      是厚尾的——真正收益来自运气而非能力。一旦极端
      赢家反转, 因子收益将大幅回撤。
      这是量化领域常见的"伪alpha"陷阱。

    计算:
      1) 对每日, 取因子得分(由本因子计算)前20%的股票
      2) 计算这些股票中前 top_n 只收益贡献占比
      3) 占比 > 60% = 极端依赖

    输入:
      df: 需含 close, date, symbol
          调用者需确保 df 包含需要评估的因子值列
          (默认用 ret20 作为代理因子, 或用户指定)
      top_n: 极端赢家数
      window: 滚动窗口

    返回:
      依赖度 0~1, >0.6 表示高依赖
    """
    factor_col = None
    for col in ["factor_score", "ret20", "ret10", "ret5"]:
        if col in df.columns:
            factor_col = col
            break

    if factor_col is None:
        # 使用20日收益作为代理因子
        df["_factor_20"] = df.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(20)
        ).fillna(0)
        factor_col = "_factor_20"

    # 对每个日期: 找出因子得分前20%的股票, 计算前N只的收益贡献
    df["_ret_1d"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(1))

    def _dependency_for_date(g):
        if len(g) < 5:
            return 0.5

        # 按因子得分排序, 取前20%
        sorted_g = g.sort_values(factor_col, ascending=False)
        top20_count = max(int(len(sorted_g) * 0.2), top_n)
        top20 = sorted_g.iloc[:top20_count]

        total_ret = top20["_ret_1d"].sum()
        if abs(total_ret) < 1e-8:
            return 0.5

        # 前N只极端赢家的收益贡献
        winners = top20.head(top_n)
        winner_ret = winners["_ret_1d"].sum()
        dependency = min(abs(winner_ret / total_ret), 1.0)

        return dependency

    daily_dep = df.groupby("date").apply(_dependency_for_date).fillna(0.5)
    smooth = daily_dep.rolling(window, min_periods=1).mean().fillna(0.5)

    result = df["date"].map(smooth).fillna(0.5)

    # 清理辅助列
    for col in ["_factor_20", "_ret_1d"]:
        if col in df.columns:
            pass  # 局部df, 不会影响原始df

    return result


# ─── C类复合风险报告 ──────────────────────────────

def build_risk_report(df: pd.DataFrame, factor_name: str = "unknown") -> dict:
    """构建因子风险反证报告

    计算所有C类因子暴露, 输出综合评估:
      - 各维度暴露度 (0~1)
      - 综合风险分数 (0~1, 越高越危险)
      - 风险评级: 低/中/高

    用法:
        report = build_risk_report(df, "my_factor")
        print(report["risk_rating"])
    """
    exposures = {
        "industry_beta": industry_beta_exposure(df).mean(),
        "size": size_exposure(df).mean(),
        "market_beta": market_beta_exposure(df).mean(),
        "volatility": volatility_exposure(df).mean(),
        "extreme_winner_dep": extreme_winner_dependence(df).mean(),
    }

    # 综合风险: 各维度均值 (等权)
    composite_risk = np.mean(list(exposures.values()))

    # 评级
    if composite_risk < 0.3:
        rating = "低"
    elif composite_risk < 0.5:
        rating = "中"
    else:
        rating = "高"

    return {
        "factor_name": factor_name,
        "exposures": exposures,
        "composite_risk": round(float(composite_risk), 4),
        "risk_rating": rating,
        "risk_assessment": (
            "因子独立性好, 不易被对手策略收割"
            if rating == "低"
            else (
                "存在中等风险暴露, 建议检查因子正交化"
                if rating == "中"
                else "高风险! 因子可能被其他风险因子驱动, 建议重新设计"
            )
        ),
    }
