"""ETF 注册表 — A 股主流主题 ETF 元数据

数据来源: 公开市场数据, 截至 2026-07
字段含义:
  etf_code: 上交所/深交所 ETF 代码
  theme: 主题分类 (用于与 restricted 信号匹配)
  exchange: SH/SZ
  expense_ratio: 管理费率(%)
  aum: 规模估算(亿元), None=未知
  avg_amount_20d: 20日均成交额(万元), None=未知
  listing_date: 上市日期
  tracked_index: 跟踪指数
"""
import csv, os
from pathlib import Path
from typing import Optional
import pandas as pd

ETF_REGISTRY_PATH = Path(__file__).parent.parent.parent / "data" / "etf" / "etf_registry.csv"

ETF_DATA = [
    # ── 科创芯片 / 科创半导体 ──
    ("588200", "科创芯片ETF", "SH", "科创芯片", "上证科创板芯片指数", "2022-10", 0.50, 85, 52000, None),
    ("588290", "科创芯片ETF华安", "SH", "科创芯片", "上证科创板芯片指数", "2022-10", 0.50, 12, 8500, None),

    # ── 半导体设备 ──
    ("159516", "半导体设备ETF", "SZ", "半导体设备", "中证半导体设备指数", "2023-05", 0.50, 18, 12000, None),
    ("560780", "半导体设备材料ETF", "SH", "半导体设备", "中证半导体设备材料指数", "2023-05", 0.50, 8, 4500, None),

    # ── 科创50 ──
    ("588000", "科创50ETF", "SH", "科创50", "上证科创板50指数", "2020-09", 0.50, 680, 180000, None),
    ("588080", "科创50ETF易方达", "SH", "科创50", "上证科创板50指数", "2020-09", 0.50, 420, 95000, None),
    ("588090", "科创50ETF华泰柏瑞", "SH", "科创50", "上证科创板50指数", "2020-09", 0.50, 180, 42000, None),

    # ── 科创100 ──
    ("588030", "科创100ETF", "SH", "科创100", "上证科创板100指数", "2023-09", 0.50, 95, 35000, None),
    ("588190", "科创100ETF易方达", "SH", "科创100", "上证科创板100指数", "2023-09", 0.50, 45, 18000, None),
    ("588220", "科创100ETF华泰柏瑞", "SH", "科创100", "上证科创板100指数", "2023-09", 0.50, 38, 15000, None),

    # ── 中证半导体 / 芯片 ──
    ("159995", "芯片ETF", "SZ", "芯片", "国证芯片指数", "2020-02", 0.50, 220, 85000, None),
    ("512760", "芯片ETF易方达", "SH", "芯片", "中证半导体指数", "2019-06", 0.50, 180, 72000, None),
    ("159813", "半导体ETF", "SZ", "芯片", "中证半导体指数", "2020-05", 0.50, 65, 28000, None),

    # ── 创业板 ──
    ("159915", "创业板ETF", "SZ", "创业板", "创业板指数", "2011-09", 0.50, 380, 150000, None),
    ("159952", "创业板ETF广发", "SZ", "创业板", "创业板指数", "2011-11", 0.50, 65, 22000, None),
    ("159977", "创业板ETF天弘", "SZ", "创业板", "创业板指数", "2019-09", 0.50, 55, 18000, None),

    # ── 创业板成长 ──
    ("159967", "创业板成长ETF", "SZ", "创业板成长", "创业板动量成长指数", "2019-07", 0.50, 45, 12000, None),
    ("159966", "创业板低波价值ETF", "SZ", "创业板成长", "创业板低波价值指数", "2019-07", 0.50, 12, 3500, None),

    # ── 人工智能 / 算力 ──
    ("159819", "人工智能ETF", "SZ", "人工智能", "中证人工智能指数", "2020-12", 0.50, 85, 32000, None),
    ("515980", "人工智能ETF易方达", "SH", "人工智能", "中证人工智能指数", "2020-07", 0.50, 42, 15000, None),
    ("159998", "计算机ETF", "SZ", "人工智能", "中证计算机指数", "2021-03", 0.50, 28, 11000, None),
]


def load_etf_registry(path=None) -> list:
    """加载 ETF 注册表

    如果 CSV 文件存在则从 CSV 加载, 否则从内置数据生成。
    """
    if path is None:
        path = ETF_REGISTRY_PATH

    if path.exists():
        etfs = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                etfs.append(row)
        return etfs

    # 首次运行时从内置数据生成 CSV
    os.makedirs(path.parent, exist_ok=True)
    fields = ["etf_code", "etf_name", "exchange", "theme", "tracked_index",
              "listing_date", "expense_ratio", "aum", "avg_amount_20d", "holdings_available"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for row in ETF_DATA:
            w.writerow(row)

    return load_etf_registry(path)


def get_etf_by_theme(theme: str) -> list:
    """按主题获取 ETF 列表"""
    all_etfs = load_etf_registry()
    return [e for e in all_etfs if e.get("theme", "") == theme]


def list_themes() -> list:
    """列出所有主题"""
    all_etfs = load_etf_registry()
    return sorted(set(e["theme"] for e in all_etfs if e.get("theme")))


def map_restricted_to_theme(board: str, keywords: list = None) -> str:
    """根据受限板块和关键词推断 ETF 主题

    参数:
        board: "科创板"/"创业板"/"北交所"
        keywords: [symbol, ret5, ...]

    返回: theme 名称
    """
    # 多种信号综合判断, 简化版按板块映射
    theme_map = {
        "科创板": "科创50",  # 默认科创50, 如果有芯片关键词则用芯片
        "创业板": "创业板成长",
        "北交所": "创业板",  # 北交所暂无专门 ETF
    }
    base = theme_map.get(board, "创业板")

    # 如果有芯片/半导体关键词, 优先使用芯片主题
    if keywords:
        kw_str = " ".join(str(k).lower() for k in keywords)
        if any(w in kw_str for w in ["688", "芯片", "半导体", "集成电路", "光刻"]):
            return "科创芯片"
        if any(w in kw_str for w in ["300", "301", "创业"]):
            return "创业板成长"
    return base


# ═══════════════════════════════════════════════════════════
# ETF 替代方案 — 个股不可交易时自动匹配 ETF
# ═══════════════════════════════════════════════════════════

# 个股→主题/行业映射前缀规则
# 基于股票代码前缀和常见行业分类推断其对应主题
STOCK_TO_THEME_PREFIX = {
    # ── 科创板 ——
    "688012": "半导体设备",   # 中微公司
    "688072": "半导体设备",   # 拓荆科技
    "688120": "半导体设备",   # 华海清科
    "688037": "半导体设备",   # 芯源微
    "688001": "半导体设备",   # 华兴源创
    "688008": "芯片",        # 澜起科技
    "688256": "芯片",        # 寒武纪
    "688041": "芯片",        # 海光信息
    "688981": "芯片",        # 中芯国际
    "688099": "芯片",        # 晶晨股份
    "688126": "芯片",        # 沪硅产业
    "688396": "芯片",        # 华润微
    "688385": "芯片",        # 复旦微电
    "688052": "芯片",        # 纳芯微
    "688798": "芯片",        # 艾为电子
    "688536": "芯片",        # 思瑞浦
    "688095": "人工智能",    # 福昕软件
    "688568": "人工智能",    # 中科星图
    "688111": "人工智能",    # 金山办公
    "688188": "人工智能",    # 柏楚电子
    # ── 半导体/芯片 (主板/中小板) ──
    "002371": "半导体设备",   # 北方华创
    "002049": "芯片",        # 紫光国微
    "600703": "芯片",        # 三安光电
    "603501": "芯片",        # 韦尔股份
    "600745": "芯片",        # 闻泰科技
    "603986": "芯片",        # 兆易创新
    "600460": "芯片",        # 士兰微
    "300661": "芯片",        # 圣邦股份
    "300223": "芯片",        # 北京君正
    "300782": "芯片",        # 卓胜微
    "300458": "芯片",        # 全志科技
    "300672": "芯片",        # 国科微
    # ── 人工智能 ──
    "002230": "人工智能",    # 科大讯飞
    "300308": "人工智能",    # 中际旭创
    "300502": "人工智能",    # 新易盛
    "300394": "人工智能",    # 天孚通信
    "603019": "人工智能",    # 中科曙光
    "000977": "人工智能",    # 浪潮信息
    "300624": "人工智能",    # 万兴科技
    "002415": "人工智能",    # 海康威视
    # ── 计算机 ──
    "002602": "人工智能",    # 世纪华通
}

# 行业代码前缀 → 行业名称
# 用于没有精确主题映射时的行业级回退
STOCK_PREFIX_TO_BOARD = {
    "300": "创业",
    "301": "创业",
    "688": "科创",
    "689": "科创",
    "600": "主板",
    "601": "主板",
    "603": "主板",
    "605": "主板",
    "000": "深主板",
    "001": "深主板",
    "002": "中小板",
    "003": "中小板",
    "4": "北交所",
    "8": "北交所",
}


def _infer_stock_theme(symbol: str) -> str:
    """根据股票代码推断最佳匹配主题

    优先级: 精确代码匹配 > 行业关键词推断 > 板块默认
    """
    sym = symbol.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()

    # 1. 精确代码匹配
    if sym in STOCK_TO_THEME_PREFIX:
        return STOCK_TO_THEME_PREFIX[sym]

    # 2. 前缀匹配 (取最长前缀)
    matched_prefix = ""
    for prefix in sorted(STOCK_TO_THEME_PREFIX.keys(), key=len, reverse=True):
        if sym.startswith(prefix):
            return STOCK_TO_THEME_PREFIX[prefix]

    # 3. 板块级推断
    prefix = sym[:3] if len(sym) >= 3 else sym[:1]
    board = STOCK_PREFIX_TO_BOARD.get(prefix, "主板")

    if board == "科创":
        return "科创芯片"  # 科创板默认→芯片主题(最常见科创主题ETF)
    elif board == "创业":
        return "创业板成长"
    elif board in ("主板", "深主板", "中小板"):
        return "创业板"  # 主板宽基→创业板ETF作为成长替代
    elif board == "北交所":
        return "创业板"
    return "创业板"


def find_etf_substitute(
    symbol: str,
    etf_universe: list = None,
    theme_map: dict = None,
) -> list[dict]:
    """为不可交易的股票寻找最佳替代 ETF

    匹配优先级: 同主题 > 同行业 > 宽基指数

    Args:
        symbol: 股票代码 (如 "688012" 或 "688012.SH")
        etf_universe: ETF 数据库 (list of dicts), 默认 load_etf_registry()
        theme_map: {symbol: [theme_tags]}, 可选的外部主题映射

    Returns:
        [{etf_code, etf_name, match_reason, weight, score}, ...]
        按匹配度降序排列, 最多返回 5 个
    """
    if etf_universe is None:
        etf_universe = load_etf_registry()

    sym = symbol.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()

    # 确定目标主题
    target_themes = set()

    # 1. 外部 theme_map 优先
    if theme_map and sym in theme_map:
        tags = theme_map[sym]
        if isinstance(tags, str):
            target_themes.add(tags)
        else:
            target_themes.update(tags)

    # 2. 内置推断
    target_themes.add(_infer_stock_theme(sym))

    # 如果符号以 688 开头, 添加科创类备选
    if sym.startswith("688"):
        target_themes.update(["科创50", "科创芯片", "半导体设备"])
    elif sym.startswith(("300", "301")):
        target_themes.update(["创业板", "创业板成长"])
    elif sym.startswith(("002", "600", "601", "603", "000", "001")):
        target_themes.update(["芯片", "人工智能", "创业板成长", "创业板"])

    # 匹配 ETF
    matches = []
    etf_codes_seen = set()

    # 按优先级评分: 精确主题=25, 宽基/近似=15, 兜底=5
    for etf in etf_universe:
        etf_code = etf.get("etf_code", "")
        if etf_code in etf_codes_seen:
            continue

        etf_theme = etf.get("theme", "")
        etf_name = etf.get("etf_name", "")
        etf_index = etf.get("tracked_index", "")

        if not etf_code or not etf_name:
            continue

        # 计算匹配得分
        score = 0
        match_reason = ""

        if etf_theme in target_themes:
            score = 25
            match_reason = f"同主题({etf_theme})"
        elif etf_theme in ("创业板成长", "创业板") and any(
            t in target_themes for t in ("创业板成长", "创业板", "创业")
        ):
            score = 20
            match_reason = f"创业板相关({etf_theme})"
        elif etf_theme in ("科创50", "科创100", "科创芯片") and any(
            t in target_themes for t in ("科创50", "科创芯片", "科创100")
        ):
            score = 20
            match_reason = f"科创板相关({etf_theme})"
        elif etf_theme == "宽基":
            score = 5
            match_reason = "宽基指数"
        elif "芯片" in etf_theme and any("芯片" in t for t in target_themes):
            score = 15
            match_reason = f"芯片相关ETF({etf_theme})"
        elif "半导体" in etf_theme and any("半导体" in t for t in target_themes):
            score = 15
            match_reason = f"半导体相关ETF({etf_theme})"

        if score > 0:
            # 流动性/规模加分
            try:
                amount = float(etf.get("avg_amount_20d", 0) or 0)
                if amount >= 50000:
                    score += 5
                elif amount >= 10000:
                    score += 3
            except (ValueError, TypeError):
                pass

            etf_codes_seen.add(etf_code)
            matches.append({
                "etf_code": etf_code,
                "etf_name": etf_name,
                "match_reason": match_reason,
                "score": score,
                "weight": round(score / 100, 4),  # 简化为相对权重
                "theme": etf_theme,
                "tracked_index": etf_index,
                "avg_amount_20d": etf.get("avg_amount_20d", "?"),
                "aum": etf.get("aum", "?"),
            })

    # 按评分降序排列
    matches.sort(key=lambda x: -x["score"])

    # 最多返回 5 个
    return matches[:5]


def build_etf_universe() -> pd.DataFrame:
    """使用 akshare 构建 A 股 ETF 数据库

    尝试从 akshare 获取实时 ETF 列表, 如果失败则回退到内置注册表。

    Returns:
        pd.DataFrame with columns: [代码, 名称, 最新价, 成交额, 市值, 跟踪指数]
    """
    try:
        import akshare as ak

        etf = ak.fund_etf_spot_em()
        if etf.empty:
            raise ValueError("akshare 返回空数据")

        # 选择常用字段并标准化列名
        col_map = {
            "代码": "etf_code",
            "名称": "etf_name",
            "最新价": "price",
            "成交额": "amount",
            "市值": "aum",
            "跟踪指数": "tracked_index",
            "日涨跌幅": "pct_chg",
        }
        available = {k: v for k, v in col_map.items() if k in etf.columns}
        df = etf[list(available.keys())].rename(columns=available)

        # 过滤无效代码
        df = df[df["etf_code"].astype(str).str.match(r"^\d{6}$")].copy()
        df["etf_code"] = df["etf_code"].astype(str)

        return df

    except ImportError:
        pass  # akshare 未安装, 回退
    except Exception:
        pass  # 其他获取失败, 回退

    # 回退: 从内置注册表构建
    import pandas as pd

    registry = load_etf_registry()
    rows = []
    for e in registry:
        rows.append({
            "etf_code": e.get("etf_code", ""),
            "etf_name": e.get("etf_name", ""),
            "price": None,
            "amount": e.get("avg_amount_20d"),
            "aum": e.get("aum"),
            "tracked_index": e.get("tracked_index", ""),
            "theme": e.get("theme", ""),
        })
    return pd.DataFrame(rows)
