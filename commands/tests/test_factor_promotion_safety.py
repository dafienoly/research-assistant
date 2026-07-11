from __future__ import annotations

import json

import factor_lab.pipeline_confirm as pipeline_confirm
from factor_lab.shadow_observer import ShadowObserver


def test_shadow_ic_history_is_sorted_by_validation_time_not_ic_value(tmp_path) -> None:
    observer = ShadowObserver()
    observer.cfg.RESULT_DIR = tmp_path
    observations = [
        ("2026-07-03", -0.05),
        ("2026-07-01", 0.10),
        ("2026-07-02", 0.03),
    ]
    for index, (validated_at, ic_mean) in enumerate(observations):
        run = tmp_path / f"run-{index}"
        run.mkdir()
        (run / "factor_meta.json").write_text(
            json.dumps(
                {"name": "safe_factor", "validated_at": validated_at, "ic_mean": ic_mean}
            ),
            encoding="utf-8",
        )

    assert observer._collect_ic_history("safe_factor", "2026-07-01") == [0.10, 0.03, -0.05]


def test_human_confirmation_keeps_factor_disabled_until_shadow_and_oos(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "registry"
    alpha_dir = registry_root / "alpha-safe"
    alpha_dir.mkdir(parents=True)
    registry = registry_root / "registry_index.json"
    pending = registry_root / "pending_confirmations.json"
    spec = alpha_dir / "alpha_spec.json"
    registry.write_text(
        json.dumps([{"alpha_id": "alpha-safe", "status": "draft", "enabled": False}]),
        encoding="utf-8",
    )
    pending.write_text(
        json.dumps([{"alpha_id": "alpha-safe", "name": "safe", "status": "pending"}]),
        encoding="utf-8",
    )
    spec.write_text(
        json.dumps({"alpha_id": "alpha-safe", "status": "draft", "enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline_confirm, "ALPHA_REGISTRY_ROOT", registry_root)
    monkeypatch.setattr(pipeline_confirm, "REGISTRY_INDEX", registry)
    monkeypatch.setattr(pipeline_confirm, "PENDING_FILE", pending)
    monkeypatch.setattr(ShadowObserver, "mark_observing", lambda self, alpha_id: None)
    monkeypatch.setattr("factor_lab.notify.notify_goal_done", lambda *args, **kwargs: None)

    result = pipeline_confirm.cmd_confirm("alpha-safe")

    persisted = json.loads(registry.read_text(encoding="utf-8"))[0]
    persisted_spec = json.loads(spec.read_text(encoding="utf-8"))
    assert "进入影子观察" in result
    for row in (persisted, persisted_spec):
        assert row["status"] == "human_approved_shadow"
        assert row["enabled"] is False
        assert row["paper_enabled"] is False
        assert row["live_enabled"] is False
