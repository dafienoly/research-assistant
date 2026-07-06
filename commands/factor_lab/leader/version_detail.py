"""Version Completion Detail — 版本完成记录生成"""
import subprocess, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
REPO = "/home/ly/.hermes/research-assistant"
REPORT_DIR = Path("/mnt/d/HermesReports/version_reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def capture_completion(version: str, name: str, since_version: str = None):
    """捕获版本完成的详细记录：git 变更、提交、功能说明"""
    record = {
        "version": version,
        "name": name,
        "completed_at": datetime.now(CST).isoformat(),
        "commits": [],
        "files_changed": [],
        "stats": {},
    }

    # 1. Git 提交记录（since 上次完成版本）
    try:
        if since_version:
            r = subprocess.run(
                ["git", "log", f"--since={since_version}", "--oneline", "--no-decorate"],
                capture_output=True, text=True, cwd=REPO, timeout=10
            )
        else:
            # 获取最近 20 条
            r = subprocess.run(["git", "log", "-20", "--oneline", "--no-decorate"],
                               capture_output=True, text=True, cwd=REPO, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                parts = line.split(" ", 1)
                record["commits"].append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
    except Exception:
        pass

    # 2. Git 文件变更统计
    try:
        r = subprocess.run(["git", "diff", "--stat", "HEAD~5..HEAD"],
                           capture_output=True, text=True, cwd=REPO, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            record["files_changed"] = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    except Exception:
        pass

    # 3. Git diff stat 汇总
    try:
        r = subprocess.run(["git", "diff", "--shortstat", "HEAD~5..HEAD"],
                           capture_output=True, text=True, cwd=REPO, timeout=10)
        if r.returncode == 0:
            record["stats"]["diff_shortstat"] = r.stdout.strip()
    except Exception:
        pass

    # 4. 保存到文件
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"completion_{version}_{ts}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    # 更新最新 completion 详情
    (REPORT_DIR / f"latest_completion_{version}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False))

    return record


def get_completion_detail(version: str = None) -> dict:
    """获取版本完成详情"""
    if version:
        path = REPORT_DIR / f"latest_completion_{version}.json"
        if path.exists():
            return json.loads(path.read_text())
    # 返回最新的
    files = sorted(REPORT_DIR.glob("completion_*.json"), reverse=True)
    if files:
        return json.loads(files[0].read_text())
    return {"error": "no completion records"}
