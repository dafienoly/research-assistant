"""基准 (Benchmark) API — 查询、构建基准组合。"""

from fastapi import APIRouter, Request, Path, Query
from factor_lab.api_server.response import api_success, api_error

router = APIRouter()

_SAMPLE_BENCHMARKS = {
    "hs300": {"id": "hs300", "name": "沪深300", "type": "index", "annual_return": 8.5, "volatility": 18.2, "sharpe": 0.47},
    "zz500": {"id": "zz500", "name": "中证500", "type": "index", "annual_return": 6.8, "volatility": 22.1, "sharpe": 0.31},
    "zz1000": {"id": "zz1000", "name": "中证1000", "type": "index", "annual_return": 5.2, "volatility": 25.4, "sharpe": 0.20},
    "csi_bond": {"id": "csi_bond", "name": "中证全债", "type": "index", "annual_return": 3.5, "volatility": 1.2, "sharpe": 2.92},
}


@router.get("/benchmarks")
async def list_benchmarks(request: Request, type: str = Query("", description="按类型过滤: index/custom")):
    """列出所有可用的基准。"""
    benchmarks = list(_SAMPLE_BENCHMARKS.values())
    if type:
        benchmarks = [b for b in benchmarks if b["type"] == type]
    return api_success(data={"benchmarks": benchmarks, "total": len(benchmarks)}, request=request)


@router.get("/benchmarks/{benchmark_id}")
async def get_benchmark(request: Request, benchmark_id: str = Path(..., description="基准 ID")):
    """查询单个基准详情。"""
    bm = _SAMPLE_BENCHMARKS.get(benchmark_id)
    if not bm:
        return api_error("NOT_FOUND", f"基准 {benchmark_id} 不存在", status_code=404, request=request)
    return api_success(data={"benchmark": bm}, request=request)


@router.post("/benchmarks/build")
async def build_benchmark(request: Request, body: dict):
    """构建自定义基准组合。"""
    name = body.get("name", "")
    constituents = body.get("constituents", [])
    if not name:
        return api_error("INVALID_PARAMS", "name 不能为空", status_code=400, request=request)
    return api_success(
        data={
            "status": "queued",
            "benchmark_id": f"custom_{name.lower().replace(' ', '_')}",
            "name": name,
            "constituent_count": len(constituents),
            "message": "基准构建任务已加入队列",
        },
        status_code=202,
        request=request,
    )
