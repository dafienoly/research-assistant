"""Evidence-backed dynamic benchmark matching without synthetic fallback."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkMatch:
    primary: str | None
    secondary: list[str]
    reason: str
    evidence_source: str | None


class BenchmarkMatcher:
    def __init__(
        self,
        stock_sector_map: dict[str, dict] | None = None,
        etf_map: dict[str, dict] | None = None,
    ):
        self.stock_sector_map = stock_sector_map or {}
        self.etf_map = etf_map or {}

    def match_instrument(self, symbol: str, instrument_type: str) -> BenchmarkMatch:
        if instrument_type == "stock":
            row = self.stock_sector_map.get(symbol)
            if not row or not row.get("benchmark") or not row.get("source"):
                return BenchmarkMatch(None, [], "没有可验证的行业基准映射", None)
            return BenchmarkMatch(
                row["benchmark"],
                ["000300.SH"],
                "行业ETF/指数为主，沪深300为辅",
                row["source"],
            )
        row = self.etf_map.get(symbol)
        if not row or not row.get("tracked_index") or not row.get("source"):
            return BenchmarkMatch(None, [], "没有可验证的跟踪指数映射", None)
        secondary = [
            item
            for item in [row.get("peer_etf"), row.get("broad_index", "000300.SH")]
            if item
        ]
        return BenchmarkMatch(
            row["tracked_index"],
            secondary,
            "跟踪指数为主，同类ETF和宽基为辅",
            row["source"],
        )

    @staticmethod
    def match_portfolio(
        exposure_weights: dict[str, float], tradable: set[str]
    ) -> dict | None:
        usable = {
            symbol: weight
            for symbol, weight in exposure_weights.items()
            if symbol in tradable and weight > 0
        }
        total = sum(usable.values())
        if total <= 0:
            return None
        return {
            "components": {symbol: weight / total for symbol, weight in usable.items()},
            "method": "tradable_exposure_matched",
        }
