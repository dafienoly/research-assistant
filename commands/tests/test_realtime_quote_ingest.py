"""V5.2 Realtime Quote Ingest — Tests

Covers:
  - Quote model (creation, serialization, completeness)
  - QuoteResult / BatchQuoteResult (construction, summary stats)
  - Provider adapters with mocked underlying providers
  - RealtimeQuoteEngine with mocked registry + adapters
  - Fallback chain behaviour
  - Health tracking integration
  - Edge cases (empty symbols, all fail, unknown source)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pytest

from factor_lab.data_source.quote import Quote, QuoteResult, BatchQuoteResult
from factor_lab.data_source.adapters import (
    EastmoneyQuoteAdapter,
    RsscastQuoteAdapter,
    TencentQuoteAdapter,
    SinaQuoteAdapter,
    get_adapter,
    list_adapters,
)
from factor_lab.data_source.ingest import RealtimeQuoteEngine
from factor_lab.data_source.spec import (
    DataSourceSpec, DataSourceCapability, DataSourceCategory, DataSourceStatus,
)
from factor_lab.data_source.registry import DataRegistry
from factor_lab.data_source.health import HealthTracker


CST = timezone(timedelta(hours=8))

# =========================================================================
# Sample data
# =========================================================================

SAMPLE_EASTMONEY_RAW = {
    "688012": {
        "code": "688012", "name": "中微公司",
        "price": 158.32, "open": 156.50, "high": 159.80, "low": 155.20,
        "volume": 2_850_000, "amount": 452_000_000.0,
        "change_pct": 1.25, "change_amount": 1.96,
        "provider": "eastmoney_direct",
    },
    "002371": {
        "code": "002371", "name": "北方华创",
        "price": 312.50, "open": 310.00, "high": 315.00, "low": 308.50,
        "volume": 1_200_000, "amount": 376_000_000.0,
        "change_pct": -0.85, "change_amount": -2.68,
        "provider": "eastmoney_direct",
    },
}

SAMPLE_RSSCAST_RAW = {
    "688012": {
        "code": "688012", "name": "中微公司",
        "price": 158.30, "open": 156.50, "high": 159.80, "low": 155.20,
        "volume": 2_850_000, "amount": 452_000_000.0,
        "change_pct": 1.25, "change_amount": 1.96,
        "prev_close": 156.36,
        "amplitude": 2.95, "turnover_rate": 0.45,
        "provider": "rsscast_mcp",
    },
}

SAMPLE_TENCENT_RAW = {
    "688012": {
        "code": "688012", "name": "中微公司",
        "price": 158.30, "open": 156.50, "high": 159.80, "low": 155.20,
        "volume": 2_850_000, "amount": 452_000_000.0,
        "change_pct": 1.26, "prev_close": 156.36,
        "amplitude": 2.95, "turnover_rate": 0.45,
        "provider": "tencent",
    },
}

SAMPLE_SINA_RAW = {
    "688012": {
        "code": "688012", "name": "中微公司",
        "price": 158.30, "open": 156.50, "high": 159.80, "low": 155.20,
        "volume": 2_850_000, "amount": 452_000_000.0,
        "change_pct": 1.24, "prev_close": 156.36,
        "provider": "sina",
    },
}


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def isolated_registry(monkeypatch, tmp_path):
    """将注册表根目录重定向到临时目录"""
    from factor_lab.data_source import registry as reg_mod
    from factor_lab.data_source import health as hlth_mod

    test_root = tmp_path / "data_source_registry"
    monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
    monkeypatch.setattr(hlth_mod, "REGISTRY_ROOT", test_root)
    return DataRegistry()


@pytest.fixture()
def seeded_registry(isolated_registry):
    """预填充种子数据的注册表"""
    isolated_registry.seed_defaults()
    return isolated_registry


@pytest.fixture()
def engine(seeded_registry):
    """默认引擎实例"""
    return RealtimeQuoteEngine(registry=seeded_registry)


# =========================================================================
# Quote model tests
# =========================================================================

class TestQuote:
    def test_create_minimal(self):
        """最小字段创建"""
        q = Quote(symbol="688012", price=158.3)
        assert q.symbol == "688012"
        assert q.price == 158.3
        assert q.source_id == ""
        assert q.timestamp != ""

    def test_create_full(self):
        """完整字段创建"""
        q = Quote(
            symbol="688012", name="中微公司",
            price=158.3, open=156.5, high=159.8, low=155.2,
            volume=2_850_000, amount=452_000_000.0,
            change_pct=1.25, change_amount=1.96,
            source_id="eastmoney_direct",
            prev_close=156.36, amplitude=2.95, turnover_rate=0.45,
            bid=158.30, ask=158.32, bid_vol=1000, ask_vol=2000,
        )
        assert q.symbol == "688012"
        assert q.bid == 158.30
        assert q.ask_vol == 2000

    def test_to_dict(self):
        """序列化"""
        q = Quote(symbol="688012", price=158.3, source_id="test")
        d = q.to_dict()
        assert d["symbol"] == "688012"
        assert d["price"] == 158.3
        assert d["source_id"] == "test"
        assert "timestamp" in d

    def test_from_dict(self):
        """反序列化"""
        d = {
            "symbol": "002371", "price": 312.5, "source_id": "test",
            "name": "北方华创", "volume": 1_200_000,
            "timestamp": "2026-07-06T10:30:00+08:00",
        }
        q = Quote.from_dict(d)
        assert q.symbol == "002371"
        assert q.price == 312.5
        assert q.name == "北方华创"
        assert q.volume == 1_200_000

    def test_is_complete(self):
        """完整检查"""
        q1 = Quote(symbol="688012", price=158.3)
        assert q1.is_complete() is True

        q2 = Quote(symbol="688012")  # no price
        assert q2.is_complete() is False

    def test_default_timestamp(self):
        """默认时间戳自动生成"""
        q = Quote(symbol="000001", price=10.0)
        assert "T" in q.timestamp
        assert "+" in q.timestamp  # timezone offset


class TestQuoteResult:
    def test_success_result(self):
        """成功结果"""
        q = Quote(symbol="688012", price=158.3, source_id="em")
        result = QuoteResult(
            symbol="688012", success=True, quote=q,
            source_id="em", latency_ms=45.2,
            fallback_chain=["em"],
        )
        assert result.success is True
        assert result.quote.price == 158.3
        assert result.latency_ms == 45.2

    def test_fail_result(self):
        """失败结果"""
        result = QuoteResult(
            symbol="688012", success=False,
            error="connection_timeout",
            fallback_chain=["em", "rsscast"],
        )
        assert result.success is False
        assert result.quote is None
        assert result.error == "connection_timeout"
        assert len(result.fallback_chain) == 2

    def test_to_dict(self):
        """序列化"""
        q = Quote(symbol="688012", price=100.0)
        result = QuoteResult(symbol="688012", success=True, quote=q)
        d = result.to_dict()
        assert d["symbol"] == "688012"
        assert d["success"] is True
        assert d["quote"]["price"] == 100.0


class TestBatchQuoteResult:
    def test_all_success(self):
        """全成功"""
        results = {
            "688012": QuoteResult(symbol="688012", success=True, source_id="em"),
            "002371": QuoteResult(symbol="002371", success=True, source_id="em"),
        }
        batch = BatchQuoteResult(symbols=["688012", "002371"], results=results)
        assert batch.total_symbols == 2
        assert batch.success_count == 2
        assert batch.fail_count == 0

    def test_partial_failure(self):
        """部分失败"""
        q = Quote(symbol="688012", price=100.0)
        results = {
            "688012": QuoteResult(symbol="688012", success=True, quote=q),
            "002371": QuoteResult(symbol="002371", success=False, error="timeout"),
        }
        batch = BatchQuoteResult(symbols=["688012", "002371"], results=results)
        assert batch.success_count == 1
        assert batch.fail_count == 1

    def test_summary(self):
        """summary 统计"""
        results = {
            "688012": QuoteResult(symbol="688012", success=True),
            "002371": QuoteResult(symbol="002371", success=True),
        }
        batch = BatchQuoteResult(
            symbols=["688012", "002371"],
            results=results,
            total_latency_ms=123.4,
        )
        s = batch.summary()
        assert s["total_symbols"] == 2
        assert s["success_count"] == 2
        assert s["fail_count"] == 0
        assert s["success_rate"] == 100.0
        assert s["total_latency_ms"] == 123.4


# =========================================================================
# Adapter tests (mocked)
# =========================================================================

class TestEastmoneyQuoteAdapter:
    def test_provider_id(self):
        """返回正确的 provider_id"""
        adapter = EastmoneyQuoteAdapter()
        assert adapter.provider_id == "eastmoney_direct"

    def test_fetch_returns_normalised(self, monkeypatch):
        """正常获取返回规范化数据"""
        def mock_get_quotes(self, codes):
            return dict(SAMPLE_EASTMONEY_RAW)
        monkeypatch.setattr(
            "eastmoney_direct.EastmoneyProvider.get_quotes",
            mock_get_quotes,
        )

        adapter = EastmoneyQuoteAdapter()
        result = adapter.fetch(["688012", "002371"])
        assert "688012" in result
        assert result["688012"]["symbol"] == "688012"
        assert result["688012"]["price"] == 158.32
        assert result["688012"]["change_pct"] == 1.25
        assert result["688012"]["source_id"] == "eastmoney_direct"
        assert "688012" in result
        assert result["688012"]["_latency_ms"] >= 0

    def test_fetch_empty_response(self, monkeypatch):
        """空响应"""
        def mock_get_quotes(self, codes):
            return {}
        monkeypatch.setattr(
            "eastmoney_direct.EastmoneyProvider.get_quotes",
            mock_get_quotes,
        )

        adapter = EastmoneyQuoteAdapter()
        result = adapter.fetch(["688012"])
        assert result == {}

    def test_fetch_provider_error(self, monkeypatch):
        """提供者异常"""
        def mock_get_quotes(self, codes):
            raise RuntimeError("connection failed")
        monkeypatch.setattr(
            "eastmoney_direct.EastmoneyProvider.get_quotes",
            mock_get_quotes,
        )

        adapter = EastmoneyQuoteAdapter()
        result = adapter.fetch(["688012"])
        assert result == {}


class TestRsscastQuoteAdapter:
    def test_provider_id(self):
        """返回正确的 provider_id"""
        adapter = RsscastQuoteAdapter()
        assert adapter.provider_id == "rsscast_mcp"

    def test_fetch_returns_normalised(self, monkeypatch):
        """正常获取"""
        def mock_get_quotes(self, codes):
            return dict(SAMPLE_RSSCAST_RAW)
        monkeypatch.setattr(
            "provider_matrix.RSScastProvider.get_quotes",
            mock_get_quotes,
        )

        adapter = RsscastQuoteAdapter()
        result = adapter.fetch(["688012"])
        assert "688012" in result
        assert result["688012"]["price"] == 158.30
        assert result["688012"]["prev_close"] == 156.36
        assert result["688012"]["amplitude"] == 2.95
        assert result["688012"]["source_id"] == "rsscast_mcp"


class TestTencentQuoteAdapter:
    def test_provider_id(self):
        """返回正确的 provider_id"""
        adapter = TencentQuoteAdapter()
        assert adapter.provider_id == "tencent_qt"

    def test_fetch_returns_normalised(self, monkeypatch):
        """正常获取"""
        def mock_get_quotes(self, codes):
            return dict(SAMPLE_TENCENT_RAW)
        monkeypatch.setattr(
            "provider_matrix.TencentProvider.get_quotes",
            mock_get_quotes,
        )

        adapter = TencentQuoteAdapter()
        result = adapter.fetch(["688012"])
        assert result["688012"]["price"] == 158.30
        assert result["688012"]["turnover_rate"] == 0.45
        assert result["688012"]["source_id"] == "tencent_qt"


class TestSinaQuoteAdapter:
    def test_provider_id(self):
        """返回正确的 provider_id"""
        adapter = SinaQuoteAdapter()
        assert adapter.provider_id == "sina"

    def test_fetch_returns_normalised(self, monkeypatch):
        """正常获取"""
        def mock_get_quotes(self, codes):
            return dict(SAMPLE_SINA_RAW)
        monkeypatch.setattr(
            "provider_matrix.SinaProvider.get_quotes",
            mock_get_quotes,
        )

        adapter = SinaQuoteAdapter()
        result = adapter.fetch(["688012"])
        assert result["688012"]["price"] == 158.30
        assert result["688012"]["source_id"] == "sina"


class TestAdapterRegistry:
    def test_get_adapter_known(self):
        """已知适配器可获取"""
        adapter = get_adapter("eastmoney_direct")
        assert adapter is not None
        assert adapter.provider_id == "eastmoney_direct"

    def test_get_adapter_unknown(self):
        """未知适配器返回 None"""
        adapter = get_adapter("nonexistent")
        assert adapter is None

    def test_list_adapters(self):
        """列出所有适配器"""
        adapters = list_adapters()
        assert "eastmoney_direct" in adapters
        assert "rsscast_mcp" in adapters
        assert "tencent_qt" in adapters
        assert "sina" in adapters
        assert len(adapters) >= 4


# =========================================================================
# RealtimeQuoteEngine tests
# =========================================================================

class TestRealtimeQuoteEngine:
    def test_init(self, seeded_registry):
        """引擎初始化"""
        engine = RealtimeQuoteEngine(registry=seeded_registry)
        assert engine.registry is seeded_registry
        assert engine.health is not None
        assert engine.default_cap == "realtime_quote"

    def test_fetch_quote_single_success(self, engine, monkeypatch):
        """单只行情获取成功"""
        def mock_fetch(_, symbols):
            return {
                "688012": {
                    "symbol": "688012", "name": "中微公司",
                    "price": 158.3, "open": 156.5, "high": 159.8,
                    "low": 155.2, "volume": 2_850_000, "amount": 452_000_000.0,
                    "change_pct": 1.25, "change_amount": 1.96,
                    "source_id": "rsscast_mcp",
                    "_latency_ms": 45.0,
                }
            }

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        result = engine.fetch_quote("688012")
        assert result.success is True
        assert result.quote is not None
        assert result.quote.symbol == "688012"
        assert result.quote.price == 158.3
        assert result.quote.name == "中微公司"
        assert result.source_id == "rsscast_mcp"
        assert result.fallback_used is False

    def test_fetch_quotes_batch(self, engine, monkeypatch):
        """批量行情获取"""
        def mock_fetch(_, symbols):
            return {
                "688012": {"symbol": "688012", "price": 158.3, "source_id": "rsscast_mcp", "_latency_ms": 40.0},
                "002371": {"symbol": "002371", "price": 312.5, "source_id": "rsscast_mcp", "_latency_ms": 42.0},
            }

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        results = engine.fetch_quotes(["688012", "002371"])
        assert len(results) == 2
        assert results["688012"].success is True
        assert results["002371"].success is True
        assert results["688012"].quote.price == 158.3
        assert results["002371"].quote.price == 312.5

    def test_fetch_batch_wrapper(self, engine, monkeypatch):
        """fetch_batch 包装返回 BatchQuoteResult"""
        def mock_fetch(_, symbols):
            return {
                "688012": {"symbol": "688012", "price": 100.0, "source_id": "rsscast_mcp", "_latency_ms": 30.0},
            }

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        batch = engine.fetch_batch(["688012"])
        assert isinstance(batch, BatchQuoteResult)
        assert batch.success_count == 1
        assert batch.fail_count == 0
        assert batch.summary()["success_rate"] == 100.0

    def test_preferred_source(self, engine, monkeypatch):
        """优先使用指定数据源"""
        calls = []

        class FakeAdapter:
            provider_id = "tencent_qt"
            def fetch(self, symbols):
                calls.append("tencent")
                return {
                    "688012": {"symbol": "688012", "price": 158.0, "source_id": "tencent_qt", "_latency_ms": 30.0},
                }

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            lambda sid: FakeAdapter() if sid == "tencent_qt" else None,
        )

        result = engine.fetch_quote("688012", preferred_source="tencent_qt")
        assert result.success is True
        assert result.source_id == "tencent_qt"
        assert calls == ["tencent"]

    def test_fallback_on_primary_failure(self, engine, monkeypatch):
        """主源失败时降级到备源"""
        adapter_calls = []

        def mock_get_adapter(source_id):
            class PrimaryAdapter:
                provider_id = "eastmoney_direct"
                def fetch(self, symbols):
                    adapter_calls.append("eastmoney")
                    return {}  # primary fails

            class FallbackAdapter:
                provider_id = "tencent_qt"
                def fetch(self, symbols):
                    adapter_calls.append("tencent")
                    return {
                        "688012": {"symbol": "688012", "price": 158.0, "source_id": "tencent_qt", "_latency_ms": 50.0},
                    }

            mapping = {"eastmoney_direct": PrimaryAdapter(), "tencent_qt": FallbackAdapter()}
            return mapping.get(source_id)

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            mock_get_adapter,
        )

        result = engine.fetch_quote("688012", preferred_source="eastmoney_direct")
        assert result.success is True
        assert result.source_id == "tencent_qt"
        assert result.fallback_used is True
        assert adapter_calls == ["eastmoney", "tencent"]

    def test_all_sources_fail(self, engine, monkeypatch):
        """所有源全部失败"""
        def mock_get_adapter(source_id):
            class FailingAdapter:
                provider_id = source_id
                def fetch(self, symbols):
                    return {}
            return FailingAdapter()

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            mock_get_adapter,
        )

        result = engine.fetch_quote("688012")
        assert result.success is False
        assert result.error is not None
        assert result.quote is None

    def test_no_available_source(self, isolated_registry):
        """注册表无可用源"""
        engine = RealtimeQuoteEngine(registry=isolated_registry)
        result = engine.fetch_quote("688012")
        assert result.success is False
        assert "no_available_source" in (result.error or "")

    def test_partial_response(self, engine, monkeypatch):
        """部分符号在返回中出现（另一符号缺失）"""
        def mock_fetch(_, symbols):
            return {
                "688012": {"symbol": "688012", "price": 158.3, "source_id": "rsscast_mcp", "_latency_ms": 40.0},
            }

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        results = engine.fetch_quotes(["688012", "002371"])
        assert results["688012"].success is True
        assert results["002371"].success is False
        assert "symbol_not_in" in results["002371"].error

    def test_health_tracking_on_success(self, engine, monkeypatch):
        """成功调用记录健康"""
        def mock_fetch(_, symbols):
            return {"688012": {"symbol": "688012", "price": 100.0, "source_id": "rsscast_mcp", "_latency_ms": 30.0}}

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        engine.fetch_quote("688012")
        report = engine.health.check_health("rsscast_mcp")
        assert report.total_calls >= 1
        assert report.success_rate > 0

    def test_health_tracking_on_failure(self, engine, monkeypatch):
        """失败调用记录健康"""
        def mock_get_adapter(source_id):
            class FailingAdapter:
                provider_id = source_id
                def fetch(self, symbols):
                    return {}
            return FailingAdapter()

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            mock_get_adapter,
        )

        engine.fetch_quote("688012")
        report = engine.health.check_health("rsscast_mcp")
        assert report.total_calls >= 1

    def test_quote_produced_has_correct_fields(self, engine, monkeypatch):
        """生成的 Quote 对象字段正确"""
        def mock_fetch(_, symbols):
            return {
                "688012": {
                    "symbol": "688012", "name": "中微公司",
                    "price": 158.3, "open": 156.5, "high": 159.8,
                    "low": 155.2, "volume": 2_850_000, "amount": 452_000_000.0,
                    "change_pct": 1.25, "change_amount": 1.96,
                    "prev_close": 156.36, "amplitude": 2.95, "turnover_rate": 0.45,
                    "source_id": "rsscast_mcp", "_latency_ms": 35.0,
                }
            }

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        result = engine.fetch_quote("688012")
        q = result.quote
        assert q.price == 158.3
        assert q.open == 156.5
        assert q.high == 159.8
        assert q.low == 155.2
        assert q.volume == 2_850_000
        assert q.amount == 452_000_000.0
        assert q.change_pct == 1.25
        assert q.change_amount == 1.96
        assert q.prev_close == 156.36
        assert q.amplitude == 2.95
        assert q.turnover_rate == 0.45

    def test_empty_symbols_list(self, engine, monkeypatch):
        """空符号列表"""
        results = engine.fetch_quotes([])
        assert results == {}


# =========================================================================
# Integration-style tests
# =========================================================================

class TestEngineWithRealAdapterMock:
    """Engine + adapter integration via monkeypatched provider"""

    def test_engine_eastmoney_adapter(self, engine, monkeypatch):
        """Engine 使用 EastmoneyAdapter 成功"""
        def mock_get_quotes(self, codes):
            return dict(SAMPLE_EASTMONEY_RAW)
        monkeypatch.setattr(
            "eastmoney_direct.EastmoneyProvider.get_quotes",
            mock_get_quotes,
        )

        def mock_get_adapter(source_id):
            if source_id == "eastmoney_direct":
                return EastmoneyQuoteAdapter()
            if source_id == "rsscast_mcp":
                # Return failing adapter so fallback doesn't shadow
                class Fail:
                    provider_id = "rsscast_mcp"
                    def fetch(self, symbols):
                        return {}
                return Fail()
            return None

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            mock_get_adapter,
        )

        result = engine.fetch_quote("688012", preferred_source="eastmoney_direct")
        assert result.success is True
        assert result.source_id == "eastmoney_direct"
        assert result.quote.price == 158.32

    def test_engine_fallback_chain_full(self, engine, monkeypatch):
        """完整降级链：eastmoney → rsscast → tencent"""
        call_order = []

        def mock_get_adapter(source_id):
            if source_id == "eastmoney_direct":
                class EM:
                    provider_id = "eastmoney_direct"
                    def fetch(self, symbols):
                        call_order.append("em")
                        return {}
                return EM()
            if source_id == "rsscast_mcp":
                class RS:
                    provider_id = "rsscast_mcp"
                    def fetch(self, symbols):
                        call_order.append("rsscast")
                        return {}
                return RS()
            if source_id == "tencent_qt":
                class TENC:
                    provider_id = "tencent_qt"
                    def fetch(self, symbols):
                        call_order.append("tencent")
                        return {"688012": {"symbol": "688012", "price": 158.0, "source_id": "tencent_qt", "_latency_ms": 30.0}}
                return TENC()
            return None

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            mock_get_adapter,
        )

        result = engine.fetch_quote("688012", preferred_source="eastmoney_direct")
        assert result.success is True
        assert result.source_id == "tencent_qt"
        assert result.fallback_used is True
        assert call_order == ["em", "rsscast", "tencent"]

    def test_engine_no_fallback_mode(self, engine, monkeypatch):
        """fallback=False 时仅尝试主源"""
        call_order = []

        def mock_get_adapter(source_id):
            if source_id == "eastmoney_direct":
                class EM:
                    provider_id = "eastmoney_direct"
                    def fetch(self, symbols):
                        call_order.append("em")
                        return {}
                return EM()
            return None

        monkeypatch.setattr(
            "factor_lab.data_source.ingest.get_adapter",
            mock_get_adapter,
        )

        result = engine.fetch_quote(
            "688012",
            preferred_source="eastmoney_direct",
            fallback=False,
        )
        assert result.success is False
        assert call_order == ["em"]

    def test_health_tracking_multiple_calls(self, engine, monkeypatch):
        """多次调用后健康追踪累计"""
        def mock_fetch(_, symbols):
            return {"688012": {"symbol": "688012", "price": 100.0, "source_id": "rsscast_mcp", "_latency_ms": 30.0}}

        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        for _ in range(5):
            engine.fetch_quote("688012")

        report = engine.health.check_health("rsscast_mcp")
        assert report.total_calls >= 5
        assert report.success_rate == 100.0
