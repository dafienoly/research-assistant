#!/usr/bin/env python3
"""
data:bootstrap / data:update / data:health CLI 命令实现

提供 DataManager 类，封装全量初始化、增量更新、健康检查三种数据管理操作。
基于 commands.data_providers.tushare 下 5 个现有 Provider 实现。

用法:
    from commands.data_manager import DataManager

    dm = DataManager(source="tushare")
    dm.bootstrap(start="20190101")
    dm.update(days=5)
    dm.health()
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ─── 数据目录基路径 ──────────────────────────────────────────────
DATA_ROOT = Path(__file__).parent.parent / "data"
MANIFEST_DIR = DATA_ROOT / "audit" / "manifests"
HEALTH_DIR = DATA_ROOT / "audit" / "health"

# ─── 配置常量 ────────────────────────────────────────────────────
MANIFESTS_TOUCH_RECORD = "latest_bootstrap.json"
FRESHNESS_FILE = "freshness_report.json"
HEALTH_FILE = "health_report.json"

# 各 Provider 的业务数据子目录映射
PROVIDER_DATA_DIRS = {
    "tushare_market": DATA_ROOT / "market",
    "tushare_fina": DATA_ROOT / "fundamentals",
    "tushare_stock": DATA_ROOT / "market",
    "tushare_fund_flow": DATA_ROOT / "fundamentals",
    "tushare_event": DATA_ROOT / "events",
}


def _ensure_dirs():
    """确保 audit 子目录存在"""
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)


def _now_cst_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════════
# DataManager
# ═══════════════════════════════════════════════════════════════


class DataManager:
    """数据管理层 — bootstrap / update / health"""

    def __init__(self, source: str = "tushare"):
        if source not in ("tushare",):
            raise ValueError(f"不支持的数据源: {source}。当前仅支持: tushare")
        self.source = source
        _ensure_dirs()

    # ── Provider 加载 ──────────────────────────────────────────

    @staticmethod
    def _get_providers():
        """返回所有 Tushare Provider 实例。Provider 不可用时直接报错。"""
        # 使用 importlib 绕过 sys.path 限制
        import importlib
        try:
            mod = importlib.import_module("data_providers.tushare")
            _tushare_providers = mod.get_all_providers
        except ModuleNotFoundError:
            # 备用：尝试从 commands 包路径导入
            import sys
            _p = Path(__file__).parent.resolve()
            if str(_p) not in sys.path:
                sys.path.insert(0, str(_p))
            _tushare_providers = Path(__file__).parent / "data_providers" / "tushare" / "__init__.py"
            # fallback: 直接加载
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "data_providers.tushare",
                Path(__file__).parent / "data_providers" / "tushare" / "__init__.py",
                submodule_search_locations=[str(Path(__file__).parent / "data_providers" / "tushare")]
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _tushare_providers = mod.get_all_providers

        providers = _tushare_providers()
        if not providers:
            raise RuntimeError("未发现任何 Tushare Provider (get_all_providers 返回空)")
        return providers

    # ═══════════════════════════════════════════════════════════
    # data:bootstrap
    # ═══════════════════════════════════════════════════════════

    def bootstrap(self, start: str, end: Optional[str] = None) -> dict:
        """全量数据初始化：遍历所有 Provider，执行 self_check，生成 manifest。

        Args:
            start: 起始日期 YYYYMMDD，如 20190101
            end:   截止日期 YYYYMMDD，默认当天

        Returns:
            dict: {provider_id: {"status": ..., "data_types": ..., "manifest_path": ...}}
        """
        if not start:
            raise ValueError("--start 参数必须提供 (YYYYMMDD 格式)")

        if end is None:
            end = datetime.now(CST).strftime("%Y%m%d")

        print(f"🚀 开始全量数据初始化 (source={self.source}, start={start}, end={end})")
        print()

        providers = self._get_providers()
        results: dict[str, dict] = {}

        for provider in providers:
            pid = provider.capability.name
            print(f"  ── 检查 {pid} ...")

            try:
                health = provider.self_check()
            except Exception as e:
                logger.exception(f"{pid} self_check 异常")
                results[pid] = {"status": "error", "error": str(e)}
                print(f"     ❌ {pid} 自检异常: {e}")
                continue

            if health.status == "error":
                results[pid] = {
                    "status": "error",
                    "errors": health.errors,
                    "warnings": health.warnings,
                }
                print(f"     ❌ {pid} 自检失败: {'; '.join(health.errors)}")
                continue

            # 收集该 Provider 的能力（可用的数据类型）
            cap = provider.capability
            enabled_types = [
                attr.replace("can_", "")
                for attr in dir(cap)
                if attr.startswith("can_") and getattr(cap, attr)
            ]

            manifest = {
                "source": self.source,
                "provider_id": pid,
                "provider_name": pid,
                "start_date": start,
                "end_date": end,
                "data_types": sorted(enabled_types),
                "status": health.status,
                "freshness": health.data_freshness,
                "warnings": health.warnings,
                "errors": health.errors,
                "bootstrapped_at": _now_cst_str(),
            }

            # 写入 manifest
            manifest_path = MANIFEST_DIR / f"manifest_{pid}.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            results[pid] = {
                "status": health.status,
                "data_types": enabled_types,
                "manifest_path": str(manifest_path),
                "warnings": health.warnings,
                "errors": health.errors,
            }

            status_icon = "✅" if health.status == "ok" else "⚠️"
            print(f"     {status_icon} {health.status:7s} | {len(enabled_types)} data types | manifest: {manifest_path.name}")

        # 写入全局 bootstrap 记录
        touch_path = MANIFEST_DIR / MANIFESTS_TOUCH_RECORD
        touch_record = {
            "source": self.source,
            "start": start,
            "end": end,
            "providers": results,
            "bootstrapped_at": _now_cst_str(),
        }
        with open(touch_path, "w", encoding="utf-8") as f:
            json.dump(touch_record, f, ensure_ascii=False, indent=2)

        print()
        ok_count = sum(1 for v in results.values() if v.get("status") == "ok")
        err_count = sum(1 for v in results.values() if v.get("status") == "error")
        print(f"📋 汇总: {len(results)} providers, {ok_count} ok, {err_count} error")
        print(f"   全局 manifest: {touch_path}")

        return results

    # ═══════════════════════════════════════════════════════════
    # data:update
    # ═══════════════════════════════════════════════════════════

    def update(self, days: int = 5) -> dict:
        """增量更新：基于最近 N 个交易日逐 Provider 刷新健康状态。

        Args:
            days: 最近 N 个交易日（默认 5）

        Returns:
            dict: {provider_id: {"status": ..., "freshness": ...}}
        """
        if days <= 0:
            raise ValueError("--days 必须 > 0")

        print(f"🔄 开始增量数据更新 (source={self.source}, days={days})")
        print()

        providers = self._get_providers()
        results: dict[str, dict] = {}

        for provider in providers:
            pid = provider.capability.name
            print(f"  ── 检查 {pid} ...")

            try:
                health = provider.self_check()
            except Exception as e:
                logger.exception(f"{pid} self_check 异常")
                results[pid] = {"status": "error", "error": str(e)}
                print(f"     ❌ {pid} 自检异常: {e}")
                continue

            results[pid] = {
                "status": health.status,
                "freshness": health.data_freshness,
                "warnings": health.warnings,
                "errors": health.errors,
                "checked_at": _now_cst_str(),
            }

            status_icon = "✅" if health.status == "ok" else ("⚠️" if health.status == "partial" else "❌")
            fresh_info = "; ".join(
                f"{k}={v}" for k, v in health.data_freshness.items()
            ) or "no freshness data"
            print(f"     {status_icon} {health.status:7s} | {fresh_info}")
            if health.warnings:
                for w in health.warnings:
                    print(f"       ⚠ {w}")
            if health.errors:
                for e in health.errors:
                    print(f"       ❌ {e}")

        # 写入 freshness 记录
        freshness_path = HEALTH_DIR / FRESHNESS_FILE
        freshness_record = {
            "source": self.source,
            "days": days,
            "providers": results,
            "updated_at": _now_cst_str(),
        }
        with open(freshness_path, "w", encoding="utf-8") as f:
            json.dump(freshness_record, f, ensure_ascii=False, indent=2)

        print()
        ok_count = sum(1 for v in results.values() if v.get("status") == "ok")
        partial_count = sum(1 for v in results.values() if v.get("status") == "partial")
        err_count = sum(1 for v in results.values() if v.get("status") == "error")
        print(f"📋 汇总: {len(results)} providers, {ok_count} ok, {partial_count} partial, {err_count} error")
        print(f"   freshness 记录: {freshness_path}")

        return results

    # ═══════════════════════════════════════════════════════════
    # data:health
    # ═══════════════════════════════════════════════════════════

    def health(self) -> list[dict]:
        """输出所有数据源健康状态，格式为表格。

        返回每个 Provider 的：覆盖率、缺失率、最新日期、异常值、
        以及最近一次 freshness 记录中的状态。

        Returns:
            list[dict]: 健康状态列表
        """
        print(f"📊 数据源健康状态 (source={self.source})")
        print()

        providers = self._get_providers()

        # 读取上次 freshness 记录
        freshness_path = HEALTH_DIR / FRESHNESS_FILE
        past_freshness: dict = {}
        if freshness_path.exists():
            try:
                with open(freshness_path, "r") as f:
                    past_freshness = json.load(f)
            except (json.JSONDecodeError, Exception):
                past_freshness = {}

        rows: list[dict] = []

        # ── 表头 ──
        header = f"{'Provider':24s} {'Status':10s} {'Latest Date':16s} {'Data Types':12s} {'Errors':12s} {'Warnings':12s}"
        sep = "-" * len(header)
        print(header)
        print(sep)

        for provider in providers:
            pid = provider.capability.name

            # 实时自检
            try:
                health = provider.self_check()
            except Exception as e:
                health_status = "error"
                latest_date = "-"
                errors = str(e)
                warnings = "-"
                data_types_count = 0
            else:
                health_status = health.status
                errors = "; ".join(health.errors) if health.errors else "-"
                warnings = "; ".join(health.warnings) if health.warnings else "-"

                # 从 freshness 中提取最新日期
                freshness_map = health.data_freshness
                # 尝试从 freshness 中找日期列
                date_values = [v for v in freshness_map.values() if v != "ok" and v != "-"]
                latest_date = max(date_values) if date_values else "-"

                # 统计数据类型数
                cap = provider.capability
                enabled_types = [
                    attr.replace("can_", "")
                    for attr in dir(cap)
                    if attr.startswith("can_") and getattr(cap, attr)
                ]
                data_types_count = len(enabled_types)

            row = {
                "provider": pid,
                "status": health_status,
                "latest_date": latest_date,
                "data_types": data_types_count,
                "errors": errors if errors != "-" else "",
                "warnings": warnings if warnings != "-" else "",
            }
            rows.append(row)

            status_icon = "✅" if health_status == "ok" else ("⚠️" if health_status == "partial" else "❌")
            print(f"{pid:24s} {status_icon} {health_status:8s} {str(latest_date)[:14]:16s} {str(data_types_count):12s} {errors[:10]:12s} {warnings[:10]:12s}")

        # ── 覆盖率 / 缺失率统计 ──
        print()
        total = len(rows)
        ok_count = sum(1 for r in rows if r["status"] == "ok")
        partial_count = sum(1 for r in rows if r["status"] == "partial")
        err_count = sum(1 for r in rows if r["status"] == "error")
        total_data_types = sum(r["data_types"] for r in rows)

        coverage_rate = ok_count / total * 100 if total > 0 else 0
        missing_rate = (partial_count + err_count) / total * 100 if total > 0 else 0

        print(f"  覆盖率: {ok_count}/{total} ({coverage_rate:.1f}%)")
        print(f"  缺失率: {partial_count + err_count}/{total} ({missing_rate:.1f}%)")
        print(f"  异常数: {err_count}")
        print(f"  总计数据类型: {total_data_types}")

        # 如果有过去的 freshness 记录，输出上次更新时间
        if past_freshness:
            last_update = past_freshness.get("updated_at", "未知")
            print(f"  最近更新: {last_update}")

        # 写入 health report
        health_report_path = HEALTH_DIR / HEALTH_FILE
        report = {
            "source": self.source,
            "checked_at": _now_cst_str(),
            "providers": rows,
            "summary": {
                "total": total,
                "ok": ok_count,
                "partial": partial_count,
                "error": err_count,
                "coverage_pct": round(coverage_rate, 1),
                "missing_pct": round(missing_rate, 1),
                "total_data_types": total_data_types,
            },
        }
        with open(health_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n  健康报告已保存: {health_report_path}")

        return rows


# ═══════════════════════════════════════════════════════════════
# CLI Handler Functions
# ═══════════════════════════════════════════════════════════════


def cmd_bootstrap(args: list[str]) -> None:
    """处理 data:bootstrap 命令"""
    source = "tushare"
    start = ""
    end = ""

    for i, a in enumerate(args):
        if a == "--source" and i + 1 < len(args):
            source = args[i + 1]
        elif a == "--start" and i + 1 < len(args):
            start = args[i + 1]
        elif a == "--end" and i + 1 < len(args):
            end = args[i + 1]

    if not start:
        print("❌ 用法: hermes data:bootstrap --source tushare --start 20190101 [--end 20261231]")
        return

    dm = DataManager(source=source)
    dm.bootstrap(start=start, end=end or None)


def cmd_update(args: list[str]) -> None:
    """处理 data:update 命令"""
    source = "tushare"
    days = 5

    for i, a in enumerate(args):
        if a == "--source" and i + 1 < len(args):
            source = args[i + 1]
        elif a == "--days" and i + 1 < len(args):
            try:
                days = int(args[i + 1])
            except ValueError:
                pass

    dm = DataManager(source=source)
    dm.update(days=days)


def cmd_health(args: list[str]) -> None:
    """处理 data:health 命令"""
    source = "tushare"
    for i, a in enumerate(args):
        if a == "--source" and i + 1 < len(args):
            source = args[i + 1]

    dm = DataManager(source=source)
    dm.health()
