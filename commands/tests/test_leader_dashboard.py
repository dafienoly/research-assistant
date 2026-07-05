from factor_lab.leader.dashboard import DASHBOARD_HTML, collect_status


def test_dashboard_collect_status_has_core_sections():
    status = collect_status()
    for key in [
        "generated_at",
        "state",
        "health",
        "roadmap_progress",
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


def test_dashboard_html_uses_status_api_and_auto_refresh():
    assert "/api/status" in DASHBOARD_HTML
    assert "setInterval(refresh, 5000)" in DASHBOARD_HTML
    assert "Hermes 自动版本推进监控台" in DASHBOARD_HTML
    assert "Hermes 实时运行输出" in DASHBOARD_HTML
    assert "agentOutput" in DASHBOARD_HTML
