"""Export truthful VNext data recovery, gap and freshness artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .contracts import DataStatus, now_iso


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(pd.read_csv(path, encoding="utf-8-sig"))
    except (OSError, UnicodeError, pd.errors.ParserError):
        return 0


def _expected_stock_count(project_root: Path) -> tuple[int, str]:
    reference = project_root / "data/normalized/reference/stock_basic.csv"
    if reference.exists():
        try:
            frame = pd.read_csv(reference, encoding="utf-8-sig", dtype={"ts_code": str, "list_status": str})
            active = frame[frame["list_status"] == "L"] if "list_status" in frame else frame
            if not active.empty and "ts_code" in active:
                return len(active.drop_duplicates("ts_code")), "data/normalized/reference/stock_basic.csv:list_status=L"
        except (OSError, UnicodeError, pd.errors.ParserError):
            pass
    universes = _load_json(project_root / "data" / "universes.json")
    u0 = universes.get("universes", {}).get("U0", {})
    stocks = u0.get("stocks", []) if isinstance(u0, dict) else []
    return len(stocks), "data/universes.json:universes.U0.stocks"


def _dataset_coverage(
    project_root: Path,
    expected_stocks: int,
    expected_symbols: set[str],
) -> list[dict[str, Any]]:
    normalized = project_root / "data" / "normalized"
    market = normalized / "market"

    def _symbols(paths: list[Path], *, prefix: str = "") -> set[str]:
        symbols = set()
        for path in paths:
            stem = path.stem
            if prefix and stem.startswith(prefix):
                stem = stem[len(prefix) :]
            if stem:
                symbols.add(stem)
        return symbols

    definitions = [
        (
            "daily_kline",
            _symbols([path for path in market.glob("*.csv") if not path.name.startswith("valuation_")]),
            expected_stocks,
            str(market / "*.csv"),
        ),
        (
            "daily_valuation",
            _symbols(list(market.glob("valuation_*.csv")), prefix="valuation_"),
            expected_stocks,
            str(market / "valuation_*.csv"),
        ),
        (
            "stock_moneyflow",
            _symbols(list((normalized / "fund_flow").glob("*.csv"))),
            expected_stocks,
            str(normalized / "fund_flow" / "*.csv"),
        ),
        (
            "fina_indicator",
            _symbols(list((normalized / "fundamentals").glob("*.csv"))),
            expected_stocks,
            str(normalized / "fundamentals" / "*.csv"),
        ),
        (
            "concept_catalog",
            _row_count(normalized / "concept" / "concept_list.csv"),
            380,
            str(normalized / "concept" / "concept_list.csv"),
        ),
        (
            "industry_catalog",
            _row_count(normalized / "industry" / "industry_list.csv"),
            80,
            str(normalized / "industry" / "industry_list.csv"),
        ),
    ]
    coverage = []
    for dataset, observed, expected, source in definitions:
        is_symbol_dataset = isinstance(observed, set)
        if is_symbol_dataset:
            observed_symbols = observed
            matching_symbols = observed_symbols.intersection(expected_symbols)
            missing_symbols = sorted(expected_symbols - observed_symbols)
            extra_symbols = sorted(observed_symbols - expected_symbols)
            observed_count = len(observed_symbols)
            matched_count = len(matching_symbols)
            missing = len(missing_symbols)
            extra = len(extra_symbols)
        else:
            observed_count = observed
            matched_count = min(observed, expected)
            missing = max(expected - observed, 0)
            extra = max(observed - expected, 0)
            missing_symbols = []
            extra_symbols = []
        if observed_count == 0:
            status = DataStatus.MISSING.value
        elif missing:
            status = DataStatus.PARTIAL.value
        else:
            status = DataStatus.OK.value
        coverage.append(
            {
                "dataset": dataset,
                "status": status,
                "observed_files_or_rows": observed_count,
                "matched_expected_symbols": matched_count if is_symbol_dataset else None,
                "expected_files_or_rows": expected,
                "missing": missing,
                "extra": extra,
                "missing_symbols": missing_symbols,
                "extra_symbols": extra_symbols,
                "coverage_ratio": round(matched_count / expected, 6) if expected else None,
                "source": source,
            }
        )
    return coverage


def _recovery_runs(project_root: Path) -> dict[str, Any]:
    root = project_root / "data" / "audit" / "recovery" / "manifests"
    runs: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        payload = _load_json(path)
        entry_checks = []
        for symbol, entry in payload.get("entries", {}).items():
            output = Path(str(entry.get("output_path", ""))) if entry.get("output_path") else None
            expected_hash = entry.get("content_hash")
            actual_hash = _sha256(output) if output else None
            entry_checks.append(
                {
                    "symbol": symbol,
                    "status": entry.get("status"),
                    "output_hash_valid": bool(expected_hash and actual_hash == expected_hash),
                    "returned_rows": entry.get("returned_rows", 0),
                    "persisted_rows": entry.get("persisted_rows", 0),
                    "min_date": entry.get("min_date"),
                    "max_date": entry.get("max_date"),
                    "resume_hits": entry.get("resume_hits", 0),
                }
            )
        runs.append(
            {
                "run_id": payload.get("run_id"),
                "dataset": payload.get("dataset"),
                "status": payload.get("status"),
                "provider": payload.get("provider"),
                "api_name": payload.get("api_name"),
                "requested_start": payload.get("requested_start"),
                "requested_end": payload.get("requested_end"),
                "summary": payload.get("summary", {}),
                "resume_count": payload.get("resume_count", 0),
                "manifest_path": str(path),
                "manifest_sha256": _sha256(path),
                "entries": entry_checks,
            }
        )
    return {
        "manifest_count": len(runs),
        "verified_success_runs": sum(
            run.get("status") == "OK"
            and all(entry.get("output_hash_valid") for entry in run.get("entries", []))
            for run in runs
        ),
        "runs": runs,
    }


def export_vnext_data_audit(
    project_root: str | Path,
    *,
    as_of: str,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Create the three required PR-02 audit artifacts from real local state."""
    root = Path(project_root).resolve()
    destination = Path(output_root).resolve() if output_root else root / "artifacts" / "vnext"
    source_audit = root / "data" / "audit"
    source_gap_path = source_audit / "data_gap_report.json"
    source_freshness_path = source_audit / "data_freshness_report.json"
    source_gap = _load_json(source_gap_path)
    source_freshness = _load_json(source_freshness_path)
    expected_stocks, expected_source = _expected_stock_count(root)
    reference = root / "data/normalized/reference/stock_basic.csv"
    if reference.exists():
        frame = pd.read_csv(reference, encoding="utf-8-sig", dtype={"ts_code": str, "list_status": str})
        if "list_status" in frame:
            frame = frame[frame["list_status"] == "L"]
        expected_symbols = set(frame.get("ts_code", pd.Series(dtype=str)).dropna().astype(str))
    else:
        universes = _load_json(root / "data" / "universes.json")
        u0 = universes.get("universes", {}).get("U0", {})
        expected_symbols = {
            str(item.get("ts_code", "")).strip()
            for item in u0.get("stocks", [])
            if isinstance(item, dict) and str(item.get("ts_code", "")).strip()
        }
    coverage = _dataset_coverage(root, expected_stocks, expected_symbols)
    partial_datasets = [item["dataset"] for item in coverage if item["status"] != DataStatus.OK.value]
    core_datasets = {"daily_kline", "daily_valuation"}
    core_partial_datasets = [item for item in partial_datasets if item in core_datasets]
    auxiliary_partial_datasets = [item for item in partial_datasets if item not in core_datasets]
    structural_gaps = list(source_gap.get("gaps", []))
    gap_payload = {
        "schema_version": "1.0",
        "status": DataStatus.PARTIAL.value if partial_datasets or structural_gaps else DataStatus.OK.value,
        "as_of": as_of,
        "generated_at": now_iso(),
        "expected_a_share_stocks": expected_stocks,
        "expected_stock_source": expected_source,
        "coverage": coverage,
        "partial_datasets": partial_datasets,
        "core_partial_datasets": core_partial_datasets,
        "auxiliary_partial_datasets": auxiliary_partial_datasets,
        "auxiliary_gate_mode": "watch_only" if auxiliary_partial_datasets and not core_partial_datasets else "normal",
        "structural_gaps": structural_gaps,
        "source_report": str(source_gap_path),
        "source_report_sha256": _sha256(source_gap_path),
        "truthfulness": "exact U0 symbol-set coverage and source audit only; extra files cannot offset missing symbols",
    }

    freshness_blocking = bool(source_freshness.get("blocking", True))
    freshness_status = str(source_freshness.get("overall_status", "missing_files"))
    freshness_payload = {
        "schema_version": "1.0",
        "status": DataStatus.OK.value if freshness_status == "ok" and not freshness_blocking else DataStatus.STALE.value,
        "as_of": as_of,
        "generated_at": now_iso(),
        "overall_status": freshness_status,
        "blocking": freshness_blocking,
        "files": source_freshness.get("files", []),
        "source_check_time": source_freshness.get("check_time"),
        "source_report": str(source_freshness_path),
        "source_report_sha256": _sha256(source_freshness_path),
        "production_signal_eligible": not freshness_blocking and freshness_status == "ok",
    }

    recovery = _recovery_runs(root)
    snapshot_path = destination / "snapshot_manifest.json"
    snapshot = _load_json(snapshot_path)
    snapshot_ok = snapshot.get("status") == DataStatus.OK.value
    historical_research_ok = not core_partial_datasets and snapshot_ok
    production_ready = not partial_datasets and freshness_payload["status"] == DataStatus.OK.value and snapshot_ok
    audit_payload = {
        "schema_version": "1.0",
        "status": DataStatus.OK.value if production_ready else DataStatus.PARTIAL.value,
        "as_of": as_of,
        "generated_at": now_iso(),
        "data_gap_status": gap_payload["status"],
        "data_freshness_status": freshness_payload["status"],
        "immutable_snapshot_status": snapshot.get("status", DataStatus.MISSING.value),
        "immutable_snapshot_sha256": _sha256(snapshot_path),
        "recovery": recovery,
        "historical_research_eligible": historical_research_ok,
        "auxiliary_gate_mode": gap_payload["auxiliary_gate_mode"],
        "formal_ml_status": DataStatus.OK.value if historical_research_ok else DataStatus.BLOCKED.value,
        "shadow_status": DataStatus.OK.value if production_ready else DataStatus.BLOCKED.value,
        "order_draft_status": DataStatus.OK.value if production_ready else DataStatus.BLOCKED.value,
        "blocking_reasons": [
            reason
            for condition, reason in (
                (bool(core_partial_datasets), "core_data_gaps_remain"),
                (freshness_payload["status"] != DataStatus.OK.value, "critical_freshness_check_failed"),
                (not snapshot_ok, "immutable_snapshot_not_verified"),
            )
            if condition
        ],
        "warnings": ["auxiliary_data_gaps_watch_only"] if auxiliary_partial_datasets and not core_partial_datasets else [],
        "no_mock_or_fallback": True,
        "no_live_trade": True,
    }
    _atomic_json(destination / "data_gap_report.json", gap_payload)
    _atomic_json(destination / "data_freshness_report.json", freshness_payload)
    _atomic_json(destination / "data_audit_report.json", audit_payload)
    return audit_payload
