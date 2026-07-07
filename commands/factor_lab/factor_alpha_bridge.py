"""Factor ↔ Alpha Factory 双向联动桥

功能:
  1. factor → alpha: 将 factor_base.py 中的因子同步到 Alpha Registry
  2. alpha → factor: 将 Alpha Registry 的状态同步回 factor_base REGISTRY
  3. 增量同步: 只同步新增/变更的条目
  4. 标记联动: factor_base 中的 factor 记录其对应的 alpha_id
  5. 统一视图: 提供联合查询接口

用法:
  from factor_lab.factor_alpha_bridge import sync_factors_to_alpha, sync_alpha_to_factors, unified_list
  sync_factors_to_alpha()              # 所有未同步的 factor → Alpha
  result = unified_list()              # 返回合并后的列表
"""

import sys, os, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

# 标记因子已在 factor_base REGISTRY 中关联了 alpha_id
FACTOR_ALPHA_MARKER = "_alpha_id"


def _get_factor_base_registry():
    """获取 factor_base 的 REGISTRY（只读快照）"""
    from factor_lab.factor_base import list_factors
    return list_factors()


def _find_factor_in_registry(name: str, registry: list) -> Optional[dict]:
    """在 factor_base REGISTRY 中按名称查找因子"""
    for f in registry:
        if f.get("name") == name:
            return f
    return None


def sync_factors_to_alpha(dry_run: bool = False, category: str = None) -> dict:
    """将 factor_base 中的因子同步到 Alpha Registry

    只有满足以下条件的 factor 才会同步:
      - 尚未存在于 Alpha Registry
      - 可选按 category 筛选

    Returns:
        {"synced": N, "skipped": N, "errors": [...], "details": [...]}
    """
    from factor_lab.factor_base import list_factors as _list_factors
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.alpha.registry import register_alpha, list_alpha

    all_factors = _list_factors()
    if category:
        all_factors = [f for f in all_factors if f.get("category") == category]

    existing_alphas = list_alpha()
    existing_names = {a.get("name") for a in existing_alphas if a.get("name")}

    synced = []
    skipped = []
    errors = []

    for factor in all_factors:
        name = factor.get("name", "")
        cat = factor.get("category", "")
        desc = factor.get("description", "")

        # 跳过已同步的
        if name in existing_names:
            skipped.append({"name": name, "reason": "已在 Alpha Registry 中"})
            continue

        try:
            spec = AlphaSpec(
                name=name,
                description=desc or f"{cat} factor: {name}",
                hypothesis=f"{name}: {desc}" if desc else f"{name} 对 A 股未来收益具有预测能力",
                factor_expression=factor.get("expression", f"computed via {name}()"),
                universe="all_watchlist",
                signal_direction="long",
                rebalance_frequency="monthly",
                status="registered",
                author="system",
                source=f"factor_base.py:{name}",
                enabled=False,
                paper_enabled=False,
                live_enabled=False,
                tags=[cat, name] if cat else [name],
            )

            if not dry_run:
                result = register_alpha(spec)
                # 标记 factor_base 条目
                factor[FACTOR_ALPHA_MARKER] = result["alpha_id"]
                synced.append({"name": name, "alpha_id": result["alpha_id"]})
            else:
                synced.append({"name": name, "alpha_id": f"DRY_RUN_{name}"})

        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    return {
        "total_in_registry": len(all_factors),
        "dry_run": dry_run,
        "synced": len(synced),
        "skipped": len(skipped),
        "errors": len(errors),
        "details": {"synced": synced, "skipped": skipped, "errors": errors},
    }


def sync_single_factor_to_alpha(factor_name: str) -> Optional[str]:
    """将单个 factor 同步到 Alpha Registry，返回 alpha_id 或 None"""
    from factor_lab.factor_base import REGISTRY
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.alpha.registry import register_alpha, list_alpha

    # 查重
    existing = [a for a in list_alpha() if a.get("name") == factor_name]
    if existing:
        return existing[0]["alpha_id"]

    # 找 factor
    factor = _find_factor_in_registry(factor_name, REGISTRY)
    if not factor:
        return None

    name = factor.get("name", "")
    cat = factor.get("category", "")
    desc = factor.get("description", "")

    spec = AlphaSpec(
        name=name,
        description=desc or f"{cat} factor: {name}",
        hypothesis=f"{name}: {desc}" if desc else f"{name} 对 A 股未来收益具有预测能力",
        factor_expression=factor.get("expression", f"computed via {name}()"),
        universe="all_watchlist",
        signal_direction="long",
        rebalance_frequency="monthly",
        status="registered",
        author="system",
        source=f"factor_base.py:{name}",
        enabled=False,
        paper_enabled=False,
        live_enabled=False,
        tags=[cat, name] if cat else [name],
    )
    result = register_alpha(spec)
    factor[FACTOR_ALPHA_MARKER] = result["alpha_id"]
    return result["alpha_id"]


def sync_alpha_to_factors() -> int:
    """将 Alpha Registry 状态同步回 factor_base REGISTRY

    当前同步内容:
      - 标记已退役的 Alpha 对应的 factor

    Returns:
        更新的条目数
    """
    from factor_lab.factor_base import REGISTRY
    from factor_lab.alpha.registry import list_alpha, get_alpha

    alphas = list_alpha()
    updated = 0

    for a in alphas:
        name = a.get("name")
        if not name:
            continue

        factor = _find_factor_in_registry(name, REGISTRY)
        if not factor:
            continue

        alpha_detail = get_alpha(a["alpha_id"])
        if not alpha_detail or isinstance(alpha_detail, dict) and "error" in alpha_detail:
            continue

        # 标记 alpha_id
        factor[FACTOR_ALPHA_MARKER] = a["alpha_id"]

        # 退役状态同步
        status = alpha_detail.get("status", "")
        if status == "retired":
            factor["_retired"] = True

        updated += 1

    return updated


def unified_list(category: str = None, include_alpha_status: bool = True) -> list[dict]:
    """统一视图：列出所有因子及对应的 Alpha 状态

    返回合并了 Alpha Registry 状态的因子列表。
    """
    factors = _get_factor_base_registry()
    if category:
        factors = [f for f in factors if f.get("category") == category]

    if not include_alpha_status:
        return factors

    # 加载 Alpha Registry 信息
    from factor_lab.alpha.registry import list_alpha, get_alpha
    alphas = {a.get("name"): a for a in list_alpha() if a.get("name")}

    result = []
    for f in factors:
        name = f.get("name", "")
        entry = {**f}
        entry.pop("func", None)  # 函数不可序列化

        if name in alphas:
            alpha = alphas[name]
            entry["alpha_id"] = alpha.get("alpha_id", "")
            entry["alpha_status"] = alpha.get("status", "registered")
            # 加载详细状态
            detail = get_alpha(alpha["alpha_id"])
            if detail and isinstance(detail, dict) and "error" not in detail:
                entry["alpha_enabled"] = detail.get("enabled", False)
                entry["alpha_paper_enabled"] = detail.get("paper_enabled", False)
                entry["alpha_live_enabled"] = detail.get("live_enabled", False)
        else:
            entry["alpha_status"] = "not_synced"

        result.append(entry)

    return result


# ── CLI 辅助函数 ──────────────────────────────────


def cmd_sync(dry_run: bool = False, category: str = None) -> str:
    """同步 factor → Alpha Registry"""
    result = sync_factors_to_alpha(dry_run=dry_run, category=category)
    lines = [
        f"{'🔍' if dry_run else '✅'} Factor → Alpha 同步",
        f"  Registry 总数: {result['total_in_registry']}",
        f"  {'将同步' if dry_run else '已同步'}: {result['synced']}",
        f"  跳过: {result['skipped']}",
        f"  错误: {result['errors']}",
    ]
    if result["details"]["synced"]:
        lines.append("")
        for s in result["details"]["synced"][:10]:
            lines.append(f"    {s['name']} → {s['alpha_id']}")
        if len(result["details"]["synced"]) > 10:
            lines.append(f"    ... 还有 {len(result['details']['synced'])-10} 个")
    return "\n".join(lines)


def cmd_unified_list(category: str = None) -> str:
    """统一列表视图"""
    entries = unified_list(category=category)
    if not entries:
        return "📭 无因子"

    synced = sum(1 for e in entries if e.get("alpha_status") != "not_synced")
    lines = [
        f"📊 统一因子视图 ({len(entries)} 个, Alpha 已同步: {synced}/{len(entries)}):\n"
    ]

    for e in entries:
        status = e.get("alpha_status", "?")
        icon = {
            "registered": "📝",
            "backtest_ready": "🔬",
            "backtested": "📊",
            "paper_active": "🧪",
            "live_active": "🟢",
            "retired": "⚪",
            "not_synced": "⬜",
        }.get(status, "❓")

        enabled = e.get("alpha_enabled", False)
        flag = "🔒" if enabled else ""

        name = e.get("name", "?")
        cat = e.get("category", "?")
        desc = e.get("description", "")[:40]
        lines.append(f"  {icon} {name:25s} [{cat:15s}] {flag}{desc}")

    return "\n".join(lines)
