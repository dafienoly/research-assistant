"""Confirmed position ingestion from CSV, clipboard tables, OCR, and MiniQMT."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Book, Position, PositionDiff, PositionSnapshot
from .storage import DecisionLoopStore


ALIASES = {
    "symbol": {"symbol", "code", "证券代码", "股票代码", "代码"},
    "name": {"name", "证券名称", "股票名称", "名称"},
    "quantity": {"quantity", "volume", "持仓数量", "股票余额", "证券数量", "数量"},
    "available_quantity": {
        "available_quantity",
        "available",
        "可用数量",
        "可用余额",
        "可卖数量",
    },
    "cost_price": {"cost_price", "cost", "成本价", "成本"},
    "market_price": {"market_price", "price", "市价", "现价", "最新价"},
    "instrument_type": {"instrument_type", "type", "品种", "证券类型"},
    "book": {"book", "账簿", "周期仓"},
    "theme": {"theme", "主题", "行业"},
}


def _normalize_header(value: str) -> str:
    candidate = value.strip().lower().replace(" ", "_")
    for canonical, aliases in ALIASES.items():
        if candidate in {alias.lower().replace(" ", "_") for alias in aliases}:
            return canonical
    return candidate


def _number(value: Any, default: float = 0.0) -> float:
    cleaned = (
        str(value or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    )
    if not cleaned or cleaned in {"--", "-"}:
        return default
    return float(cleaned.rstrip("%"))


def _position_from_row(raw: dict[str, Any]) -> Position:
    row = {
        _normalize_header(str(key)): value
        for key, value in raw.items()
        if key is not None
    }
    symbol = re.sub(r"[^0-9A-Za-z.]", "", str(row.get("symbol", ""))).upper()
    if not symbol:
        raise ValueError("position row is missing symbol")
    quantity = int(_number(row.get("quantity")))
    available_raw = row.get("available_quantity")
    available = quantity if available_raw in (None, "") else int(_number(available_raw))
    instrument = str(row.get("instrument_type", "stock")).lower()
    if "etf" in instrument or "基金" in instrument:
        instrument = "etf"
    else:
        instrument = "stock"
    book_value = str(row.get("book", "swing")).lower()
    book_alias = {"催化": "catalyst", "波段": "swing", "核心": "core"}
    book_value = book_alias.get(book_value, book_value)
    return Position(
        symbol=symbol,
        name=str(row.get("name", "")),
        quantity=quantity,
        available_quantity=available,
        cost_price=_number(row.get("cost_price")),
        market_price=_number(row.get("market_price"))
        if row.get("market_price") not in (None, "")
        else None,
        instrument_type=instrument,
        book=Book(book_value),
        theme=str(row.get("theme", "unclassified")) or "unclassified",
    )


def parse_delimited(text: str) -> list[Position]:
    cleaned = text.strip("\ufeff\n\r ")
    if not cleaned:
        return []
    first = cleaned.splitlines()[0]
    delimiter = "\t" if first.count("\t") >= first.count(",") else ","
    reader = csv.DictReader(io.StringIO(cleaned), delimiter=delimiter)
    return [
        _position_from_row(row)
        for row in reader
        if any(str(value or "").strip() for value in row.values())
    ]


def parse_ocr_text(text: str) -> list[Position]:
    """Turn Tesseract's aligned whitespace table into the standard parser."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    normalized = []
    for line in lines:
        # Broker screenshots normally use compact single-token names/codes;
        # Tesseract does not preserve column spacing reliably, so every
        # whitespace run is treated as a column boundary.
        cells = line.split()
        normalized.append("\t".join(cells))
    return parse_delimited("\n".join(normalized))


def ocr_image(image_path: str | Path, timeout: int = 30) -> str:
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    completed = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "chi_sim+eng", "--psm", "6"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("OCR failed: " + completed.stderr.strip()[:300])
    return completed.stdout


class PositionIngestionService:
    def __init__(self, store: DecisionLoopStore | None = None):
        self.store = store or DecisionLoopStore()

    def preview_text(self, text: str, source: str = "clipboard") -> PositionDiff:
        if source not in {"csv", "clipboard", "manual", "miniqmt"}:
            raise ValueError("unsupported source")
        return self.preview_positions(parse_delimited(text), source)

    def preview_ocr(self, image_path: str | Path) -> PositionDiff:
        return self.preview_positions(parse_ocr_text(ocr_image(image_path)), "ocr")

    def preview_rows(
        self, rows: list[dict[str, Any]], source: str = "manual"
    ) -> PositionDiff:
        return self.preview_positions([_position_from_row(row) for row in rows], source)

    def preview_positions(self, positions: list[Position], source: str) -> PositionDiff:
        now = datetime.now().astimezone()
        normalized = sorted(positions, key=lambda item: (item.symbol, item.book.value))
        payload = [item.model_dump(mode="json") for item in normalized]
        content_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        snapshot = PositionSnapshot(
            snapshot_id=f"pos_{now:%Y%m%d_%H%M%S}_{content_hash[:8]}",
            as_of=now,
            source=source,
            positions=normalized,
            content_hash=content_hash,
        )
        current_raw = self.store.read_json("positions/current.json")
        current = PositionSnapshot.model_validate(current_raw) if current_raw else None
        old = (
            {(p.symbol, p.book.value): p for p in current.positions} if current else {}
        )
        new = {(p.symbol, p.book.value): p for p in normalized}
        additions = [new[key] for key in sorted(new.keys() - old.keys())]
        removals = [old[key] for key in sorted(old.keys() - new.keys())]
        changes = []
        compared_fields = (
            "quantity",
            "available_quantity",
            "cost_price",
            "market_price",
            "theme",
            "thesis",
            "invalidation",
        )
        for key in sorted(old.keys() & new.keys()):
            delta = {
                field: {
                    "old": getattr(old[key], field),
                    "new": getattr(new[key], field),
                }
                for field in compared_fields
                if getattr(old[key], field) != getattr(new[key], field)
            }
            if delta:
                changes.append({"symbol": key[0], "book": key[1], "fields": delta})
        preview = PositionDiff(
            preview_id=f"preview_{uuid.uuid4().hex}",
            created_at=now,
            source=source,
            additions=additions,
            removals=removals,
            changes=changes,
            unchanged=len(old.keys() & new.keys()) - len(changes),
            proposed_snapshot=snapshot,
        )
        self.store.write_json(
            f"positions/previews/{preview.preview_id}.json",
            preview.model_dump(mode="json"),
        )
        return preview

    def confirm(self, preview_id: str, expected_hash: str) -> PositionSnapshot:
        raw = self.store.read_json(f"positions/previews/{preview_id}.json")
        if not raw:
            raise KeyError("position preview not found")
        preview = PositionDiff.model_validate(raw)
        if preview.proposed_snapshot.content_hash != expected_hash:
            raise ValueError("preview hash mismatch; import must be previewed again")
        snapshot = preview.proposed_snapshot.model_copy(update={"confirmed": True})
        self.store.write_json(
            "positions/current.json", snapshot.model_dump(mode="json")
        )
        self.store.append_jsonl(
            "positions/history.jsonl", snapshot.model_dump(mode="json")
        )
        return snapshot

    def current(self) -> PositionSnapshot | None:
        raw = self.store.read_json("positions/current.json")
        return PositionSnapshot.model_validate(raw) if raw else None
