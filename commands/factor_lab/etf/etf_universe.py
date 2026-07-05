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
