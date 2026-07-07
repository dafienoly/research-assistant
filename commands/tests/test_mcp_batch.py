"""MCP 服务器 + Batch Evaluator 单元测试"""

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from factor_lab.mcp_server import create_app, tool_list_operators, tool_validate_expression
from factor_lab.mcp_server import tool_list_universes, tool_diagnose_factor, tool_knowledge_search
from factor_lab.research_loop.batch_evaluator import (
    batch_evaluate, cmd_batch_evaluate, _estimate_ic,
)


# ═══════════════════════════════════════════════════════
# MCP Server Tests
# ═══════════════════════════════════════════════════════

class TestMCPServer:
    @pytest.fixture
    def client(self):
        app = create_app()
        return TestClient(app)

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "research-assistant-mcp"

    def test_list_tools(self, client):
        r = client.get("/tools")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert len(data["tools"]) >= 9

    def test_list_operators(self, client):
        r = client.post("/tools/list_operators")
        assert r.status_code == 200
        ops = r.json()
        assert isinstance(ops, list)
        assert len(ops) >= 50
        assert "rank" in ops
        assert "ts_mean" in ops

    def test_list_universes(self, client):
        r = client.post("/tools/list_universes")
        assert r.status_code == 200
        data = r.json()
        assert "universes" in data

    def test_validate_valid_expression(self, client):
        r = client.post("/tools/validate_expression", json={
            "expression": "rank(close / ts_mean(close, 20))",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True

    def test_validate_invalid_expression(self, client):
        r = client.post("/tools/validate_expression", json={
            "expression": "rank(close / broken(",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        assert data["error"]

    def test_validate_v2_expression(self, client):
        r = client.post("/tools/validate_expression", json={
            "expression": "where(returns > 0 and close < ts_mean(close, 20), 1, 0)",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True

    def test_diagnose_factor(self, client):
        r = client.post("/tools/diagnose_factor", json={
            "expression": "rank(close)",
            "score": 50.0,
            "ic_mean": 0.02,
            "ic_ir": 0.3,
        })
        assert r.status_code == 200
        data = r.json()
        assert "strategy" in data
        assert "reason" in data
        assert "mutation_prompt" in data

    def test_knowledge_search_empty(self, client):
        r = client.post("/tools/knowledge_search", json={
            "query": "nonexistent_term_xyz",
        })
        assert r.status_code == 200
        data = r.json()
        assert "results" in data


class TestMCPStandaloneTools:
    def test_tool_list_operators(self):
        ops = json.loads(tool_list_operators())
        assert isinstance(ops, list)
        assert "rank" in ops

    def test_tool_validate_valid(self):
        r = json.loads(tool_validate_expression("rank(close)"))
        assert r["valid"] is True

    def test_tool_validate_invalid(self):
        r = json.loads(tool_validate_expression("rank(broken("))
        assert r["valid"] is False

    def test_tool_diagnose_factor(self):
        r = json.loads(tool_diagnose_factor("rank(close)", score=50, ic_mean=0.02, ic_ir=0.3))
        assert r["strategy"] is not None
        assert "mutation_prompt" in r


# ═══════════════════════════════════════════════════════
# Batch Evaluator Tests
# ═══════════════════════════════════════════════════════

class TestBatchEvaluator:
    def test_single_expression(self):
        results = batch_evaluate(
            ["rank(close / ts_mean(close, 20))"],
            max_concurrent=5,
        )
        assert len(results) >= 1
        assert results[0]["status"] == "completed"

    def test_multiple_expressions(self):
        exprs = [
            "rank(close / ts_mean(close, 20))",
            "rank(ts_delta(close, 5) / close)",
            "rank(volume / ts_mean(volume, 20))",
        ]
        results = batch_evaluate(exprs, max_concurrent=5)
        assert len(results) == 3
        # Results sorted by fitness
        for i in range(len(results) - 1):
            assert results[i]["fitness"] >= results[i + 1]["fitness"]

    def test_invalid_expression_handled(self):
        results = batch_evaluate(
            ["rank(close / ts_mean(close, 20))", "syntax error {{{"],
            max_concurrent=5,
        )
        # Invalid one should be failed
        valid = [r for r in results if r["status"] == "completed"]
        assert len(valid) >= 1

    def test_estimate_ic(self):
        ic = _estimate_ic("rank(close / ts_mean(close, 20))")
        assert isinstance(ic, float)
        assert -0.05 < ic < 0.05

    def test_high_concurrent(self):
        exprs = [f"rank(ts_mean(close, {w}))" for w in [5, 10, 20, 40, 60]]
        results = batch_evaluate(exprs, max_concurrent=10)
        assert len(results) == len(exprs)
        assert all(r["status"] == "completed" for r in results)

    def test_dedup(self):
        exprs = [
            "rank(close)",
            "rank(close / ts_mean(close, 20))",
            "rank(close)",  # duplicate
        ]
        results = batch_evaluate(exprs, max_concurrent=5)
        # Should dedup to 2 unique
        assert len(results) == 2
