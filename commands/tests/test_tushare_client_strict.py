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


def test_rate_limit_uses_current_window_start_not_future_boundary(monkeypatch):
    instance = TushareClient(token="test")
    instance._rate_limit_reset = 1_000.0
    instance._request_count = 120
    instance._last_request_time = 0.0
    sleeps = []
    monkeypatch.setattr(module.time, "time", lambda: 1_030.0)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)

    instance._rate_limit()

    assert sleeps == [31.0]
    assert instance._request_count == 1
    assert instance._rate_limit_reset == 1_030.0


def test_rate_limit_resets_elapsed_minute_without_sleep(monkeypatch):
    instance = TushareClient(token="test")
    instance._rate_limit_reset = 1_000.0
    instance._request_count = 120
    instance._last_request_time = 0.0
    sleeps = []
    monkeypatch.setattr(module.time, "time", lambda: 1_061.0)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)

    instance._rate_limit()

    assert sleeps == []
    assert instance._request_count == 1
    assert instance._rate_limit_reset == 1_061.0
