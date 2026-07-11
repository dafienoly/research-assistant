from __future__ import annotations

import pandas as pd
import pytest

import factor_lab.data.tushare_client as module
from factor_lab.data.tushare_client import TushareClient


class FailedPro:
    def forecast(self, **_params):
        raise ValueError("bad gateway payload")


class EmptyPro:
    def forecast(self, **_params):
        return pd.DataFrame()


def client(pro) -> TushareClient:
    instance = TushareClient(token="test")
    instance._pro = pro
    instance._rate_limit = lambda: None
    return instance


def test_query_default_remains_backward_compatible_on_provider_failure(monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    assert client(FailedPro())._query("forecast").empty


def test_query_strict_raises_after_provider_failure(monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="request failed"):
        client(FailedPro())._query("forecast", raise_on_failure=True)


def test_query_strict_preserves_legitimate_empty_response():
    assert client(EmptyPro())._query("forecast", raise_on_failure=True).empty
