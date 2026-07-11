from pathlib import Path

import pytest

import scripts.register_strategy_alpha as registration


def test_one_off_strategy_registration_is_retired() -> None:
    with pytest.raises(SystemExit, match="governed alpha candidate"):
        registration.main()


def test_retired_script_cannot_forge_metrics_or_promote() -> None:
    source = Path(registration.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "register_alpha",
        "status='backtested'",
        '"status": "backtested"',
        "peer_benchmark_result",
        "ic_mean_history",
        "272.1",
        "25.2",
        "49.31",
    ):
        assert forbidden not in source
