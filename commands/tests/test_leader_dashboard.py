from factor_lab.agent_console.server import CONSOLE_HTML
from factor_lab.leader.dashboard import DASHBOARD_HTML, _DashboardHandler, collect_status


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
    assert "agentOutput" in DASHBOARD_HTML


def test_agent_console_post_endpoints_are_implemented():
    assert hasattr(_DashboardHandler, "do_POST")
    assert "/api/agent-console/sessions" in CONSOLE_HTML
    assert "method: 'POST'" in CONSOLE_HTML
    assert "/cancel" in CONSOLE_HTML
