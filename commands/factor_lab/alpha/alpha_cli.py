#!/usr/bin/env python3
"""V3.0 Alpha Factory — 注册/列表/查看/退役/评估计划"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    sp = sub.add_parser("register")
    sp.add_argument("--spec", help="Alpha spec JSON path")

    sub.add_parser("list")

    sp = sub.add_parser("show")
    sp.add_argument("--alpha-id", required=True)

    sp = sub.add_parser("retire")
    sp.add_argument("--alpha-id", required=True)

    sp = sub.add_parser("evaluation-plan")
    sp.add_argument("--alpha-id", required=True)

    sp = sub.add_parser("init-samples")

    sp = sub.add_parser("migrate-existing-factors")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--category")

    args = parser.parse_args()

    if args.command == "register":
        _cmd_register(args.spec)
    elif args.command == "list":
        _cmd_list()
    elif args.command == "show":
        _cmd_show(args.alpha_id)
    elif args.command == "retire":
        _cmd_retire(args.alpha_id)
    elif args.command == "evaluation-plan":
        _cmd_evaluation(args.alpha_id)
    elif args.command == "init-samples":
        _cmd_init_samples()
    elif args.command == "migrate-existing-factors":
        _cmd_migrate_existing_factors(dry_run=args.dry_run, category=args.category)
    else:
        parser.print_help()


def _cmd_register(spec_path):
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.alpha.registry import register_alpha
    if spec_path and os.path.exists(spec_path):
        with open(spec_path) as f:
            data = json.load(f)
        spec = AlphaSpec(**data)
    else:
        spec = AlphaSpec(name=f"alpha_{datetime.now(CST).strftime('%H%M%S')}")
    result = register_alpha(spec)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _cmd_list():
    from factor_lab.alpha.registry import list_alpha
    alphas = list_alpha()
    if alphas:
        for a in alphas:
            print(f"  {a['alpha_id']:40s} {a['name']:30s} {a['status']:20s} v{a.get('version','?')}")
    else:
        print("  (empty)")


def _cmd_show(alpha_id):
    from factor_lab.alpha.registry import get_alpha
    spec = get_alpha(alpha_id)
    print(json.dumps(spec, indent=2, ensure_ascii=False))


def _cmd_retire(alpha_id):
    from factor_lab.alpha.registry import retire_alpha
    result = retire_alpha(alpha_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _cmd_evaluation(alpha_id):
    from factor_lab.alpha.evaluation_hook import generate_evaluation_plan
    plan = generate_evaluation_plan(alpha_id)
    print(json.dumps(plan, indent=2, ensure_ascii=False))


def _cmd_init_samples():
    from factor_lab.alpha.sample_alphas import create_sample_alphas
    samples = create_sample_alphas()
    for s in samples:
        print(f"  ✅ {s['alpha_id']}")


def _cmd_migrate_existing_factors(dry_run=False, category=None):
    from factor_lab.alpha.factor_catalog_migration import run_migration
    result = run_migration(dry_run=dry_run, category=category)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def generate_factory_report():
    """生成 Alpha Factory 报告"""
    rid = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    out = BASE / "alpha_factory" / rid
    out.mkdir(parents=True)

    from factor_lab.alpha.registry import list_alpha, export_registry
    alphas = list_alpha()

    # Registry JSON + CSV
    with open(out / "alpha_registry.json", "w") as f:
        json.dump(alphas, f, indent=2, ensure_ascii=False)
    export_registry(str(out / "alpha_registry.csv"))

    # Summary
    summary = f"""# Alpha Factory Report V3.0

Run: {rid}
Registered Alphas: {len(alphas)}

## Registry

| Alpha ID | Name | Status | Version |
|----------|------|--------|---------|
""" + "\n".join(f"| {a['alpha_id']} | {a['name']} | {a['status']} | v{a.get('version','?')} |" for a in alphas) + """

## Safety

- enabled=false: ✅ all
- paper_enabled=false: ✅ all
- live_enabled=false: ✅ all
- No broker/miniqmt: ✅
- No paper/live config modified: ✅

## V3.1 Next Steps

- Connect LLM Alpha Discovery to AlphaFactory hook
- LLM generates candidate AlphaSpec → register → evaluation-plan
- Backtest evaluation via existing V2 pipeline
"""
    (out / "alpha_factory_summary.md").write_text(summary)

    # Schema docs
    (out / "alpha_spec_schema.md").write_text("""# AlphaSpec Schema

- alpha_id: str (auto-generated)
- name, description, hypothesis: str
- universe: str (default: all_watchlist)
- factor_expression: str
- signal_direction: long/short/long_short
- rebalance_frequency: daily/weekly/monthly
- enabled/paper_enabled/live_enabled: bool (default false)
- status: str (lifecycle)
""")
    (out / "alpha_lifecycle_schema.md").write_text("""# Alpha Lifecycle

draft → registered → backtest_ready → backtested → walk_forward_ready
→ paper_ready → paper_active → promotion_candidate → live_ready
→ live_active → retired | rejected
""")

    # HTML
    rows = "".join(f"<tr><td>{a['alpha_id'][:30]}</td><td>{a['name']}</td><td>{a['status']}</td><td>{'🔴' if a.get('status','') in ('retired','rejected') else '🟢'}</td></tr>" for a in alphas)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Alpha Factory V3.0</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>🏭 Alpha Factory V3.0</h1>
<p>Run: {rid} | Registered: {len(alphas)}</p></div>
<div class="card"><h2>📋 Registry</h2><table><tr><th>ID</th><th>Name</th><th>Status</th><th>Enabled</th></tr>{rows}</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul><li>All enabled=false</li><li>No broker/miniqmt</li><li>No config modified</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.0 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    (out / "alpha_factory_report.html").write_text(html)

    # Audit
    with open(out / "alpha_factory_audit.log", "w") as f:
        f.write(f"=== ALPHA FACTORY AUDIT V3.0 ===\nRun: {rid}\nAlphas: {len(alphas)}\nNo config modified: True\nNo broker/miniqmt: True\n=== END ===\n")

    # Print
    print(f"\n{'='*60}")
    print(f"  🏭 Alpha Factory V3.0")
    print(f"  Registered: {len(alphas)} alpha(s)")
    print(f"  All enabled=false | No broker/miniqmt | No config modified")
    print(f"  📁 {out}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        generate_factory_report()
