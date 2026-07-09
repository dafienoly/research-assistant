"""人工确认接口 — 因子注册确认/拒绝

注册后推送待确认消息，用户通过 CLI 确认或拒绝。
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

ALPHA_REGISTRY_ROOT = Path("/mnt/d/HermesData/alpha_registry")
REGISTRY_INDEX = ALPHA_REGISTRY_ROOT / "registry_index.json"
PENDING_FILE = ALPHA_REGISTRY_ROOT / "pending_confirmations.json"


def _load_pending() -> list[dict]:
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text())
    return []


def _save_pending(data: list[dict]):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def add_pending(alpha_id: str, name: str, ic_mean: float, sharpe: float,
                max_dd: float, summary: str):
    """添加待确认项"""
    pending = _load_pending()
    # 去重
    pending = [p for p in pending if p["alpha_id"] != alpha_id]
    pending.append({
        "alpha_id": alpha_id,
        "name": name,
        "ic_mean": ic_mean,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "summary": summary,
        "created_at": datetime.now(CST).isoformat(),
        "status": "pending",
    })
    _save_pending(pending)


def cmd_pending_list() -> str:
    """列出待确认项"""
    pending = _load_pending()
    active = [p for p in pending if p["status"] == "pending"]
    if not active:
        return "📭 无待确认的因子注册"

    lines = ["📋 待确认因子注册:", ""]
    for p in active:
        created = p.get("created_at", "?")[:19]
        lines.append(
            f"  [{p['alpha_id']}] {p['name']}\n"
            f"     IC={p['ic_mean']:.4f}  Sharpe={p['sharpe']:.2f}  "
            f"MaxDD={p['max_dd']:.1f}%\n"
            f"     创建: {created}"
        )
    lines.append(f"\n共 {len(active)} 项待确认")
    lines.append("确认: pipeline:confirm --alpha-id <id>")
    lines.append("拒绝: pipeline:reject  --alpha-id <id> [--reason ...]")
    return "\n".join(lines)


def cmd_confirm(alpha_id: str) -> str:
    """确认注册：将 Alpha 状态设为 draft + 标记开始影子观察"""
    pending = _load_pending()
    matched = [p for p in pending if p["alpha_id"] == alpha_id]

    if not matched:
        return f"❌ 未找到待确认项: {alpha_id}"

    item = matched[0]
    name = item["name"]

    # 更新 registry index: status draft → enabled
    if REGISTRY_INDEX.exists():
        index = json.loads(REGISTRY_INDEX.read_text())
        for entry in index:
            if entry.get("alpha_id") == alpha_id:
                entry["status"] = "draft"
                entry["enabled"] = True
                entry["updated_at"] = datetime.now(CST).isoformat()
                REGISTRY_INDEX.write_text(
                    json.dumps(index, indent=2, ensure_ascii=False)
                )
                break

    # 更新 alpha_spec.json
    alpha_dir = ALPHA_REGISTRY_ROOT / alpha_id
    spec_file = alpha_dir / "alpha_spec.json"
    if spec_file.exists():
        spec = json.loads(spec_file.read_text())
        spec["status"] = "draft"
        spec["enabled"] = True
        spec["updated_at"] = datetime.now(CST).isoformat()
        spec_file.write_text(json.dumps(spec, indent=2, ensure_ascii=False))

    # 进入影子观察
    try:
        sys.path.insert(0, str(Path(__file__).parent.resolve()))
        from shadow_observer import ShadowObserver
        ShadowObserver().mark_observing(alpha_id)
    except Exception as e:
        pass  # 非阻塞

    # 移除待确认
    pending = [p for p in pending if p["alpha_id"] != alpha_id]
    _save_pending(pending)

    # 企微通知
    try:
        from factor_lab.notify import notify_goal_done
        notify_goal_done(
            f"✅ 因子确认: {name}",
            f"因子 {name} 已确认，进入影子观察期\nAlpha ID: {alpha_id}"
        )
    except Exception:
        pass

    return f"✅ {name} ({alpha_id}) 已确认，进入影子观察"


def cmd_reject(alpha_id: str, reason: str = "") -> str:
    """拒绝注册：从 registry 移除或标记为 rejected"""
    pending = _load_pending()
    matched = [p for p in pending if p["alpha_id"] == alpha_id]
    if not matched:
        return f"❌ 未找到待确认项: {alpha_id}"

    item = matched[0]
    name = item["name"]

    # 标记 registry 为 rejected
    if REGISTRY_INDEX.exists():
        index = json.loads(REGISTRY_INDEX.read_text())
        for entry in index:
            if entry.get("alpha_id") == alpha_id:
                entry["status"] = "rejected"
                entry["updated_at"] = datetime.now(CST).isoformat()
                REGISTRY_INDEX.write_text(
                    json.dumps(index, indent=2, ensure_ascii=False)
                )
                break

    # 从 pending 移除
    pending = [p for p in pending if p["alpha_id"] != alpha_id]
    _save_pending(pending)

    msg = f"因子 {name} ({alpha_id}) 已拒绝"
    if reason:
        msg += f"\n原因: {reason}"
    return f"❌ {msg}"
