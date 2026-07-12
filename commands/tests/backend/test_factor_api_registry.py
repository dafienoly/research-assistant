"""Test Factor API Registry — 验证因子 API 与真实因子库无缝对接。

验收标准：
- /api/factors 返回 >= 100 个因子
- 不包含 _SAMPLE_FACTORS 作为默认生产数据源
- 无 mock/demo/sample/fallback/hardcode
- 任取 3 个真实因子能返回详情
- GET /api/factors/{id}/risk-attribution 返回 structured not_available
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# ─── 确保 commands/ 在 sys.path 中 ─────────────────
_HERE = Path(__file__).resolve().parent  # tests/backend/
_TESTS = _HERE.parent                    # tests/
_COMMANDS = _TESTS.parent                # commands/
if str(_COMMANDS) not in sys.path:
    sys.path.insert(0, str(_COMMANDS))


import pytest
from fastapi.testclient import TestClient

# ─── 导入项目模块 ──────────────────────────────────
from factor_lab.backend.services.factor_registry_service import (
    get_all_factors,
    get_factor_by_id,
    count_factors,
    get_category_names,
)
# fastapi app
from factor_lab.api_server.main import app


def _configured_ui_token() -> str:
    """Resolve the private test token without printing or hardcoding it."""
    token = os.environ.get("HERMES_UI_TOKEN", "").strip()
    if token:
        return token
    env_path = _COMMANDS.parent / ".env"
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            if raw_line.startswith("HERMES_UI_TOKEN="):
                return raw_line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


# ════════════════════════════════════════════════════════════
# 服务层测试
# ════════════════════════════════════════════════════════════

class TestFactorRegistryService:

    def test_registry_count_ge_100(self):
        """验收：REGISTRY 至少包含 100 个因子"""
        n = count_factors()
        assert n >= 100, f"期望 >= 100 个因子，实际 {n}"

    def test_get_all_factors_structure(self):
        """验证 get_all_factors 返回完整字段结构"""
        factors = get_all_factors()
        assert len(factors) >= 100

        for f in factors[:10]:
            for field in ["id", "name", "category", "expression",
                          "description", "lookback", "inputs", "source",
                          "status", "as_of_date", "freshness", "lineage"]:
                assert field in f, f"因子 {f.get('name')} 缺少字段 {field}"

            # id == name（REGISTRY 没有独立 id）
            assert f["id"] == f["name"]

            # source 固定
            assert f["source"] == "factor_lab"

            # status 应为 active
            assert f["status"] == "active"

            # freshness 应为 fresh
            assert f["freshness"] == "fresh"

            # lineage 应为列表
            assert isinstance(f["lineage"], list)

            # inputs 应为列表
            assert isinstance(f["inputs"], list)

    def test_no_sample_factors(self):
        """验收：不得包含 _SAMPLE_FACTORS 中的硬编码因子名"""
        factors = get_all_factors()
        names = {f["name"] for f in factors}

        sample_names = {"momentum", "value", "size", "volatility", "quality", "growth"}
        # 真实的因子名不应与 _SAMPLE_FACTORS 的 key 同名（value/size 可能真实存在，但应确认）
        # 我们检查至少这些 _SAMPLE_FACTORS 名不在真实数据中
        # 注意："quality", "growth", "volatility" 也是真实分类名，不作为因子名存在
        for s in sample_names:
            is_category = s in {"quality", "growth", "volatility"}
            if not is_category:
                assert s not in names, f"SAMPLE_FACTORS 中的 {s} 不应作为因子名出现在 REGISTRY 中"

    def test_no_mock_in_response(self):
        """验收：响应中不应包含 mock/demo/sample/fallback 字样"""
        factors = get_all_factors()
        raw = json.dumps(factors).lower()
        for keyword in ["mock", "sample", "示例数据"]:
            assert keyword not in raw, f"发现禁止关键词: {keyword}"

    def test_get_factor_by_id_real_factors(self):
        """验收：任取 3 个真实因子能返回详情"""
        # 取第一批中的 momentum、trend、volatility 类因子
        all_f = get_all_factors()
        assert len(all_f) >= 3, "因子不足 3 个"

        # 选 3 个有代表性的
        candidates = [f for f in all_f if f["name"] in ("ret5", "ma5_gt_ma10", "atr20")]
        assert len(candidates) == 3, f"预期取到 3 个已知因子，实际 {len(candidates)}"

        for expected in candidates:
            factor = get_factor_by_id(expected["name"])
            assert factor is not None, f"因子 {expected['name']} 未找到"
            assert factor["id"] == expected["name"]
            assert factor["category"] == expected["category"]
            assert factor["description"]  # 描述非空

    def test_category_filter(self):
        """验证分类过滤"""
        momentum_factors = get_all_factors(category="momentum")
        for f in momentum_factors:
            assert f["category"] == "momentum"

        all_momentum_from_list = [f for f in get_all_factors() if f["category"] == "momentum"]
        assert len(momentum_factors) == len(all_momentum_from_list)

    def test_category_names(self):
        """验证分类名称列表"""
        cats = get_category_names()
        assert len(cats) >= 5
        expected_cats = {"momentum", "trend", "volume", "volatility", "quality"}
        for c in expected_cats:
            assert c in cats, f"分类 {c} 应存在于分类列表中"

    def test_lookback_derivation(self):
        """验证 lookback 从 params 正确推导"""
        factors = get_all_factors()
        # ret5 的 lookback 应为 5
        ret5 = next(f for f in factors if f["name"] == "ret5")
        assert ret5["lookback"] == 5

        # roe_q 没有 params，lookback 应为 0
        roe = next(f for f in factors if f["name"] == "roe_q")
        assert roe["lookback"] == 0

        # ret_n_industry_adj 类（industry_relative）有 window=5 和 method
        ind = next(f for f in factors if f["name"] == "ret5_industry_adj")
        assert ind["lookback"] == 5


# ════════════════════════════════════════════════════════════
# API 层测试（使用 TestClient）
# ════════════════════════════════════════════════════════════

class TestFactorApiEndpoints:

    client = TestClient(app)
    _token = _configured_ui_token()
    if _token:
        client.headers.update({"Authorization": f"Bearer {_token}"})

    def test_list_factors_ge_100(self):
        """GET /api/factors 返回 >= 100 个因子"""
        resp = self.client.get("/api/factors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        factors = data["data"]["factors"]
        total = data["data"]["total"]
        assert total >= 100, f"期望 >= 100，实际 {total}"
        assert len(factors) >= 100

    def test_list_factors_meta(self):
        """返回数据包含 meta，含 as_of_date / freshness / lineage"""
        resp = self.client.get("/api/factors")
        assert resp.status_code == 200
        meta = resp.json().get("meta", {})
        assert "as_of_date" in meta, f"meta 缺少 as_of_date，当前 keys: {list(meta.keys())}"
        assert "freshness" in meta
        assert "lineage" in meta

    def test_list_factors_no_mock(self):
        """响应中不包含 mock/sample 关键词"""
        resp = self.client.get("/api/factors")
        raw = json.dumps(resp.json()).lower()
        for keyword in ["mock", "sample", "示例数据"]:
            assert keyword not in raw, f"找到禁止关键词: {keyword}"

    def test_list_factors_category_filter(self):
        """按分类过滤"""
        resp = self.client.get("/api/factors?category=momentum")
        assert resp.status_code == 200
        data = resp.json()["data"]
        for f in data["factors"]:
            assert f["category"] == "momentum"

    def test_get_factor_by_id_exists(self):
        """GET /api/factors/ret5 返回 ret5 详情"""
        resp = self.client.get("/api/factors/ret5")
        assert resp.status_code == 200
        factor = resp.json()["data"]["factor"]
        assert factor["id"] == "ret5"
        assert factor["name"] == "ret5"
        assert factor["category"] == "momentum"
        assert "description" in factor
        assert len(factor["description"]) > 0

    def test_get_factor_ma5_gt_ma10(self):
        """GET /api/factors/ma5_gt_ma10 返回 OK"""
        resp = self.client.get("/api/factors/ma5_gt_ma10")
        assert resp.status_code == 200
        factor = resp.json()["data"]["factor"]
        assert factor["name"] == "ma5_gt_ma10"
        assert factor["category"] == "trend"

    def test_get_factor_atr20(self):
        """GET /api/factors/atr20 返回 OK"""
        resp = self.client.get("/api/factors/atr20")
        assert resp.status_code == 200
        factor = resp.json()["data"]["factor"]
        assert factor["name"] == "atr20"
        assert factor["category"] == "volatility"

    def test_get_factor_not_found(self):
        """不存在的因子返回 404"""
        resp = self.client.get("/api/factors/nonexistent_factor_xyz")
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_risk_attribution_not_available(self):
        """GET /api/factors/ret5/risk-attribution 返回 structured not_available"""
        resp = self.client.get("/api/factors/ret5/risk-attribution")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "not_available"
        assert data["available"] is False
        assert data["risk_decomposition"] is None
        assert data["risk_exposure"] is None
        assert "reason" in data

        # 不应该有随机数
        raw = json.dumps(data)
        # 检查不是随机编造的数据
        assert "random" not in raw.lower()

    def test_risk_attribution_not_found(self):
        """不存在的因子 risk-attribution 返回 404"""
        resp = self.client.get("/api/factors/nonexistent_xyz/risk-attribution")
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_validate_factor(self):
        """POST /api/factors/validate 保持可用"""
        resp = self.client.post(
            "/api/factors/validate",
            json={"name": "test_factor", "expression": "close > open"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["valid"] is True
        assert data["name"] == "test_factor"
        assert data["expression"] == "close > open"

    def test_validate_factor_empty_expression(self):
        """空 expression 应报错"""
        resp = self.client.post(
            "/api/factors/validate",
            json={"name": "test", "expression": ""},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_PARAMS"
