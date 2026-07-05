"""Hermes Leader Dashboard — 本地只读自动版本推进监控台。"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
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
AGENT_LOG_ROOT = TASKS_DIR / "agent_logs"

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


def _related_run_ids(run_id: str | None) -> list[str]:
    # 不把 align_* 猜成 auto_*；同秒生成的二者可能不是同一轮任务。
    return [run_id] if run_id else []


def _log_has_bad_markers(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:6000]
    except Exception:
        return False
    bad = ("V2.15", "some_task", "dry_run_completion", "[DRY-RUN] 未调用模型")
    return any(marker in text for marker in bad)


def _agent_log_files(latest: dict[str, Any], completion: dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    report_dir = completion.get("report_dir")
    if report_dir:
        candidates.append(Path(report_dir))

    for rid in _related_run_ids(latest.get("run_id")):
        candidates.append(AGENT_LOG_ROOT / rid)

    if AGENT_LOG_ROOT.exists():
        recent_dirs = sorted(
            [p for p in AGENT_LOG_ROOT.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(recent_dirs[:8])

    seen: set[str] = set()
    files: list[Path] = []
    for d in candidates:
        if not d.exists() or not d.is_dir():
            continue
        for f in sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
            if _log_has_bad_markers(f):
                continue
            key = str(f)
            if key not in seen:
                seen.add(key)
                files.append(f)
    return files


def _agent_output_snapshot(latest: dict[str, Any], completion: dict[str, Any], lines: int = 160) -> dict[str, Any]:
    """读取当前/最近 agent backend 输出，过滤旧 V2.15/dry-run 污染。"""
    log_files = _agent_log_files(latest, completion)
    snippets = []
    POLLUTION = ("V2.15", "some_task", "dry_run_completion", "rebalance_diff real dry-run",
                 "[DRY-RUN]", "Align V", "live_execution")
    for f in log_files[:8]:
        raw = _tail(f, lines)
        # 如果文件内容全部是污染日志，跳过
        clean_lines = [l for l in raw if not any(p in l for p in POLLUTION)]
        if not clean_lines:
            continue
        snippets.append({
            "file": str(f),
            "mtime": datetime.fromtimestamp(f.stat().st_mtime, tz=CST).isoformat(),
            "lines": clean_lines[-80:],
        })
    return {"log_files": [s["file"] for s in snippets], "snippets": snippets}


def _roadmap_details() -> list[dict[str, Any]]:
    rows = []
    for item in get_roadmap():
        d = _as_dict(item)
        version = d.get("version", "")
        if version.startswith("V3"):
            series = "V3 Alpha Factory"
        elif version.startswith("V4"):
            series = "V4 Controlled Execution"
        elif version.startswith("V5"):
            series = "V5 Data Platform"
        elif version.startswith("V6"):
            series = "V6 Research Automation"
        elif version.startswith("V7"):
            series = "V7 Product UI/Ops"
        elif version.startswith("V8"):
            series = "V8 Multi-Agent Engineering"
        elif version.startswith("V9"):
            series = "V9 Future Backlog"
        else:
            series = "Other"
        d["series"] = series
        d["backlog"] = is_backlog(version)
        rows.append(d)
    return rows


def _stream_event(handler: BaseHTTPRequestHandler, event: str, payload: dict[str, Any]) -> bool:
    try:
        data = json.dumps(payload, ensure_ascii=False)
        handler.wfile.write(f"event: {event}\n".encode("utf-8"))
        for line in data.splitlines() or [""]:
            handler.wfile.write(f"data: {line}\n".encode("utf-8"))
        handler.wfile.write(b"\n")
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError):
        return False


def _stream_logs(handler: BaseHTTPRequestHandler, max_seconds: int = 3600) -> None:
    watched: dict[Path, int] = {}

    def update_watch_files() -> None:
        for path in [LOG_PATH, *_agent_log_files(_read_json(LATEST), _read_json(COMPLETION))[:8]]:
            if path.exists() and path not in watched:
                # SSE 只推新增内容；历史快照由 /api/status 提供。
                watched[path] = path.stat().st_size

    update_watch_files()
    started = time.time()
    last_status = 0.0
    while time.time() - started < max_seconds:
        now = time.time()
        if now - last_status >= 5:
            if not _stream_event(handler, "status", collect_status()):
                return
            last_status = now
            update_watch_files()

        for path in list(watched):
            if not path.exists():
                continue
            size = path.stat().st_size
            offset = watched.get(path, 0)
            if size < offset:
                offset = 0
            if size > offset:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    chunk = f.read()
                watched[path] = size
                event = "runner_log" if path == LOG_PATH else "agent_log"
                if not _stream_event(handler, event, {"file": str(path), "chunk": chunk, "at": _now()}):
                    return
        time.sleep(1)

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
    comp_version = completion.get("version")
    completion_matches_current = not comp_version or comp_version in {latest_current, cursor_current}
    if completion_matches_current:
        if comp_status in {"blocked", "failed"}:
            bump("red", f"latest_completion.status={comp_status}")
        elif comp_status in {"partial", "running"}:
            bump("yellow", f"latest_completion.status={comp_status}")
    elif comp_status:
        reasons.append(f"忽略旧 completion: {comp_version} status={comp_status}")

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
    agent_output = _agent_output_snapshot(latest, completion)
    state = _derive_state(health_info, latest, completion, cursor, log_lines, git)
    return {
        "generated_at": _now(),
        "state": state,
        "health": health_info,
        "roadmap_progress": progress,
        "roadmap_details": _roadmap_details(),
        "cursor": cursor,
        "latest": latest,
        "latest_completion": completion,
        "backend": backend,
        "git": git,
        "latest_task_snapshot": task_snapshot,
        "agent_output": agent_output,
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
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border-bottom: 1px solid #25304c; padding: 8px 6px; text-align: left; vertical-align: top; }
    th { color: #9aa7c7; position: sticky; top: 0; background: #121a35; }
    .wide { grid-column: 1 / -1; }
    #streamOutput { max-height: 520px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <header>
    <h1>Hermes 自动版本推进监控台</h1>
    <div class="sub">只读本地页面 · 状态每 5 秒刷新 · SSE 日志流式更新 · <span id="updated">加载中...</span></div>
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

    <section class="card wide">
      <h2>固定版本规划详情</h2>
      <div id="roadmapDetails"></div>
    </section>

    <section class="grid">
      <div class="card"><h2>当前任务文件</h2><pre id="tasks"></pre></div>
      <div class="card wide"><h2>SSE 实时日志流</h2><pre id="streamOutput">等待日志流连接...</pre></div>
      <div class="card"><h2>Hermes Backend 输出快照</h2><pre id="agentOutput"></pre></div>
      <div class="card"><h2>Runner 最近日志快照</h2><pre id="logs"></pre></div>
    </section>
  </main>
<script>
function esc(v){ return String(v ?? '').replace(/[&<>]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[s])); }
function metric(k,v){ return `<div class="metric"><span>${esc(k)}</span><span class="mono">${esc(v)}</span></div>`; }
function renderMetrics(el, obj, keys){
  document.getElementById(el).innerHTML = keys.map(([k,label]) => metric(label, obj?.[k])).join('');
}
function renderRoadmapDetails(rows, cursor){
  const completed = new Set(cursor?.completed_versions || []);
  const current = cursor?.current_version || '';
  const html = `<table><thead><tr>
    <th>系列</th><th>版本</th><th>名称</th><th>目标</th><th>自动</th><th>人工门禁</th><th>交易模式</th><th>状态</th>
  </tr></thead><tbody>` + (rows || []).map(r => {
    const st = r.version === current ? '当前' : completed.has(r.version) ? '已完成' : r.backlog ? 'Backlog' : '待执行';
    return `<tr><td>${esc(r.series)}</td><td class="mono">${esc(r.version)}</td><td>${esc(r.name)}</td><td>${esc(r.objective)}</td><td>${esc(r.auto_allowed)}</td><td>${esc(r.manual_required)}</td><td>${esc(r.trading_mode)}</td><td>${esc(st)}</td></tr>`;
  }).join('') + '</tbody></table>';
  document.getElementById('roadmapDetails').innerHTML = html;
}
function appendStream(kind, text){
  const el = document.getElementById('streamOutput');
  const prefix = kind ? `\n### ${kind}\n` : '';
  el.textContent += prefix + text;
  const maxLen = 60000;
  if (el.textContent.length > maxLen) el.textContent = el.textContent.slice(-maxLen);
  el.scrollTop = el.scrollHeight;
}
function startStream(){
  if (!window.EventSource) { appendStream('SSE', '浏览器不支持 EventSource，使用快照刷新。\n'); return; }
  const es = new EventSource('/api/stream');
  es.addEventListener('open', () => appendStream('SSE', '已连接日志流。\n'));
  es.addEventListener('status', ev => { try { renderStatus(JSON.parse(ev.data)); } catch(e){} });
  es.addEventListener('runner_log', ev => { const x = JSON.parse(ev.data); appendStream('runner ' + x.file, x.chunk); });
  es.addEventListener('agent_log', ev => { const x = JSON.parse(ev.data); appendStream('agent ' + x.file, x.chunk); });
  es.onerror = () => appendStream('SSE', '连接中断，浏览器会自动重连。\n');
}
function renderStatus(s){
  const state = s?.state || {};
  const badge = document.getElementById('stateBadge');
  badge.className = 'status ' + (state.level || 'yellow');
  badge.textContent = state.label || '未知状态';
  document.getElementById('updated').textContent = s?.generated_at || '';
  document.getElementById('reasons').innerHTML = (state.reasons || []).map(x => `<li>${esc(x)}</li>`).join('');

  const p = s?.roadmap_progress || {};
  document.getElementById('roadmap').innerHTML =
    `<div class="bar"><div style="width:${esc(p.percent || 0)}%"></div></div>` +
    metric('进度', `${p.completed_auto_versions || 0}/${p.total_auto_versions || 0} (${p.percent || 0}%)`) +
    metric('当前版本', s?.cursor?.current_version || '') +
    metric('下一批', (p.next_versions || []).join(', '));

  renderMetrics('health', s?.health || {}, [
    ['cron_service_running','cron'], ['crontab_registered','crontab'],
    ['tick_age_seconds','tick_age_seconds'], ['lock_status','lock_status']
  ]);
  renderMetrics('latest', s?.latest || {}, [
    ['run_id','run_id'], ['current','current'], ['next','next'], ['status','status'], ['path','path']
  ]);
  renderMetrics('completion', s?.latest_completion || {}, [
    ['status','status'], ['version','version'], ['stage','stage'], ['report_dir','report_dir'], ['next_question','next_question']
  ]);
  renderMetrics('backend', s?.backend || {}, [
    ['recommended_backend','recommended'], ['coding_backend_configured','configured'], ['claude_bin_path','claude_bin']
  ]);
  renderMetrics('git', s?.git || {}, [
    ['head','head'], ['dirty','dirty']
  ]);

  document.getElementById('tasks').textContent = JSON.stringify(s?.latest_task_snapshot || {}, null, 2);
  document.getElementById('agentOutput').textContent = JSON.stringify(s?.agent_output || {}, null, 2);
  document.getElementById('logs').textContent = (s?.log_tail || []).join('\n');
  renderRoadmapDetails(s?.roadmap_details || [], s?.cursor || {});
}
async function refresh(){
  try {
    const r = await fetch('/api/status', {cache: 'no-store'});
    renderStatus(await r.json());
  } catch(e) {
    document.getElementById('stateBadge').className = 'status red';
    document.getElementById('stateBadge').textContent = '页面刷新失败';
    document.getElementById('reasons').innerHTML = `<li>${esc(e)}</li>`;
  }
}
refresh();
startStream();
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
        if parsed.path == "/console":
            from factor_lab.agent_console.server import CONSOLE_HTML
            self._send(200, CONSOLE_HTML.encode("utf-8"), "text/html; charset=utf-8")
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
        if parsed.path == "/api/roadmap":
            body = json.dumps({"items": _roadmap_details()}, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            _stream_logs(self)
            return
        if parsed.path == "/api/agent-output":
            body = json.dumps(
                _agent_output_snapshot(_read_json(LATEST), _read_json(COMPLETION)),
                ensure_ascii=False, indent=2,
            ).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/agent-console/adapters":
            from factor_lab.agent_console.adapters import get_adapters
            body = json.dumps({"adapters": get_adapters()}, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

        # --- Agent Console API ---
        if parsed.path == "/api/agent-console/sessions":
            import uuid as _uuid
            qs = parse_qs(parsed.query)
            agent = qs.get("agent", ["hermes_research"])[0]
            prompt = qs.get("prompt", [""])[0]
            if not prompt.strip():
                self._send(400, b'{"error":"prompt required"}', "application/json")
                return
            from factor_lab.agent_console.adapters import get_adapters
            adapter_ids = {item["id"] for item in get_adapters()}
            if agent not in adapter_ids:
                body = json.dumps({"error": f"unknown agent: {agent}"}).encode()
                self._send(400, body, "application/json; charset=utf-8")
                return
            from factor_lab.agent_console.sessions import create_session
            from factor_lab.agent_console.adapters import start_session
            import threading as _t
            sid = create_session(agent, prompt)
            _t.Thread(target=start_session, args=(sid, agent, prompt), daemon=True).start()
            body = json.dumps({"session_id": sid, "status": "running"}).encode()
            self._send(201, body, "application/json; charset=utf-8")
            return

        if parsed.path.startswith("/api/agent-console/sessions/"):
            parts = parsed.path.split("/")
            if len(parts) >= 6 and parts[5] == "stream":
                sid = parts[4]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                import time as _time
                from factor_lab.agent_console.sessions import SESSIONS_DIR
                last_count = 0
                while True:
                    try:
                        el = SESSIONS_DIR / sid / "events.jsonl"
                        if el.exists():
                            lines = el.read_text().splitlines()
                            for line in lines[last_count:]:
                                self.wfile.write(f"data: {line}\n\n".encode())
                                self.wfile.flush()
                                last_count += 1
                            # 检查是否完成
                            if lines and '"done"' in lines[-1]:
                                break
                        _time.sleep(0.5)
                    except BrokenPipeError:
                        break
                    except Exception:
                        break
                return

            if len(parts) >= 6 and parts[5] == "cancel":
                sid = parts[4]
                from factor_lab.agent_console.adapters import cancel_session
                cancel_session(sid)
                self._send(200, b'{"status":"cancelled"}', "application/json")
                return

            sid = parts[4] if len(parts) >= 5 else ""
            from factor_lab.agent_console.sessions import get_session
            session = get_session(sid)
            body = json.dumps(session, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        """Handle Agent Console mutations used by the browser UI.

        The Console frontend creates and cancels sessions with POST. Keeping this
        separate from do_GET prevents the browser from receiving the stdlib 501
        response for an otherwise valid Agent Console action.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/api/agent-console/sessions":
            qs = parse_qs(parsed.query)
            agent = qs.get("agent", ["hermes_research"])[0]
            prompt = qs.get("prompt", [""])[0]
            if not prompt.strip():
                self._send(400, b'{"error":"prompt required"}', "application/json")
                return
            from factor_lab.agent_console.adapters import get_adapters
            adapter_ids = {item["id"] for item in get_adapters()}
            if agent not in adapter_ids:
                body = json.dumps({"error": f"unknown agent: {agent}"}).encode()
                self._send(400, body, "application/json; charset=utf-8")
                return
            from factor_lab.agent_console.sessions import create_session
            from factor_lab.agent_console.adapters import start_session
            import threading as _t
            sid = create_session(agent, prompt)
            _t.Thread(target=start_session, args=(sid, agent, prompt), daemon=True).start()
            body = json.dumps({"session_id": sid, "status": "running"}).encode()
            self._send(201, body, "application/json; charset=utf-8")
            return

        if parsed.path.startswith("/api/agent-console/sessions/"):
            parts = parsed.path.split("/")
            if len(parts) >= 6 and parts[5] == "cancel":
                sid = parts[4]
                from factor_lab.agent_console.adapters import cancel_session
                cancel_session(sid)
                self._send(200, b'{"status":"cancelled"}', "application/json")
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
