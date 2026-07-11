import json
import hashlib
from datetime import datetime

import pandas as pd

from factor_lab.datahub_ingestion.regulatory_events import RegulatoryEventIngestion
from factor_lab.risk.pretrade_risk_check import run_pretrade_risk_check
from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist
from factor_lab.risk.st_watchlist import STWatchlist
from announcement_parser import AnnouncementParser


def write_reference_manifest(source):
    payload = {
        "status": "OK",
        "generated_at": datetime.now().astimezone().isoformat(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "conflicts": [],
    }
    (source.parent / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def write_regulatory_manifest(source, status="OK"):
    payload = {
        "status": status,
        "generated_at": datetime.now().astimezone().isoformat(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "conflicts": [],
    }
    source.with_suffix(".manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_regulatory_ingestion_classifies_and_records_coverage(tmp_path):
    def fetcher(symbol):
        return [{
            "symbol": symbol, "title": "收到中国证监会立案调查通知",
            "date": "2026-07-10", "source": "cninfo", "id": "ann-1",
        }]

    payload = RegulatoryEventIngestion(tmp_path, fetcher).fetch(["688012.SH"])
    watchlist = RegulatoryWatchlist(tmp_path / "data/normalized/events/regulatory_watchlist.json")

    assert payload["status"] == "OK"
    assert watchlist.load_cache()
    assert watchlist.covers("688012.SH")
    assert not watchlist.covers("688072.SH")
    assert watchlist.is_blacklisted("688012.SH")
    assert payload["announcements"][0]["title"] == "收到中国证监会立案调查通知"


def test_pretrade_blocks_symbol_absent_from_regulatory_coverage(tmp_path):
    regulatory = tmp_path / "regulatory.json"
    regulatory.write_text(json.dumps({
        "status": "OK", "covered_symbols": ["688012"], "events": [],
    }), encoding="utf-8")
    write_regulatory_manifest(regulatory)
    stock_basic = tmp_path / "stock_basic.csv"
    stock_basic.write_text(
        "ts_code,symbol,name,list_status\n688012.SH,688012,中微公司,L\n688072.SH,688072,拓荆科技,L\n",
        encoding="utf-8",
    )
    write_reference_manifest(stock_basic)
    frame = pd.DataFrame([
        {"date": "2026-07-10", "symbol": "688072.SH", "close": 100, "volume": 1000},
    ])
    result = run_pretrade_risk_check(
        [{"symbol": "688072.SH"}], frame, "2026-07-10",
        st_watchlist=STWatchlist(stock_basic),
        regulatory_watchlist=RegulatoryWatchlist(regulatory),
    )

    assert "regulatory_truth_unavailable" in result["details"][0]["risk_type"]


def test_regulatory_ingestion_does_not_treat_provider_failure_as_empty_coverage(tmp_path):
    def failed_fetcher(_symbol):
        raise RuntimeError("all announcement sources failed")

    payload = RegulatoryEventIngestion(tmp_path, failed_fetcher).fetch(["688012.SH"])

    assert payload["status"] == "PARTIAL"
    assert payload["covered_symbols"] == []
    assert payload["failed_symbols"] == [{"symbol": "688012", "error": "RuntimeError"}]


def test_announcement_parser_reads_only_canonical_snapshot(tmp_path):
    snapshot = tmp_path / "regulatory_watchlist.json"
    snapshot.write_text(json.dumps({
        "covered_symbols": ["688012"],
        "announcements": [{
            "symbol": "688012", "date": "2026-07-10", "title": "重大合同公告",
            "source": "sse", "source_ref": "ann-2",
        }],
    }), encoding="utf-8")

    parsed = AnnouncementParser(snapshot).parse_for_stock("688012.SH")

    assert parsed[0]["announce_type"] == "重大合同"
    assert parsed[0]["announce_id"] == "ann-2"


def test_regulatory_watchlist_rejects_stale_or_tampered_snapshot(tmp_path):
    snapshot = tmp_path / "regulatory_watchlist.json"
    snapshot.write_text(
        json.dumps({"status": "OK", "covered_symbols": ["688012"], "events": []}),
        encoding="utf-8",
    )
    write_regulatory_manifest(snapshot)
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    tampered = RegulatoryWatchlist(snapshot)
    assert tampered.load_cache() is False
    assert "hash mismatch" in (tampered.error or "")

    write_regulatory_manifest(snapshot)
    manifest_path = snapshot.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generated_at"] = "2020-01-01T00:00:00+08:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    stale = RegulatoryWatchlist(snapshot)
    assert stale.load_cache() is False
    assert "stale" in (stale.error or "")
