"""Industry Mapper — 行业分类映射 V3.1

为 Industry Relative Alpha Pack 提供股票→行业映射。
支持数据源:
1. Baostock query_stock_industry (首选)
2. 本地缓存的 stock_industry.csv
3. tag_features.csv 中 style/tags 的 fallback
4. 所有股票归入 "unknown" (兜底)

用法:
    from factor_lab.alpha.industry_mapper import IndustryMapper
    mapper = IndustryMapper()
    industry = mapper.get_industry("000001")      # → "银行"
    mapping = mapper.get_industry_map()            # → {"000001": "银行", ...}
    stocks_by_industry = mapper.get_stocks_by_industry()  # → {"银行": ["000001", ...], ...}
"""

import csv
import json
import os
from pathlib import Path
from typing import Optional

# ─── 路径常量 ──────────────────────────────────────────────
DATA_HUB = Path(os.environ.get("DATA_HUB", "/mnt/c/Users/ly/.codex/data/a-share-data-hub"))
HERMES_DATA = Path("/home/ly/.hermes/research-assistant/data")

STOCK_INDUSTRY_CSV = HERMES_DATA / "tags" / "stock_industry.csv"
POOL_CSV = DATA_HUB / "market" / "pool.csv"
TAG_FEATURES_CSV = DATA_HUB / "features" / "tag_features.csv"
FUNDAMENTAL_FEATURES_CSV = DATA_HUB / "features" / "fundamental_features.csv"
STYLE_INDUSTRY_MAP = {
    "cyclical_growth": "cyclical",
    "cyclical_value": "cyclical",
    "defensive_growth": "defensive",
    "defensive_value": "defensive",
    "large_cap_growth": "large_cap",
    "large_cap_value": "large_cap",
    "small_cap_growth": "small_cap",
    "small_cap_value": "small_cap",
    "thematic": "other",
}


class IndustryMapper:
    """股票→行业映射管理器"""

    def __init__(self, auto_load: bool = True):
        self._mapping: dict[str, str] = {}
        self._industry_codes: dict[str, set[str]] = {}
        if auto_load:
            self.load()

    # ─── 加载 ────────────────────────────────────────────

    def load(self) -> dict[str, str]:
        """加载行业映射, 优先顺序: baostock → 缓存CSV → fallback"""
        if self._try_load_from_baostock():
            pass
        elif self._try_load_from_cache():
            pass
        else:
            self._try_load_from_tag_features()
        self._build_index()
        return self._mapping

    def _try_load_from_baostock(self) -> bool:
        """尝试从 baostock 拉取行业数据"""
        try:
            from baostock_data import fetch_stock_industry
            _, errors = fetch_stock_industry()
            if errors == 0 and STOCK_INDUSTRY_CSV.exists():
                return self._try_load_from_cache()
            return False
        except Exception:
            return False

    def _try_load_from_cache(self) -> bool:
        """从本地缓存 CSV 加载"""
        if not STOCK_INDUSTRY_CSV.exists():
            return False
        try:
            with open(STOCK_INDUSTRY_CSV, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = (row.get("code") or "").strip()
                    industry = (row.get("industry") or "").strip()
                    if code and industry:
                        self._mapping[code] = industry
            return len(self._mapping) > 0
        except Exception:
            return False

    def _try_load_from_tag_features(self) -> bool:
        """从 tag_features.csv 的 style 推测行业"""
        if not TAG_FEATURES_CSV.exists():
            self._fallback_unknown()
            return
        try:
            with open(TAG_FEATURES_CSV, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = (row.get("symbol") or "").strip()
                    style = (row.get("style") or "").strip().lower()
                    if code:
                        industry = STYLE_INDUSTRY_MAP.get(style, "unknown")
                        self._mapping[code] = industry
            if not self._mapping:
                self._fallback_unknown()
        except Exception:
            self._fallback_unknown()

    def _fallback_unknown(self):
        """兜底: 从 pool.csv 取所有股票代码, 全部分类为 unknown"""
        if not POOL_CSV.exists():
            return
        with open(POOL_CSV, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("code") or "").strip()
                if code:
                    self._mapping[code] = "unknown"

    def _build_index(self):
        """构建 industry → [stock code] 倒排索引"""
        self._industry_codes = {}
        for code, ind in self._mapping.items():
            self._industry_codes.setdefault(ind, set()).add(code)

    # ─── 公共 API ────────────────────────────────────────

    def get_industry(self, symbol: str) -> str:
        """获取单只股票的行业"""
        return self._mapping.get(symbol, "unknown")

    def get_industry_map(self) -> dict[str, str]:
        """获取完整映射 {symbol: industry}"""
        return dict(self._mapping)

    def get_stocks_by_industry(self) -> dict[str, list[str]]:
        """获取行业→股票列表 {industry: [symbol, ...]}"""
        return {ind: sorted(codes) for ind, codes in self._industry_codes.items()}

    def get_industry_list(self) -> list[str]:
        """获取所有行业列表"""
        return sorted(self._industry_codes.keys())

    def get_industry_count(self) -> dict[str, int]:
        """获取行业股票数量 {industry: count}"""
        return {ind: len(codes) for ind, codes in self._industry_codes.items()}

    def add_industry(self, symbol: str, industry: str):
        """手动添加/覆盖单个股票行业"""
        self._mapping[symbol] = industry
        self._build_index()

    def save_cache(self):
        """保存映射到本地 CSV"""
        STOCK_INDUSTRY_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(STOCK_INDUSTRY_CSV, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["code", "industry", "asof_date"])
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            for code in sorted(self._mapping.keys()):
                w.writerow([code, self._mapping[code], now])

    def to_dict(self) -> dict:
        """序列化为 JSON 可序列化 dict"""
        return {
            "mapping": self._mapping,
            "industry_count": self.get_industry_count(),
            "total_stocks": len(self._mapping),
            "industry_list": self.get_industry_list(),
        }


def quick_industry_map() -> dict[str, str]:
    """快速获取行业映射 (单行便捷函数)"""
    return IndustryMapper().get_industry_map()


if __name__ == "__main__":
    mapper = IndustryMapper()
    print(f"行业数量: {len(mapper.get_industry_list())}")
    print(f"股票数量: {len(mapper.get_industry_map())}")
    print(f"行业分布: {json.dumps(mapper.get_industry_count(), ensure_ascii=False, indent=2)}")
