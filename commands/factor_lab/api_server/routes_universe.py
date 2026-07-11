"""股票池 (Universe) API — 查询、构建股票池。

从 commands.universes 模块读取真实数据，使用 UniverseCache 避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import sys
import logging
from datetime import datetime, timezone, timedelta
import pathlib
from typing import Any

from fastapi import APIRouter, Request, Path as FPath

from factor_lab.api_server.response import api_success, api_error

from commands import universes

# ── 确保项目根目录在 sys.path 上，以便导入 backend.services ──────────
_PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)  # .../research-assistant/
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from factor_lab.backend.services.universe_cache import get_cache

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 全局异步锁：防止并发后台构建 ──────────────────────────────────────
_BUILD_LOCK = asyncio.Lock()

_UNIVERSE_DISPLAY_ORDER = ["U0", "U1", "U2", "U3", "U4", "ETF"]
_UNIVERSE_LABELS = {
    "U0": "全A基础池",
    "U1": "用户可交易池",
    "U2": "AI/半导体广义池",
    "U3": "半导体核心池",
    "U4": "匹配对照池",
    "ETF": "ETF替代池",
}

CST = timezone(timedelta(hours=8))


# ── 辅助函数 ───────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _warm_cache_from_file() -> None:
    """如果 ``universes.json`` 存在且缓存为空，预填充缓存（避免冷启动 202）。"""
    cache = get_cache()
    if cache.get() is not None:
        return
    output = universes.OUTPUT_FILE
    if output.exists():
        try:
            with open(output, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("universes"):
                cache.set(data)
                logger.info("Universe cache pre-warmed from %s", output)
        except Exception as exc:
            logger.warning("Failed to warm cache from file: %s", exc)


def _build_universe_list(all_data: dict[str, Any]) -> list[dict[str, Any]]:
    """从完整的 build_all() 结果中提取各 stock 池的摘要列表。"""
    universe_list: list[dict[str, Any]] = []
    for name in _UNIVERSE_DISPLAY_ORDER:
        u = all_data.get("universes", {}).get(name, {})
        if u:
            universe_list.append({
                "id": name,
                "name": name,
                "label": u.get("label", _UNIVERSE_LABELS.get(name, name)),
                "count": u.get("total_stocks", 0),
                "description": u.get("description", ""),
                "built_at": u.get("built_at", ""),
            })
    return universe_list


def _lineage(cache, *, fresh: bool) -> dict[str, Any]:
    """构建 lineage 元信息。"""
    return {
        "cache_hit": cache.get() is not None,
        "fresh": fresh,
        "built_at": cache.built_at or None,
        "age_seconds": cache.age_seconds,
    }


async def _background_build() -> None:
    """在后台线程中执行 ``build_all()``，完成后填充缓存。

    使用 ``asyncio.to_thread`` 将同步操作交给线程池，避免阻塞事件循环。
    全局锁 ``_BUILD_LOCK`` 确保同时只有一个构建在运行。
    """
    async with _BUILD_LOCK:
        cache = get_cache()
        # 双检锁：等待锁期间可能已有其他请求填充了缓存
        if cache.is_fresh():
            logger.debug("Background build skipped — cache already fresh")
            return
        try:
            logger.info("Starting background universe build...")
            data = await asyncio.to_thread(universes.build_all)
            cache.set(data)
            logger.info("Background universe build complete — cache updated")
        except Exception as exc:
            logger.error("Background universe build failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════
# GET /universe
# ══════════════════════════════════════════════════════════════════════

@router.get("/universe")
async def list_universes(request: Request):
    """列出所有可用的股票池（含元数据）。

    响应策略
    -------
    * **缓存存在且未过期** → 立即返回，``freshness: "fresh"``
    * **缓存存在但已过期** → 返回旧数据 + ``refreshing: true``，后台触发重建
    * **完全无缓存** → 返回 ``202 Accepted``，后台触发重建
    """
    cache = get_cache()

    # 冷启动时优先从已有文件预热
    if cache.get() is None:
        _warm_cache_from_file()

    cached_data = cache.get()

    # ── 情况 1：缓存存在且未过期 ──────────────────────────────────
    if cached_data is not None and cache.is_fresh():
        universe_list = _build_universe_list(cached_data)
        return api_success(
            data={
                "universes": universe_list,
                "total": len(universe_list),
                "as_of_date": cache.built_at,
                "freshness": "fresh",
                "lineage": _lineage(cache, fresh=True),
            },
            request=request,
        )

    # ── 情况 2：缓存存在但已过期 → 返回旧数据 + 后台刷新 ──────────
    if cached_data is not None and not cache.is_fresh():
        universe_list = _build_universe_list(cached_data)
        # 非阻塞触发后台重建
        asyncio.ensure_future(_background_build())
        return api_success(
            data={
                "universes": universe_list,
                "total": len(universe_list),
                "as_of_date": cache.built_at or "",
                "freshness": "stale",
                "refreshing": True,
                "lineage": _lineage(cache, fresh=False),
            },
            request=request,
        )

    # ── 情况 3：完全无缓存 → 202 Accepted ──────────────────────────
    asyncio.ensure_future(_background_build())
    return api_success(
        data={
            "status": "building",
            "message": "Universe data is being built in the background. "
                       "Please retry in ~120 seconds.",
            "as_of_date": None,
            "freshness": "unknown",
            "lineage": {
                "cache_hit": False,
                "fresh": False,
                "built_at": None,
                "age_seconds": None,
            },
        },
        status_code=202,
        request=request,
    )


# ══════════════════════════════════════════════════════════════════════
# GET /universe/{universe_id}
# ══════════════════════════════════════════════════════════════════════

@router.get("/universe/{universe_id}")
async def get_universe_detail(
    request: Request,
    universe_id: str = FPath(..., description="股票池 ID，如 U0 / U1 / U2 / U3 / U4 / ETF"),
):
    """查询单个股票池详情（含全部成分股数据）。"""
    if universe_id not in _UNIVERSE_LABELS:
        return api_error(
            "NOT_FOUND",
            f"股票池 {universe_id} 不存在，可选: {', '.join(_UNIVERSE_DISPLAY_ORDER)}",
            status_code=404,
            request=request,
        )

    cache = get_cache()
    if cache.get() is None:
        _warm_cache_from_file()

    cached_data = cache.get()
    if cached_data is None:
        # 冷缓存 → 202
        asyncio.ensure_future(_background_build())
        return api_success(
            data={
                "status": "building",
                "message": "Universe data is being built. Please retry later.",
                "universe_id": universe_id,
            },
            status_code=202,
            request=request,
        )

    universe = cached_data.get("universes", {}).get(universe_id)
    if not universe or not universe.get("stocks"):
        return api_error(
            "EMPTY",
            f"股票池 {universe_id} 数据为空，请先运行 universe:build",
            status_code=404,
            request=request,
        )

    result: dict[str, Any] = {
        "universe": universe,
        "as_of_date": cache.built_at,
        "freshness": "fresh" if cache.is_fresh() else "stale",
        "lineage": _lineage(cache, fresh=cache.is_fresh()),
    }

    if not cache.is_fresh():
        result["refreshing"] = True
        asyncio.ensure_future(_background_build())

    return api_success(data=result, request=request)


# ══════════════════════════════════════════════════════════════════════
# GET /universe/{universe_id}/audit
# ══════════════════════════════════════════════════════════════════════

@router.get("/universe/{universe_id}/audit")
async def audit_universe(
    request: Request,
    universe_id: str = FPath(..., description="股票池 ID"),
):
    """查询股票池审计信息（纯度 / 覆盖率 / 权限分布）。"""
    if universe_id not in _UNIVERSE_LABELS:
        return api_error(
            "NOT_FOUND",
            f"股票池 {universe_id} 不存在",
            status_code=404,
            request=request,
        )

    cache = get_cache()
    if cache.get() is None:
        _warm_cache_from_file()

    cached_data = cache.get()
    if cached_data is None:
        asyncio.ensure_future(_background_build())
        return api_success(
            data={
                "status": "building",
                "message": "Universe data is being built. Please retry later.",
                "universe_id": universe_id,
            },
            status_code=202,
            request=request,
        )

    # 从缓存的完整数据中提取该 stock 池
    universe = cached_data.get("universes", {}).get(universe_id)
    if not universe:
        return api_error(
            "NOT_FOUND",
            f"股票池 {universe_id} 不存在",
            status_code=404,
            request=request,
        )

    # universes.audit() 从文件读取，文件应与缓存数据一致
    # （build_all() 总是在 set cache 的同时写文件）
    try:
        report = universes.audit()
    except Exception as exc:
        return api_error(
            "AUDIT_ERROR",
            f"审计股票池 {universe_id} 失败: {exc}",
            status_code=500,
            request=request,
        )

    detail = report.get("details", {}).get(universe_id, {})
    summary = report.get("summary", {})

    result: dict[str, Any] = {
        "universe_id": universe_id,
        "name": universe.get("label", universe_id),
        "total_stocks": universe.get("total_stocks", 0),
        "audited_at": report.get("audited_at", ""),
        "detail": detail,
        "summary": summary,
        "as_of_date": cache.built_at,
        "freshness": "fresh" if cache.is_fresh() else "stale",
        "lineage": _lineage(cache, fresh=cache.is_fresh()),
    }

    if not cache.is_fresh():
        result["refreshing"] = True
        asyncio.ensure_future(_background_build())

    return api_success(data=result, request=request)
