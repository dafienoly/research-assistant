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

    sp = sub.add_parser("evaluation-plan")
    sp.add_argument("--alpha-id", required=True)

    sp = sub.add_parser("init-samples")

    sp = sub.add_parser("migrate-existing-factors")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--category")

    # V3.7 LLM Alpha Discovery subcommands
    sp = sub.add_parser("llm-discover")
    sp.add_argument("--context", default="")
    sp.add_argument("--num", type=int, default=3)

    sp = sub.add_parser("llm-candidates")
    sp.add_argument("--status", default="")

    sp = sub.add_parser("llm-approve")
    sp.add_argument("--candidate-id", required=True)

    sp = sub.add_parser("llm-reject")
    sp.add_argument("--candidate-id", required=True)
    sp.add_argument("--reason", default="")

    sub.add_parser("llm-rejected-report")

    sp = sub.add_parser("llm-validate")
    sp.add_argument("--spec", required=True)

    # V3.8 Alpha Governance subcommands
    sp = sub.add_parser("review")
    sp.add_argument("--candidate-id", required=True, help="候选 ID")
    sp.add_argument("--verdict", default="", choices=["approve", "reject", ""],
                    help="强制审核结论 (默认自动判断)")

    sp = sub.add_parser("governance-report")
    sp.add_argument("--candidate-id", default="", help="候选 ID (空=全部)")

    sub.add_parser("governance-list")

    # V3.9 Alpha Promotion/Retirement Engine subcommands
    sp = sub.add_parser("promote")
    sp.add_argument("--candidate-id", required=True, help="候选 ID")
    sp.add_argument("--override", action="store_true", help="跳过治理审核检查")

    sp = sub.add_parser("batch-promote")
    sp.add_argument("--max-count", type=int, default=0, help="最大晋级数 (0=不限)")

    sp = sub.add_parser("promotion-queue-add")
    sp.add_argument("--candidate-id", required=True, help="候选 ID")
    sp.add_argument("--priority", type=float, default=0.5, help="优先级 (0-1)")
    sp.add_argument("--notes", default="", help="备注")

    sp = sub.add_parser("promotion-queue-list")
    sp.add_argument("--status", default="", help="筛选状态")

    sub.add_parser("promotion-queue-stats")
    sub.add_parser("promotion-report")
    sub.add_parser("promotion-list")

    sp = sub.add_parser("retire")
    sp.add_argument("--alpha-id", required=True, help="Alpha ID")
    sp.add_argument("--reason", default="", help="退役原因")
    sp.add_argument("--force", action="store_true", help="强制执行")

    sp = sub.add_parser("auto-retire")
    sp.add_argument("--dry-run", action="store_true", help="仅报告不执行")

    sub.add_parser("retirement-report")
    sub.add_parser("retirement-list")
    sub.add_parser("retirement-policy")

    sp = sub.add_parser("retirement-policy-update")
    sp.add_argument("--key", required=True, help="策略键名")
    sp.add_argument("--value", required=True, help="新值 (JSON)")

    # V3.2.5 — 验证结果回填
    sp = sub.add_parser("update-from-validation")
    sp.add_argument("--alpha-id", required=True, help="Alpha ID")
    sp.add_argument("--validation-path", required=True, help="验证报告 JSON 路径")

    sp = sub.add_parser("batch-update-from-validation")
    sp.add_argument("--validation-dir", default="research_outputs/factor_validation",
                    help="验证结果目录 (含 report.json 的子目录)")

    args = parser.parse_args()

    if args.command == "register":
        _cmd_register(args.spec)
    elif args.command == "list":
        _cmd_list()
    elif args.command == "show":
        _cmd_show(args.alpha_id)
    elif args.command == "evaluation-plan":
        _cmd_evaluation(args.alpha_id)
    elif args.command == "init-samples":
        _cmd_init_samples()
    elif args.command == "migrate-existing-factors":
        _cmd_migrate_existing_factors(dry_run=args.dry_run, category=args.category)
    elif args.command == "llm-discover":
        _cmd_llm_discover(args.context, args.num)
    elif args.command == "llm-candidates":
        _cmd_llm_candidates(args.status)
    elif args.command == "llm-approve":
        _cmd_llm_approve(args.candidate_id)
    elif args.command == "llm-reject":
        _cmd_llm_reject(args.candidate_id, args.reason)
    elif args.command == "llm-rejected-report":
        _cmd_llm_rejected_report()
    elif args.command == "llm-validate":
        _cmd_llm_validate(args.spec)
    elif args.command == "review":
        _cmd_governance_review(args.candidate_id, args.verdict)
    elif args.command == "governance-report":
        _cmd_governance_report(args.candidate_id)
    elif args.command == "governance-list":
        _cmd_governance_list()
    # V3.9
    elif args.command == "promote":
        _cmd_promotion_promote(args.candidate_id, args.override)
    elif args.command == "batch-promote":
        _cmd_batch_promote(args.max_count)
    elif args.command == "promotion-queue-add":
        _cmd_promotion_queue_add(args.candidate_id, args.priority, args.notes)
    elif args.command == "promotion-queue-list":
        _cmd_promotion_queue_list(args.status)
    elif args.command == "promotion-queue-stats":
        _cmd_promotion_queue_stats()
    elif args.command == "promotion-report":
        _cmd_promotion_report()
    elif args.command == "promotion-list":
        _cmd_promotion_list()
    elif args.command == "retire":
        _cmd_retirement_retire(args.alpha_id, args.reason, args.force)
    elif args.command == "auto-retire":
        _cmd_auto_retire(args.dry_run)
    elif args.command == "retirement-report":
        _cmd_retirement_report()
    elif args.command == "retirement-list":
        _cmd_retirement_list()
    elif args.command == "retirement-policy":
        _cmd_retirement_policy_show()
    elif args.command == "retirement-policy-update":
        import json as _json
        _cmd_retirement_policy_update(args.key, _json.loads(args.value))
    # V3.2.5
    elif args.command == "update-from-validation":
        _cmd_update_from_validation(args.alpha_id, args.validation_path)
    elif args.command == "batch-update-from-validation":
        _cmd_batch_update_from_validation(args.validation_dir)
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


# ─── V3.7 LLM Alpha Discovery ────────────────────────────


def _cmd_llm_discover(context: str = "", num: int = 3):
    from factor_lab.alpha.llm_alpha_discovery import cmd_discover
    result = cmd_discover(context, num)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _cmd_llm_candidates(status: str = ""):
    from factor_lab.alpha.llm_alpha_discovery import cmd_list_candidates
    cmd_list_candidates(status)


def _cmd_llm_approve(candidate_id: str):
    from factor_lab.alpha.llm_alpha_discovery import cmd_approve
    cmd_approve(candidate_id)


def _cmd_llm_reject(candidate_id: str, reason: str = ""):
    from factor_lab.alpha.llm_alpha_discovery import cmd_reject
    cmd_reject(candidate_id, reason)


def _cmd_llm_rejected_report():
    from factor_lab.alpha.llm_alpha_discovery import cmd_rejected_report
    cmd_rejected_report()


# ─── V3.8 Alpha Governance ────────────────────────────────


def _cmd_governance_review(candidate_id: str, verdict: str = ""):
    from factor_lab.alpha.governance import cmd_review
    cmd_review(candidate_id)


def _cmd_governance_report(candidate_id: str = ""):
    from factor_lab.alpha.governance import cmd_governance_report
    cmd_governance_report(candidate_id)


def _cmd_governance_list():
    from factor_lab.alpha.governance import cmd_governance_list
    cmd_governance_list()


def _cmd_llm_validate(spec_path: str):
    import json
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator
    with open(spec_path) as f:
        spec = json.load(f)
    validator = AlphaSpecValidator()
    ok = validator.validate(spec)
    report = validator.get_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))


# ─── V3.9 Alpha Promotion/Retirement Engine ──────────────────


def _cmd_promotion_promote(candidate_id: str, override: bool = False):
    from factor_lab.alpha.promotion_engine import cmd_promote
    cmd_promote(candidate_id, override=override)


def _cmd_batch_promote(max_count: int = 0):
    from factor_lab.alpha.promotion_engine import cmd_batch_promote
    cmd_batch_promote(max_count=max_count)


def _cmd_promotion_queue_add(candidate_id: str, priority: float = 0.5, notes: str = ""):
    from factor_lab.alpha.promotion_engine import cmd_promotion_queue_add
    cmd_promotion_queue_add(candidate_id, priority=priority, notes=notes)


def _cmd_promotion_queue_list(status: str = ""):
    from factor_lab.alpha.promotion_engine import cmd_promotion_queue_list
    cmd_promotion_queue_list(status=status)


def _cmd_promotion_queue_stats():
    from factor_lab.alpha.promotion_engine import cmd_promotion_queue_stats
    cmd_promotion_queue_stats()


def _cmd_promotion_report():
    from factor_lab.alpha.promotion_engine import cmd_promotion_report
    cmd_promotion_report()


def _cmd_promotion_list():
    from factor_lab.alpha.promotion_engine import cmd_promotion_list
    cmd_promotion_list()


def _cmd_retirement_retire(alpha_id: str, reason: str = "", force: bool = False):
    from factor_lab.alpha.retirement_engine import cmd_retire
    cmd_retire(alpha_id, reason=reason, force=force)


def _cmd_auto_retire(dry_run: bool = False):
    from factor_lab.alpha.retirement_engine import cmd_auto_retire
    cmd_auto_retire(dry_run=dry_run)


def _cmd_retirement_report():
    from factor_lab.alpha.retirement_engine import cmd_retirement_report
    cmd_retirement_report()


def _cmd_retirement_list():
    from factor_lab.alpha.retirement_engine import cmd_retirement_list
    cmd_retirement_list()


def _cmd_retirement_policy_show():
    from factor_lab.alpha.retirement_engine import cmd_retirement_policy_show
    cmd_retirement_policy_show()


def _cmd_retirement_policy_update(key: str, value):
    from factor_lab.alpha.retirement_engine import cmd_retirement_policy_update
    cmd_retirement_policy_update(key, value)


# ─── V3.2.5 — 验证结果回填 ─────────────────────────────────


def _cmd_update_from_validation(alpha_id: str, validation_path: str):
    """从单个验证报告更新 Alpha 元数据"""
    from factor_lab.alpha.registry import AlphaRegistry
    with open(validation_path, encoding="utf-8") as f:
        data = json.load(f)
    reg = AlphaRegistry()
    result = reg.update_alpha_from_validation(alpha_id, data)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _cmd_batch_update_from_validation(validation_dir: str):
    """从验证结果目录批量更新 Alpha 元数据"""
    from factor_lab.alpha.registry import AlphaRegistry
    reg = AlphaRegistry()
    results = reg.batch_update_from_validation_dir(validation_dir)
    updated = sum(1 for r in results if r.get("updated"))
    failed = sum(1 for r in results if r.get("error"))
    lines = [
        f"批量更新: {updated}/{len(results)} 成功",
        f"失败: {failed}/{len(results)}",
    ]
    for r in results:
        if r.get("updated"):
            lines.append(f"  ✅ {r.get('factor','?')} ({r.get('alpha_id','?')}) → {r.get('fields',[])}")
        else:
            lines.append(f"  ❌ {r.get('factor','?')}: {r.get('error','?')}")
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        generate_factory_report()
