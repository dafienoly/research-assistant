from __future__ import annotations

import sys

import hermes_cli


def test_factor_mining_cli_fails_closed_without_canonical_inputs(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(sys, "argv", ["hermes_cli.py", "factor:mine"])

    hermes_cli.main()

    output = capsys.readouterr().out
    assert "已阻断" in output
    assert "不会生成演示行情" in output


def test_factor_registration_rejects_demo_placeholder(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys, "argv", ["hermes_cli.py", "factor:mine-register"]
    )

    hermes_cli.main()

    output = capsys.readouterr().out
    assert "已阻断" in output
    assert "candidate/promotion" in output


def test_strategy_report_requires_explicit_return_file(capsys) -> None:
    hermes_cli._handle_strategy_report([])

    assert "缺少 --from-strategy-returns" in capsys.readouterr().out


def test_sector_research_clis_do_not_execute_demo_data(capsys) -> None:
    hermes_cli._handle_sector_rotation([])
    hermes_cli._handle_sector_rankings([])

    output = capsys.readouterr().out
    assert output.count("已阻断") == 2
    assert output.count("随机演示行情") == 2
