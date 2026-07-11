#!/usr/bin/env python3
"""Generate non-handwritten capability/blocker documentation from runtime state."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "commands"))

from factor_lab.decision_loop.service import DecisionLoopService  # noqa: E402
from factor_lab.broker.qmt_client import QMTClient  # noqa: E402
from factor_lab.datahub_access import LIVE_SNAPSHOT_PATH  # noqa: E402
from factor_lab.datahub_access import ETF_HOLDINGS_PATH  # noqa: E402


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "MISSING"}


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    service = DecisionLoopService()
    status = service.status()
    data = read(ROOT / "artifacts/vnext/data_audit_report.json")
    integrity = read(ROOT / "data/audit/health/integrity.json")
    benchmark_projection = read(ROOT / "data/normalized/derived/benchmarks/manifest.json")
    live_snapshot = read(LIVE_SNAPSHOT_PATH.with_suffix(".manifest.json"))
    etf_holdings = read(ETF_HOLDINGS_PATH.with_suffix(".manifest.json"))
    regulatory_truth = read(ROOT / "data/normalized/events/regulatory_watchlist.json")
    corporate_events = read(ROOT / "data/normalized/events/corporate_events/manifest.json")
    certification = service.store.read_json("certification/latest.json", default={"status": "NOT_RUN"})
    qmt_response = QMTClient().health()
    qmt = qmt_response.get("data") if qmt_response.get("status") == "ok" else {}
    qmt_account_ready = bool(qmt.get("xttrader_connected"))
    qmt_reason = qmt.get("trader_error") or qmt_response.get("error") or "account and positions readable"
    lines = [
        "# Hermes 当前能力与阻断项（自动生成）",
        "",
        f"> 生成时间：{datetime.now().astimezone().isoformat()}。请勿手工编辑。",
        "",
        "| 能力 | 当前状态 | 证据 / 阻断 |",
        "|---|---|---|",
        f"| VNext 数据健康 | {data.get('status', 'MISSING')} | {'；'.join(data.get('blocking_reasons', [])) or '无'} |",
        f"| 行情行级完整性 | {integrity.get('status', 'MISSING')} | 问题文件={integrity.get('problematic_file_count', 'unknown')}，缺失活跃文件={len(integrity.get('missing_active_files', []))} |",
        f"| 动态基准投影 | {benchmark_projection.get('status', 'MISSING')} | canonical DataHub derived/benchmarks |",
        f"| 盘中 canonical 快照 | {live_snapshot.get('status', 'MISSING')} | rows={live_snapshot.get('rows', 0)}，observed_at={live_snapshot.get('observed_at', 'unknown')} |",
        f"| ETF 权重真值 | {etf_holdings.get('status', 'MISSING')} | rows={etf_holdings.get('rows', 0)}，etf_count={etf_holdings.get('etf_count', 0)} |",
        f"| 监管公告真值 | {regulatory_truth.get('status', 'MISSING')} | 缺失时 PreTrade BUY fail-closed |",
        f"| 公司事件真值 | {corporate_events.get('status', 'MISSING')} | forecast/holdertrade/repurchase/share_float/dividend |",
        f"| 真实确认持仓 | {'READY' if status.get('current_position_snapshot') else 'BLOCKED'} | {status.get('current_position_snapshot', {}).get('snapshot_id', 'confirmed snapshot missing') if status.get('current_position_snapshot') else 'confirmed snapshot missing'} |",
        f"| 日级授权 | {(status.get('daily_authorization') or {}).get('status', 'inactive')} | 收盘自动失效，参数/数据/审计/风险变化自动撤销 |",
        f"| 分钟决策周期 | {service.store.read_json('cycles/latest.json', default={'status': 'NOT_RUN'}).get('status')} | 统一 DecisionCycleResult + 周期锁 |",
        f"| QMT 只读账户/持仓 | {'OK' if qmt_account_ready else 'BLOCKED'} | {qmt_reason} |",
        f"| Paper/Shadow/Live 认证 | {'BLOCKED' if not certification.get('live_activation_allowed') else 'READY'} | live_activation_allowed={certification.get('live_activation_allowed', False)} |",
        f"| 实盘开关 | {'ON' if os.environ.get('QMT_LIVE_TRADING_ENABLED') == '1' else 'OFF'} | P0/Paper/Shadow/小额白名单完成前必须 OFF |",
        "",
        "## 当前阻断项",
        "",
    ]
    blockers = list(data.get("blocking_reasons", [])) + list(status.get("execution_readiness", {}).get("reasons", []))
    if integrity.get("status") != "OK":
        blockers.append("canonical_daily_integrity_not_ok")
    if regulatory_truth.get("status") not in {"OK", "EMPTY"}:
        blockers.append("regulatory_truth_unavailable")
    lines.extend([f"- {item}" for item in dict.fromkeys(blockers)] or ["- 无"])
    output = ROOT / "docs/generated/current_capabilities.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in (
        "events/events.jsonl",
        "execution/audit.jsonl",
        "notifications/delivery_receipts.jsonl",
        "notifications/acknowledgements.jsonl",
        "notifications/dead_letter.jsonl",
        "cycles/history.jsonl",
        "reviews/records.jsonl",
        "authorization/audit.jsonl",
        "positions/history.jsonl",
        "positions/rollback_audit.jsonl",
        "reconciliation/history.jsonl",
        "reconciliation/failure_history.jsonl",
        "parameters/candidates.jsonl",
        "parameters/weekly_candidates.jsonl",
        "parameters/audit.jsonl",
        "parameters/production_history.jsonl",
        "certification/history.jsonl",
    ):
        service.store.archive_jsonl(name, datetime.now().astimezone() - timedelta(days=90))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
