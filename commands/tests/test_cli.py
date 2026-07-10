from factor_lab.vnext.cli import handle


def test_cli_declines_unknown_command():
    assert handle("not:a:vnext:command", []) is False


def test_cli_disable_gate_is_fail_visible(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_VNEXT_ENABLED", "false")
    assert handle("broker:qmt-probe", []) is True
    output = capsys.readouterr().out
    assert '"status": "BLOCKED"' in output
    assert '"real_broker_called": false' in output
