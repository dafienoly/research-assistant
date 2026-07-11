from __future__ import annotations

import importlib

import pytest


def test_mx_fetch_step_requires_environment_credential(monkeypatch) -> None:
    module = importlib.import_module("scripts.mx_fetch_step")
    monkeypatch.setattr(module, "APIKEY", "")

    with pytest.raises(RuntimeError, match="MX_APIKEY is required"):
        module.fetch_table({})
