"""Ingest — 实时行情摄取引擎 (V5.2)

RealtimeQuoteEngine orchestrates the realtime quote ingestion pipeline:

  1. Resolves the best available source via DataRegistry
  2. Attempts fetch through the corresponding adapter
  3. Falls back through the registry's fallback chain on failure
  4. Records health telemetry via HealthTracker
  5. Returns a structured BatchQuoteResult

Usage:
    engine = RealtimeQuoteEngine()
    result = engine.fetch_quotes(["688012", "002371"])
    if result.success_count > 0:
        quote = result.results["688012"].quote
        print(f"{quote.symbol}: {quote.price}")
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.health import HealthTracker
from factor_lab.data_source.discovery import get_fallback_chain, resolve_source
from factor_lab.data_source.spec import DataSourceCapability, DataSourceStatus
from factor_lab.data_source.quote import Quote, QuoteResult, BatchQuoteResult
from factor_lab.data_source.adapters import get_adapter, list_adapters


CST = timezone(timedelta(hours=8))


class RealtimeQuoteEngine:
    """实时行情摄取引擎

    Orchestrates the realtime quote fetch pipeline with automatic
    source discovery, fallback, and health tracking.

    Attributes:
        registry:       DataRegistry instance
        health:         HealthTracker instance
        default_cap:    capability string for source resolution
    """

    def __init__(
        self,
        registry: Optional[DataRegistry] = None,
        health_tracker: Optional[HealthTracker] = None,
    ):
        self.registry = registry or DataRegistry()
        self.health = health_tracker or HealthTracker(self.registry)
        self.default_cap = DataSourceCapability.REALTIME_QUOTE.value

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_quote(
        self,
        symbol: str,
        preferred_source: Optional[str] = None,
        fallback: bool = True,
    ) -> QuoteResult:
        """获取单只股票实时行情

        Args:
            symbol:           6位股票代码
            preferred_source: 优先使用的数据源ID
            fallback:         是否启用自动降级 (默认 True)

        Returns:
            QuoteResult
        """
        results = self.fetch_quotes(
            [symbol],
            preferred_source=preferred_source,
            fallback=fallback,
        )
        return results.get(symbol, QuoteResult(
            symbol=symbol, success=False, error="no_result",
        ))

    def fetch_quotes(
        self,
        symbols: list[str],
        preferred_source: Optional[str] = None,
        fallback: bool = True,
    ) -> dict[str, QuoteResult]:
        """批量获取实时行情，含自动降级

        Strategy:
          1. If preferred_source given, try it first.
          2. Otherwise resolve best source from registry.
          3. If fallback enabled, walk the fallback chain on failure.

        Args:
            symbols:          股票代码列表
            preferred_source: 优先使用的数据源ID
            fallback:         是否启用自动降级

        Returns:
            dict[symbol -> QuoteResult]
        """
        t_start = time.time()

        # Determine the source order to try
        source_chain = self._build_source_chain(preferred_source, fallback)

        if not source_chain:
            return self._all_failed(symbols, "no_available_source", t_start)

        # Attempt each source in order; first one that returns data wins
        used_fallback = False
        last_error: Optional[str] = None
        raw_data: dict[str, dict] = {}
        success_source: Optional[str] = None

        for idx, source_id in enumerate(source_chain):
            adapter = get_adapter(source_id)
            if adapter is None:
                self._record_outcome(source_id, False, 0, "no_adapter")
                continue

            try:
                t_fetch = time.time()
                raw = adapter.fetch(symbols)
                fetch_ms = (time.time() - t_fetch) * 1000

                if raw:
                    raw_data = raw
                    success_source = source_id
                    used_fallback = idx > 0
                    self._record_outcome(source_id, True, fetch_ms)
                    break
                else:
                    last_error = f"{source_id} returned empty"
                    self._record_outcome(source_id, False, fetch_ms, last_error)
            except Exception as exc:
                last_error = f"{source_id}: {exc}"
                self._record_outcome(source_id, False, 0, str(exc)[:200])

        total_ms = (time.time() - t_start) * 1000

        # Build per-symbol results
        results: dict[str, QuoteResult] = {}
        if success_source and raw_data:
            chain_used = source_chain[:source_chain.index(success_source) + 1]
            for sym in symbols:
                if sym in raw_data:
                    raw_item = raw_data[sym]
                    raw_item.pop("_latency_ms", None)
                    quote = Quote(
                        symbol=sym,
                        source_id=success_source,
                        timestamp=datetime.now(CST).isoformat(),
                        **{k: raw_item[k] for k in (
                            "name", "price", "open", "high", "low",
                            "volume", "amount", "change_pct", "change_amount",
                            "prev_close", "amplitude", "turnover_rate",
                        ) if k in raw_item and raw_item[k] is not None},
                    )
                    lat = raw_data[sym].get("_latency_ms", total_ms)
                    results[sym] = QuoteResult(
                        symbol=sym, success=True, quote=quote,
                        source_id=success_source, latency_ms=round(lat, 1),
                        fallback_used=used_fallback,
                        fallback_chain=chain_used,
                    )
                else:
                    results[sym] = QuoteResult(
                        symbol=sym, success=False,
                        error=f"symbol_not_in_{success_source}_response",
                        source_id=success_source, latency_ms=round(total_ms, 1),
                        fallback_used=used_fallback,
                        fallback_chain=source_chain,
                    )
        else:
            # All sources failed
            for sym in symbols:
                results[sym] = QuoteResult(
                    symbol=sym, success=False,
                    error=last_error or "all_sources_failed",
                    source_id=source_chain[0] if source_chain else "none",
                    latency_ms=round(total_ms, 1),
                    fallback_chain=source_chain,
                )

        return results

    def fetch_batch(
        self,
        symbols: list[str],
        preferred_source: Optional[str] = None,
        fallback: bool = True,
    ) -> BatchQuoteResult:
        """批量获取并以 BatchQuoteResult 返回

        Convenience wrapper around fetch_quotes that packs the
        result into a BatchQuoteResult with summary statistics.
        """
        t_start = time.time()
        results = self.fetch_quotes(symbols, preferred_source, fallback)
        total_ms = (time.time() - t_start) * 1000

        return BatchQuoteResult(
            symbols=symbols,
            results=results,
            total_latency_ms=round(total_ms, 1),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_source_chain(
        self,
        preferred_source: Optional[str],
        fallback: bool,
    ) -> list[str]:
        """构建待尝试的数据源顺序列表"""
        chain: list[str] = []

        if preferred_source:
            # Check preferred source exists in registry
            spec = self.registry.get_source(preferred_source)
            if spec and self.default_cap in spec.capabilities:
                chain.append(preferred_source)

        if fallback:
            fallback_specs = get_fallback_chain(self.default_cap)
            for fs in fallback_specs:
                if fs.source_id not in chain:
                    chain.append(fs.source_id)

        if not chain and not preferred_source:
            # No fallback, no preferred — just try the best source
            best = resolve_source(self.default_cap)
            if best:
                chain.append(best.source_id)

        return chain

    def _record_outcome(
        self,
        source_id: str,
        success: bool,
        latency_ms: float,
        error: str = "",
    ):
        """向 HealthTracker 记录调用结果"""
        try:
            self.health.record_call(
                source_id=source_id,
                success=success,
                latency_ms=latency_ms,
                error=error,
            )
        except Exception:
            pass  # health tracking failure must not break ingestion

    def _all_failed(
        self,
        symbols: list[str],
        reason: str,
        t_start: float,
    ) -> dict[str, QuoteResult]:
        """所有符号均失败时的快速路径"""
        total_ms = (time.time() - t_start) * 1000
        return {
            sym: QuoteResult(
                symbol=sym, success=False, error=reason,
                latency_ms=round(total_ms, 1),
            )
            for sym in symbols
        }
