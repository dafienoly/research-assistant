import json
import threading
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from urllib.parse import quote
from urllib.request import urlopen

from factor_lab.agent_console.adapters import get_adapters
from factor_lab.agent_console.schemas import AgentEvent
from factor_lab.agent_console.server import CONSOLE_HTML
from factor_lab.agent_console.sessions import append_event
from factor_lab.leader.dashboard import DASHBOARD_HTML, _DashboardHandler, _current_answer_snapshot, _derive_state, collect_status


def _serve_dashboard():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_dashboard_collect_status_has_core_sections():
    status = collect_status()
    for key in [
        "generated_at",
        "state",
        "health",
        "roadmap_progress",
        "roadmap_details",
        "cursor",
        "latest",
        "latest_completion",
        "backend",
        "git",
        "latest_task_snapshot",
        "current_answer",
        "agent_output",
        "log_tail",
    ]:
        assert key in status
    assert "snippets" in status["agent_output"]
    assert status["state"]["level"] in {"green", "yellow", "red"}
    assert "current_version" in status["cursor"]
    versions = [item["version"] for item in status["roadmap_details"]]
    assert "V3.0" in versions
    assert "V8.9" in versions
    assert "V9.0" in versions


def test_dashboard_html_uses_status_api_sse_and_auto_refresh():
    assert "/api/status" in DASHBOARD_HTML
    assert "/api/stream" in DASHBOARD_HTML
    assert "new EventSource('/api/stream')" in DASHBOARD_HTML
    assert "setInterval(refresh, 5000)" in DASHBOARD_HTML
    assert "Hermes 自动版本推进监控台" in DASHBOARD_HTML
    assert "SSE 实时日志流" in DASHBOARD_HTML
    assert "固定版本规划详情" in DASHBOARD_HTML
    assert "roadmapDetails" in DASHBOARD_HTML
    assert "当前自动开发回答" in DASHBOARD_HTML
    assert "currentAnswer" in DASHBOARD_HTML
    assert "current_answer" in DASHBOARD_HTML
    assert "agentOutput" in DASHBOARD_HTML


def test_current_answer_snapshot_reads_latest_log(tmp_path, monkeypatch):
    from factor_lab.leader import dashboard

    run_id = "auto_test_current"
    log_dir = tmp_path / run_id
    log_dir.mkdir()
    log_file = log_dir / "T001.log"
    log_file.write_text(
        "$ claude --print --output-format stream-json --permission-mode bypassPermissions\n"
        "# started_at=2026-07-05T00:00:00+08:00\n\n"
        "hello stream\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard, "AGENT_LOG_ROOT", tmp_path)
    answer = _current_answer_snapshot({"run_id": run_id, "current": "V3.1"})
    assert answer["streaming_mode"] == "stream-json"
    assert answer["permission_mode"] == "bypassPermissions"
    assert answer["text"] == "hello stream"


def test_current_answer_snapshot_skips_non_auto_and_dry_run(tmp_path, monkeypatch):
    from factor_lab.leader import dashboard

    monkeypatch.setattr(dashboard, "AGENT_LOG_ROOT", tmp_path)
    assert _current_answer_snapshot({"run_id": "roadmap_1", "current": "V3.1"})["text"] == ""

    run_id = "auto_dry"
    log_dir = tmp_path / run_id
    log_dir.mkdir()
    (log_dir / "T001.log").write_text("[DRY-RUN] 未调用模型\n", encoding="utf-8")
    assert _current_answer_snapshot({"run_id": run_id, "current": "V3.1"})["text"] == ""


def test_agent_console_post_endpoints_are_implemented():
    assert hasattr(_DashboardHandler, "do_POST")
    assert "/api/agent-console/sessions" in CONSOLE_HTML
    assert "method: 'POST'" in CONSOLE_HTML
    assert "/cancel" in CONSOLE_HTML


def test_dashboard_ignores_stale_completion_status():
    state = _derive_state(
        health_info={"cron_service_running": True, "crontab_registered": True, "tick_age_seconds": 1, "lock_status": "free"},
        latest={"current": "V3.0.1", "status": "pending"},
        completion={"version": "live_execution", "status": "blocked"},
        cursor={"current_version": "V3.0.1"},
        log_lines=[],
        git={"dirty": False},
    )
    assert state["level"] == "green"
    assert any("忽略旧 completion" in reason for reason in state["reasons"])


def test_agent_console_adapter_metadata_declares_buffered_claude():
    adapters = {item["id"]: item for item in get_adapters()}
    assert {"hermes_demo", "hermes_research", "claude_code"} <= set(adapters)
    assert adapters["claude_code"]["streaming"] == "buffered"
    assert adapters["claude_code"]["supports_realtime_delta"] is False
    assert adapters["hermes_research"]["label"] == "Hermes Agent (研究模式)"


def test_agent_console_post_stream_and_cancel(monkeypatch, tmp_path):
    from factor_lab.agent_console import adapters, sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)

    def fake_start_session(sid, agent, prompt):
        append_event(sid, AgentEvent("answer_delta", sid, data=f"answer:{agent}:{prompt}", status="running"))
        append_event(sid, AgentEvent("diagnostic", sid, data="diag"))
        append_event(sid, AgentEvent("done", sid, status="completed"))

    monkeypatch.setattr(adapters, "start_session", fake_start_session)

    server, base = _serve_dashboard()
    try:
        prompt = quote("ping")
        with urlopen(f"{base}/api/agent-console/sessions?agent=hermes_research&prompt={prompt}",
                     data=b"", timeout=5) as resp:
            assert resp.status == 201
            created = json.loads(resp.read().decode("utf-8"))
        sid = created["session_id"]

        stream_parts = []
        with urlopen(f"{base}/api/agent-console/sessions/{sid}/stream", timeout=5) as resp:
            for _ in range(20):
                line = resp.readline().decode("utf-8")
                stream_parts.append(line)
                if '"type": "done"' in line:
                    break
        stream_body = "".join(stream_parts)
        assert "answer:hermes_research:ping" in stream_body
        assert '"type": "diagnostic"' in stream_body
        assert '"type": "done"' in stream_body

        with urlopen(f"{base}/api/agent-console/sessions/{sid}/cancel", data=b"", timeout=5) as resp:
            assert resp.status == 200
            assert json.loads(resp.read().decode("utf-8"))["status"] == "cancelled"
    finally:
        server.shutdown()


def test_agent_console_rejects_unknown_agent(monkeypatch, tmp_path):
    from factor_lab.agent_console import sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    server, base = _serve_dashboard()
    try:
        try:
            urlopen(f"{base}/api/agent-console/sessions?agent=hermes&prompt=ping", data=b"", timeout=5)
        except Exception as exc:
            assert getattr(exc, "code", None) == 400
        else:
            raise AssertionError("unknown agent should be rejected")
    finally:
        server.shutdown()


def test_hermes_research_marks_failed_command_as_failed(monkeypatch, tmp_path):
    from factor_lab.agent_console import adapters, sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    sid = sessions.create_session("hermes_research", "status")

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=2, stdout="broken output\n", stderr="boom\n")

    monkeypatch.setattr(adapters.subprocess, "run", fake_run)
    adapters._run_hermes_research(sid, "status")

    session = sessions.get_session(sid)
    done_events = [event for event in session["events"] if event["type"] == "done"]
    assert done_events[-1]["status"] == "failed"
    assert "分析未完全完成" in session["answer"]


def test_claude_buffered_failure_marks_failed(monkeypatch, tmp_path):
    from factor_lab.agent_console import adapters, sessions

    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
    sid = sessions.create_session("claude_code", "hello")
    monkeypatch.setattr(adapters.pty, "openpty", lambda: (_ for _ in ()).throw(OSError("no pty")))

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=7, stdout="", stderr="claude failed\n")

    monkeypatch.setattr(adapters.subprocess, "run", fake_run)
    adapters._run_claude(sid, "hello")

    session = sessions.get_session(sid)
    done_events = [event for event in session["events"] if event["type"] == "done"]
    assert done_events[-1]["status"] == "failed"
    assert "claude failed" in session["answer"]
