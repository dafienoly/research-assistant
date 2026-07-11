"""Industry Mapper — 行业分类映射 V3.1

为 Industry Relative Alpha Pack 提供股票→行业映射。
唯一数据源是 canonical DataHub reference/stock_basic.csv；缺失时显式
MISSING，单标的查询返回 ``unknown``，不读取或写入平行缓存。

用法:
    from factor_lab.alpha.industry_mapper import IndustryMapper
    mapper = IndustryMapper()
    industry = mapper.get_industry("000001")      # → "银行"
    mapping = mapper.get_industry_map()            # → {"000001": "银行", ...}
    stocks_by_industry = mapper.get_stocks_by_industry()  # → {"银行": ["000001", ...], ...}
"""

import json

from factor_lab.datahub_access import read_stock_industry_map


class IndustryMapper:
    """股票→行业映射管理器"""

    def __init__(self, auto_load: bool = True):
        self._mapping: dict[str, str] = {}
        self._industry_codes: dict[str, set[str]] = {}
        self.status = "NOT_LOADED"
        self.error = ""
        if auto_load:
            self.load()

    # ─── 加载 ────────────────────────────────────────────

    def load(self) -> dict[str, str]:
        """Load only the canonical DataHub stock-industry mapping."""
        self._mapping.clear()
        if self._try_load_from_datahub():
            self.status = "OK"
            self.error = ""
        else:
            self.status = "MISSING"
        self._build_index()
        return self._mapping

    def _try_load_from_datahub(self) -> bool:
        """从 canonical DataHub 股票主表读取行业映射。"""
        try:
            self._mapping.update(read_stock_industry_map())
            return bool(self._mapping)
        except (FileNotFoundError, OSError, ValueError) as exc:
            self.error = str(exc)
            return False

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
        """Reject parallel cache writes; DataHub owns the reference dataset."""
        raise RuntimeError("industry mapping is DataHub-owned and read-only")

    def to_dict(self) -> dict:
        """序列化为 JSON 可序列化 dict"""
        return {
            "mapping": self._mapping,
            "industry_count": self.get_industry_count(),
            "total_stocks": len(self._mapping),
            "industry_list": self.get_industry_list(),
            "status": self.status,
            "error": self.error,
        }


def quick_industry_map() -> dict[str, str]:
    """快速获取行业映射 (单行便捷函数)"""
    return IndustryMapper().get_industry_map()


if __name__ == "__main__":
    mapper = IndustryMapper()
    print(f"行业数量: {len(mapper.get_industry_list())}")
    print(f"股票数量: {len(mapper.get_industry_map())}")
    print(f"行业分布: {json.dumps(mapper.get_industry_count(), ensure_ascii=False, indent=2)}")
