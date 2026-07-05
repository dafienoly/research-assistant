"""发布 Strategy Lab 结果包给 Codex ingest"""
import csv, json, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
INCOMING = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/incoming_from_hermes")
BASE = Path("/home/ly/.hermes/research-assistant")
PERF = BASE / "performance"
OUTPUT = BASE / "research_outputs"


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def publish_results(pkg_type: str = "strategy_lab_results"):
    """打包全部策略实验室结果 → incoming_from_hermes

    pkg_type: 包类型标识，如 'strategy_lab_results', 'factor_lab_results', 'paper_trading_results'
    """
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    pkg_id = f"{pkg_type}_{ts}"
    tmp = INCOMING / f"{pkg_id}.tmp"
    final = INCOMING / pkg_id

    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    if final.exists():
        import shutil
        shutil.rmtree(final)

    # 构建 payload
    payload = tmp / "payload"
    targets = []

    # performance/ 下的 CSV
    for rel in ["strategy_registry.csv", "strategy_leaderboard.csv", "strategy_risk_dashboard.json"]:
        src = PERF / rel
        if src.exists():
            dst = payload / "performance" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            targets.append(("performance/" + rel, src))

    # backtests/
    bt_dir = PERF / "backtests"
    if bt_dir.exists():
        for strategy_dir in sorted(bt_dir.iterdir()):
            if not strategy_dir.is_dir():
                continue
            for f in strategy_dir.glob("*"):
                if f.is_file():
                    rel = f"performance/backtests/{strategy_dir.name}/{f.name}"
                    dst = payload / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(f.read_bytes())
                    targets.append((rel, f))

    # signals/
    sig_dir = PERF / "signals"
    if sig_dir.exists():
        for f in sig_dir.glob("*"):
            rel = f"performance/signals/{f.name}"
            dst = payload / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(f.read_bytes())
            targets.append((rel, f))

    # strategy_review_material/
    review_dir = OUTPUT / "strategy_review_material"
    if review_dir.exists():
        for f in review_dir.glob("*.json"):
            rel = f"research_outputs/strategy_review_material/{f.name}"
            dst = payload / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(f.read_bytes())
            targets.append((rel, f))

    # 写 manifest.json
    files_meta = []
    for rel, src in targets:
        if src.suffix == ".csv":
            with open(src) as f:
                rows = sum(1 for _ in f)
        elif src.suffix == ".json":
            with open(src) as f:
                content = f.read()
                rows = content.count("\n") + 1 if content else 0
        else:
            rows = 1
        files_meta.append({
            "path": rel,
            "rows": rows,
            "sha256": sha256(src),
        })

    manifest = {
        "package_id": pkg_id,
        "producer": "hermes",
        "env": "wsl",
        "created_at": now_str(),
        "type": pkg_type,
        "files": files_meta,
        "freshness": {"status": "ok", "blocking": False, "max_delay_seconds": 0},
    }
    (tmp / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_sha256"] = sha256(tmp / "manifest.json")
    (tmp / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 原子发布
    tmp.rename(final)
    (final / "_SUCCESS").write_text(f"Strategy Lab results {pkg_id} completed at {now_str()}\n")

    return {
        "package_id": pkg_id,
        "files": len(targets),
        "path": str(final),
    }
