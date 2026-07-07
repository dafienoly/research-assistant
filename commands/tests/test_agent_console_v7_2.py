"""测试: V7.2 AgentOps Control Tower — 控制塔

覆盖: session history API, answer_delta 渲染, diagnostic panel,
session 取消流, 版本/Agent 过滤, 错误状态, 产物链接, 控制塔前端完整性.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import threading
from http.server import ThreadingHTTPServer
from urllib.parse import quote
from urllib.request import urlopen
from pathlib import Path

import pytest

from factor_lab.agent_console.schemas import AgentEvent
from factor_lab.agent_console.sessions import (
    create_session, get_session, append_event, update_status,
    list_sessions, SESSIONS_DIR,
)
from factor_lab.agent_console.server import CONSOLE_HTML
from factor_lab.leader.dashboard import _DashboardHandler


# ─── Helpers ─────────────────────────────────────────────────────

def _serve_dashboard():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def _fake_session(monkeypatch, tmp_path, agent="hermes_demo",
                  prompt="测试 prompt", version="V7.2",
                  status="completed", with_answer=True):
    """创建一个伪造 session 用于测试"""
    monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

    sid = create_session(agent, prompt, version=version)
    if with_answer:
        append_event(sid, AgentEvent("answer_delta", sid, data=f"这是来自 {agent} 的回答正文\n支持多行内容\n", status="running"))
        append_event(sid, AgentEvent("diagnostic", sid, data="[诊断] 步骤1: 初始化"))
        append_event(sid, AgentEvent("diagnostic", sid, data="[诊断] 步骤2: 执行"))
    if status == "completed":
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed", agent=agent, prompt=prompt)
    elif status == "failed":
        append_event(sid, AgentEvent("error", sid, data="执行失败", status="failed"))
        update_status(sid, "failed", agent=agent, prompt=prompt)
    elif status == "cancelled":
        update_status(sid, "cancelled", agent=agent, prompt=prompt)
    return sid


# ─── Tests ───────────────────────────────────────────────────────


class TestSessionListAPI:
    """session 历史列表 API 测试"""

    def test_list_sessions_returns_sessions(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = _fake_session(monkeypatch, tmp_path)
        sessions = list_sessions()
        assert len(sessions) >= 1
        assert sessions[0]["session_id"] == sid
        assert sessions[0]["agent"] == "hermes_demo"
        assert sessions[0]["status"] == "completed"

    def test_list_sessions_returns_multiple(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        s1 = _fake_session(monkeypatch, tmp_path, prompt="第一", version="V7.1")
        s2 = _fake_session(monkeypatch, tmp_path, prompt="第二", version="V7.2")
        sessions = list_sessions()
        assert len(sessions) == 2

    def test_list_sessions_empty_directory(self, tmp_path):
        sessions = list_sessions()
        assert isinstance(sessions, list)

    def test_list_sessions_contains_core_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path)
        sessions = list_sessions()
        s = sessions[0]
        for field in ["session_id", "agent", "version", "status", "prompt",
                       "created_at", "updated_at", "events_count", "has_artifact"]:
            assert field in s, f"缺少字段: {field}"

    def test_list_sessions_artifact_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, with_answer=True)
        sessions = list_sessions()
        assert sessions[0]["has_artifact"] is True

    def test_list_sessions_no_artifact(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, with_answer=False)
        sessions = list_sessions()
        assert sessions[0]["has_artifact"] is False

    def test_list_sessions_limit(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        for i in range(5):
            _fake_session(monkeypatch, tmp_path, prompt=f"s{i}")
        assert len(list_sessions(limit=3)) == 3
        assert len(list_sessions(limit=10)) == 5


class TestSessionListFiltering:
    """session history 过滤能力测试"""

    def test_filter_by_agent(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, agent="hermes_demo", prompt="demo")
        _fake_session(monkeypatch, tmp_path, agent="claude_code", prompt="claude")

        assert len(list_sessions(agent="hermes_demo")) == 1
        assert len(list_sessions(agent="claude_code")) == 1
        assert len(list_sessions(agent="hermes_research")) == 0

    def test_filter_by_version(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, version="V7.1")
        _fake_session(monkeypatch, tmp_path, version="V7.2")

        assert len(list_sessions(version="V7.2")) == 1
        assert len(list_sessions(version="V6.0")) == 0

    def test_filter_by_status(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, status="completed")
        _fake_session(monkeypatch, tmp_path, status="failed")
        _fake_session(monkeypatch, tmp_path, status="cancelled")

        assert len(list_sessions(status_filter="completed")) == 1
        assert len(list_sessions(status_filter="failed")) == 1
        assert len(list_sessions(status_filter="cancelled")) == 1

    def test_filter_combined(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, agent="claude_code", version="V7.2", status="completed")
        _fake_session(monkeypatch, tmp_path, agent="hermes_demo", version="V7.2", status="failed")

        result = list_sessions(agent="claude_code", version="V7.2", status_filter="completed")
        assert len(result) == 1
        assert result[0]["agent"] == "claude_code"

    def test_filter_combined_no_match(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, agent="hermes_demo", version="V7.1")
        assert len(list_sessions(agent="claude_code", version="V7.2")) == 0


class TestSessionsListEndpoint:
    """HTTP API /api/agent-console/sessions-list 端点测试"""

    def test_sessions_list_endpoint(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, agent="hermes_demo", version="V7.2")

        server, base = _serve_dashboard()
        try:
            with urlopen(f"{base}/api/agent-console/sessions-list", timeout=5) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert "sessions" in data
                assert len(data["sessions"]) >= 1
        finally:
            server.shutdown()

    def test_sessions_list_filter_version(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, version="V7.2")

        server, base = _serve_dashboard()
        try:
            with urlopen(f"{base}/api/agent-console/sessions-list?version=V7.2", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert all(s["version"] == "V7.2" for s in data["sessions"])
        finally:
            server.shutdown()

    def test_sessions_list_filter_agent(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        _fake_session(monkeypatch, tmp_path, agent="claude_code", version="V7.2")
        _fake_session(monkeypatch, tmp_path, agent="hermes_demo", version="V7.1")

        server, base = _serve_dashboard()
        try:
            with urlopen(f"{base}/api/agent-console/sessions-list?agent=claude_code", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert all(s["agent"] == "claude_code" for s in data["sessions"])
        finally:
            server.shutdown()

    def test_sessions_list_empty(self, tmp_path):
        server, base = _serve_dashboard()
        try:
            with urlopen(f"{base}/api/agent-console/sessions-list", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert "sessions" in data
        finally:
            server.shutdown()


class TestAnswerDeltaRendering:
    """answer_delta 回答正文渲染测试"""

    def test_answer_delta_content_stored(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_demo", "test answer content")
        expected = "这是实时回答正文内容"
        append_event(sid, AgentEvent("answer_delta", sid, data=expected, status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert expected in session["answer"]

    def test_answer_delta_multiple_chunks(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_research", "multi chunk")
        for chunk in ["第一段\n", "第二段\n", "第三段"]:
            append_event(sid, AgentEvent("answer_delta", sid, data=chunk, status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert "第一段" in session["answer"]
        assert "第二段" in session["answer"]
        assert "第三段" in session["answer"]

    def test_answer_delta_with_multiline(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("claude_code", "multiline test")
        text = "\n".join([f"行{i}" for i in range(20)])
        append_event(sid, AgentEvent("answer_delta", sid, data=text, status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        for i in range(20):
            assert f"行{i}" in session["answer"]

    def test_answer_delta_empty_not_stored(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_demo", "empty test")
        append_event(sid, AgentEvent("answer_delta", sid, data="", status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert session["answer"] == "" or session["answer"] == ""

    def test_answer_delta_stream_events_in_order(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_research", "order test")
        for i in range(5):
            append_event(sid, AgentEvent("answer_delta", sid, data=f"chunk{i}\n", status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert "chunk0" in session["answer"]
        # 事件流顺序
        events = session["events"]
        answer_events = [e for e in events if e["type"] == "answer_delta"]
        assert len(answer_events) == 5
        assert answer_events[0]["data"] == "chunk0\n"
        assert answer_events[-1]["data"] == "chunk4\n"


class TestDiagnosticPanel:
    """diagnostic panel — 诊断面板测试"""

    def test_diagnostic_events_stored(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_demo", "diag test")
        diag_lines = ["[诊断] 加载数据", "[诊断] 计算因子", "[诊断] 生成报告"]
        for line in diag_lines:
            append_event(sid, AgentEvent("diagnostic", sid, data=line, status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert len(session["diagnostics"]) == 3
        assert session["diagnostics"][0] == "[诊断] 加载数据"

    def test_diagnostic_limit_50(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_research", "many diag")
        for i in range(60):
            append_event(sid, AgentEvent("diagnostic", sid, data=f"[诊断] step{i}", status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert len(session["diagnostics"]) <= 50

    def test_diagnostic_mixed_with_answer(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("claude_code", "mixed")
        append_event(sid, AgentEvent("answer_delta", sid, data="回答正文", status="running"))
        append_event(sid, AgentEvent("diagnostic", sid, data="诊断信息", status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert "回答正文" in session["answer"]
        assert "诊断信息" in session["diagnostics"]


class TestSessionCancelFlow:
    """session 取消流测试"""

    def test_cancel_flow_endpoint(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_demo", "cancel test")
        update_status(sid, "running")

        from factor_lab.agent_console.adapters import cancel_session
        cancel_session(sid)

        session = get_session(sid)
        assert session["status"] == "cancelled"
        done_events = [e for e in session["events"] if e["type"] == "done"]
        assert len(done_events) >= 1
        assert done_events[-1]["status"] == "cancelled"

    def test_cancel_api_via_http(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_research", "http cancel")
        update_status(sid, "running")

        server, base = _serve_dashboard()
        try:
            with urlopen(f"{base}/api/agent-console/sessions/{sid}/cancel",
                         data=b"", timeout=5) as resp:
                assert resp.status == 200
                assert json.loads(resp.read().decode("utf-8"))["status"] == "cancelled"

            session = get_session(sid)
            assert session["status"] == "cancelled"
        finally:
            server.shutdown()

    def test_cancel_already_completed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("claude_code", "already done")
        update_status(sid, "completed")

        from factor_lab.agent_console.adapters import cancel_session
        cancel_session(sid)

        session = get_session(sid)
        # 取消会覆盖状态
        assert session["status"] == "cancelled"

    def test_cancel_nonexistent_session(self):
        from factor_lab.agent_console.adapters import cancel_session
        # 不应抛出异常
        cancel_session("nonexistent_999")


class TestConsoleFrontend:
    """控制塔前端完整性测试"""

    def test_console_html_has_session_history_sidebar(self):
        # 侧边栏
        assert "会话历史" in CONSOLE_HTML
        assert "sessions-list" in CONSOLE_HTML
        assert "sidebar" in CONSOLE_HTML

    def test_console_html_has_filter_controls(self):
        assert "filterAgent" in CONSOLE_HTML
        assert "filterStatus" in CONSOLE_HTML
        assert "filterVersion" in CONSOLE_HTML

    def test_console_html_has_answer_delta_sse(self):
        assert "answer_delta" in CONSOLE_HTML
        assert "EventSource" in CONSOLE_HTML
        assert "/stream" in CONSOLE_HTML

    def test_console_html_has_diagnostic_panel(self):
        assert "diagnostic" in CONSOLE_HTML
        assert "toggleDiagnostic" in CONSOLE_HTML

    def test_console_html_has_cancel_support(self):
        assert "cancelSession" in CONSOLE_HTML
        assert "/cancel" in CONSOLE_HTML

    def test_console_html_has_artifact_links(self):
        assert "has_artifact" in CONSOLE_HTML

    def test_console_html_has_session_list_auto_refresh(self):
        assert "loadSessions()" in CONSOLE_HTML
        assert "setInterval(loadSessions, 15000)" in CONSOLE_HTML

    def test_console_html_has_status_labels(self):
        for label in ["运行中", "已完成", "失败", "已取消"]:
            assert label in CONSOLE_HTML

    def test_console_html_has_version_agent_3_adapters(self):
        for adapter_id in ["hermes_demo", "hermes_research", "claude_code"]:
            assert adapter_id in CONSOLE_HTML

    def test_console_html_title_contains_control_tower(self):
        assert "控制塔" in CONSOLE_HTML


class TestSessionLoad:
    """加载历史 session 并验证内容测试"""

    def test_load_session_returns_answer(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("hermes_research", "research task", version="V7.2")
        append_event(sid, AgentEvent("answer_delta", sid, data="## 分析结果\n\n因子表现良好", status="running"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        assert session["answer"] == "## 分析结果\n\n因子表现良好"
        assert session["version"] == "V7.2"
        assert session["agent"] == "hermes_research"

    def test_load_session_returns_events_in_order(self, monkeypatch, tmp_path):
        monkeypatch.setattr("factor_lab.agent_console.sessions.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("factor_lab.agent_console.sessions.BACKUP_DIR", tmp_path / "backups")

        sid = create_session("claude_code", "event order")
        append_event(sid, AgentEvent("answer_delta", sid, data="A", status="running"))
        append_event(sid, AgentEvent("diagnostic", sid, data="D1"))
        append_event(sid, AgentEvent("answer_delta", sid, data="B", status="running"))
        append_event(sid, AgentEvent("diagnostic", sid, data="D2"))
        append_event(sid, AgentEvent("done", sid, data="", status="completed"))
        update_status(sid, "completed")

        session = get_session(sid)
        events = session["events"]
        types = [e["type"] for e in events]
        assert types == ["answer_delta", "diagnostic", "answer_delta", "diagnostic", "done"]


class TestErrorHandling:
    """控制塔错误处理测试"""

    def test_session_not_found(self):
        session = get_session("nonexistent_999")
        assert "error" in session
        assert session["error"] == "not found"

    def test_list_sessions_tolerates_corrupt_dir(self, tmp_path):
        bad_dir = tmp_path / "ac_corrupt_001"
        bad_dir.mkdir()
        (bad_dir / "request.json").write_text("not valid json{{{")
        sessions = list_sessions()
        assert isinstance(sessions, list)

    def test_list_sessions_tolerates_missing_request_json(self, tmp_path):
        bad_dir = tmp_path / "ac_no_request_001"
        bad_dir.mkdir()
        sessions = list_sessions()
        assert isinstance(sessions, list)

    def test_sessions_list_api_tolerates_missing(self):
        server, base = _serve_dashboard()
        try:
            with urlopen(f"{base}/api/agent-console/sessions-list?version=V9.999", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert len(data["sessions"]) == 0
        finally:
            server.shutdown()
