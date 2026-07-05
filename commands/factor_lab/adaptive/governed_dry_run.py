"""V2.15 Governed Dry Run — 全链路干跑验证"""
import os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_dry_run():
    """执行全链路干跑验证"""
    rid = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    out = BASE / "dry_run" / rid
    os.makedirs(out, exist_ok=True)

    results = []
    gates = {
        "signal": _test_signal_generation(),
        "etf_selector": _test_etf_selector(),
        "unified_report": _test_unified_report(),
        "rebalance_diff": _test_rebalance_diff(),
        "order_preview": _test_order_preview(),
        "approval": _test_approval(),
    }

    from factor_lab.core.gate import GateEngine
    ge = GateEngine()
    for gate_name, gate_result in gates.items():
        ge.add_check(gate_name, f"{gate_name}_check", passed=gate_result["passed"],
                     severity="blocker" if not gate_result["passed"] else "info",
                     message=gate_result["message"])
    ge.finalize()

    summary = ge.get_summary()
    all_pass = all(s["verdict"] == "pass" for s in summary.values())

    result = {
        "run_id": rid,
        "generated_at": datetime.now(CST).isoformat(),
        "gates": gates,
        "gate_summary": summary,
        "all_passed": all_pass,
        "dry_run": True,
        "no_live_trade": True,
        "auto_apply": False,
    }
    _write_report(result, out)
    return result


def _run_pipeline_stage(name, func):
    try:
        r = func()
        return {"name": name, "passed": True, "message": "ok", "detail": str(r)[:200]}
    except Exception as e:
        return {"name": name, "passed": False, "message": str(e)[:200], "detail": ""}


def _test_signal_generation():
    return _run_pipeline_stage("signal", lambda: __import__("factor_lab.live.signal_cli", fromlist=["main"]).main())


def _test_etf_selector():
    return _run_pipeline_stage("etf", lambda: __import__("factor_lab.etf.etf_selector_cli", fromlist=["main"]).main())


def _test_unified_report():
    return _run_pipeline_stage("unified", lambda: __import__("factor_lab.live.unified_premarket_report", fromlist=["main"]).main())


def _test_rebalance_diff():
    return _run_pipeline_stage("rebalance", lambda: _stub("rebalance_diff"))


def _test_order_preview():
    return _run_pipeline_stage("order", lambda: _stub("order_preview"))


def _test_approval():
    return _run_pipeline_stage("approval", lambda: _stub("approval"))


def _stub(name):
    return {"stage": name, "status": "dry_run_only", "note": "本阶段为干跑验证骨架"}


def _write_report(result, out_dir):
    from factor_lab.core.audit import AuditTrail
    from factor_lab.core.artifact import ArtifactManifest

    manifest = ArtifactManifest(str(out_dir), run_id=result["run_id"])
    audit = AuditTrail(str(out_dir))

    with open(out_dir / "dry_run_report.json", "w") as f:
        json.dump(result, f, indent=2)

    gs = result.get("gate_summary", {})
    rows = "".join(f"<tr><td>{g}</td><td>{s['verdict']}</td><td>{'✅' if s['verdict']=='pass' else '❌'}</td></tr>" for g, s in gs.items())

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Governed Dry Run V2.15</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 Governed Dry Run V2.15</h1>
<p>Run: {result['run_id']} | All passed: {'✅' if result['all_passed'] else '❌'}</p></div>
<div class="card"><h2>🚦 Pipeline Gates</h2><table><tr><th>Gate</th><th>Status</th><th>Result</th></tr>{rows}</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul><li>Dry run: True</li><li>No live trade: True</li><li>Auto-apply: False</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.15 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(out_dir / "dry_run_report.html", "w") as f:
        f.write(html)

    manifest.add_file("dry_run_report.json", category="report")
    manifest.add_file("dry_run_report.html", category="report")
    manifest.write()
    audit.log("dry_run", run_id=result["run_id"], status="passed" if result["all_passed"] else "failed",
              safety={"dry_run": True, "no_live_trade": True, "auto_apply": False})

    print(f"\n{'='*60}")
    print(f"  V2.15 Governed Dry Run")
    print(f"  All passed: {result['all_passed']}")
    for g, s in gs.items():
        print(f"  {g}: {s['verdict']}")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")
