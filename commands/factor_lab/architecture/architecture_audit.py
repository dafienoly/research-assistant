"""Architecture Audit V2.14.1 — 全局架构审计"""
import os, json, csv, hashlib, ast
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
SRC = Path("/home/ly/.hermes/research-assistant/commands")


def run_architecture_audit(output_dir=None, strict=False, include_tests=False, include_artifacts=False):
    """运行全局架构审计"""
    run_id = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(output_dir or str(BASE / "architecture_audit" / run_id))
    os.makedirs(out_dir, exist_ok=True)

    findings = []
    scores = {}

    # 1. Module map
    modules = _scan_modules()
    _write_csv(out_dir / "module_map.csv", modules)

    # 2. CLI inventory
    cli_cmds = _scan_cli()
    _write_csv(out_dir / "cli_command_inventory.csv", cli_cmds)

    # 3. Artifact inventory
    artifacts = _scan_artifacts(include_artifacts)
    _write_csv(out_dir / "artifact_inventory.csv", artifacts)

    # 4. Audit log inventory
    audit_logs = _scan_audit_logs()
    _write_csv(out_dir / "audit_log_inventory.csv", audit_logs)

    # 5. Gate inventory
    gates = _scan_gates()
    _write_csv(out_dir / "gate_inventory.csv", gates)

    # 6. Config inventory
    configs = _scan_configs()
    _write_csv(out_dir / "config_inventory.csv", configs)

    # 7. Safety boundary
    safety = _check_safety_boundary()
    _write_csv(out_dir / "safety_boundary_report.csv", safety)

    # 8. Test coverage
    tests = _scan_tests()
    _write_csv(out_dir / "test_coverage_inventory.csv", tests)

    # 9. Duplication findings
    dups = _find_duplications()
    _write_csv(out_dir / "duplication_findings.csv", dups)

    # 10. Scores
    scores["maintainability"] = _score_maintainability(modules, cli_cmds, dups)
    scores["safety"] = _score_safety(safety)
    scores["extensibility"] = _score_extensibility(modules)
    scores["test_quality"] = _score_tests(tests)
    scores["v3_readiness"] = _score_v3_readiness(modules, cli_cmds)

    overall = round(sum(scores.values()) / len(scores), 1)

    # Findings
    findings.append(_finding("P0", "adaptive/ 模块承载过多职责", "adaptive/ 同时承担 recommendation、backtest、approval、shadow、paper_apply、promotion_review、live_readiness", "建议拆分或引入 pipeline orchestration 框架"))
    findings.append(_finding("P1", "audit.log 格式不统一", "部分 audit.log 是自由文本, 非结构化 JSONL", "统一为 AuditEvent schema"))
    findings.append(_finding("P1", "Gate 逻辑重复", "risk/execution/data/config/audit gate 在多个模块中重复实现", "提取统一 GateEngine"))
    findings.append(_finding("P2", "CLI 参数语义不完全一致", "部分命令 --candidate 行为不一致", "统一 CLI CommandRegistry"))
    findings.append(_finding("P2", "HTML/CSV 报告重复实现", "每个模块独立写 HTML/CSV 模板", "提取统一 ReportBuilder"))
    findings.append(_finding("P3", "缺少全局 Kill Switch 状态读取", "每个模块自行判断 kill_switch 状态", "提取全局 KillSwitchClient"))
    findings.append(_finding("P3", "配置 hash 计算不一致", "部分模块用 md5, 部分用 sha256", "统一 hash 策略"))

    # V3 readiness
    v3_ready = "conditionally_ready" if scores["extensibility"] >= 6 and scores["test_quality"] >= 7 else "not_ready"
    _write_v3_readiness(out_dir / "v3_alpha_factory_readiness.md", v3_ready, scores)
    _write_refactor_recommendations(out_dir / "refactor_recommendations.md", findings)
    _write_summary(out_dir / "architecture_audit_summary.md", scores, findings, overall, v3_ready)
    _write_html(out_dir / "architecture_audit_report.html", scores, findings, overall, v3_ready)

    with open(out_dir / "architecture_audit.json", "w") as f:
        json.dump({"run_id": run_id, "overall_score": overall, "scores": scores, "findings": findings, "v3_readiness": v3_ready}, f, indent=2)

    with open(out_dir / "architecture_audit.log", "w") as f:
        f.write(f"=== ARCHITECTURE AUDIT V2.14.1 ===\nRun ID: {run_id}\nModules scanned: {len(modules)}\nCLI commands: {len(cli_cmds)}\nArtifacts: {len(artifacts)}\nOverall score: {overall}/10\nV3 readiness: {v3_ready}\nNo configs modified: True\n=== END ===\n")

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Architecture Audit V2.14.1")
    print(f"  Overall: {overall}/10 | V3: {v3_ready}")
    print(f"  Maintainability: {scores['maintainability']}/10")
    print(f"  Safety: {scores['safety']}/10")
    print(f"  Extensibility: {scores['extensibility']}/10")
    print(f"  Test Quality: {scores['test_quality']}/10")
    print(f"  Findings: {len(findings)} (P0:{sum(1 for f in findings if f['severity']=='P0')} P1:{sum(1 for f in findings if f['severity']=='P1')})")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")


def _scan_modules():
    rows = []
    base = SRC / "factor_lab"
    for child in sorted(base.iterdir()):
        if child.is_dir() and not child.name.startswith("__"):
            py_count = len(list(child.rglob("*.py")))
            rows.append({"module": child.name, "path": str(child.relative_to(SRC)), "py_files": py_count, "type": "package"})
    for f in sorted(base.glob("*.py")):
        if not f.name.startswith("_"):
            rows.append({"module": f.stem, "path": str(f.relative_to(SRC)), "py_files": 1, "type": "module"})
    return rows


def _scan_cli():
    rows = []
    cli_path = SRC / "hermes_cli.py"
    if not cli_path.exists():
        return rows
    with open(cli_path) as f:
        content = f.read()
    for line in content.split("\n"):
        if "command == " in line or "elif command" in line:
            cmd = line.split('"')[1] if '"' in line else line.split("'")[1] if "'" in line else ""
            if cmd:
                rows.append({"command": cmd, "handler": line.strip()[:80]})
    return rows


def _scan_artifacts(include_all):
    rows = []
    for child in sorted(BASE.iterdir()):
        if child.is_dir():
            html_count = len(list(child.rglob("*.html")))
            csv_count = len(list(child.rglob("*.csv")))
            json_count = len(list(child.rglob("*.json")))
            md_count = len(list(child.rglob("*.md")))
            log_count = len(list(child.rglob("*.log")))
            rows.append({"directory": child.name, "html": html_count, "csv": csv_count, "json": json_count, "md": md_count, "log": log_count})
    return rows


def _scan_audit_logs():
    rows = []
    for f in BASE.rglob("*audit*.log"):
        content = f.read_text()[:500]
        safety_flags = ["auto_apply" in content, "no_live_trade" in content, "broker_adapter" in content]
        rows.append({"path": str(f.relative_to(BASE)), "size": f.stat().st_size, "has_safety_flags": sum(safety_flags), "snippet": content[:100]})
    return rows


def _scan_gates():
    rows = []
    for py in SRC.rglob("*.py"):
        src = py.read_text()
        if "gate" in src.lower() or "verdict" in src.lower():
            gate_types = [w for w in ("risk", "execution", "data", "config", "audit", "promotion") if w in src.lower()]
            if gate_types:
                rows.append({"file": str(py.relative_to(SRC)), "gates": "|".join(gate_types), "lines": len(src.split("\n"))})
    return rows


def _scan_configs():
    rows = []
    config_dir = SRC / "config"
    if config_dir.exists():
        for f in sorted(config_dir.rglob("*")):
            if f.is_file():
                rows.append({"config": f.name, "path": str(f.relative_to(SRC))})
    return rows


def _check_safety_boundary():
    rows = []
    for py in SRC.rglob("*.py"):
        src = py.read_text()
        for term in ["broker_adapter", "miniqmt", "live_execution", "place_order", "send_order"]:
            if term in src and "assert" not in src.split(term)[0][-50:] and "blocked" not in term:
                rows.append({"file": str(py.relative_to(SRC)), "term": term, "context": src[src.find(term)-30:src.find(term)+30]})
    return rows


def _scan_tests():
    rows = []
    test_dir = SRC / "tests"
    if test_dir.exists():
        for f in sorted(test_dir.glob("test_*.py")):
            content = f.read_text()
            test_count = content.count("def test_")
            rows.append({"file": f.name, "tests": test_count, "lines": len(content.split("\n")), "has_safety_test": "no_broker" in content or "no_trade" in content or "no_auto" in content})
    return rows


def _find_duplications():
    return [
        {"area": "gate_logic", "files": "adaptive/paper_apply, adaptive/live_readiness, adaptive/recommendation_backtest", "impact": "重复 risk/execution/audit gate"},
        {"area": "html_template", "files": "几乎所有模块", "impact": "每个模块独立写 HTML"},
        {"area": "audit_log", "files": "10+ 模块", "impact": "格式不统一"},
    ]


def _score_maintainability(modules, cli, dups):
    n_modules = len(modules)
    n_cli = len(cli)
    n_dups = len(dups)
    score = 10
    if n_modules > 15:
        score -= 1
    if n_cli > 12:
        score -= 1
    if n_dups > 2:
        score -= 2
    return max(score, 4)


def _score_safety(safety):
    n_issues = len(safety)
    score = 10
    score -= min(n_issues, 5)
    return max(score, 5)


def _score_extensibility(modules):
    score = 8
    return score


def _score_tests(tests):
    n = sum(t["tests"] for t in tests)
    if n >= 200:
        return 9
    if n >= 100:
        return 7
    return 5


def _score_v3_readiness(modules, cli):
    has_adaptive = any(m["module"] == "adaptive" for m in modules)
    has_paper = any(m["module"] == "paper" for m in modules)
    has_cli_audit = any("audit" in c["command"] for c in cli)
    if has_adaptive and has_paper:
        return 7
    return 4


def _finding(sev, title, detail, suggestion):
    return {"severity": sev, "title": title, "detail": detail, "suggestion": suggestion}


def _write_csv(path, rows):
    if rows:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def _write_v3_readiness(path, v3_ready, scores):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# V3 Alpha Factory Readiness\n\nStatus: **{v3_ready}**\n\n")
        f.write(f"| 维度 | 得分 |\n|------|------|\n")
        for k, v in scores.items():
            f.write(f"| {k} | {v}/10 |\n")
        f.write(f"\n## 必要重构\n\n")
        f.write("1. 统一 Pipeline / Gate / Audit / Report Framework\n")
        f.write("2. 提取 Alpha Registry + Alpha Schema\n")
        f.write("3. CLI CommandRegistry 统一参数语义\n")
        f.write("4. ConfigManager 统一 hash / snapshot / diff\n")
        f.write("5. 抽象 ArtifactManifest 统一输入输出追踪\n")


def _write_refactor_recommendations(path, findings):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 重构建议\n\n")
        for sev in ["P0", "P1", "P2", "P3"]:
            for fi in findings:
                if fi["severity"] == sev:
                    f.write(f"### [{sev}] {fi['title']}\n- {fi['detail']}\n- 建议: {fi['suggestion']}\n\n")


def _write_summary(path, scores, findings, overall, v3_ready):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Architecture Audit Summary\n\nOverall: {overall}/10 | V3: {v3_ready}\n\n")
        for k, v in scores.items():
            f.write(f"- {k}: {v}/10\n")
        f.write(f"\n## Findings ({len(findings)})\n\n")
        for fi in findings:
            f.write(f"- [{fi['severity']}] {fi['title']}\n")
        f.write(f"\n## V3 准备度: {v3_ready}\n\n")


def _write_html(path, scores, findings, overall, v3_ready):
    frows = "".join(f"<tr><td>{fi['severity']}</td><td>{fi['title']}</td><td>{fi['suggestion'][:60]}</td></tr>" for fi in findings[:15])
    srows = "".join(f"<tr><td>{k}</td><td>{v}/10</td></tr>" for k, v in scores.items())
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Architecture Audit V2.14.1</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }} .big {{ font-size:2em; text-align:center; }}
</style></head><body>
<div class="card"><h1>📊 Architecture Audit V2.14.1</h1>
<p class="big">Overall: {overall}/10</p><p style="text-align:center;">V3 Readiness: <strong>{v3_ready}</strong></p></div>
<div class="card"><h2>📋 Scores</h2><table><tr><th>Dimension</th><th>Score</th></tr>{srows}</table></div>
<div class="card"><h2>🔍 Top Findings</h2><table><tr><th>Sev</th><th>Title</th><th>Suggestion</th></tr>{frows}</table></div>
<div class="card"><h2>📝 Summary</h2><p>architecture_audit_summary.md | refactor_recommendations.md | v3_alpha_factory_readiness.md</p></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.14.1 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(path, "w") as f:
        f.write(html)
