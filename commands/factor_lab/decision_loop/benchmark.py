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

    @classmethod
    def from_durable_registry(cls):
        """Build mappings only from exact stock tags and the persisted ETF registry."""
        from factor_lab.etf.etf_universe import (
            ETF_REGISTRY_PATH,
            STOCK_TO_THEME_PREFIX,
            load_etf_registry,
        )

        etfs = load_etf_registry()
        by_theme: dict[str, list[dict]] = {}
        for row in etfs:
            by_theme.setdefault(row.get("theme", ""), []).append(row)
        for rows in by_theme.values():
            rows.sort(key=lambda row: float(row.get("avg_amount_20d") or 0), reverse=True)
        stock_map = {}
        for code, theme in STOCK_TO_THEME_PREFIX.items():
            rows = by_theme.get(theme) or []
            if not rows:
                continue
            best = rows[0]
            exchange = best.get("exchange") or ("SH" if str(best["etf_code"]).startswith("5") else "SZ")
            stock_map[code] = {
                "benchmark": f"{best['etf_code']}.{exchange}",
                "source": f"exact_stock_theme+{ETF_REGISTRY_PATH}",
            }
            stock_map[f"{code}.SH"] = stock_map[code]
            stock_map[f"{code}.SZ"] = stock_map[code]
        etf_map = {}
        for row in etfs:
            code = str(row.get("etf_code", ""))
            if not code or not row.get("tracked_index"):
                continue
            exchange = row.get("exchange") or ("SH" if code.startswith("5") else "SZ")
            peers = [peer for peer in by_theme.get(row.get("theme", ""), []) if peer.get("etf_code") != code]
            peer_symbol = None
            if peers:
                peer_exchange = peers[0].get("exchange") or ("SH" if str(peers[0]["etf_code"]).startswith("5") else "SZ")
                peer_symbol = f"{peers[0]['etf_code']}.{peer_exchange}"
            entry = {
                "tracked_index": row["tracked_index"],
                "peer_etf": peer_symbol,
                "source": str(ETF_REGISTRY_PATH),
            }
            etf_map[code] = entry
            etf_map[f"{code}.{exchange}"] = entry
        return cls(stock_map, etf_map)

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
