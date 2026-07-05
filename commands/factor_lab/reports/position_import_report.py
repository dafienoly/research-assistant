"""Position Import Report — 持仓导入报告"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.broker.broker_position_adapter import STANDARD_FIELDS
from factor_lab.live.account_profile import get_board, is_self_tradable

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports/position_import")


def generate_import_report(source_result: dict, output_dir: str = None) -> dict:
    """生成持仓导入报告"""
    now = datetime.now(CST)
    run_id = now.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir or str(BASE / run_id))
    out_dir.mkdir(parents=True, exist_ok=True)

    positions = source_result.get("positions", [])
    cash = source_result.get("cash", 0.0)

    # 统计
    stocks = [p for p in positions if p.get("symbol","").upper() != "CASH" and not p.get("symbol","").startswith(("5", "1"))]
    etfs = [p for p in positions if p.get("symbol","").upper() != "CASH" and p.get("symbol","").startswith(("5", "1"))]
    stocks_main = [p for p in stocks if get_board(p.get("symbol","")) == "main"]
    stocks_restricted = [p for p in stocks if get_board(p.get("symbol","")) != "main"]

    total_value = sum(float(p.get("market_value", int(p.get("shares",0)) * float(p.get("current_price",1)))) for p in stocks + etfs)
    n_duplicate = len(positions) - len({p["symbol"] for p in positions if p.get("symbol")})

    report = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "source_used": source_result.get("source_used", "?"),
        "preferred_source": source_result.get("preferred_source", "?"),
        "fallback_used": source_result.get("fallback_used", False),
        "fallback_reason": source_result.get("fallback_reason", ""),
        "encoding_used": source_result.get("encoding_used", ""),
        "adapter_status": source_result.get("adapter_status", "?"),
        "status": source_result.get("status", "?"),
        "summary": {
            "total_positions": len(positions),
            "stocks": len(stocks),
            "etfs": len(etfs),
            "main_board_stocks": len(stocks_main),
            "restricted_board_stocks": len(stocks_restricted),
            "cash": round(cash, 2),
            "total_market_value": round(cash + total_value, 2),
            "duplicate_symbols": n_duplicate,
        },
        "warnings": source_result.get("adapter_warnings", []),
        "errors": source_result.get("adapter_errors", []),
        "field_map": source_result.get("field_map", {}),
    }

    # JSON
    with open(out_dir / "position_import.json", "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # normalized CSV
    from factor_lab.broker.broker_position_adapter import normalize_to_csv
    normalize_to_csv(positions, str(out_dir / "normalized_positions.csv"))

    # adapter_status.json
    with open(out_dir / "adapter_status.json", "w") as f:
        json.dump(source_result.get("source_status", {}), f, indent=2)

    # field_mapping_used.json
    with open(out_dir / "field_mapping_used.json", "w") as f:
        json.dump(report["field_map"], f, indent=2)

    # validation_errors.json
    with open(out_dir / "validation_errors.json", "w") as f:
        json.dump(report["errors"] + report["warnings"], f, indent=2)

    # HTML
    html = _build_html(report, now)
    with open(out_dir / "position_import_report.html", "w") as f:
        f.write(html)

    # audit
    with open(out_dir / "audit.log", "w") as f:
        f.write(f"=== POSITION IMPORT AUDIT ===\nRun: {run_id}\nSource: {report['source_used']}\nFallback: {report['fallback_used']}\nStocks: {report['summary']['stocks']}\nETF: {report['summary']['etfs']}\nCash: {report['summary']['cash']}\nNo auto-order: True\n=== END ===\n")

    return {"output_dir": str(out_dir), "report": report}


def _build_html(report, now):
    s = report["summary"]
    source = report["source_used"] or "none"
    fallback_note = f"<p style='color:#ff9100;'>Fallback: {report['fallback_reason']}</p>" if report["fallback_used"] else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>持仓导入报告</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card"><h1>📦 持仓导入报告</h1>
<p style="color:#aaa;">{now.strftime('%Y-%m-%d %H:%M:%S')}</p>
<p>Source: <strong>{source}</strong> | Encoding: {report.get('encoding_used','?')} | Status: {report['status']}</p>
{fallback_note}</div>
<div class="card"><h2>📊 摘要</h2>
<table>
<tr><td>总持仓</td><td class="num">{s['total_positions']}</td></tr>
<tr><td>股票</td><td class="num">{s['stocks']} (主板{s['main_board_stocks']} | 受限{s['restricted_board_stocks']})</td></tr>
<tr><td>ETF</td><td class="num">{s['etfs']}</td></tr>
<tr><td>现金</td><td class="num">{s['cash']:.0f}</td></tr>
<tr><td>总资产</td><td class="num">{s['total_market_value']:.0f}</td></tr>
<tr><td>重复 symbol</td><td class="num">{s['duplicate_symbols']}</td></tr>
</table></div>
{f'<div class="card"><h2>⚠️ Warnings</h2><ul>{"".join(f"<li>{w}</li>" for w in report.get("warnings",[]))}</ul></div>' if report.get('warnings') else ''}
<div class="card"><h2>📋 说明</h2>
<ul>
<li>不自动下单, 仅供 rebalance-diff 参考</li>
<li>标准化格式: {', '.join(STANDARD_FIELDS[:6])} ...</li>
</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.1.1 | {now.strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
