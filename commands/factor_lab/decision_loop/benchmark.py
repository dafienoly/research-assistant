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

    @classmethod
    def match_portfolio(
        cls,
        exposure_weights: dict[str, float],
        tradable: set[str],
        *,
        tradable_benchmarks: set[str] | None = None,
        instrument_types: dict[str, str] | None = None,
        matcher: "BenchmarkMatcher" | None = None,
    ) -> dict | None:
        """Map actual exposure to a verifiable, tradable mixed benchmark.

        ``tradable`` describes which exposure symbols are eligible for the
        portfolio.  ``tradable_benchmarks`` optionally narrows the benchmark
        instruments that can be traded; for backwards compatibility it falls
        back to ``tradable`` when omitted.  An unmapped exposure is retained
        in ``unmapped`` with its reason and never silently becomes its own
        benchmark.
        """
        if not exposure_weights:
            return None
        active_matcher = matcher or cls.from_durable_registry()
        benchmark_universe = set(tradable_benchmarks or tradable)
        instrument_types = instrument_types or {}
        components: dict[str, float] = {}
        evidence: dict[str, str] = {}
        unmapped: dict[str, str] = {}

        for raw_symbol, raw_weight in exposure_weights.items():
            symbol = str(raw_symbol).strip().upper()
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                continue
            if symbol not in tradable or weight <= 0:
                continue
            instrument_type = instrument_types.get(symbol) or cls._infer_instrument_type(symbol)
            match = active_matcher.match_instrument(symbol, instrument_type)
            candidates = [item for item in [match.primary, *match.secondary] if item]
            selected = next((item for item in candidates if item in benchmark_universe), None)
            if not selected:
                unmapped[symbol] = match.reason or "没有可交易的可靠基准映射"
                continue
            components[selected] = components.get(selected, 0.0) + weight
            if match.evidence_source:
                evidence[selected] = match.evidence_source

        total = sum(components.values())
        if total <= 0:
            return {
                "components": None,
                "method": "dynamic_exposure_mapped",
                "reason": "没有可交易的可靠基准映射",
                "unmapped": unmapped,
            }
        result = {
            "components": {symbol: round(weight / total, 8) for symbol, weight in components.items()},
            "method": "dynamic_exposure_mapped",
            "mapping_evidence": evidence,
        }
        if unmapped:
            result["unmapped"] = unmapped
        return result

    @staticmethod
    def _infer_instrument_type(symbol: str) -> str:
        code = symbol.split(".", 1)[0]
        return "etf" if code.startswith(("15", "16", "50", "51", "52", "56", "58")) else "stock"
