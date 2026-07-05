"""Position Source Registry — 统一选择持仓数据源"""
import os, json
from pathlib import Path
from factor_lab.broker.broker_position_adapter import read_positions


def resolve_source(config: dict) -> dict:
    """从配置中选择可用的持仓数据源

    config: {
        "preferred": "broker_export",
        "fallback_order": ["broker_export", "manual_csv"],
        "broker_export": {"path": "...", "encoding": "auto"},
        "manual_csv": {"path": "..."},
    }

    返回: {source_used, fallback_used, fallback_reason, source_status, positions, ...}
    """
    preferred = config.get("preferred", "manual_csv")
    fallback_order = config.get("fallback_order", [preferred])

    result = {
        "preferred_source": preferred,
        "source_used": None,
        "fallback_used": False,
        "fallback_reason": "",
        "source_status": {},
        "positions": [],
        "cash": 0.0,
        "errors": [],
        "status": "ok",
    }

    tried = []
    for source_name in fallback_order:
        source_cfg = config.get(source_name, {})
        path = source_cfg.get("path", "")
        if not path or not os.path.exists(path):
            result["source_status"][source_name] = {
                "available": False,
                "reason": "文件不存在" if path else "路径未配置",
            }
            tried.append(source_name)
            continue

        # 读取
        adapter_result = read_positions(path, encoding=source_cfg.get("encoding", "auto"))
        result["source_status"][source_name] = {
            "available": adapter_result["status"] in ("ok", "partial"),
            "status": adapter_result["status"],
            "encoding": adapter_result.get("encoding_used", ""),
            "rows": len(adapter_result.get("normalized", [])),
        }

        if adapter_result["status"] == "failed":
            tried.append(source_name)
            continue

        result["source_used"] = source_name
        result["positions"] = adapter_result.get("normalized", [])
        result["cash"] = adapter_result.get("cash", 0.0)
        result["encoding_used"] = adapter_result.get("encoding_used", "")
        result["field_map"] = adapter_result.get("field_map", {})
        result["adapter_status"] = adapter_result.get("status", "ok")
        result["adapter_warnings"] = adapter_result.get("warnings", [])
        result["adapter_errors"] = adapter_result.get("errors", [])

        if source_name != preferred:
            result["fallback_used"] = True
            result["fallback_reason"] = f"{preferred} 不可用, 切换到 {source_name}: {', '.join(adapter_result.get('errors', []))}"

        return result

    # 所有数据源都不可用
    result["source_used"] = "none"
    result["status"] = "failed"
    result["errors"] = [f"所有数据源不可用: {', '.join(tried)}"]
    return result
