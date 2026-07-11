"""Real-data dataset builders for VNext policy backtests and ML ranking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import DataStatus, now_iso


def _atomic_metadata(path: Path, payload: dict[str, Any]) -> None:
    destination = path.with_suffix(path.suffix + ".metadata.json")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(destination)


class PolicyBacktestDatasetBuilder:
    """Build fixed/dynamic policy-hypothesis features without provider fallback."""

    INDEX_CODES = {
        "sse": "000001.SH",
        "csi300": "000300.SH",
        "csi500": "000905.SH",
        "csi1000": "000852.SH",
        "all_a": "000985.CSI",
    }
    FUND_CODES = {
        "semiconductor": "512480.SH",
        "technology": "515000.SH",
    }
    ANCHORS = ("002371.SZ", "688012.SH", "688256.SH", "688041.SH", "688126.SH", "600183.SH")

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.daily_root = self.project_root / "data" / "normalized" / "market"
        self.sources: list[dict[str, Any]] = []

    def build(self, start: str, end: str, output: str | Path) -> dict[str, Any]:
        index_frames = {
            name: self._query("index_daily", code, start.replace("-", ""), end.replace("-", ""))
            for name, code in self.INDEX_CODES.items()
        }
        fund_frames = {
            name: self._query("fund_daily", code, start.replace("-", ""), end.replace("-", ""))
            for name, code in self.FUND_CODES.items()
        }
        base = self._series(index_frames["sse"], "close").rename("sse_close").to_frame()
        if base.empty:
            return {
                "status": DataStatus.MISSING.value,
                "missing_evidence": ["datahub:index_daily:000001.SH"],
                "sources": self.sources,
            }
        sse = index_frames["sse"].set_index("trade_date").sort_index()
        for field in ("open", "high", "low", "close", "pct_chg", "amount"):
            if field in sse:
                base[f"sse_{field}"] = pd.to_numeric(sse[field], errors="coerce")
            else:
                base[f"sse_{field}"] = np.nan

        for name, frame in index_frames.items():
            close = self._series(frame, "close")
            if not close.empty:
                base[name] = close.pct_change()
            elif name not in base:
                base[name] = np.nan
        for name, frame in fund_frames.items():
            close = self._series(frame, "close")
            if not close.empty:
                base[name] = close.pct_change()
                volume = self._series(frame, "vol")
                if not volume.empty:
                    base[f"{name}_volume_ratio20"] = volume / volume.rolling(20).mean()
            else:
                base[name] = np.nan
            if f"{name}_volume_ratio20" not in base:
                base[f"{name}_volume_ratio20"] = np.nan

        breadth = self._breadth(start, end)
        base = base.join(breadth, how="left")
        for field in ("advancing", "declining"):
            if field not in base:
                base[field] = np.nan
        pool_equal = self._anchor_equal_return(start, end)
        if not pool_equal.empty:
            base["pool_equal"] = pool_equal
        else:
            base["pool_equal"] = np.nan
        base["semi_etf"] = base.get("semiconductor")
        base["cash"] = 0.0
        old_topn_path = self.project_root / "data" / "vnext" / "backtest-inputs" / "old_topn_returns.csv"
        if old_topn_path.exists():
            old = pd.read_csv(old_topn_path)
            if {"date", "return"}.issubset(old):
                old["date"] = pd.to_datetime(old["date"], errors="coerce")
                base["old_topn"] = old.set_index("date")["return"]
                self.sources.append({"source": str(old_topn_path), "status": DataStatus.OK.value, "records": len(old)})
        else:
            self.sources.append({"source": str(old_topn_path), "status": DataStatus.MISSING.value, "records": 0})

        base["decline_ratio"] = base["declining"] / (base["advancing"] + base["declining"])
        range_size = (base["sse_high"] - base["sse_low"]).replace(0, np.nan)
        base["index_reversal_strength"] = (base["sse_close"] - base["sse_low"]) / range_size
        base["semi_excess20"] = (1 + base["semiconductor"]).rolling(20).apply(np.prod, raw=True) - (
            (1 + base["csi300"]).rolling(20).apply(np.prod, raw=True)
        )
        base["technology_excess20"] = (1 + base["technology"]).rolling(20).apply(np.prod, raw=True) - (
            (1 + base["csi300"]).rolling(20).apply(np.prod, raw=True)
        )
        base["rolling_q20"] = base["sse_close"].rolling(120, min_periods=60).quantile(0.2)
        base["rolling_q80"] = base["sse_close"].rolling(120, min_periods=60).quantile(0.8)
        support_common = (
            (base["decline_ratio"] >= 0.65)
            & (base["index_reversal_strength"] >= 0.55)
            & (base["semi_excess20"] > 0)
        )
        base["policy_support_signal"] = (base["sse_close"] <= 3950) & support_common
        base["policy_support_dynamic_signal"] = (base["sse_close"] <= base["rolling_q20"]) & support_common
        base["breadth_divergence_signal"] = (
            (base["decline_ratio"] >= 0.70)
            & (base["sse_pct_chg"] > 0)
            & (base["semi_excess20"] > 0)
        )
        base["upper_box_risk_signal"] = (
            (base["sse_close"] >= 4050)
            & (base["semi_excess20"] < 0)
            & (base.get("semiconductor_volume_ratio20", pd.Series(index=base.index, dtype=float)) >= 1.0)
        )
        base["upper_box_dynamic_risk_signal"] = (
            (base["sse_close"] >= base["rolling_q80"])
            & (base["semi_excess20"] < 0)
        )

        attack = (base["policy_support_signal"] | base["policy_support_dynamic_signal"] | base["breadth_divergence_signal"])
        position = attack.rolling(5, min_periods=1).max().astype(float)
        position[base["upper_box_risk_signal"] | base["upper_box_dynamic_risk_signal"]] = 0.0
        base["strategy_position"] = position
        base["turnover"] = position.diff().abs().fillna(position.abs())
        base["strategy_return"] = position.shift(1).fillna(0.0) * base["semiconductor"]
        base["regime"] = self._regime(base["sse_close"])
        base.index.name = "date"
        base = base.loc[pd.Timestamp(start):pd.Timestamp(end)].reset_index()
        if base.empty:
            return {
                "status": DataStatus.MISSING.value,
                "missing_evidence": [f"no index rows in requested range: {start}..{end}"],
                "sources": self.sources,
            }

        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        base.to_csv(temporary, index=False, encoding="utf-8-sig")
        temporary.replace(destination)
        missing = [item["source"] for item in self.sources if item["status"] != DataStatus.OK.value]
        metadata = {
            "status": DataStatus.OK.value if not missing else DataStatus.PARTIAL.value,
            "retrieved_at": now_iso(),
            "date_range": [start, end],
            "records": len(base),
            "fields": list(base.columns),
            "sources": self.sources,
            "missing_evidence": missing,
            "lookahead_control": "strategy position is shifted one trading day before applying returns",
            "fixed_threshold_warning": "3900/3950/4050/4100/4200 are research hypotheses, not permanent rules",
        }
        _atomic_metadata(destination, metadata)
        return {**metadata, "output": str(destination)}

    def _query(self, api_name: str, code: str, start: str, end: str) -> pd.DataFrame:
        category = "index" if api_name == "index_daily" else "fund"
        path = self.project_root / "data/normalized/market_series" / category / f"{code}.csv"
        source = f"datahub:{api_name}:{code}"
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"trade_date": str})
            if not frame.empty and "trade_date" in frame:
                frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d", errors="coerce")
                frame = frame[
                    frame["trade_date"].between(pd.Timestamp(start), pd.Timestamp(end))
                ].sort_values("trade_date")
            self.sources.append({"source": source, "status": DataStatus.OK.value if not frame.empty else DataStatus.MISSING.value, "records": len(frame)})
            return frame
        except Exception as exc:
            self.sources.append({"source": source, "status": DataStatus.MISSING.value, "records": 0, "error": type(exc).__name__, "path": str(path)})
            return pd.DataFrame()

    @staticmethod
    def _series(frame: pd.DataFrame, field: str) -> pd.Series:
        if frame.empty or "trade_date" not in frame or field not in frame:
            return pd.Series(dtype=float)
        return pd.Series(pd.to_numeric(frame[field], errors="coerce").values, index=pd.to_datetime(frame["trade_date"]), dtype=float).sort_index()

    def _breadth(self, start: str, end: str) -> pd.DataFrame:
        files = [path for path in self.daily_root.glob("*.csv") if not path.name.startswith("valuation_")]
        usable = 0
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        buffer: list[pd.DataFrame] = []
        batch_counts: list[pd.DataFrame] = []

        def flush() -> None:
            if not buffer:
                return
            combined = pd.concat(buffer, ignore_index=True)
            combined["advancing"] = (combined["pct_chg"] > 0).astype("int32")
            combined["declining"] = (combined["pct_chg"] < 0).astype("int32")
            batch_counts.append(combined.groupby("trade_date")[["advancing", "declining"]].sum())
            buffer.clear()

        for path in files:
            try:
                frame = pd.read_csv(path, usecols=lambda column: column in {"trade_date", "pct_chg"}, encoding="utf-8-sig")
                if not {"trade_date", "pct_chg"}.issubset(frame):
                    continue
                frame["trade_date"] = pd.to_datetime(
                    frame["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True),
                    format="%Y%m%d",
                    errors="coerce",
                )
                frame["pct_chg"] = pd.to_numeric(frame["pct_chg"], errors="coerce")
                frame = frame[(frame["trade_date"] >= start_ts) & (frame["trade_date"] <= end_ts)].dropna()
                if frame.empty:
                    continue
                buffer.append(frame[["trade_date", "pct_chg"]])
                usable += 1
                if len(buffer) >= 250:
                    flush()
            except (OSError, ValueError):
                continue
        flush()
        self.sources.append({
            "source": str(self.daily_root),
            "status": DataStatus.OK.value if usable else DataStatus.MISSING.value,
            "records": usable,
            "metric": "historical_market_breadth",
        })
        if not batch_counts:
            return pd.DataFrame(columns=["advancing", "declining"], index=pd.DatetimeIndex([], name="trade_date"))
        return pd.concat(batch_counts).groupby(level=0).sum().sort_index()

    def _anchor_equal_return(self, start: str, end: str) -> pd.Series:
        series = []
        for symbol in self.ANCHORS:
            path = self.daily_root / f"{symbol}.csv"
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path, usecols=lambda column: column in {"trade_date", "close"}, encoding="utf-8-sig")
                frame["trade_date"] = pd.to_datetime(
                    frame["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True),
                    format="%Y%m%d",
                    errors="coerce",
                )
                before = len(frame)
                frame = frame.dropna(subset=["trade_date"]).drop_duplicates("trade_date", keep="last")
                duplicate_rows = before - len(frame)
                close = pd.Series(pd.to_numeric(frame["close"], errors="coerce").values, index=frame["trade_date"])
                series.append(close.pct_change().rename(symbol))
                if duplicate_rows:
                    self.sources.append({"source": f"datahub:daily:{symbol}", "status": DataStatus.PARTIAL.value, "duplicate_rows": duplicate_rows})
            except (OSError, ValueError, KeyError):
                continue
        if not series:
            self.sources.append({"source": "datahub:semiconductor_anchors", "status": DataStatus.MISSING.value, "records": 0})
            return pd.Series(dtype=float)
        frame = pd.concat(series, axis=1).loc[pd.Timestamp(start):pd.Timestamp(end)]
        self.sources.append({"source": "datahub:semiconductor_anchors", "status": DataStatus.OK.value, "records": len(frame)})
        return frame.mean(axis=1, skipna=True)

    @staticmethod
    def _regime(close: pd.Series) -> pd.Series:
        returns = close.pct_change()
        rolling_return = close / close.shift(60) - 1
        volatility = returns.rolling(20).std() * np.sqrt(252)
        result = pd.Series("RANGE_BOUND", index=close.index, dtype=object)
        result[rolling_return >= 0.10] = "BULL"
        result[rolling_return <= -0.10] = "BEAR"
        result[(volatility >= 0.30) & (returns <= -0.025)] = "LIQUIDITY_SHOCK"
        return result


class MLRankingDatasetBuilder:
    """Create point-in-time factor features and forward-return labels."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.daily_root = self.project_root / "data" / "normalized" / "market"

    def build(
        self,
        start: str,
        end: str,
        training_output: str | Path,
        scoring_output: str | Path,
        *,
        max_symbols: int | None = None,
    ) -> dict[str, Any]:
        files = sorted(path for path in self.daily_root.glob("*.csv") if not path.name.startswith("valuation_"))
        if max_symbols:
            files = files[:max_symbols]
        frames = []
        failed = []
        for path in files:
            try:
                frame = pd.read_csv(
                    path,
                    usecols=lambda column: column in {"ts_code", "trade_date", "close", "vol", "amount"},
                    encoding="utf-8-sig",
                )
                required = {"trade_date", "close"}
                if not required.issubset(frame):
                    failed.append(path.name)
                    continue
                frame["date"] = pd.to_datetime(frame["trade_date"].astype(str), errors="coerce")
                frame["symbol"] = frame.get("ts_code", path.stem)
                close = pd.to_numeric(frame["close"], errors="coerce")
                volume = pd.to_numeric(frame.get("vol"), errors="coerce") if "vol" in frame else pd.Series(np.nan, index=frame.index)
                amount = pd.to_numeric(frame.get("amount"), errors="coerce") if "amount" in frame else pd.Series(np.nan, index=frame.index)
                frame["ret5"] = close.pct_change(5)
                frame["ret20"] = close.pct_change(20)
                frame["reversal5"] = -frame["ret5"]
                frame["volatility20"] = close.pct_change().rolling(20).std()
                frame["price_to_ma20"] = close / close.rolling(20).mean() - 1
                frame["volume_ratio20"] = volume / volume.rolling(20).mean()
                frame["amount_log"] = np.log1p(amount.clip(lower=0))
                frame["forward_return"] = close.shift(-5) / close - 1
                frames.append(
                    frame[
                        [
                            "date", "symbol", "ret5", "ret20", "reversal5", "volatility20",
                            "price_to_ma20", "volume_ratio20", "amount_log", "forward_return",
                        ]
                    ]
                )
            except (OSError, ValueError, KeyError):
                failed.append(path.name)
        if not frames:
            return {
                "status": DataStatus.MISSING.value,
                "missing_evidence": ["real daily stock histories"],
                "files_seen": len(files),
            }
        dataset = pd.concat(frames, ignore_index=True)
        dataset = dataset[(dataset["date"] >= pd.Timestamp(start)) & (dataset["date"] <= pd.Timestamp(end))]
        feature_columns = [
            "ret5", "ret20", "reversal5", "volatility20", "price_to_ma20", "volume_ratio20", "amount_log",
        ]
        training = dataset.dropna(subset=feature_columns + ["forward_return"])
        latest_date = dataset["date"].dropna().max()
        scoring = dataset[dataset["date"] == latest_date].dropna(subset=feature_columns).drop(columns=["forward_return"])
        if training.empty:
            return {
                "status": DataStatus.MISSING.value,
                "missing_evidence": ["no complete point-in-time training rows in requested range"],
                "files_seen": len(files),
                "failed_files": failed[:100],
            }
        training_path, scoring_path = Path(training_output), Path(scoring_output)
        training_path.parent.mkdir(parents=True, exist_ok=True)
        scoring_path.parent.mkdir(parents=True, exist_ok=True)
        training.to_csv(training_path, index=False, encoding="utf-8-sig")
        scoring.to_csv(scoring_path, index=False, encoding="utf-8-sig")
        metadata = {
            "status": DataStatus.OK.value if not failed else DataStatus.PARTIAL.value,
            "retrieved_at": now_iso(),
            "source": str(self.daily_root),
            "symbols": int(training["symbol"].nunique()),
            "training_rows": len(training),
            "scoring_rows": len(scoring),
            "training_window": [start, end],
            "scoring_date": latest_date.date().isoformat() if pd.notna(latest_date) else None,
            "features": feature_columns,
            "target": "forward_return_5d",
            "point_in_time_controls": [
                "all features use current/past rows only",
                "label uses close.shift(-5) and is excluded from scoring output",
                "time split is enforced by CrossSectionalRanker.fit",
            ],
            "failed_files": failed[:100],
        }
        _atomic_metadata(training_path, metadata)
        _atomic_metadata(scoring_path, metadata)
        return {**metadata, "training_output": str(training_path), "scoring_output": str(scoring_path)}
