"""人工确认接口 — 因子注册确认/拒绝

注册后推送待确认消息，用户通过 CLI 确认或拒绝。
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from factor_lab.alpha.storage import read_json, update_json, write_json

CST = timezone(timedelta(hours=8))

ALPHA_REGISTRY_ROOT = Path("/mnt/d/HermesData/alpha_registry")
REGISTRY_INDEX = ALPHA_REGISTRY_ROOT / "registry_index.json"
PENDING_FILE = ALPHA_REGISTRY_ROOT / "pending_confirmations.json"


def _load_pending() -> list[dict]:
    return read_json(PENDING_FILE, [])


def _save_pending(data: list[dict]):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(PENDING_FILE, data)


def add_pending(alpha_id: str, name: str, ic_mean: float, sharpe: float,
                max_dd: float, summary: str):
    """添加待确认项"""
    record = {
        "alpha_id": alpha_id,
        "name": name,
        "ic_mean": ic_mean,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "summary": summary,
        "created_at": datetime.now(CST).isoformat(),
        "status": "pending",
    }
    update_json(
        PENDING_FILE,
        [],
        lambda pending: [p for p in pending if p["alpha_id"] != alpha_id] + [record],
    )


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
    """Human-approve a disabled candidate and start Shadow observation."""
    pending = _load_pending()
    matched = [p for p in pending if p["alpha_id"] == alpha_id]

    if not matched:
        return f"❌ 未找到待确认项: {alpha_id}"

    item = matched[0]
    name = item["name"]

    # Human approval is not production approval. Shadow and OOS must still pass.
    if REGISTRY_INDEX.exists():
        def approve_index(index):
            for entry in index:
                if entry.get("alpha_id") != alpha_id:
                    continue
                entry["status"] = "human_approved_shadow"
                entry["enabled"] = False
                entry["paper_enabled"] = False
                entry["live_enabled"] = False
                entry["human_approved_at"] = datetime.now(CST).isoformat()
                entry["updated_at"] = datetime.now(CST).isoformat()
            return index

        update_json(REGISTRY_INDEX, [], approve_index)

    # 更新 alpha_spec.json
    alpha_dir = ALPHA_REGISTRY_ROOT / alpha_id
    spec_file = alpha_dir / "alpha_spec.json"
    if spec_file.exists():
        def approve_spec(spec):
            spec.update({
                "status": "human_approved_shadow", "enabled": False,
                "paper_enabled": False, "live_enabled": False,
                "human_approved_at": datetime.now(CST).isoformat(),
                "updated_at": datetime.now(CST).isoformat(),
            })
            return spec

        update_json(spec_file, {}, approve_spec)

    # 进入影子观察
    try:
        sys.path.insert(0, str(Path(__file__).parent.resolve()))
        from shadow_observer import ShadowObserver
        ShadowObserver().mark_observing(alpha_id)
    except Exception:
        pass  # 非阻塞

    # 移除待确认
    update_json(PENDING_FILE, [], lambda rows: [p for p in rows if p["alpha_id"] != alpha_id])

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
        def reject_index(index):
            for entry in index:
                if entry.get("alpha_id") == alpha_id:
                    entry["status"] = "rejected"
                    entry["updated_at"] = datetime.now(CST).isoformat()
            return index

        update_json(REGISTRY_INDEX, [], reject_index)

    # 从 pending 移除
    update_json(PENDING_FILE, [], lambda rows: [p for p in rows if p["alpha_id"] != alpha_id])

    msg = f"因子 {name} ({alpha_id}) 已拒绝"
    if reason:
        msg += f"\n原因: {reason}"
    return f"❌ {msg}"
