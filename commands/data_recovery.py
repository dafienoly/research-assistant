"""Crash-safe recovery manifests for long-running market-data pulls.

The ledger is intentionally independent of any provider implementation.  It
records what was requested and what was durably written, and only resumes a
completed item when the on-disk content still matches the recorded hash.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def frame_date_range(frame: pd.DataFrame) -> tuple[str | None, str | None]:
    """Return the best available min/max business date without inventing one."""
    for column in ("trade_date", "ann_date", "f_ann_date", "end_date", "date", "datetime"):
        if column not in frame.columns:
            continue
        text = frame[column].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
        if not parsed.notna().any():
            parsed = pd.to_datetime(frame[column], errors="coerce")
        if parsed.notna().any():
            return parsed.min().isoformat(), parsed.max().isoformat()
    return None, None


def atomic_write_frame(frame: pd.DataFrame, output_path: Path) -> str:
    """Write a CSV atomically and return the durable file content hash."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.replace(output_path)
    try:
        directory_fd = os.open(str(output_path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        # Some mounted filesystems do not support directory fsync.  The file
        # itself was already synced, and the limitation remains observable in
        # the host environment rather than changing data semantics.
        pass
    return file_sha256(output_path)


def merge_without_data_loss(new_frame: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    """Merge a response with existing valid history instead of truncating it."""
    if not output_path.exists():
        return new_frame.copy()
    try:
        existing = pd.read_csv(output_path, encoding="utf-8-sig", on_bad_lines="error")
    except (OSError, UnicodeError, pd.errors.ParserError):
        raise ValueError(f"existing output is unreadable: {output_path}") from None
    if existing.empty:
        return new_frame.copy()
    combined = pd.concat([existing, new_frame], ignore_index=True, sort=False)
    date_key = next(
        (column for column in ("trade_date", "end_date", "ann_date", "date") if column in combined.columns),
        None,
    )
    dedup_keys = [column for column in ("ts_code", date_key) if column and column in combined.columns]
    if dedup_keys:
        if "ts_code" in dedup_keys:
            combined["ts_code"] = combined["ts_code"].astype(str).str.strip()
        if date_key:
            raw_dates = combined[date_key].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
            compact_mask = raw_dates.str.fullmatch(r"\d{8}")
            compact = pd.to_datetime(raw_dates.where(compact_mask), format="%Y%m%d", errors="coerce")
            general = pd.to_datetime(raw_dates.where(~compact_mask), format="mixed", errors="coerce")
            parsed_dates = compact.fillna(general)
            combined[date_key] = parsed_dates.dt.strftime("%Y%m%d").where(parsed_dates.notna(), raw_dates)
        combined = combined.drop_duplicates(subset=dedup_keys, keep="last")
        combined = combined.sort_values(dedup_keys, kind="stable")
    else:
        combined = combined.drop_duplicates(keep="last")
    return combined.reset_index(drop=True)


@dataclass(frozen=True)
class ResumeRecord:
    reusable: bool
    rows: int = 0
    reason: str = "not_completed"


class RecoveryManifest:
    """Append-by-key batch state with an atomic checkpoint and final manifest."""

    schema_version = "1.0"

    def __init__(
        self,
        root: str | Path,
        *,
        dataset: str,
        provider: str,
        api_name: str,
        start: str,
        end: str,
        symbols: Iterable[str],
        batch_size: int,
        batch_sleep_seconds: float,
    ) -> None:
        self.root = Path(root)
        self.manifest_dir = self.root / "manifests"
        self.checkpoint_dir = self.root / "checkpoints"
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        normalized_symbols = list(dict.fromkeys(str(symbol) for symbol in symbols))
        identity = {
            "dataset": dataset,
            "provider": provider,
            "api_name": api_name,
            "start": start,
            "end": end,
            "symbols": normalized_symbols,
        }
        self.run_id = f"{dataset}-{_canonical_hash(identity)[:16]}"
        self.manifest_path = self.manifest_dir / f"{self.run_id}.json"
        self.checkpoint_path = self.checkpoint_dir / f"{self.run_id}.json"
        existing = self._read_existing()
        if existing:
            if existing.get("identity_hash") != _canonical_hash(identity):
                raise RuntimeError("recovery manifest identity mismatch")
            self.payload = existing
            self.payload["resumed_at"] = _utc_now()
            self.payload["resume_count"] = int(self.payload.get("resume_count", 0)) + 1
            self.payload["status"] = "RUNNING"
        else:
            now = _utc_now()
            self.payload = {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "identity_hash": _canonical_hash(identity),
                "dataset": dataset,
                "provider": provider,
                "api_name": api_name,
                "requested_start": start,
                "requested_end": end,
                "symbols": normalized_symbols,
                "requested_symbols": len(normalized_symbols),
                "batch_size": batch_size,
                "batch_sleep_seconds": batch_sleep_seconds,
                "rate_limit_owner": "provider_client",
                "retry_backoff_owner": "provider_client",
                "started_at": now,
                "updated_at": now,
                "resume_count": 0,
                "status": "RUNNING",
                "entries": {},
            }
        self._persist()

    def _read_existing(self) -> dict[str, Any] | None:
        candidate = self.checkpoint_path if self.checkpoint_path.exists() else self.manifest_path
        if not candidate.exists():
            return None
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        if candidate == self.checkpoint_path and isinstance(raw.get("payload"), dict):
            return raw["payload"]
        return raw

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.replace(path)

    def _persist(self) -> None:
        self.payload["updated_at"] = _utc_now()
        completed = sorted(
            symbol
            for symbol, entry in self.payload["entries"].items()
            if entry.get("status") == "SUCCESS"
        )
        checkpoint = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "identity_hash": self.payload["identity_hash"],
            "updated_at": self.payload["updated_at"],
            "completed_symbols": completed,
            "remaining_symbols": [symbol for symbol in self.payload["symbols"] if symbol not in completed],
            "payload": self.payload,
        }
        # Keep a full payload at the top level for backward-compatible recovery
        # from manifests, while the checkpoint additionally exposes cursors.
        self._atomic_json(self.manifest_path, self.payload)
        self._atomic_json(self.checkpoint_path, checkpoint)

    def resume_record(self, symbol: str, output_path: Path) -> ResumeRecord:
        entry = self.payload["entries"].get(symbol)
        if not entry or entry.get("status") != "SUCCESS":
            return ResumeRecord(False)
        if not output_path.exists():
            return ResumeRecord(False, reason="output_missing")
        expected_hash = str(entry.get("content_hash", ""))
        if not expected_hash or file_sha256(output_path) != expected_hash:
            return ResumeRecord(False, reason="output_hash_changed")
        entry["last_resume_verified_at"] = _utc_now()
        entry["resume_hits"] = int(entry.get("resume_hits", 0)) + 1
        self._persist()
        return ResumeRecord(True, rows=int(entry.get("returned_rows", 0)), reason="verified_success")

    def record_success(
        self,
        symbol: str,
        *,
        output_path: Path,
        rows: int,
        persisted_rows: int,
        min_date: str | None,
        max_date: str | None,
        content_hash: str,
        started_at: str,
    ) -> None:
        self.payload["entries"][symbol] = {
            "status": "SUCCESS",
            "request": {
                "symbol": symbol,
                "start": self.payload["requested_start"],
                "end": self.payload["requested_end"],
            },
            "started_at": started_at,
            "finished_at": _utc_now(),
            "returned_rows": rows,
            "persisted_rows": persisted_rows,
            "min_date": min_date,
            "max_date": max_date,
            "content_hash": content_hash,
            "output_path": str(output_path),
            "error": None,
            "resume_hits": 0,
        }
        self._persist()

    def record_missing(self, symbol: str, *, started_at: str) -> None:
        self.payload["entries"][symbol] = {
            "status": "MISSING",
            "request": {
                "symbol": symbol,
                "start": self.payload["requested_start"],
                "end": self.payload["requested_end"],
            },
            "started_at": started_at,
            "finished_at": _utc_now(),
            "returned_rows": 0,
            "min_date": None,
            "max_date": None,
            "content_hash": _canonical_hash([]),
            "output_path": None,
            "error": "provider returned no rows",
            "resume_hits": 0,
        }
        self._persist()

    def record_error(self, symbol: str, error: Exception, *, started_at: str) -> None:
        self.payload["entries"][symbol] = {
            "status": "ERROR",
            "request": {
                "symbol": symbol,
                "start": self.payload["requested_start"],
                "end": self.payload["requested_end"],
            },
            "started_at": started_at,
            "finished_at": _utc_now(),
            "returned_rows": 0,
            "min_date": None,
            "max_date": None,
            "content_hash": None,
            "output_path": None,
            "error": f"{type(error).__name__}: {str(error)[:300]}",
            "resume_hits": 0,
        }
        self._persist()

    def finish(self) -> Path:
        entries = self.payload["entries"]
        statuses = [entry.get("status") for entry in entries.values()]
        if len(entries) != self.payload["requested_symbols"] or any(status == "ERROR" for status in statuses):
            status = "PARTIAL"
        elif statuses and all(item == "MISSING" for item in statuses):
            status = "MISSING"
        elif any(item == "MISSING" for item in statuses):
            status = "PARTIAL"
        else:
            status = "OK"
        self.payload["status"] = status
        self.payload["finished_at"] = _utc_now()
        self.payload["summary"] = {
            "success": sum(item == "SUCCESS" for item in statuses),
            "missing": sum(item == "MISSING" for item in statuses),
            "error": sum(item == "ERROR" for item in statuses),
            "rows": sum(int(entry.get("returned_rows", 0)) for entry in entries.values()),
        }
        self._persist()
        return self.manifest_path
