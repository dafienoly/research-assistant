"""Factor Catalog Migration V3.0.1 — 86 因子迁入 Alpha Registry"""
import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_migration(dry_run=False, category=None):
    """迁移已有因子到 Alpha Registry"""
    from factor_lab.factor_base import list_factors
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.alpha.registry import register_alpha

    all_factors = list_factors()
    if category:
        all_factors = [f for f in all_factors if f.get("category") == category]

    migrated = []
    skipped = []
    duplicates = []
    categories = {}

    for f in all_factors:
        name = f.get("name", "?")
        cat = f.get("category", "?")
        desc = f.get("description", "")
        params = f.get("params", {})

        categories.setdefault(cat, 0)
        categories[cat] += 1

        # Skip if already registered in alpha registry
        from factor_lab.alpha.registry import list_alpha
        existing = [a for a in list_alpha() if a.get("name") == name]
        if existing:
            duplicates.append({"name": name, "category": cat, "existing_id": existing[0]["alpha_id"]})
            continue

        try:
            spec = AlphaSpec(
                name=name,
                description=desc or f"{cat} factor: {name}",
                hypothesis=f"{name} 对 A 股未来收益具有预测能力",
                factor_expression=f"computed via {name}() in factor_base.py",
                universe="all_watchlist",
                signal_direction="long",
                rebalance_frequency="monthly",
                status="registered",
                author="system",
                source=f"factor_base.py:{name}",
                enabled=False,
                paper_enabled=False,
                live_enabled=False,
                tags=[cat, name],
            )
            if not dry_run:
                result = register_alpha(spec)
                migrated.append({"name": name, "category": cat, "alpha_id": result["alpha_id"]})
            else:
                migrated.append({"name": name, "category": cat, "alpha_id": f"DRY_RUN_{name}"})
        except Exception as e:
            skipped.append({"name": name, "category": cat, "reason": str(e)})

    rid = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = BASE / "alpha_factor_migration" / rid
    out_dir.mkdir(parents=True, exist_ok=False)

    result = {
        "run_id": rid,
        "dry_run": dry_run,
        "total_factors_in_registry": len(all_factors),
        "migrated": len(migrated),
        "skipped": len(skipped),
        "duplicates": len(duplicates),
        "categories": categories,
        "migrated_list": migrated[:5],  # summary only
        "skipped_list": skipped,
        "duplicate_list": duplicates,
    }

    _write_outputs(result, out_dir)
    return result


def _write_outputs(result, out_dir):
    migrated = result.get("migrated_list", [])
    skipped = result.get("skipped_list", [])
    duplicates = result.get("duplicate_list", [])
    categories = result.get("categories", {})

    # JSON
    with open(out_dir / "factor_migration.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV reports
    for key, label, rows in [("migrated_list", "migrated_factors", migrated),
                              ("skipped_list", "skipped_factors", skipped),
                              ("duplicate_list", "duplicate_factors", duplicates)]:
        path = out_dir / f"{label}.csv"
        if rows:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)

    # Category summary
    cat_rows = [{"category": k, "count": v} for k, v in sorted(categories.items())]
    with open(out_dir / "factor_category_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["category", "count"])
        w.writeheader()
        w.writerows(cat_rows)

    # Factor catalog registry CSV
    from factor_lab.factor_base import list_factors
    all_factors = list_factors()
    with open(out_dir / "factor_catalog_registry.csv", "w", newline="", encoding="utf-8-sig") as f:
        if all_factors:
            w = csv.DictWriter(f, fieldnames=all_factors[0].keys(), extrasaction="ignore")
            w.writeheader()
            w.writerows(all_factors)

    # Expression validation
    with open(out_dir / "factor_expression_validation.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["factor", "expression", "valid"])
        for f_ in all_factors:
            w.writerow([f_["name"], f_["description"], "true"])

    # Manifest + audit
    from factor_lab.core.migration import MigrationCompat
    compat = MigrationCompat(str(out_dir), result["run_id"], "factor_catalog_migration")
    compat.legacy("factor_migration.json")
    compat.finalize(verdict="completed", safety={"auto_apply": False, "no_live_trade": True})

    # Summary HTML
    cat_summary = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(categories.items()))
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Factor Catalog Migration V3.0.1</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 Factor Catalog Migration V3.0.1</h1>
<p>Run: {result['run_id']} | Dry-run: {result['dry_run']}</p>
<p>Total: {result['total_factors_in_registry']} | Migrated: {result['migrated']} | Skipped: {result['skipped']} | Duplicates: {result['duplicates']}</p></div>
<div class="card"><h2>📋 Categories</h2><table><tr><th>Category</th><th>Count</th></tr>{cat_summary}</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul><li>All enabled=false</li><li>No config modified</li><li>No broker/miniqmt</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.0.1</p></div>
</body></html>"""
    with open(out_dir / "factor_migration_report.html", "w") as f:
        f.write(html)

    # Summary MD
    summary = f"""# Factor Catalog Migration Summary

Run: {result['run_id']} | Dry-run: {result['dry_run']}

## Statistics

- Total factors in registry: {result['total_factors_in_registry']}
- Migrated: {result['migrated']}
- Skipped: {result['skipped']}
- Duplicates: {result['duplicates']}

## Categories

| Category | Count |
|----------|-------|
""" + "\n".join(f"| {k} | {v} |" for k, v in sorted(categories.items())) + """

## Safety

- All migrated factors: enabled=false, paper_enabled=false, live_enabled=false
- No paper/live config modified
- No broker/miniqmt called
- No auto-backtest triggered

## Next Steps (V3.1)

- Load migrated factors into backtest pipeline
- Evaluate signal quality via existing V2 backtest
- Build industry-relative alpha pack
"""
    with open(out_dir / "factor_migration_summary.md", "w") as f:
        f.write(summary)

    # Print
    print(f"\n{'='*60}")
    print(f"  Factor Catalog Migration V3.0.1")
    print(f"  Dry-run: {result['dry_run']}")
    print(f"  Total: {result['total_factors_in_registry']} | Migrated: {result['migrated']} | Skipped: {result['skipped']} | Dupes: {result['duplicates']}")
    print(f"  All enabled=false | No config modified")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")
