"""Build a VNext snapshot from authenticated Tushare and real local files."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import DataStatus, QualityStatus, Tradability, clamp, finite_number, now_iso, sha256_payload
from .providers import (
    ImmutableSnapshotStore,
    LocalCsvFetcher,
    ProviderQuery,
    ProviderRegistry,
    ProviderRouteResult,
    ProviderRouter,
    TushareFetcher,
)


ANCHORS = {
    "002371.SZ": "北方华创",
    "688012.SH": "中微公司",
    "688256.SH": "寒武纪",
    "688041.SH": "海光信息",
    "688126.SH": "沪硅产业",
    "600183.SH": "生益科技",
}


ASSET_PROXIES = {
    "semiconductor": ("512480.SH", "半导体ETF"),
    "technology": ("515000.SH", "科技ETF"),
    "star_chip": ("588200.SH", "科创芯片ETF"),
    "hong_kong_tech": ("513180.SH", "恒生科技ETF"),
    "dividend": ("510880.SH", "红利ETF"),
    "financial": ("510230.SH", "金融ETF"),
    "consumer": ("159928.SZ", "主要消费ETF"),
    "cyclical": ("512400.SH", "有色金属ETF"),
    "military": ("512660.SH", "军工ETF"),
    "ai_compute": ("515070.SH", "人工智能ETF"),
    "gold": ("518880.SH", "黄金ETF"),
    "bond": ("511010.SH", "国债ETF"),
    "nasdaq_proxy": ("513100.SH", "纳指ETF代理"),
}


STYLE_BASKETS = {
    "optical_modules": ("300308.SZ", "300502.SZ", "300394.SZ", "002281.SZ", "300570.SZ"),
    "pcb": ("600183.SH", "002463.SZ", "002916.SZ", "300476.SZ"),
}


class HubSnapshotBuilder:
    """No-fallback snapshot builder.

    A failed Tushare call or absent local file is recorded as ``MISSING``.  The
    builder never substitutes another provider or a generated time series.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        live_snapshot: str | Path | None = None,
        provider_router: ProviderRouter | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.data_root = self.project_root / "data"
        self.daily_root = self.data_root / "normalized" / "market"
        self.live_snapshot = Path(live_snapshot) if live_snapshot else Path(
            "/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/live_snapshot.csv"
        )
        self.source_statuses: list[dict[str, Any]] = []
        self.provider_route_summaries: list[dict[str, Any]] = []
        if provider_router is None:
            registry = ProviderRegistry()
            registry.register(TushareFetcher(self._client()))
            registry.register(LocalCsvFetcher([self.data_root, self.live_snapshot.parent]))
            provider_router = ProviderRouter(
                registry,
                ImmutableSnapshotStore(self.data_root / "vnext" / "provider-snapshots"),
            )
        self.provider_router = provider_router

    def build(self, as_of: str) -> dict[str, Any]:
        self.source_statuses = []
        self.provider_route_summaries = []
        target = pd.Timestamp(as_of)
        start = (target - pd.Timedelta(days=220)).strftime("%Y%m%d")
        end = target.strftime("%Y%m%d")
        index = self._fetch_index("000001.SH", start, end)
        funds = {role: self._fetch_fund(symbol, start, end) for role, (symbol, _) in ASSET_PROXIES.items()}
        live = self._load_live_snapshot(as_of)
        anchors = {symbol: self._load_local_daily(symbol, as_of) for symbol in ANCHORS}
        style_baskets = {
            role: {symbol: self._load_local_daily(symbol, as_of) for symbol in symbols}
            for role, symbols in STYLE_BASKETS.items()
        }

        index = index.sort_values("trade_date") if not index.empty and "trade_date" in index.columns else index
        current_index = finite_number(index.iloc[-1].get("close")) if not index.empty else None
        index_history = index.get("close", pd.Series(dtype=float)).dropna().astype(float).tolist()
        reversal = None
        if not index.empty:
            row = index.iloc[-1]
            high, low, close = (finite_number(row.get(name)) for name in ("high", "low", "close"))
            if high is not None and low is not None and close is not None and high > low:
                reversal = clamp((close - low) / (high - low))

        advancing = declining = None
        if not live.empty and "change_pct" in live.columns:
            changes = pd.to_numeric(live["change_pct"], errors="coerce").dropna()
            advancing = int((changes > 0).sum())
            declining = int((changes < 0).sum())

        index_ret = self._period_return(index, 20)
        semi_ret = self._period_return(funds["semiconductor"], 20)
        tech_ret = self._period_return(funds["technology"], 20)
        overseas_ret = self._period_return(funds["nasdaq_proxy"], 5)
        dividend_ret = self._period_return(funds["dividend"], 20)
        semiconductor_strength = self._relative_score(semi_ret, index_ret)
        technology_strength = self._relative_score(tech_ret, index_ret)
        defensive_strength = self._relative_score(dividend_ret, index_ret)
        anchor_scores = [self._relative_score(self._period_return(frame, 20), index_ret) for frame in anchors.values()]
        anchor_available = [value for value in anchor_scores if value is not None]
        anchor_support = float(np.mean(anchor_available)) if anchor_available else None
        subsector_breadth = (
            float(sum(value >= 0.5 for value in anchor_available) / len(anchor_available)) if anchor_available else None
        )
        semi_volume = self._volume_strength(funds["semiconductor"])
        liquidity = self._market_liquidity(live)
        breadth_score = (
            advancing / (advancing + declining)
            if advancing is not None and declining is not None and advancing + declining > 0
            else None
        )
        market_trend = self._trend_score(index)
        volatility = self._volatility_stress(index)
        distribution = self._distribution_risk(funds["semiconductor"])
        drawdown = self._drawdown_pressure(funds["semiconductor"])
        overseas_score = self._absolute_score(overseas_ret)

        style_returns = self._aligned_returns(funds)
        style_returns.update(self._basket_returns(style_baskets))
        style_dates = sorted({row["date"] for rows in style_returns.values() for row in rows})
        if style_dates:
            style_returns["cash"] = [{"date": day, "return": 0.0} for day in style_dates]
            self._record("assumption:cash-zero-daily-return", DataStatus.OK, len(style_dates), "explicit cash benchmark")
        candidates = self._build_candidates(anchors, funds)
        missing_sources = [item["source"] for item in self.source_statuses if item["status"] != DataStatus.OK.value]
        manifest_paths = sorted(
            {
                path
                for route in self.provider_route_summaries
                for path in route.get("snapshot_manifest_paths", [])
            }
        )
        data_snapshot_id = f"vnext-{as_of}-{sha256_payload(manifest_paths)[:20]}"
        return {
            "status": DataStatus.OK.value if not missing_sources else DataStatus.PARTIAL.value,
            "as_of": as_of,
            "data_snapshot_id": data_snapshot_id,
            "updated_at": now_iso(),
            "data_sources": [item["source"] for item in self.source_statuses],
            "source_statuses": self.source_statuses,
            "provider_routes": self.provider_route_summaries,
            "snapshot_manifest_paths": manifest_paths,
            "provider_conflicts": [
                conflict
                for route in self.provider_route_summaries
                for conflict in route.get("conflicts", [])
            ],
            "silent_fallback_used": False,
            "missing_evidence": missing_sources,
            "index_history": index_history,
            "current_index": current_index,
            "advancing": advancing,
            "declining": declining,
            "intraday_reversal_strength": reversal,
            "semiconductor_relative_strength": semiconductor_strength,
            "technology_relative_strength": technology_strength,
            "etf_abnormal_volume": semi_volume,
            "large_cap_tech_support": anchor_support,
            "technology_weakness": (1 - technology_strength) if technology_strength is not None else None,
            "etf_stall_volume": distribution,
            "style_rotation_away": defensive_strength,
            "semi_inputs": {
                "relative_strength": semiconductor_strength,
                "etf_volume_strength": semi_volume,
                "anchor_support": anchor_support,
                "subsector_breadth": subsector_breadth,
                "policy_support": None,
                "distribution_risk": distribution,
                "drawdown_pressure": drawdown,
                "liquidity_support": liquidity,
                "data_sources": [item["source"] for item in self.source_statuses],
            },
            "regime_inputs": {
                "market_trend": market_trend,
                "breadth": breadth_score,
                "liquidity": liquidity,
                "technology_strength": technology_strength,
                "semiconductor_strength": semiconductor_strength,
                "defensive_strength": defensive_strength,
                "policy_support": None,
                "overseas_tech_lead": overseas_score,
                "volatility_stress": volatility,
                "data_sources": [item["source"] for item in self.source_statuses],
            },
            "style_returns": style_returns,
            "portfolio_weights": self._default_weights(style_returns),
            "asset_exposures": self._asset_exposures(style_returns),
            "candidates": candidates,
        }

    def _client(self) -> Any:
        from factor_lab.data.tushare_client import get_ts_client

        return get_ts_client()

    def _fetch_index(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        source = f"tushare:index_daily:{symbol}"
        route = self.provider_router.route(
            ProviderQuery(
                dataset="index_daily",
                instrument_id=symbol,
                as_of=pd.Timestamp(end).strftime("%Y-%m-%d"),
                params={"api_name": "index_daily", "ts_code": symbol, "start_date": start, "end_date": end},
                required_fields=["trade_date", "close"],
            ),
            primary_provider="tushare",
        )
        frame = self._frame_from_route(route)
        self._record_route(source, route, len(frame))
        return self._normalise_date(frame)

    def _fetch_fund(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        source = f"tushare:fund_daily:{symbol}"
        route = self.provider_router.route(
            ProviderQuery(
                dataset="fund_daily",
                instrument_id=symbol,
                as_of=pd.Timestamp(end).strftime("%Y-%m-%d"),
                params={"api_name": "fund_daily", "ts_code": symbol, "start_date": start, "end_date": end},
                required_fields=["trade_date", "close"],
            ),
            primary_provider="tushare",
        )
        frame = self._frame_from_route(route)
        self._record_route(source, route, len(frame))
        return self._normalise_date(frame)

    def _load_live_snapshot(self, as_of: str) -> pd.DataFrame:
        source = f"local:{self.live_snapshot}"
        route = self.provider_router.route(
            ProviderQuery(
                dataset="live_snapshot",
                instrument_id="A_SHARE_ALL",
                as_of=as_of,
                params={"path": str(self.live_snapshot), "as_of_field": "update_time"},
                required_fields=["change_pct"],
            ),
            primary_provider="local_csv",
        )
        frame = self._frame_from_route(route)
        update = pd.to_datetime(frame.get("update_time"), errors="coerce") if not frame.empty else pd.Series(dtype="datetime64[ns]")
        stale = update.notna().any() and update.max().date() < pd.Timestamp(as_of).date()
        self._record_route(source, route, len(frame), force_stale=bool(stale))
        return frame

    def _load_local_daily(self, symbol: str, as_of: str) -> pd.DataFrame:
        path = self.daily_root / f"{symbol}.csv"
        source = f"local:{path}"
        route = self.provider_router.route(
            ProviderQuery(
                dataset="local_daily",
                instrument_id=symbol,
                as_of=as_of,
                params={"path": str(path), "as_of_field": "trade_date"},
                required_fields=["trade_date", "close"],
            ),
            primary_provider="local_csv",
        )
        frame = self._normalise_date(self._frame_from_route(route))
        self._record_route(source, route, len(frame))
        return frame

    @staticmethod
    def _frame_from_route(route: ProviderRouteResult) -> pd.DataFrame:
        data = route.primary.data
        return pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame([data])

    def _record_route(
        self,
        source: str,
        route: ProviderRouteResult,
        records: int,
        *,
        force_stale: bool = False,
    ) -> None:
        quality = route.primary.quality_status
        if force_stale:
            status = DataStatus.STALE
            message = "snapshot older than as_of"
        elif quality == QualityStatus.OK:
            status = DataStatus.OK
            message = ""
        elif quality == QualityStatus.MISSING:
            status = DataStatus.MISSING
            message = "; ".join(route.primary.warnings)
        else:
            status = DataStatus.PARTIAL
            message = "; ".join(route.primary.warnings)
        self._record(source, status, records, message)
        summary = route.to_dict()
        summary["primary"].pop("data", None)
        for alternative in summary.get("alternatives", []):
            alternative.get("envelope", {}).pop("data", None)
        self.provider_route_summaries.append(summary)

    def _record(self, source: str, status: DataStatus, records: int, message: str = "") -> None:
        self.source_statuses.append(
            {"source": source, "status": status.value, "records": int(records), "message": message, "checked_at": now_iso()}
        )

    @staticmethod
    def _normalise_date(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        result = frame.copy()
        for column in ("trade_date", "date", "timeString"):
            if column in result.columns:
                result["trade_date"] = pd.to_datetime(result[column].astype(str), errors="coerce")
                break
        return result.sort_values("trade_date") if "trade_date" in result.columns else result

    @staticmethod
    def _period_return(frame: pd.DataFrame, periods: int) -> float | None:
        if frame.empty or "close" not in frame.columns:
            return None
        values = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if len(values) <= periods:
            return None
        start = float(values.iloc[-periods - 1])
        return float(values.iloc[-1] / start - 1) if start > 0 else None

    @staticmethod
    def _relative_score(asset_return: float | None, benchmark_return: float | None) -> float | None:
        if asset_return is None or benchmark_return is None:
            return None
        return clamp(0.5 + 4.0 * (asset_return - benchmark_return))

    @staticmethod
    def _absolute_score(value: float | None) -> float | None:
        return None if value is None else clamp(0.5 + 5.0 * value)

    @staticmethod
    def _volume_strength(frame: pd.DataFrame) -> float | None:
        volume_column = "vol" if "vol" in frame.columns else ("volume" if "volume" in frame.columns else None)
        if frame.empty or volume_column is None:
            return None
        values = pd.to_numeric(frame[volume_column], errors="coerce").dropna()
        if len(values) < 20 or float(values.iloc[-20:-1].mean()) <= 0:
            return None
        ratio = float(values.iloc[-1] / values.iloc[-20:-1].mean())
        return clamp(ratio / 2.0)

    @staticmethod
    def _market_liquidity(frame: pd.DataFrame) -> float | None:
        if frame.empty or "amount" not in frame.columns:
            return None
        amounts = pd.to_numeric(frame["amount"], errors="coerce").dropna()
        if amounts.empty:
            return None
        positive = amounts[amounts > 0]
        if positive.empty:
            return None
        median = float(positive.median())
        return clamp(np.log10(max(median, 1.0)) / 10.0)

    @staticmethod
    def _trend_score(frame: pd.DataFrame) -> float | None:
        if frame.empty or "close" not in frame.columns:
            return None
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if len(close) < 60:
            return None
        ma20, ma60 = float(close.tail(20).mean()), float(close.tail(60).mean())
        if ma60 <= 0:
            return None
        return clamp(0.5 + 6 * (ma20 / ma60 - 1))

    @staticmethod
    def _volatility_stress(frame: pd.DataFrame) -> float | None:
        if frame.empty or "close" not in frame.columns:
            return None
        returns = pd.to_numeric(frame["close"], errors="coerce").pct_change().dropna().tail(60)
        if len(returns) < 20:
            return None
        annualized = float(returns.std(ddof=1) * np.sqrt(252))
        return clamp(annualized / 0.40)

    @staticmethod
    def _distribution_risk(frame: pd.DataFrame) -> float | None:
        if frame.empty or "close" not in frame.columns:
            return None
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if len(close) < 20:
            return None
        ret5 = float(close.iloc[-1] / close.iloc[-6] - 1)
        volume_score = HubSnapshotBuilder._volume_strength(frame)
        stall = clamp(0.5 - 5 * ret5)
        return clamp(0.6 * stall + 0.4 * (volume_score if volume_score is not None else 0.5))

    @staticmethod
    def _drawdown_pressure(frame: pd.DataFrame) -> float | None:
        if frame.empty or "close" not in frame.columns:
            return None
        close = pd.to_numeric(frame["close"], errors="coerce").dropna().tail(60)
        if len(close) < 10:
            return None
        drawdown = 1 - float(close.iloc[-1] / close.max())
        return clamp(drawdown / 0.20)

    @staticmethod
    def _aligned_returns(funds: dict[str, pd.DataFrame]) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        for role, frame in funds.items():
            if frame.empty or "close" not in frame.columns or "trade_date" not in frame.columns:
                continue
            clean = frame[["trade_date", "close"]].copy()
            clean["return"] = pd.to_numeric(clean["close"], errors="coerce").pct_change()
            output[role] = [
                {"date": row.trade_date.date().isoformat(), "return": float(row.return_)}
                for row in clean.rename(columns={"return": "return_"}).dropna().itertuples()
            ]
        return output

    @staticmethod
    def _basket_returns(baskets: dict[str, dict[str, pd.DataFrame]]) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        for role, members in baskets.items():
            series: list[pd.Series] = []
            for symbol, frame in members.items():
                if frame.empty or "close" not in frame.columns or "trade_date" not in frame.columns:
                    continue
                close = pd.Series(
                    pd.to_numeric(frame["close"], errors="coerce").values,
                    index=pd.to_datetime(frame["trade_date"], errors="coerce"),
                    name=symbol,
                )
                series.append(close.pct_change())
            if not series:
                continue
            equal_return = pd.concat(series, axis=1).mean(axis=1, skipna=True).dropna().sort_index()
            output[role] = [
                {"date": day.date().isoformat(), "return": float(value)}
                for day, value in equal_return.items()
            ]
        return output

    @staticmethod
    def _default_weights(style_returns: dict[str, Any]) -> dict[str, float]:
        desired = {
            "semiconductor": 0.35,
            "technology": 0.15,
            "hong_kong_tech": 0.10,
            "dividend": 0.12,
            "gold": 0.10,
            "bond": 0.10,
            "nasdaq_proxy": 0.08,
        }
        available = {name: weight for name, weight in desired.items() if name in style_returns}
        total = sum(available.values())
        return {name: weight / total for name, weight in available.items()} if total else {}

    @staticmethod
    def _asset_exposures(style_returns: dict[str, Any]) -> dict[str, dict[str, float]]:
        definitions = {
            "semiconductor": {"technology_beta": 0.95, "semiconductor_beta": 1.0},
            "technology": {"technology_beta": 1.0, "semiconductor_beta": 0.55},
            "star_chip": {"technology_beta": 0.95, "semiconductor_beta": 0.95},
            "hong_kong_tech": {"technology_beta": 0.85, "semiconductor_beta": 0.25},
            "dividend": {"technology_beta": 0.05, "semiconductor_beta": 0.0},
            "financial": {"technology_beta": 0.10, "semiconductor_beta": 0.0},
            "consumer": {"technology_beta": 0.15, "semiconductor_beta": 0.0},
            "cyclical": {"technology_beta": 0.05, "semiconductor_beta": 0.05},
            "military": {"technology_beta": 0.45, "semiconductor_beta": 0.20},
            "ai_compute": {"technology_beta": 1.0, "semiconductor_beta": 0.55},
            "optical_modules": {"technology_beta": 1.0, "semiconductor_beta": 0.50},
            "pcb": {"technology_beta": 0.90, "semiconductor_beta": 0.65},
            "gold": {"technology_beta": -0.05, "semiconductor_beta": -0.05},
            "bond": {"technology_beta": -0.10, "semiconductor_beta": -0.10},
            "nasdaq_proxy": {"technology_beta": 0.95, "semiconductor_beta": 0.45},
            "cash": {"technology_beta": 0.0, "semiconductor_beta": 0.0},
        }
        return {name: definitions[name] for name in style_returns if name in definitions}

    def _build_candidates(self, anchors: dict[str, pd.DataFrame], funds: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for symbol, name in ANCHORS.items():
            board = "STAR" if symbol.startswith("688") else "MAINBOARD"
            tradability = Tradability.RESTRICTED if board == "STAR" else Tradability.TRADABLE
            frame = anchors[symbol]
            close = finite_number(frame.iloc[-1].get("close")) if not frame.empty else None
            candidates.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "market": "A_SHARE",
                    "board": board,
                    "category": "restricted-board" if tradability == Tradability.RESTRICTED else "account-tradable",
                    "tradability": tradability.value,
                    "is_restricted": tradability == Tradability.RESTRICTED,
                    "is_etf_substitution": False,
                    "alternative_etf": "512480.SH" if tradability == Tradability.RESTRICTED else None,
                    "latest_price": close,
                    "factor_score": None,
                    "ml_rank_score": None,
                    "regime_applicability": None,
                    "mainline_fit": None,
                    "marginal_sharpe": None,
                    "liquidity_check": DataStatus.MISSING.value,
                    "price_limit_check": DataStatus.MISSING.value,
                    "st_suspension_check": DataStatus.MISSING.value,
                    "recommended_weight": None,
                    "risk_level": "HIGH" if tradability == Tradability.RESTRICTED else "UNASSESSED",
                    "data_source": f"local:{self.daily_root / (symbol + '.csv')}",
                }
            )
        for role in ("semiconductor", "star_chip", "technology"):
            symbol, name = ASSET_PROXIES[role]
            frame = funds[role]
            candidates.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "market": "A_SHARE_ETF",
                    "board": "ETF",
                    "category": "ETF-substitution",
                    "tradability": Tradability.ETF_SUBSTITUTION.value,
                    "is_restricted": False,
                    "is_etf_substitution": True,
                    "alternative_etf": None,
                    "latest_price": finite_number(frame.iloc[-1].get("close")) if not frame.empty else None,
                    "factor_score": None,
                    "ml_rank_score": None,
                    "regime_applicability": None,
                    "mainline_fit": None,
                    "marginal_sharpe": None,
                    "liquidity_check": DataStatus.MISSING.value,
                    "price_limit_check": DataStatus.MISSING.value,
                    "st_suspension_check": DataStatus.MISSING.value,
                    "recommended_weight": None,
                    "risk_level": "UNASSESSED",
                    "data_source": f"tushare:fund_daily:{symbol}",
                }
            )
        return candidates
