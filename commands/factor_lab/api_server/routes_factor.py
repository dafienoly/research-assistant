"""因子 (Factor) API — 因子查询、验证、风险归因。

所有因子数据从 factor_lab.factor_base.REGISTRY（约124+因子）实时读取，
无 mock/demo/sample/hardcode。
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Path, Query
from factor_lab.api_server.response import api_success, api_error
from factor_lab.backend.services.factor_registry_service import (
    get_all_factors,
    get_factor_by_id,
    count_factors,
)
from factor_lab.api_server.factor_results_cache import merge_metrics_into_definitions
import asyncio

CST = timezone(timedelta(hours=8))

router = APIRouter()

# ══════════════════════════════════════════════════════════════
# 公共 meta 字段
# ══════════════════════════════════════════════════════════════
def _build_meta() -> dict:
    now = datetime.now(CST)
    return {
        "as_of_date": now.isoformat(),
        "freshness": "fresh",
        "lineage": [],
    }


# ══════════════════════════════════════════════════════════════
# GET /api/factors  — 列出所有因子
# ══════════════════════════════════════════════════════════════
@router.get("/factors")
async def list_factors(
    request: Request,
    category: str = Query("", description="按分类过滤，如 momentum / volatility / quality"),
    limit: int = Query(500, ge=1, le=1000, description="最大返回数量"),
):
    """列出所有可用因子（从真实 REGISTRY 动态读取，合并缓存计算结果）。"""
    factors = get_all_factors(category=category or None)
    total = len(factors)
    # 合并缓存的计算指标
    enriched = merge_metrics_into_definitions(factors)
    data = {
        "factors": enriched[:limit],
        "total": total,
        "categories": list({f["category"] for f in factors}),
    }
    return api_success(data=data, request=request, meta=_build_meta())


# ══════════════════════════════════════════════════════════════
# POST /api/factors/validate  — 验证因子定义
# ══════════════════════════════════════════════════════════════
@router.post("/factors/validate")
async def validate_factor(request: Request, body: dict):
    """验证因子定义是否正确。"""
    expression = body.get("expression", "")
    name = body.get("name", "")
    if not expression:
        return api_error(
            "INVALID_PARAMS",
            "expression 不能为空",
            status_code=400,
            request=request,
            meta=_build_meta(),
        )

    # 简单校验：检查 expression 是否可解析
    warnings = []
    errors = []

    # 检查是否在已注册因子中找到同名/同 expression
    known = get_all_factors()
    matched_names = [f["name"] for f in known if f["name"] == name] if name else []
    matched_expr = [f["name"] for f in known if f["expression"] == expression]
    if matched_names:
        warnings.append(f"因子名 '{name}' 已存在于注册表中")
    if matched_expr:
        warnings.append(f"表达式已存在于因子 '{matched_expr[0]}'")

    # 检查 expression 基本语法
    if not any(op in expression for op in ["+", "-", "*", "/", "(", ")"]):
        warnings.append("表达式不含运算符，可能无效")

    return api_success(
        data={
            "name": name or "unnamed",
            "expression": expression,
            "valid": len(errors) == 0,
            "warnings": warnings,
            "errors": errors,
            "estimated_compute_time_ms": None,
            "suggested_ic": None,
        },
        request=request,
        meta=_build_meta(),
    )


# ══════════════════════════════════════════════════════════════
# GET /api/factors/{factor_id}  — 单因子详情
# ══════════════════════════════════════════════════════════════
@router.get("/factors/{factor_id}")
async def get_factor(
    request: Request,
    factor_id: str = Path(..., description="因子 ID（即因子 name）"),
):
    """查询单个因子详情。"""
    factor = get_factor_by_id(factor_id)
    if not factor:
        return api_error(
            "NOT_FOUND",
            f"因子 '{factor_id}' 不存在",
            status_code=404,
            request=request,
            meta=_build_meta(),
        )
    return api_success(data={"factor": factor}, request=request, meta=_build_meta())


# ══════════════════════════════════════════════════════════════
# GET /api/factors/{factor_id}/risk-attribution  — 风险归因
# ══════════════════════════════════════════════════════════════
@router.get("/factors/{factor_id}/risk-attribution")
async def factor_risk_attribution(
    request: Request,
    factor_id: str = Path(..., description="因子 ID"),
):
    """查询因子的风险归因分析。

    注意：风险归因需要实时运行归因模型，当前返回 structured not_available 状态。
    """
    # 先确认因子存在
    factor = get_factor_by_id(factor_id)
    if not factor:
        return api_error(
            "NOT_FOUND",
            f"因子 '{factor_id}' 不存在",
            status_code=404,
            request=request,
            meta=_build_meta(),
        )

    return api_success(
        data={
            "factor_id": factor_id,
            "factor_name": factor["name"],
            "risk_decomposition": None,
            "risk_exposure": None,
            "status": "not_available",
            "reason": "风险归因需要运行归因模型 (RiskDecomposer)，当前未集成",
            "available": False,
        },
        request=request,
        meta=_build_meta(),
    )


# ══════════════════════════════════════════════════════════════
# POST /api/factors/compute-all  — 批量计算因子指标
# ══════════════════════════════════════════════════════════════
@router.post("/factors/compute-all")
async def compute_all_factors_endpoint(request: Request):
    """对所有注册因子批量计算 IC/RankIC/ICIR/Top-Bottom，结果写入缓存。"""
    try:
        from factor_lab.batch_compute import compute_all_and_cache
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, compute_all_and_cache)
        return api_success(data=result, request=request, meta=_build_meta())
    except Exception as e:
        return api_error(
            "COMPUTE_FAILED",
            f"批量计算失败: {e}",
            status_code=500,
            request=request,
            meta=_build_meta(),
        )
