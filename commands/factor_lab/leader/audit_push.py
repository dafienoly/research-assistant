"""Audit & Push — 敏捷迭代工作流核心
                                 
检测变更类型 → 选择 Phase → 审计 → 判断阈值 → git push

供 leader:audit-and-push CLI 和 auto_executor 共同调用。
"""
import os, sys, json, subprocess, time, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter

CST = timezone(timedelta(hours=8))
BASE = Path("/home/ly/.hermes/research-assistant")
COMMANDS = BASE / "commands"
VENV = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
AUDIT_REPORTS_DIR = BASE / "agent_tasks" / "audit_reports"

# ─── 变更类型检测 ───────────────────────────────────────────

CODE_EXTENSIONS = {".py", ".jsx", ".tsx", ".js", ".ts", ".sh", ".go", ".rs"}
DOC_EXTENSIONS = {".md", ".txt", ".rst"}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
CODE_DIR_PREFIXES = ("commands/", "strategies/", "scripts/")
DOC_DIR_PREFIXES = ("docs/",)


def _git_diff_files() -> list[str]:
    """返回当前未暂存 + 已暂存的变更文件列表"""
    files = set()
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only"], capture_output=True, text=True, timeout=10,
            cwd=str(BASE)
        )
        if r.returncode == 0:
            files.update(r.stdout.strip().splitlines())
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, timeout=10,
            cwd=str(BASE)
        )
        if r.returncode == 0:
            files.update(r.stdout.strip().splitlines())
    except Exception:
        pass
    return [f for f in files if f.strip()]


def detect_change_type() -> str:
    """返回 'code' | 'docs' | 'config' | 'mixed' | 'none'"""
    files = _git_diff_files()
    if not files:
        return "none"
    types = set()
    for f in files:
        ext = Path(f).suffix.lower()
        if ext in CODE_EXTENSIONS or f.startswith(CODE_DIR_PREFIXES):
            types.add("code")
        elif ext in DOC_EXTENSIONS or f.startswith(DOC_DIR_PREFIXES):
            types.add("docs")
        elif ext in CONFIG_EXTENSIONS:
            types.add("config")
        else:
            types.add("other")
    if "code" in types:
        return "code"
    if len(types) > 1:
        return "mixed"
    return types.pop() if types else "other"


def select_phases(change_type: str) -> list[str]:
    mapping = {
        "code":   ["phase1", "phase2", "phase4"],
        "mixed":  ["phase1", "phase2", "phase4"],
        "docs":   ["phase1"],
        "config": ["phase1"],
        "other":  ["phase1"],
        "none":   [],
    }
    return mapping.get(change_type, ["phase1"])


# ─── 审计检查项 ─────────────────────────────────────────────

class AuditReport:
    def __init__(self):
        self.version = ""
        self.status = "passed"
        self.phases_run = []
        self.results = {"passed": 0, "failed": 0, "warnings": 0}
        self.fail_items = []
        self.warn_items = []
        self.started_at = datetime.now(CST).isoformat()

    def to_dict(self):
        return {
            "version": self.version,
            "status": self.status,
            "phases_run": self.phases_run,
            "results": self.results,
            "fail_items": self.fail_items,
            "warn_items": self.warn_items,
            "started_at": self.started_at,
            "finished_at": datetime.now(CST).isoformat(),
            "report_path": "",
        }

    def fail(self, category: str, file: str, line: int, msg: str):
        self.fail_items.append({"type": category, "file": file, "line": line, "msg": msg})
        self.results["failed"] += 1
        self.status = "failed"

    def warn(self, category: str, file: str, line: int, msg: str):
        self.warn_items.append({"type": category, "file": file, "line": line, "msg": msg})
        self.results["warnings"] += 1

    def ok(self):
        self.results["passed"] += 1


def _run(cmd: list[str], timeout: int = 15, cwd=None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or str(BASE))
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except FileNotFoundError:
        return -2, "NOT_FOUND"


def phase1_infrastructure(report: AuditReport):
    """Phase 1: venv, deps, daemon, gateway, disk"""
    # venv
    rc, _ = _run(["stat", f"{VENV}"], timeout=5)
    if rc == 0: report.ok()
    else: report.fail("INFRA", "venv", 0, f"Python venv 不可用: {VENV}")

    # key packages
    for pkg in ["fastapi", "uvicorn", "pytest", "pandas"]:
        rc, out = _run([VENV, "-m", "pip", "list", "--format=columns"], timeout=10)
        if pkg in out: report.ok()
        else: report.fail("INFRA", "requirements", 0, f"缺少依赖包: {pkg}")

    # daemon
    home = os.environ.get("HOME", "/home/ly")
    rc, out = _run(["bash", f"{home}/.hermes/hermes-daemon.sh", "status"], timeout=10)
    if "运行中" in out: report.ok()
    else: report.fail("INFRA", "hermes-daemon", 0, "Hermes 守护未运行")

    # gateway ticker
    rc, out = _run(["hermes", "cron", "status"], timeout=10)
    if "ticker heartbeat" in out.lower(): report.ok()
    else: report.warn("INFRA", "gateway", 0, "Gateway ticker 不可用")

    # disk
    rc, out = _run(["df", "-h", "/"], timeout=5)
    if rc == 0:
        lines = out.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[-1].split()
            # df output: Filesystem Size Used Avail Use% Mounted
            if len(parts) >= 5:
                pct = parts[-2].replace("%", "")
                if pct.isdigit() and int(pct) < 90: report.ok()
                else: report.warn("INFRA", "disk", 0, f"磁盘使用率: {pct}%")
            else: report.ok()
        else: report.ok()
    else:
        report.warn("INFRA", "disk", 0, "无法检查磁盘")

    # git fsck
    rc, out = _run(["git", "fsck", "--no-dangling"], timeout=10, cwd=str(BASE))
    if rc == 0: report.ok()
    else: report.warn("INFRA", "git", 0, f"Git 仓库异常: {out[:100]}")


def phase2_code_quality(report: AuditReport, target_dir: str = None):
    """Phase 2: Python 语法, 安全扫描, 错误处理"""
    scan_dir = target_dir or str(COMMANDS)
    
    # Python syntax check on changed .py files
    changed_py = [f for f in _git_diff_files() if f.endswith(".py")]
    if not changed_py:
        # If no git diff, scan common files
        changed_py = []
        for root, dirs, files in os.walk(scan_dir):
            for f in files:
                if f.endswith(".py") and len(changed_py) < 20:
                    changed_py.append(os.path.join(root, f))
    
    syntax_errors = 0
    for pyfile in changed_py[:20]:
        fp = os.path.join(str(BASE), pyfile) if not pyfile.startswith("/") else pyfile
        if not os.path.exists(fp):
            continue
        rc, out = _run([VENV, "-m", "py_compile", fp], timeout=10)
        if rc != 0:
            syntax_errors += 1
            report.fail("SYNTAX", pyfile, 0, f"语法错误: {out[:100]}")
    if syntax_errors == 0:
        report.ok()
    
    # ── Security: hardcoded secrets ──
    secret_pattern = r'(api_key|secret|password|token)\s*=\s*["\'][^"\']{6,}["\']'
    rc, out = _run(["grep", "-rnE", secret_pattern,
                     scan_dir, "--include=*.py", "--include=*.js", "--include=*.sh"],
                    timeout=30)
    if rc == 1:  # grep returns 1 when no matches
        report.ok()
    elif rc == 0:
        for line in out.splitlines()[:5]:
            report.fail("SECURITY", "secrets", 0, f"可能的硬编码密钥: {line[:120]}")
    else:
        report.warn("SECURITY", "secrets", 0, "密钥扫描跳过")

    # ── Security: bare except with pass ──
    rc, out = _run(["grep", "-rn", r"except\s*:", scan_dir, "--include=*.py",
                     "-A1"], timeout=30)
    if rc in (0, 1):
        bare_excepts = []
        for line in out.splitlines():
            if "pass" in line.lower() and "except" in line.lower():
                bare_excepts.append(line.strip())
        if bare_excepts:
            for line in bare_excepts[:3]:
                report.warn("STYLE", "error-handling", 0, f"bare except + pass: {line[:100]}")
            report.ok()
        else:
            report.ok()
    else:
        report.warn("STYLE", "error-handling", 0, "bare except 扫描跳过")

    # ── Security: shell injection ──
    rc, out = _run(["grep", "-rn", r"subprocess.*shell=True", scan_dir, "--include=*.py"],
                    timeout=15)
    if rc == 1:
        report.ok()
    elif rc == 0:
        report.warn("SECURITY", "shell-injection", 0, f"subprocess shell=True 发现: {out[:100]}")
    else:
        report.ok()

    # ── Architecture: long timeout ──
    rc, out = _run(["grep", "-rn", r"timeout=3600", scan_dir, "--include=*.py"], timeout=10)
    if rc == 0:
        for line in out.splitlines()[:3]:
            report.warn("ARCH", "timeout", 0, f"1小时超时: {line.strip()[:100]}")


def phase4_process_health(report: AuditReport):
    """Phase 4: daemon 窗口, dashboard 端口, 锁状态, 日志"""
    # daemon windows
    rc, out = _run(["tmux", "list-windows", "-t", "hermes-daemon", "-F", "#{window_name}"], timeout=5)
    if rc == 0:
        wins = [w.strip() for w in out.splitlines() if w.strip()]
        if "gateway" in wins and "auto-loop" in wins and "dashboard" in wins:
            report.ok()
        else:
            report.fail("PROCESS", "tmux", 0, f"窗口缺失: {wins}")
    else:
        report.fail("PROCESS", "tmux", 0, "tmux session hermes-daemon 不存在")

    # dashboard port
    rc, out = _run(["ss", "-tlnp"], timeout=5)
    if "8766" in out:
        report.ok()
    else:
        report.fail("PROCESS", "dashboard", 0, "Dashboard 端口 :8766 未监听")

    # lock staleness
    rc, out = _run([VENV, str(COMMANDS / "hermes_cli.py"), "leader:automation-status"], timeout=15)
    if "lock_status: running" in out:
        # check age - if in the output
        report.warn("PROCESS", "lock", 0, "Lock 状态为 running（可能卡死）")
    else:
        report.ok()

    # log errors
    log_dir = Path(os.environ.get("HOME", "/home/ly")) / ".hermes"
    error_count = 0
    for logf in log_dir.glob("*.log"):
        rc, out = _run(["grep", "-ic", "ERROR|Traceback|failed", str(logf)], timeout=5)
        if rc == 0:
            try:
                cnt = int(out.strip().splitlines()[-1]) if out.strip() else 0
                error_count += cnt
            except (ValueError, IndexError):
                pass
    if error_count < 10:
        report.ok()
    else:
        report.warn("PROCESS", "logs", 0, f"{error_count} 条错误日志")


# ─── 审计调度 ───────────────────────────────────────────────

def run_audit(phases: list[str], version: str = "") -> AuditReport:
    report = AuditReport()
    report.version = version
    report.phases_run = phases
    
    for phase in phases:
        if phase == "phase1":
            phase1_infrastructure(report)
        elif phase == "phase2":
            phase2_code_quality(report)
        elif phase == "phase4":
            phase4_process_health(report)
    
    # 最终判定
    if report.results["failed"] > 0:
        report.status = "failed"
    else:
        report.status = "passed"
    
    return report


def save_report(report: AuditReport) -> str:
    AUDIT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    ver = report.version or "unknown"
    path = AUDIT_REPORTS_DIR / f"audit_{ver}_{ts}.json"
    data = report.to_dict()
    data["report_path"] = str(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    # also write latest
    (AUDIT_REPORTS_DIR / "latest.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return str(path)


def git_push(report: AuditReport) -> dict:
    """审计通过后执行 git add + commit + push"""
    steps = []
    try:
        # 清理残留 git lock
        for lockfile in [str(BASE / ".git" / "index.lock"), str(BASE / ".git" / "HEAD.lock")]:
            if os.path.exists(lockfile):
                try:
                    os.remove(lockfile)
                except Exception:
                    pass
        # git add
        r = subprocess.run(["git", "add", "-A"], capture_output=True, text=True, timeout=120, cwd=str(BASE))
        steps.append({"step": "git add", "ok": r.returncode == 0, "detail": r.stderr[:200]})
        if r.returncode != 0:
            return {"success": False, "steps": steps, "error": r.stderr[:200]}

        # git commit
        ver = report.version or "auto"
        msg = f"[audit-passed] {ver} — {report.results['passed']} passed, {report.results['failed']} failed"
        r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True, timeout=30, cwd=str(BASE))
        steps.append({"step": "git commit", "ok": r.returncode == 0, "detail": r.stdout[:200]})
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            return {"success": False, "steps": steps, "error": r.stderr[:200]}

        # git push
        r = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=120, cwd=str(BASE))
        steps.append({"step": "git push", "ok": r.returncode == 0, "detail": r.stdout[:200]})
        if r.returncode != 0:
            return {"success": False, "steps": steps, "error": r.stderr[:200]}

        return {"success": True, "steps": steps}
    except Exception as e:
        return {"success": False, "steps": steps, "error": str(e)}


def format_human_summary(report: AuditReport) -> str:
    lines = []
    lines.append(f"## 审计报告 — {report.version or 'unknown'}")
    lines.append("")
    lines.append(f"**状态**: {'✅ 通过' if report.status == 'passed' else '❌ 未通过'}")
    lines.append(f"**检查**: {report.results['passed']} 通过 / {report.results['failed']} 失败 / {report.results['warnings']} 警告")
    lines.append(f"**Phase**: {', '.join(report.phases_run)}")
    if report.fail_items:
        lines.append("")
        lines.append("### ❌ 失败项")
        for item in report.fail_items:
            lines.append(f"- [{item['type']}] {item['file']}:{item['line']} — {item['msg']}")
    if report.warn_items:
        lines.append("")
        lines.append("### ⚠️ 警告项")
        for item in report.warn_items:
            lines.append(f"- [{item['type']}] {item['file']}:{item['line']} — {item['msg']}")
    return "\n".join(lines)


# ─── CLI 入口 ───────────────────────────────────────────────

def main(args: list[str] = None):
    import argparse
    p = argparse.ArgumentParser(description="审计代码变更并推送至 GitHub")
    p.add_argument("--version", default="", help="当前版本号（auto_executor 传入）")
    p.add_argument("--mode", choices=["full", "push-hook"], default="full",
                   help="full=完整审计+推送, push-hook=只审计不推送(返回0/1)")
    p.add_argument("--force", action="store_true", help="强制通过审计（跳过失败检查）")
    opts = p.parse_args(args)

    # 1. 检测变更类型
    change_type = detect_change_type()
    print(f"变更类型: {change_type}")

    if change_type == "none":
        print("无可审计的变更")
        return 0

    # 2. 选择 Phase
    phases = select_phases(change_type)
    print(f"执行 Phase: {', '.join(phases)}")

    # 3. 审计
    print("执行审计...")
    report = run_audit(phases, version=opts.version)
    report_path = save_report(report)
    print(f"审计报告: {report_path}")

    # 4. 打印摘要
    print(format_human_summary(report))
    print("")

    # 5. 判定
    if opts.force:
        print("⚠️ 强制模式：跳过审计失败检查")
        report.status = "passed"

    if report.status != "passed":
        print(f"❌ 审计未通过: {report.results['failed']} 个失败项")
        print("   修复后重试，或使用 --force 强制提交")
        if opts.mode == "push-hook":
            print("   pre-push hook: 阻止推送")
        return 1

    # 6. 推送
    if opts.mode == "push-hook":
        print("✅ 审计通过 (push-hook 模式，不执行推送)")
        return 0

    print("审计通过，推送至 GitHub...")
    result = git_push(report)
    if result["success"]:
        print("✅ 推送成功")
        for s in result["steps"]:
            print(f"  {s['step']}: {'OK' if s['ok'] else 'FAIL'} — {s['detail'][:100]}")
        return 0
    else:
        print(f"❌ 推送失败: {result.get('error', '未知错误')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
