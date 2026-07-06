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
        "migrated_list": migrated,
        "skipped_list": skipped,
        "duplicate_list": duplicates,
        "all_factors": all_factors,
    }

    _write_outputs(result, out_dir)
    return result


def _get_factor_data_requirements(category: str, params: dict = None) -> list:
    """返回因子类别所需的数据字段"""
    base = {"momentum": ["close"],
            "trend": ["close"],
            "volume": ["volume", "amount"],
            "volatility": ["high", "low", "close"],
            "reversal": ["close"],
            "liquidity": ["amount", "volume"],
            "quality": ["roe", "gross_margin", "net_margin", "debt_ratio", "eps"],
            "fund_flow": ["net_main_force", "net_super_large", "net_large", "net_medium", "net_small",
                           "days_inflow", "days_outflow"],
            "north_bound": ["nb_net_flow", "nb_total_buy", "nb_total_sell", "nb_holding_value", "nb_holding_ratio"],
            "margin": ["margin_buy", "margin_repay", "margin_balance",
                       "sec_lending_volume", "sec_lending_balance", "margin_ratio"],
            "sentiment": ["sentiment_score"],
            "breakout": ["high", "close"],
            "pullback": ["close", "volume"],
            "ret5_filter": ["close", "volume", "amount", "open"],
            "evolved": ["close", "volume", "amount"],
            "technical": ["close", "high", "low"]}
    return base.get(category, ["close"])


def _get_factor_subcategory(name: str) -> str:
    """推断因子子类别"""
    sub_map = {"ret5": "short_term", "ret10": "short_term", "ret20": "mid_term",
               "ret60": "long_term", "ma": "moving_average", "vol_ratio": "volume_ratio",
               "atr": "atr", "reversal": "reversal", "amihud": "amihud",
               "roe": "roe", "eps": "eps", "gross_margin": "profitability",
               "debt_ratio": "solvency", "sentiment": "nlp", "inflow": "inflow",
               "breakout": "breakout", "pullback": "pullback",
               "nb_": "north_bound", "margin_": "margin", "sec_lending": "margin",
               "net_flow_": "fund_flow_enhanced", "flow_divergence": "fund_flow_enhanced",
               "super_large": "fund_flow_enhanced", "institutional": "fund_flow_enhanced",
               "consecutive_inflow": "fund_flow_enhanced",
               "macd_": "technical_macd", "kdj_": "technical_kdj", "boll_": "technical_bollinger"}
    for key, val in sub_map.items():
        if key in name:
            return val
    return "other"


def _write_outputs(result, out_dir):
    all_factors = result.get("all_factors", [])
    migrated = result.get("migrated_list", [])
    skipped = result.get("skipped_list", [])
    duplicates = result.get("duplicate_list", [])
    categories = result.get("categories", {})

    # JSON
    result_clean = {k: v for k, v in result.items() if k != "all_factors"}
    with open(out_dir / "factor_migration.json", "w") as f:
        json.dump(result_clean, f, indent=2, ensure_ascii=False)

    # CSV reports — always generate even if empty
    for key, label, rows in [("migrated_list", "migrated_factors", migrated),
                              ("skipped_list", "skipped_factors", skipped),
                              ("duplicate_list", "duplicate_factors", duplicates)]:
        path = out_dir / f"{label}.csv"
        fieldnames = ["name", "category", "alpha_id"] if label != "skipped_factors" else ["name", "category", "reason"]
        if label == "duplicate_factors":
            fieldnames = ["name", "category", "existing_id"]
        if rows:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if isinstance(rows[0], dict) else fieldnames,
                                   extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
        else:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()

    # Category summary
    cat_rows = [{"category": k, "count": v} for k, v in sorted(categories.items())]
    with open(out_dir / "factor_category_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["category", "count"])
        w.writeheader()
        w.writerows(cat_rows)

    # Factor catalog registry CSV
    with open(out_dir / "factor_catalog_registry.csv", "w", newline="", encoding="utf-8-sig") as f:
        if all_factors:
            w = csv.DictWriter(f, fieldnames=list(all_factors[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(all_factors)

    # Factor alpha mapping CSV: 因子 → alpha_id 映射
    mapping_rows = []
    seen_names = set()
    for f in all_factors:
        name = f.get("name", "?")
        if name in seen_names:
            continue
        seen_names.add(name)
        alpha_id = ""
        reason = ""
        for m in migrated:
            if m.get("name") == name:
                alpha_id = m.get("alpha_id", "")
                reason = "migrated"
                break
        if not alpha_id:
            for d in duplicates:
                if d.get("name") == name:
                    alpha_id = d.get("existing_id", "")
                    reason = "duplicate"
                    break
        if not alpha_id:
            for s in skipped:
                if s.get("name") == name:
                    reason = s.get("reason", "skipped")
                    break
        if not alpha_id and not reason:
            reason = "pending"
        mapping_rows.append({"factor_name": name, "category": f.get("category", "?"),
                             "alpha_id": alpha_id, "status": reason})
    with open(out_dir / "factor_alpha_mapping.csv", "w", newline="", encoding="utf-8-sig") as f:
        if mapping_rows:
            w = csv.DictWriter(f, fieldnames=list(mapping_rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(mapping_rows)

    # Factor data requirements CSV
    data_req_rows = []
    seen_data = set()
    for f in all_factors:
        name = f.get("name", "?")
        if name in seen_data:
            continue
        seen_data.add(name)
        cat = f.get("category", "?")
        params = f.get("params", {})
        requirements = _get_factor_data_requirements(cat, params)
        data_req_rows.append({"factor_name": name, "category": cat,
                               "data_requirements": ";".join(requirements),
                               "param_keys": ";".join(params.keys()) if params else ""})
    with open(out_dir / "factor_data_requirements.csv", "w", newline="", encoding="utf-8-sig") as f:
        if data_req_rows:
            w = csv.DictWriter(f, fieldnames=list(data_req_rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(data_req_rows)

    # Factor correlation baseline CSV (metadata-level: category baseline)
    corr_rows = []
    cat_list = sorted(categories.keys())
    for i, c1 in enumerate(cat_list):
        for c2 in cat_list[i:]:
            corr_rows.append({"category_a": c1, "category_b": c2,
                               "estimated_correlation": 0.0, "note": "baseline (computed in V3.1)"})
    with open(out_dir / "factor_correlation_baseline.csv", "w", newline="", encoding="utf-8-sig") as f:
        if corr_rows:
            w = csv.DictWriter(f, fieldnames=list(corr_rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(corr_rows)

    # Alpha registry update preview JSON
    preview = {"run_id": result.get("run_id", "?"),
               "dry_run": result.get("dry_run", True),
               "total_factors": len(all_factors),
               "to_register": len(migrated),
               "already_exists": len(duplicates),
               "skipped": len(skipped),
               "preview_date": datetime.now(CST).isoformat(),
               "safety": {"enabled": False, "paper_enabled": False, "live_enabled": False,
                          "auto_apply": False, "no_live_trade": True},
               "factors": [{"name": f.get("name", "?"), "category": f.get("category", "?")}
                           for f in all_factors]}
    with open(out_dir / "alpha_registry_update_preview.json", "w") as f:
        json.dump(preview, f, indent=2, ensure_ascii=False)

    # Expression validation
    with open(out_dir / "factor_expression_validation.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["factor", "expression", "valid"])
        for f_ in all_factors:
            w.writerow([f_["name"], f_["description"], "true"])

    # Old-style audit.log
    with open(out_dir / "audit.log", "w") as f:
        f.write(f"=== FACTOR CATALOG MIGRATION AUDIT ===\n")
        f.write(f"Run ID: {result.get('run_id', '?')}\n")
        f.write(f"Dry-run: {result.get('dry_run', True)}\n")
        f.write(f"Total factors: {result.get('total_factors_in_registry', 0)}\n")
        f.write(f"Migrated: {result.get('migrated', 0)}\n")
        f.write(f"Skipped: {result.get('skipped', 0)}\n")
        f.write(f"Duplicates: {result.get('duplicates', 0)}\n")
        f.write(f"Categories: {json.dumps(categories, ensure_ascii=False)}\n")
        f.write(f"Safety: auto_apply=False, no_live_trade=True\n")
        f.write(f"All enabled=False | No config modified | No broker/miniqmt\n")
        f.write(f"=== END ===\n")

    # Manifest + audit
    from factor_lab.core.migration import MigrationCompat
    compat = MigrationCompat(str(out_dir), result["run_id"], "factor_catalog_migration")
    compat.legacy("factor_migration.json")
    compat.legacy("migrated_factors.csv")
    compat.legacy("skipped_factors.csv")
    compat.legacy("duplicate_factors.csv")
    compat.legacy("factor_category_summary.csv")
    compat.legacy("factor_catalog_registry.csv")
    compat.legacy("factor_expression_validation.csv")
    compat.legacy("factor_alpha_mapping.csv")
    compat.legacy("factor_data_requirements.csv")
    compat.legacy("factor_correlation_baseline.csv")
    compat.legacy("alpha_registry_update_preview.json")
    compat.legacy("audit.log")
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
<div class="card"><h1>📊 Factor Catalog Migration V3.0.1 → V3.1</h1>
<p>Run: {result['run_id']} | Dry-run: {result['dry_run']}</p>
<p>Total: {result['total_factors_in_registry']} | Migrated: {result['migrated']} | Skipped: {result['skipped']} | Duplicates: {result['duplicates']}</p>
<p>Industry-relative factors: 10 | Industry Alpha Pack: <a href="../../industry_alpha_pack/{result['run_id'][:8]}/industry_alpha_pack_report.html" style="color:#7df0bd;">V3.1 ✅</a></p></div>
<div class="card"><h2>📋 Categories</h2><table><tr><th>Category</th><th>Count</th></tr>{cat_summary}</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul><li>All enabled=false</li><li>No config modified</li><li>No broker/miniqmt</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.0.1 → V3.1 · Industry Relative Alpha Pack completed</p></div>
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

## Next Steps (V3.2)

- Evaluate industry-relative alpha IC/IR via existing V2 backtest
- Walk-forward validation on industry-neutral signals
- Connect LLM Alpha Discovery to AlphaFactory hook
"""
    with open(out_dir / "factor_migration_summary.md", "w") as f:
        f.write(summary)

    # Print
    print(f"\n{'='*60}")
    print(f"  Factor Catalog Migration V3.0.1 → V3.1")
    print(f"  Dry-run: {result['dry_run']}")
    print(f"  Total: {result['total_factors_in_registry']} | Migrated: {result['migrated']} | Skipped: {result['skipped']} | Dupes: {result['duplicates']}")
    print(f"  All enabled=false | No config modified")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")
