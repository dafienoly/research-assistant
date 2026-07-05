"""Hermes Leader Dashboard — 本地只读自动版本推进监控台。"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from factor_lab.leader.auto_health import health
from factor_lab.leader.backend_policy import policy_status
from factor_lab.leader.roadmap import get_roadmap, get_version, is_backlog
from factor_lab.leader.roadmap_cursor import get_cursor
from factor_lab.leader.workloop import TASKS_DIR

CST = timezone(timedelta(hours=8))
ROOT = Path("/home/ly/.hermes/research-assistant")
COMMANDS = ROOT / "commands"
LATEST = TASKS_DIR / "latest.json"
COMPLETION = TASKS_DIR / "latest_completion.json"
CURSOR = TASKS_DIR / "roadmap_cursor.json"
LOG_PATH = Path("/tmp/hermes_agent_runner.log")

ERROR_PATTERNS = (
    "Traceback",
    "AttributeError",
    "ImportError",
    "coding_backend_not_configured",
    "live_execution",
    "V2.15",
    "some_task",
    "dry_run_completion",
)


def _now() -> str:
    return datetime.now(CST).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return {"_error": str(exc), "_path": str(path)}


def _run(cmd: list[str], timeout: int = 5) -> dict[str, Any]:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(COMMANDS),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"returncode": r.returncode, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except Exception as exc:  # pragma: no cover - defensive
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def _tail(path: Path, lines: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return content[-lines:]
    except Exception:
        return []


def _git() -> dict[str, Any]:
    head = _run(["git", "rev-parse", "--short", "HEAD"])
    log = _run(["git", "log", "-8", "--oneline"])
    status = _run(["git", "status", "--short"])
    status_lines = [line for line in status.get("stdout", "").splitlines() if line.strip()]
    return {
        "head": head.get("stdout", ""),
        "recent_commits": log.get("stdout", "").splitlines(),
        "status_lines": status_lines,
        "dirty": bool(status_lines),
    }


def _as_dict(item: Any) -> dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if is_dataclass(item):
        return asdict(item)
    return {k: getattr(item, k) for k in dir(item) if not k.startswith("_") and isinstance(getattr(item, k), (str, int, float, bool, type(None)))}


def _roadmap_progress(cursor: dict[str, Any]) -> dict[str, Any]:
    roadmap = [r for r in get_roadmap() if getattr(r, "auto_allowed", False) and not is_backlog(r.version)]
    versions = [r.version for r in roadmap]
    completed = cursor.get("completed_versions", []) or []
    completed_auto = [v for v in completed if v in versions]
    current = cursor.get("current_version", "")
    idx = versions.index(current) if current in versions else -1
    total = len(versions)
    percent = round((len(completed_auto) / total) * 100, 1) if total else 0
    current_item = _as_dict(get_version(current))
    return {
        "current_index": idx + 1 if idx >= 0 else 0,
        "total_auto_versions": total,
        "completed_auto_versions": len(completed_auto),
        "percent": percent,
        "current_item": current_item,
        "next_versions": versions[idx + 1: idx + 6] if idx >= 0 else versions[:5],
    }


def _latest_task_snapshot(latest: dict[str, Any]) -> dict[str, Any]:
    run_path = latest.get("path")
    if not run_path:
        return {"task_files": [], "bad_markers": []}
    path = Path(run_path)
    files = sorted(path.glob("tasks/*")) if path.exists() else []
    names = [f.name for f in files]
    bad = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:4000]
        except Exception:
            text = ""
        for marker in ("dry_run_completion", "some_task", "rebalance_diff", "V2.15", "live_execution", "unsafe"):
            if marker in text or marker in f.name:
                bad.append({"file": f.name, "marker": marker})
    return {"task_files": names, "bad_markers": bad}


def _derive_state(health_info: dict[str, Any], latest: dict[str, Any], completion: dict[str, Any], cursor: dict[str, Any], log_lines: list[str], git: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    level = "green"

    def bump(new_level: str, reason: str) -> None:
        nonlocal level
        order = {"green": 0, "yellow": 1, "red": 2}
        if order[new_level] > order[level]:
            level = new_level
        reasons.append(reason)

    if not health_info.get("cron_service_running"):
        bump("red", "cron_service_running=False")
    if not health_info.get("crontab_registered"):
        bump("red", "crontab 未注册")
    if float(health_info.get("tick_age_seconds", 999999) or 999999) > 600:
        bump("red", "tick 超过 10 分钟未更新")
    elif float(health_info.get("tick_age_seconds", 999999) or 999999) > 300:
        bump("yellow", "tick 超过 5 分钟未更新")
    if health_info.get("lock_status") != "free":
        bump("yellow", f"lock_status={health_info.get('lock_status')}")

    latest_current = latest.get("current")
    cursor_current = cursor.get("current_version")
    if latest_current and cursor_current and latest_current != cursor_current:
        bump("red", f"latest.current({latest_current}) != cursor.current_version({cursor_current})")

    comp_status = completion.get("status")
    if comp_status in {"blocked", "failed"}:
        bump("red", f"latest_completion.status={comp_status}")
    elif comp_status in {"partial", "running"}:
        bump("yellow", f"latest_completion.status={comp_status}")

    if latest.get("current") in {"V2.15", "live_execution", "unsafe"}:
        bump("red", f"latest.current={latest.get('current')} 属于旧污染或危险任务")

    recent_errors = [line for line in log_lines[-80:] if any(p in line for p in ERROR_PATTERNS)]
    if recent_errors:
        bump("yellow", "最近日志包含错误关键字，需确认是否为旧日志")

    if git.get("dirty"):
        bump("yellow", "git status 非空")

    if level == "green" and latest.get("status") == "pending":
        reasons.append("latest pending 且状态一致，等待下一轮自动消费")
    if not reasons:
        reasons.append("状态正常")

    labels = {
        "green": "正常推进",
        "yellow": "需要观察",
        "red": "已阻断/需处理",
    }
    return {"level": level, "label": labels[level], "reasons": reasons, "recent_error_lines": recent_errors[-10:]}


def collect_status() -> dict[str, Any]:
    health_info = health()
    cursor = get_cursor()
    latest = _read_json(LATEST)
    completion = _read_json(COMPLETION)
    backend = policy_status()
    git = _git()
    log_lines = _tail(LOG_PATH, 120)
    progress = _roadmap_progress(cursor)
    task_snapshot = _latest_task_snapshot(latest)
    state = _derive_state(health_info, latest, completion, cursor, log_lines, git)
    return {
        "generated_at": _now(),
        "state": state,
        "health": health_info,
        "roadmap_progress": progress,
        "cursor": cursor,
        "latest": latest,
        "latest_completion": completion,
        "backend": backend,
        "git": git,
        "latest_task_snapshot": task_snapshot,
        "log_tail": log_lines[-60:],
    }


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hermes Auto Roadmap Dashboard</title>
  <style>
    :root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #0b1020; color: #e8ecf8; }
    header { padding: 20px 24px; background: #111832; border-bottom: 1px solid #26304f; position: sticky; top: 0; z-index: 10; }
    h1 { margin: 0 0 6px; font-size: 22px; }
    .sub { color: #9aa7c7; font-size: 13px; }
    main { padding: 22px; display: grid; gap: 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
    .card { background: #121a35; border: 1px solid #26304f; border-radius: 14px; padding: 16px; box-shadow: 0 6px 24px #0005; }
    .card h2 { margin: 0 0 12px; font-size: 15px; color: #cdd6f8; }
    .status { display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; font-weight: 700; }
    .green { background: #0f3d2e; color: #7df0bd; }
    .yellow { background: #44380c; color: #ffdc7a; }
    .red { background: #4a1620; color: #ff8ba0; }
    .metric { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #25304c; padding: 7px 0; }
    .metric span:first-child { color: #9aa7c7; }
    .metric span:last-child { text-align: right; word-break: break-all; }
    .bar { height: 12px; background: #202946; border-radius: 999px; overflow: hidden; }
    .bar > div { height: 100%; background: linear-gradient(90deg, #73daca, #7aa2f7); width: 0%; transition: width .3s ease; }
    pre { background: #080d1c; border: 1px solid #26304f; border-radius: 12px; padding: 12px; overflow: auto; max-height: 360px; font-size: 12px; line-height: 1.45; }
    ul { margin: 8px 0 0; padding-left: 20px; }
    li { margin: 5px 0; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .ok { color: #7df0bd; } .bad { color: #ff8ba0; } .warn { color: #ffdc7a; }
  </style>
</head>
<body>
  <header>
    <h1>Hermes 自动版本推进监控台</h1>
    <div class="sub">只读本地页面 · 每 5 秒刷新 · <span id="updated">加载中...</span></div>
  </header>
  <main>
    <section class="card">
      <div id="stateBadge" class="status yellow">加载中</div>
      <ul id="reasons"></ul>
    </section>

    <section class="grid">
      <div class="card"><h2>路线图进度</h2><div id="roadmap"></div></div>
      <div class="card"><h2>自动工作流</h2><div id="health"></div></div>
      <div class="card"><h2>当前任务</h2><div id="latest"></div></div>
      <div class="card"><h2>最近完成/阻断</h2><div id="completion"></div></div>
      <div class="card"><h2>Backend</h2><div id="backend"></div></div>
      <div class="card"><h2>Git</h2><div id="git"></div></div>
    </section>

    <section class="grid">
      <div class="card"><h2>当前任务文件</h2><pre id="tasks"></pre></div>
      <div class="card"><h2>最近日志</h2><pre id="logs"></pre></div>
    </section>
  </main>
<script>
function esc(v){ return String(v ?? '').replace(/[&<>]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[s])); }
function metric(k,v){ return `<div class="metric"><span>${esc(k)}</span><span class="mono">${esc(v)}</span></div>`; }
function renderMetrics(el, obj, keys){
  document.getElementById(el).innerHTML = keys.map(([k,label]) => metric(label, obj?.[k])).join('');
}
async function refresh(){
  try {
    const r = await fetch('/api/status', {cache: 'no-store'});
    const s = await r.json();
    document.getElementById('updated').textContent = s.generated_at;
    const badge = document.getElementById('stateBadge');
    badge.className = 'status ' + s.state.level;
    badge.textContent = s.state.label;
    document.getElementById('reasons').innerHTML = s.state.reasons.map(x => `<li>${esc(x)}</li>`).join('');

    const p = s.roadmap_progress;
    document.getElementById('roadmap').innerHTML =
      metric('当前版本', s.cursor.current_version) +
      metric('当前名称', p.current_item?.name || '') +
      metric('已完成版本', `${p.completed_auto_versions}/${p.total_auto_versions}`) +
      `<div class="bar"><div style="width:${p.percent}%"></div></div>` +
      metric('进度', `${p.percent}%`) +
      metric('后续版本', (p.next_versions || []).join(' → '));

    renderMetrics('health', s.health, [
      ['cron_service_running','cron running'], ['latest_tick_at','latest tick'], ['tick_age_seconds','tick age 秒'],
      ['tick_count','tick count'], ['lock_status','lock'], ['latest_completion_status','completion status']
    ]);
    renderMetrics('latest', s.latest, [['current','current'], ['status','status'], ['task_count','task_count'], ['run_id','run_id'], ['updated_at','updated_at']]);
    renderMetrics('completion', s.latest_completion, [['version','version'], ['stage','stage'], ['status','status'], ['next_question','next_question'], ['generated_at','generated_at']]);
    renderMetrics('backend', s.backend, [['coding_backend_configured','coding backend'], ['default_for_code_change','code backend'], ['claude_bin_path','claude path'], ['cron_safe','cron_safe']]);
    document.getElementById('git').innerHTML = metric('HEAD', s.git.head) + metric('dirty', s.git.dirty) + '<pre>' + esc((s.git.recent_commits || []).join('\n')) + '</pre>';
    document.getElementById('tasks').textContent = JSON.stringify(s.latest_task_snapshot, null, 2);
    document.getElementById('logs').textContent = (s.log_tail || []).join('\n');
  } catch(e) {
    document.getElementById('stateBadge').className = 'status red';
    document.getElementById('stateBadge').textContent = '页面刷新失败';
    document.getElementById('reasons').innerHTML = `<li>${esc(e)}</li>`;
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class _DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            body = json.dumps(collect_status(), ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/log":
            qs = parse_qs(parsed.query)
            lines = int(qs.get("lines", ["120"])[0])
            body = json.dumps({"lines": _tail(LOG_PATH, lines)}, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args: Any) -> None:  # silence noisy access logs
        return


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), _DashboardHandler)
    url = f"http://{host}:{port}"
    print(f"Hermes dashboard: {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hermes 自动版本推进 Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--json", action="store_true", help="只输出状态 JSON，不启动 Web 服务")
    args = parser.parse_args(argv)
    if args.json:
        print(json.dumps(collect_status(), ensure_ascii=False, indent=2))
    else:
        serve(args.host, args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
