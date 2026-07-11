"""Materialize factor inputs from canonical DataHub datasets.

This is the only owner of the legacy wide factor-input projections.  It does
not fetch providers: fundamentals, fund flow and announcement sentiment are
derived from already-published canonical snapshots, then atomically published
with one coverage manifest.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_recovery import atomic_write_frame
from factor_lab.datahub_ingestion.event_truth import EventTruthIngestion


POSITIVE_TERMS = (
    "中标", "增长", "盈利", "突破", "签约", "订单", "合作", "回购", "增持",
    "分红", "获批", "投产", "量产", "交付", "激励",
)
NEGATIVE_TERMS = (
    "减持", "亏损", "风险", "违规", "处罚", "调查", "立案", "退市", "警示函",
    "监管函", "问询函", "诉讼", "仲裁", "冻结", "破产",
)


class FactorInputProjection:
    """Project normalized DataHub snapshots into factor-engine wide tables."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root).resolve()
        self.normalized = self.root / "data/normalized"
        self.outputs = {
            "fundamentals": self.root / "data/fundamentals/fundamentals_timeseries.csv",
            "fund-flow": self.root / "data/fundamentals/fund_flow_timeseries.csv",
            "sentiment": self.root / "data/news_sentiment_timeseries.csv",
        }
        self.manifest_path = self.root / "data/audit/manifests/factor_input_projection.json"

    def build(self, target: str) -> dict[str, Any]:
        builders = {
            "fundamentals": self._fundamentals,
            "fund-flow": self._fund_flow,
            "sentiment": self._sentiment,
        }
        if target not in builders:
            raise ValueError(f"unknown factor input target: {target}")
        frame, evidence = builders[target]()
        if frame.empty and not evidence.get("verified_empty"):
            return self._record(target, "BLOCKED", 0, evidence=evidence)
        content_hash = atomic_write_frame(frame, self.outputs[target])
        status = "EMPTY" if frame.empty else "OK"
        return self._record(target, status, len(frame), sha256=content_hash, evidence=evidence)

    def _fundamentals(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        frames: list[pd.DataFrame] = []
        files = sorted((self.normalized / "fundamentals").glob("*.csv"))
        for path in files:
            source = pd.read_csv(path, encoding="utf-8-sig", dtype={"ts_code": "string"})
            if source.empty or not {"ts_code", "end_date", "ann_date"}.issubset(source.columns):
                continue
            result = pd.DataFrame({
                "symbol": source["ts_code"].astype("string").str.extract(r"(\d{6})", expand=False),
                "report_date": source["end_date"],
                "pub_date": source["ann_date"],
            })
            aliases = {
                "roe": "roe",
                "netprofit_margin": "net_margin",
                "grossprofit_margin": "gross_margin",
                "debt_to_assets": "debt_ratio",
                "eps": "eps",
                "current_ratio": "current_ratio",
                "assets_turn": "asset_turnover",
                "roa": "roa_ttm",
            }
            for source_name, output_name in aliases.items():
                if source_name in source:
                    result[output_name] = source[source_name]
            frames.append(result)
        columns = ["symbol", "report_date", "pub_date", "roe", "net_margin", "gross_margin", "debt_ratio", "eps"]
        if not frames:
            return pd.DataFrame(columns=columns), {"reason": "canonical_fundamentals_missing", "input_files": 0}
        combined = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "report_date", "pub_date"])
        combined = combined.sort_values(["symbol", "pub_date", "report_date"], kind="stable")
        combined = combined.drop_duplicates(["symbol", "report_date"], keep="last")
        return combined, {"input_files": len(files), "source": "normalized/fundamentals"}

    def _fund_flow(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        frames: list[pd.DataFrame] = []
        files = sorted((self.normalized / "fund_flow").glob("*.csv"))
        for path in files:
            source = pd.read_csv(path, encoding="utf-8-sig", dtype={"ts_code": "string"}, low_memory=False)
            required = {"ts_code", "trade_date", "net_mf_amount"}
            if source.empty or not required.issubset(source.columns):
                continue
            result = pd.DataFrame({
                "symbol": source["ts_code"].astype("string").str.extract(r"(\d{6})", expand=False),
                "date": source["trade_date"],
                "net_main_force": source["net_mf_amount"],
            })
            for prefix, output in (
                ("elg", "net_super_large"), ("lg", "net_large"),
                ("md", "net_medium"), ("sm", "net_small"),
            ):
                buy, sell = f"buy_{prefix}_amount", f"sell_{prefix}_amount"
                if buy in source and sell in source:
                    result[output] = pd.to_numeric(source[buy], errors="coerce") - pd.to_numeric(source[sell], errors="coerce")
            frames.append(result)
        columns = ["symbol", "date", "net_main_force", "net_super_large", "net_large", "net_medium", "net_small"]
        if not frames:
            return pd.DataFrame(columns=columns), {"reason": "canonical_fund_flow_missing", "input_files": 0}
        combined = pd.concat(frames, ignore_index=True).dropna(subset=["symbol", "date"])
        combined = combined.sort_values(["symbol", "date"], kind="stable").drop_duplicates(["symbol", "date"], keep="last")
        return combined, {"input_files": len(files), "source": "normalized/fund_flow"}

    def _sentiment(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        source_path = self.normalized / "events/regulatory_watchlist.json"
        if not source_path.exists():
            return self._empty_sentiment(), {"reason": "regulatory_snapshot_missing"}
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if payload.get("status") not in {"OK", "EMPTY"}:
            return self._empty_sentiment(), {"reason": "regulatory_snapshot_not_healthy", "status": payload.get("status")}
        rows = []
        for item in payload.get("announcements", []):
            title = str(item.get("title", ""))
            positive = sum(term in title for term in POSITIVE_TERMS)
            negative = sum(term in title for term in NEGATIVE_TERMS)
            total = positive + negative
            score = (positive - negative) / total if total else 0.0
            rows.append({
                "symbol": str(item.get("symbol", ""))[:6],
                "date": str(item.get("date", "")).replace("-", ""),
                "sentiment_score": score,
                "sentiment_label": "positive" if score > 0.2 else "negative" if score < -0.2 else "neutral",
                "positive_count": positive,
                "negative_count": negative,
                "neutral_count": int(total == 0),
            })
        frame = pd.DataFrame(rows, columns=self._empty_sentiment().columns)
        if not frame.empty:
            frame = frame.dropna(subset=["symbol", "date"]).sort_values(["symbol", "date"], kind="stable")
            frame = frame.drop_duplicates(["symbol", "date"], keep="last")
        return frame, {
            "verified_empty": not rows,
            "source": "normalized/events/regulatory_watchlist.json",
            "covered_symbols": payload.get("covered_symbols", []),
        }

    @staticmethod
    def _empty_sentiment() -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "symbol", "date", "sentiment_score", "sentiment_label",
            "positive_count", "negative_count", "neutral_count",
        ])

    def _record(
        self,
        target: str,
        status: str,
        rows: int,
        *,
        sha256: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self._read_manifest()
        result = {
            "status": status,
            "rows": rows,
            "path": str(self.outputs[target].relative_to(self.root)),
            "sha256": sha256,
            "observed_at": datetime.now().astimezone().isoformat(),
            "source": "canonical_datahub_projection",
            "evidence": evidence or {},
        }
        manifest.update({"generated_at": result["observed_at"], "datasets": {**manifest.get("datasets", {}), target: result}})
        EventTruthIngestion._atomic_json(self.manifest_path, manifest)
        return result

    def _read_manifest(self) -> dict[str, Any]:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"schema_version": 1, "datasets": {}}
