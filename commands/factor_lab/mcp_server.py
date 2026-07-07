"""MCP 工具服务器 — 投研系统标准化 Agent 接口

提供 13 个工具供 Agent（Hermes/Claude Code/Codex）直接调用。

两种运行模式:
  1. HTTP: `python3 factor_lab/mcp_server.py` 启动 FastAPI (端口 8767)
  2. MCP stdio: `python3 -m factor_lab.mcp_server --stdio` (需安装 mcp 包)

工具清单:
  - list_operators       列出可用算子
  - list_universes       列出股票池
  - validate_expression  语法校验
  - run_backtest         全流程回测
  - score_factor         复合评分 (0-100)
  - diagnose_factor      诊断并建议突变策略
  - run_anti_overfit     反过拟合检验
  - run_walk_forward     Walk-Forward 验证
  - run_adversarial      对抗性验证
  - batch_evaluate       批处理并发回测
  - knowledge_search     知识库搜索
  - knowledge_add        知识库写入
  - research_loop        启动研究循环
"""

import sys, json, os, subprocess, traceback
from pathlib import Path
from typing import Optional

# ── Tool implementations (stateless functions) ────────


def tool_list_operators() -> str:
    """列出所有可用表达式算子"""
    from factor_lab.expression_parser import FUNC_REGISTRY
    return json.dumps(sorted(FUNC_REGISTRY.keys()), ensure_ascii=False)


def tool_list_universes() -> str:
    """列出股票池"""
    try:
        from strategy_lab.universe import list_universes
        u = list_universes()
        return json.dumps({"universes": list(u.keys()) if isinstance(u, dict) else u}, ensure_ascii=False)
    except Exception:
        return json.dumps({"universes": ["all_watchlist", "hs300", "csi500", "manual_watchlist"]})


def tool_validate_expression(expression: str, mode: str = "local") -> str:
    """语法校验"""
    from factor_lab.expression_parser import ExpressionParser
    p = ExpressionParser()
    err = p.validate(expression)
    return json.dumps({"valid": not err, "error": err or "", "mode": mode}, ensure_ascii=False)


def tool_score_factor(factor_name: str = "ret5") -> str:
    """复合评分"""
    try:
        from factor_lab.validate_factor import run_validation
        import argparse
        a = argparse.Namespace()
        a.factor = factor_name
        a.start = "2025-01-02"
        a.end = "2026-06-30"
        a.rebalance = "monthly"
        a.benchmark = "000300.SH"
        a.top_n = 20
        a.run_anti_overfit = True
        a.run_walk_forward = True
        a.output = None
        result = run_validation(a)
        return json.dumps({
            "factor_name": factor_name,
            "score": result.get("factor_score", {}).get("overall_score", 0),
            "grade": result.get("factor_score", {}).get("grade", "?"),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def tool_diagnose_factor(expression: str, score: float = 50.0,
                          ic_mean: float = 0.02, ic_ir: float = 0.3) -> str:
    """诊断并建议突变策略"""
    from factor_lab.research_loop.mutation import MutationEngine
    engine = MutationEngine(
        expression,
        {"backtest_summary": {"ic_mean": ic_mean, "ic_ir": ic_ir}},
        score=score,
    )
    diagnosis = engine.diagnose_failure()
    prompt = engine.build_mutation_prompt()
    return json.dumps({
        "strategy": diagnosis.strategy.value,
        "reason": diagnosis.reason,
        "details": diagnosis.details,
        "mutation_prompt": prompt,
    }, ensure_ascii=False)


def tool_run_anti_overfit(factor_name: str = "ret5") -> str:
    """反过拟合检验"""
    try:
        from factor_lab.validation.anti_overfit import run_anti_overfit
        result = run_anti_overfit(factor_name=factor_name)
        return json.dumps({
            "factor_name": factor_name,
            "verdicts": {
                "ic_stability": result.get("ic_stability", {}).get("verdict", "?"),
                "placebo": result.get("placebo", {}).get("verdict", "?"),
                "stress_test": result.get("stress_test", {}).get("verdict", "?"),
            },
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def tool_knowledge_search(query: str, kind: str = "") -> str:
    """知识库搜索"""
    from factor_lab.research_skill.knowledge_base import KnowledgeBase
    kb = KnowledgeBase()
    results = kb.search(query, kind if kind else None)
    return json.dumps({"results": results, "count": len(results)}, ensure_ascii=False)


def tool_knowledge_add(kind: str, title: str, hypothesis: str,
                        conclusion: str, evidence: str = "",
                        tags: str = "", confidence: float = 0.5) -> str:
    """知识库写入"""
    from factor_lab.research_skill.knowledge_base import KnowledgeBase, KnowledgeEntry
    kb = KnowledgeBase()
    dup = kb.check_duplicate_hypothesis(hypothesis)
    if dup:
        return json.dumps({"status": "duplicate", "existing_id": dup["entry_id"]})
    entry = KnowledgeEntry(
        kind=kind, title=title, hypothesis=hypothesis,
        conclusion=conclusion, evidence=evidence,
        tags=[t.strip() for t in tags.split(",") if t.strip()] if tags else [],
        confidence=confidence,
    )
    eid = kb.add_entry(entry)
    return json.dumps({"status": "ok", "entry_id": eid})


# ── MCP stdio mode (when mcp package is installed) ──

def _try_run_mcp_stdio():
    """尝试以 MCP stdio 模式运行"""
    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP(
            "research-assistant",
            instructions="投研系统 MCP Server — 因子挖掘、回测、验证、知识库管理",
        )

        @mcp.tool()
        def list_operators() -> str:
            return tool_list_operators()

        @mcp.tool()
        def list_universes() -> str:
            return tool_list_universes()

        @mcp.tool()
        def validate_expression(expression: str) -> str:
            return tool_validate_expression(expression)

        @mcp.tool()
        def score_factor(factor_name: str = "ret5") -> str:
            return tool_score_factor(factor_name)

        @mcp.tool()
        def diagnose_factor(expression: str, score: float = 50.0,
                            ic_mean: float = 0.02, ic_ir: float = 0.3) -> str:
            return tool_diagnose_factor(expression, score, ic_mean, ic_ir)

        @mcp.tool()
        def run_anti_overfit(factor_name: str = "ret5") -> str:
            return tool_run_anti_overfit(factor_name)

        @mcp.tool()
        def knowledge_search(query: str, kind: str = "") -> str:
            return tool_knowledge_search(query, kind)

        @mcp.tool()
        def knowledge_add(kind: str, title: str, hypothesis: str,
                          conclusion: str, evidence: str = "",
                          tags: str = "", confidence: float = 0.5) -> str:
            return tool_knowledge_add(kind, title, hypothesis, conclusion,
                                      evidence, tags, confidence)

        mcp.run(transport="stdio")
        return True
    except ImportError:
        return False


# ── HTTP mode (FastAPI) ──────────────────────────────


def create_app():
    """创建 FastAPI 应用"""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(
        title="投研系统 MCP Server",
        description="因子挖掘、回测、验证、知识库管理工具",
        version="1.0.0",
    )

    class ValidateRequest(BaseModel):
        expression: str
        mode: str = "local"

    class DiagnoseRequest(BaseModel):
        expression: str
        score: float = 50.0
        ic_mean: float = 0.02
        ic_ir: float = 0.3

    class BacktestRequest(BaseModel):
        expression: str
        universe: str = "all_watchlist"
        start: str = "2025-01-02"
        end: str = "2026-06-30"
        rebalance: str = "monthly"

    class KnowledgeAddRequest(BaseModel):
        kind: str
        title: str
        hypothesis: str
        conclusion: str
        evidence: str = ""
        tags: str = ""
        confidence: float = 0.5

    class KnowledgeSearchRequest(BaseModel):
        query: str
        kind: str = ""

    class BatchEvalRequest(BaseModel):
        expressions: list[str]
        universe: str = "all_watchlist"
        start: str = "2025-01-02"
        end: str = "2026-06-30"

    @app.get("/tools")
    def list_tools():
        return {
            "tools": [
                {"name": "list_operators", "description": "列出可用算子"},
                {"name": "list_universes", "description": "列出股票池"},
                {"name": "validate_expression", "description": "语法校验"},
                {"name": "score_factor", "description": "复合评分"},
                {"name": "diagnose_factor", "description": "诊断并建议突变策略"},
                {"name": "run_anti_overfit", "description": "反过拟合检验"},
                {"name": "knowledge_search", "description": "知识库搜索"},
                {"name": "knowledge_add", "description": "知识库写入"},
                {"name": "batch_evaluate", "description": "批处理评估"},
            ]
        }

    @app.post("/tools/list_operators")
    def api_list_operators():
        return json.loads(tool_list_operators())

    @app.post("/tools/list_universes")
    def api_list_universes():
        return json.loads(tool_list_universes())

    @app.post("/tools/validate_expression")
    def api_validate_expression(req: ValidateRequest):
        return json.loads(tool_validate_expression(req.expression, req.mode))

    @app.post("/tools/score_factor")
    def api_score_factor(factor_name: str = "ret5"):
        return json.loads(tool_score_factor(factor_name))

    @app.post("/tools/diagnose_factor")
    def api_diagnose_factor(req: DiagnoseRequest):
        return json.loads(tool_diagnose_factor(req.expression, req.score, req.ic_mean, req.ic_ir))

    @app.post("/tools/run_anti_overfit")
    def api_run_anti_overfit(factor_name: str = "ret5"):
        return json.loads(tool_run_anti_overfit(factor_name))

    @app.post("/tools/knowledge_search")
    def api_knowledge_search(req: KnowledgeSearchRequest):
        return json.loads(tool_knowledge_search(req.query, req.kind))

    @app.post("/tools/knowledge_add")
    def api_knowledge_add(req: KnowledgeAddRequest):
        return json.loads(tool_knowledge_add(
            req.kind, req.title, req.hypothesis, req.conclusion,
            req.evidence, req.tags, req.confidence,
        ))

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0", "service": "research-assistant-mcp"}

    return app


def run_http(host: str = "0.0.0.0", port: int = 8767):
    """启动 HTTP 模式"""
    import uvicorn
    app = create_app()
    print(f"📡 投研系统 MCP Server (HTTP)")
    print(f"   API: http://{host}:{port}/tools/")
    print(f"   健康检查: http://{host}:{port}/health")
    print(f"   工具列表: http://{host}:{port}/tools")
    uvicorn.run(app, host=host, port=port)


# ═══════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════


def main():
    """MCP Server 入口"""
    if "--stdio" in sys.argv:
        ok = _try_run_mcp_stdio()
        if not ok:
            print("⚠️  MCP 包未安装。请执行: pip install mcp", file=sys.stderr)
            sys.exit(1)
        return

    port = 8767
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
            except ValueError:
                pass

    run_http(port=port)


if __name__ == "__main__":
    main()
