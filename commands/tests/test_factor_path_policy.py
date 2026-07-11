from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "commands/factor_lab/pipeline.py",
    "commands/factor_lab/walk_forward.py",
    "commands/factor_lab/validation/rolling_validator.py",
    "commands/factor_lab/orthogonality/ret5_filter_validator.py",
    "commands/factor_lab/validate_factor.py",
    "commands/factor_lab/alpha/event_loader.py",
    "commands/factor_lab/alpha/industry_mapper.py",
)


def test_factor_modules_do_not_bind_to_developer_home() -> None:
    for relative in MODULES:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "/home/ly/.hermes/research-assistant" not in source, relative


def test_factor_report_roots_are_configurable() -> None:
    pipeline = (ROOT / "commands/factor_lab/pipeline.py").read_text(encoding="utf-8")
    walk_forward = (ROOT / "commands/factor_lab/walk_forward.py").read_text(encoding="utf-8")
    rolling = (ROOT / "commands/factor_lab/validation/rolling_validator.py").read_text(encoding="utf-8")
    assert "HERMES_FACTOR_REPORT_ROOT" in pipeline
    assert "HERMES_WALK_FORWARD_REPORT_ROOT" in walk_forward
    assert "HERMES_ROLLING_VALIDATION_REPORT_ROOT" in rolling
