"""FastAPI 主入口 — Hermes Quant Studio API v5.0

包含:
  - 认证中间件 (AuthMiddleware)
  - CORS 配置（从环境变量读取，不再允许 *）
  - 请求日志中间件
  - 错误处理中间件（统一错误格式）
  - RunContext 中间件（每次请求生成 run_id）
  - 全部路由注册（新旧路由共存）
"""

import sys
import os
import time
import uuid
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

_API_DIR = os.path.dirname(__file__)  # .../api_server
_FACTOR_LAB = os.path.dirname(_API_DIR)  # .../factor_lab
_PROJECT_ROOT = os.path.dirname(_FACTOR_LAB)  # .../commands/
sys.path.insert(0, _PROJECT_ROOT)

# 加载项目级 .env (优先于环境变量, 不覆盖已有值)
try:
    from dotenv import load_dotenv
    _dotenv_path = os.path.join(os.path.dirname(_PROJECT_ROOT), ".env")
    if os.path.exists(_dotenv_path):
        load_dotenv(_dotenv_path, override=False)
except ImportError:
    pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_500_INTERNAL_SERVER_ERROR

# ──────────────────────────────────────────────
# 旧路由（保持兼容）
# ──────────────────────────────────────────────
from factor_lab.api_server.routes_status import router as status_router
from factor_lab.api_server.routes_roadmap import router as roadmap_router
from factor_lab.api_server.routes_console import router as console_router
from factor_lab.api_server.routes_backup import router as backup_router
from factor_lab.api_server.routes_data import router as data_router
from factor_lab.api_server.routes_reports import router as reports_router
from factor_lab.api_server.routes_risk import router as risk_router
from factor_lab.api_server.routes_paper import router as paper_router
from factor_lab.api_server.routes_feedback import router as feedback_router
from factor_lab.api_server.routes_ops import router as ops_router

# ──────────────────────────────────────────────
# 新路由 (V5.0)
# ──────────────────────────────────────────────
from factor_lab.api_server.routes_jobs import router as jobs_router
from factor_lab.api_server.routes_audit import router as audit_router
from factor_lab.api_server.routes_universe import router as universe_router
from factor_lab.api_server.routes_benchmark import router as benchmark_router
from factor_lab.api_server.routes_factor import router as factor_router
from factor_lab.api_server.routes_backtest import router as backtest_router
from factor_lab.api_server.routes_portfolio import router as portfolio_router
from factor_lab.api_server.routes_qmt import router as qmt_router
from factor_lab.api_server.routes_live import router as live_router
from factor_lab.api_server.routes_theme import router as theme_router
from factor_lab.api_server.routes_events import router as events_router
from factor_lab.api_server.routes_settings import router as settings_router
from factor_lab.api_server.routes_vnext import router as vnext_router

# ──────────────────────────────────────────────
# 统一响应格式
# ──────────────────────────────────────────────
from factor_lab.api_server.response import api_response, api_error, api_success

CST = timezone(timedelta(hours=8))

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hermes-api")


# ══════════════════════════════════════════════
# 中间件
# ══════════════════════════════════════════════


class RunContextMiddleware(BaseHTTPMiddleware):
    """为每个请求生成唯一的 run_id（格式: run_20260708_xxxxx）。"""

    async def dispatch(self, request: Request, call_next):
        run_id = f"run_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        request.state.run_id = run_id
        response = await call_next(request)
        response.headers["X-Run-Id"] = run_id
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """HERMES_UI_TOKEN 认证。

    如果环境变量 HERMES_UI_TOKEN 未设置，允许所有请求。
    如果已设置，前端必须在 Authorization header 中提供 Bearer token。
    跳过 /api/health, /docs, /openapi.json, /redoc 等路径。
    """

    def __init__(self, app):
        super().__init__(app)
        self._token = os.environ.get("HERMES_UI_TOKEN", "")
        self._excluded_paths = frozenset({
            "/api/health",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/api/docs",
            "/api/openapi.json",
            "/api/redoc",
        })

    async def dispatch(self, request: Request, call_next):
        if not self._token:
            return await call_next(request)

        if request.url.path in self._excluded_paths:
            return await call_next(request)

        if not request.url.path.startswith("/api"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                content={
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "缺少认证 Token",
                        "detail": {},
                        "suggestion": "请在 Authorization header 中提供 Bearer token，或设置 HERMES_UI_TOKEN 环境变量",
                    },
                    "meta": {
                        "run_id": getattr(request.state, "run_id", ""),
                        "as_of": datetime.now(CST).isoformat(),
                        "source": "hermes-api",
                    },
                },
                status_code=HTTP_401_UNAUTHORIZED,
            )

        token = auth_header[7:]
        if token != self._token:
            return JSONResponse(
                content={
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Token 无效",
                        "detail": {},
                        "suggestion": "请检查 HERMES_UI_TOKEN 环境变量是否匹配",
                    },
                    "meta": {
                        "run_id": getattr(request.state, "run_id", ""),
                        "as_of": datetime.now(CST).isoformat(),
                        "source": "hermes-api",
                    },
                },
                status_code=HTTP_401_UNAUTHORIZED,
            )

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个请求的 method, path, status, duration。"""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        response.headers["X-Response-Time-Ms"] = str(round(duration, 1))
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """全局异常捕获，返回统一错误格式（无 traceback 泄露）。

    Traceback 只写入 /mnt/d/HermesReports/logs/backend_errors/。
    错误响应禁止含：Traceback, .py 路径, /home/, /mnt/, token, API key。
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.exception("未捕获的异常: %s", str(e))
            run_id = getattr(request.state, "run_id", "")
            # 写入完整 traceback 到日志文件
            _write_error_log(run_id, e)
            # 构造脱敏后的错误消息
            safe_message = _sanitize_error(str(e))
            return JSONResponse(
                content={
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "服务器内部错误",
                        "detail": {"error_type": type(e).__name__},
                        "suggestion": "请稍后重试，或联系管理员",
                    },
                    "meta": {
                        "run_id": run_id,
                        "as_of": datetime.now(CST).isoformat(),
                        "source": "hermes-api",
                        **get_meta_defaults(),
                    },
                },
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ══════════════════════════════════════════════
# 错误脱敏与日志记录
# ══════════════════════════════════════════════

# 敏感路径模式
_SENSITIVE_PATTERNS = [
    "/home/", "/mnt/", "/root/", "/Users/",
    "Traceback (most recent call last)",
    "File \"",  # .py 文件路径
    "api_key", "apikey", "API_KEY",
    "token", "Token", "TOKEN",
    "secret", "password",
]


def _sanitize_error(msg: str) -> str:
    """脱敏错误消息，移除路径和敏感信息。"""
    if not msg:
        return "未知错误"
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in msg:
            return "服务器内部错误"
    return msg[:500]


def _write_error_log(run_id: str, exc: Exception):
    """将完整 traceback 写入日志文件。"""
    import traceback
    log_dir = Path("/mnt/d/HermesReports/logs/backend_errors")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone, timedelta
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"error_{ts}_{run_id}.log"
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_file.write_text(
            f"run_id: {run_id}\n"
            f"timestamp: {datetime.now(CST).isoformat()}\n"
            f"exception: {type(exc).__name__}: {exc}\n"
            f"{'='*60}\n"
            f"{tb}\n"
        )
    except Exception as log_err:
        logger.warning("无法写入错误日志文件: %s", log_err)


def get_meta_defaults() -> dict:
    """返回 meta 默认值（as_of_date, freshness, lineage）。"""
    return {
        "as_of_date": datetime.now(CST).strftime("%Y-%m-%d"),
        "freshness": {"status": "unknown", "latest_data_date": None},
        "lineage": {"source": "hermes-api", "files": [], "functions": []},
    }


# ══════════════════════════════════════════════
# App 初始化
# ══════════════════════════════════════════════

FE_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def _get_cors_origins() -> list[str]:
    """从环境变量 HERMES_ALLOWED_ORIGINS 读取 CORS 允许源。"""
    raw = os.environ.get(
        "HERMES_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://127.0.0.1:8766",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Hermes API v5.0 启动: http://127.0.0.1:8766")
    logger.info("CORS origins: %s", _get_cors_origins())
    if os.environ.get("HERMES_UI_TOKEN"):
        logger.info("AuthMiddleware: 已启用（HERMES_UI_TOKEN 已设置）")
    else:
        logger.info("AuthMiddleware: 未启用（HERMES_UI_TOKEN 未设置，允许所有请求）")
    logger.info("Static: %s", "ready" if FE_DIST.exists() else "not built (use Vite dev server)")
    yield


app = FastAPI(
    title="Hermes Quant Studio API",
    version="5.0.0",
    lifespan=lifespan,
)

# ── 按顺序添加中间件 ──────────────────────────
# 顺序: RunContext → Auth → Logging → Error → CORS
app.add_middleware(RunContextMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)

CORS_ORIGINS = _get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Run-Id", "X-Response-Time-Ms"],
)

# ── 旧路由（保持兼容） ────────────────────────
app.include_router(status_router, prefix="/api")
app.include_router(roadmap_router, prefix="/api")
app.include_router(console_router, prefix="/api")
app.include_router(backup_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(risk_router, prefix="/api")
app.include_router(paper_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(ops_router, prefix="/api")

# ── 新路由 (V5.0) ─────────────────────────────
app.include_router(jobs_router, prefix="/api")
app.include_router(audit_router, prefix="/api")
app.include_router(universe_router, prefix="/api")
app.include_router(benchmark_router, prefix="/api")
app.include_router(factor_router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(qmt_router, prefix="/api")
app.include_router(live_router, prefix="/api")
app.include_router(theme_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(vnext_router, prefix="/api")


# ── /api/version ──────────────────────────────
@app.get("/api/version", tags=["system"])
async def version_info(request: Request):
    """版本信息 (无认证要求)。"""
    return api_success(
        data={"version": "5.0.0", "api_version": "v1"},
        request=request,
    )


# ── /api/health ──────────────────────────────
@app.get("/api/health", tags=["system"])
async def health_check(request: Request):
    """健康检查端点 (无认证要求)。"""
    return api_success(
        data={
            "status": "healthy",
            "version": "5.0.0",
            "timestamp": datetime.now(CST).isoformat(),
        },
        request=request,
    )


# ── 静态文件服务 ──────────────────────────────
if FE_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FE_DIST), html=True), name="frontend")


# ── SPA fallback ──────────────────────────────
@app.exception_handler(404)
async def spa_fallback(request: Request, exc):
    """非 API 路径返回 index.html（SPA 路由）。"""
    if not request.url.path.startswith("/api"):
        index = FE_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
    # API 404 → 统一格式
    return JSONResponse(
        content={
            "ok": False,
            "data": None,
            "error": {
                "code": "NOT_FOUND",
                "message": f"路径不存在: {request.url.path}",
                "detail": {},
                "suggestion": "请检查 API 路径是否正确",
            },
            "meta": {
                "run_id": getattr(request.state, "run_id", ""),
                "as_of": datetime.now(CST).isoformat(),
                "source": "hermes-api",
            },
        },
        status_code=404,
    )


def serve(host: str = "127.0.0.1", port: int = 8766):
    """启动 uvicorn 服务器。"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
