"""统一 API 响应格式

所有 API 端点返回此格式:

    {"ok": true/false, "data": {}, "error": null/{...}, "meta": {...}}

错误格式:
    {"code": "ERROR_CODE", "message": "human readable", "detail": {}, "suggestion": ""}
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from fastapi.responses import JSONResponse
from starlette.requests import Request

CST = timezone(timedelta(hours=8))


def api_response(
    data: Any = None,
    ok: bool = True,
    error: Optional[dict] = None,
    meta: Optional[dict] = None,
    request: Optional[Request] = None,
    status_code: int = 200,
) -> JSONResponse:
    """构建统一 API 响应。

    参数:
        data: 响应数据主体（成功时）
        ok: 是否成功
        error: 错误详情 dict，包含 code/message/detail/suggestion
        meta: 元信息，自动填充 run_id/as_of/source
        request: 当前请求（用于提取 run_id）
        status_code: HTTP 状态码
    """
    run_id = None
    if request:
        run_id = getattr(request.state, "run_id", None)

    meta = meta or {}
    if run_id and "run_id" not in meta:
        meta["run_id"] = run_id
    if "as_of" not in meta:
        meta["as_of"] = datetime.now(CST).isoformat()
    if "source" not in meta:
        meta["source"] = "hermes-api"

    body: dict[str, Any] = {
        "ok": ok,
        "data": data if ok else None,
        "error": error if not ok else None,
        "meta": meta,
    }
    return JSONResponse(content=body, status_code=status_code)


def api_error(
    code: str,
    message: str,
    detail: Any = None,
    suggestion: str = "",
    status_code: int = 400,
    request: Optional[Request] = None,
    meta: Optional[dict] = None,
) -> JSONResponse:
    """快捷构建错误响应。"""
    error = {
        "code": code,
        "message": message,
        "detail": detail or {},
        "suggestion": suggestion,
    }
    return api_response(ok=False, error=error, status_code=status_code, request=request, meta=meta)


def api_success(data: Any = None, status_code: int = 200, request: Optional[Request] = None, meta: Optional[dict] = None) -> JSONResponse:
    """快捷构建成功响应。"""
    if meta is None:
        meta = get_meta_defaults()
    return api_response(data=data, ok=True, status_code=status_code, request=request, meta=meta)


def get_meta_defaults() -> dict:
    """返回 meta 默认值（as_of_date, freshness, lineage）。"""
    from datetime import datetime, timezone, timedelta
    cst = timezone(timedelta(hours=8))
    return {
        "as_of_date": datetime.now(cst).strftime("%Y-%m-%d"),
        "freshness": {"status": "unknown", "latest_data_date": None},
        "lineage": {"source": "hermes-api", "files": [], "functions": []},
    }
