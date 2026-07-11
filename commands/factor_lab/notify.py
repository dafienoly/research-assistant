"""企业微信通知工具 — 任务完成推送 + 风控事件通知 + 每日摘要 + 盘前信号摘要

用法:
    from factor_lab.notify import notify_goal_done
    notify_goal_done("V1.7 策略验证", "ret5+close_gt_ma20 gate 全面超越基线")

    from factor_lab.notify import notify_risk_event, notify_risk_summary
    notify_risk_event("drawdown_exceeded", "最大回撤超过阈值", severity="critical")
    notify_risk_summary({"date": "2026-07-08", ...})

    from factor_lab.notify import notify_signal_summary
    notify_signal_summary("2026-07-08", "momentum_strategy", 15, 3, [...])

环境变量:
    WECHAT_WEBHOOK_URL — 企业微信机器人 webhook (已在 .bashrc 中)
"""
import hashlib
import os
import tempfile
from datetime import datetime, timezone, timedelta

from factor_lab.decision_loop.storage import DecisionLoopStore

CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 风控通知配置
# ---------------------------------------------------------------------------
_SEVERITY_LABELS = {
    "info": "ℹ️ 信息",
    "warning": "⚠️ 警告",
    "critical": "🚨 严重",
    "blocker": "🛑 阻断",
}
_last_sent: dict = {}  # 冷却缓存 {event_key: timestamp}
MAX_NOTIFICATION_ATTACHMENT_BYTES = 2 * 1024 * 1024


def queue_image_notification(title: str, image_bytes: bytes, caption: str = "") -> bool:
    """Persist one immutable PNG and queue it for both notification channels."""
    if not image_bytes or len(image_bytes) > MAX_NOTIFICATION_ATTACHMENT_BYTES:
        return False
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    digest = hashlib.sha256(image_bytes).hexdigest()
    event_digest = hashlib.sha256(f"{title}\0{caption}\0{digest}".encode("utf-8")).hexdigest()
    event_id = f"image_{event_digest[:24]}"
    queued_at = datetime.now(CST).isoformat()
    store = DecisionLoopStore()
    attachment_dir = store.path("notifications/attachments")
    attachment_dir.mkdir(parents=True, exist_ok=True)
    attachment = attachment_dir / f"{digest}.png"
    try:
        if attachment.exists():
            if hashlib.sha256(attachment.read_bytes()).hexdigest() != digest:
                return False
        else:
            fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=attachment_dir)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(image_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, attachment)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        relative_path = str(attachment.relative_to(store.root))
        payload = {
            "event_id": event_id,
            "text": caption or title,
            "attachment": {
                "relative_path": relative_path,
                "sha256": digest,
                "mime": "image/png",
                "size": len(image_bytes),
            },
        }
        store.append_unique_jsonl(
            "notifications/events.jsonl",
            {"event_id": event_id, "source": "image_notification", "title": title, "generated_at": queued_at},
            f"event:{event_id}",
        )
        store.append_unique_jsonl_batch(
            "notifications/outbox.jsonl",
            [
                (
                    {"event_id": event_id, "channel": channel, "payload": payload, "queued_at": queued_at, "max_attempts": 5},
                    f"{event_id}:{channel}",
                )
                for channel in ("telegram", "enterprise_wechat")
            ],
        )
        return True
    except (OSError, TimeoutError, ValueError):
        return False


def _send_wecom_markdown(title: str, content: str) -> bool:
    """将遗留通知持久化到 Telegram + 企业微信 outbox。

    Args:
        title: 消息标题（仅用于日志，企业微信 markdown 中不单独显示标题）
        content: Markdown 正文内容（最大 4096 字节）

    Returns:
        True 已持久化（含幂等重复），False 持久化失败。
    """
    # 企业微信 Markdown 消息最大 4096 字节，超长截断
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > 4096:
        # 截断到 4000 字节再补截断标记
        content = content_bytes[:4000].decode("utf-8", errors="ignore") + "\n\n> ⚠️ 内容已截断（原消息超 4096 字节）"

    digest = hashlib.sha256(f"{title}\0{content}".encode("utf-8")).hexdigest()
    event_id = f"legacy_{digest[:24]}"
    queued_at = datetime.now(CST).isoformat()
    store = DecisionLoopStore()
    try:
        store.append_unique_jsonl(
            "notifications/events.jsonl",
            {
                "event_id": event_id,
                "source": "legacy_notify",
                "title": title,
                "text": content,
                "generated_at": queued_at,
            },
            f"event:{event_id}",
        )
        store.append_unique_jsonl_batch(
            "notifications/outbox.jsonl",
            [
                (
                    {
                    "event_id": event_id,
                    "channel": channel,
                    "payload": {"event_id": event_id, "text": content, "format": "markdown"},
                    "queued_at": queued_at,
                    "max_attempts": 5,
                    },
                    f"{event_id}:{channel}",
                )
                for channel in ("telegram", "enterprise_wechat")
            ],
        )
        print(f"✅ 双通道通知已入队: {title} ({event_id})")
        return True
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"⚠️ 通知持久化失败 ({title}): {type(exc).__name__}")
        return False


def _check_cooldown(event_key: str, cooldown_seconds: int = 300) -> bool:
    """冷却检查，相同 event_key 在冷却期内不重复发送。

    使用内存 dict 做冷却缓存，进程重启后冷却重置。

    Args:
        event_key: 事件唯一键（如 "kill_switch_triggered" 或 "daily_summary_2026-07-08"）
        cooldown_seconds: 冷却秒数（默认 300 秒 / 5 分钟）

    Returns:
        True 表示在冷却期内（应跳过发送），False 表示可以发送。
    """
    import time
    now = time.time()
    last = _last_sent.get(event_key)
    if last is not None and (now - last) < cooldown_seconds:
        remaining = int(cooldown_seconds - (now - last))
        print(f"⏳ {event_key} 在冷却期内（剩余 {remaining}s），跳过重复发送")
        return True  # 冷却中
    _last_sent[event_key] = now
    return False  # 可以发送


def notify_goal_done(goal_name: str, summary: str = "", status: str = "completed"):
    """推送长任务完成通知到企业微信。

    仅在耗时较长的后台任务完成后调用, 通知用户回到 Hermes 会话查看结果。

    参数:
        goal_name: 任务名称 (如 "V1.7 策略验证")
        summary:   摘要 (如 "ret5+ma20_gate Sharpe+26%")
        status:    completed / failed / partial
    """
    now = datetime.now(CST).strftime("%m-%d %H:%M")
    status_icon = {"completed": "✅", "failed": "❌", "partial": "⚠️"}.get(status, "✅")

    content = (
        f"**{status_icon} {goal_name}**\n"
        f"> 时间: {now}\n"
        f"> 状态: {status}\n"
    )
    if summary:
        content += f"> {summary}\n"
    content += "> 请回到 Hermes 会话查看详细结果\n"

    _send_wecom_markdown(goal_name, content)


def notify_risk_event(
    event_type: str,
    detail: str,
    severity: str = "warning",
    symbol: str | None = None,
    value: float | None = None,
    threshold: float | None = None,
) -> bool:
    """推送风控事件到企业微信。

    参数:
        event_type: 事件类型标识（如 "drawdown_exceeded", "position_concentration"）
        detail:     事件详细描述
        severity:   严重级别: info / warning / critical / blocker
        symbol:     关联标的代码（可选）
        value:      当前实际值（可选）
        threshold:  阈值（可选）

    Returns:
        True 发送成功，False 发送失败或在冷却期内。
    """
    # 冷却检查：同一 event_type 5 分钟内不重复发送
    if _check_cooldown(f"risk_event:{event_type}", cooldown_seconds=300):
        return False

    label = _SEVERITY_LABELS.get(severity, "ℹ️ 信息")
    now = datetime.now(CST).strftime("%H:%M:%S")

    lines = [
        f"**{label} 风控事件**",
        f"> 事件类型: {event_type}",
        f"> 时间: {now}",
        f"> 详情: {detail}",
    ]
    if symbol:
        lines.append(f"> 标的: {symbol}")
    if value is not None:
        lines.append(f"> 当前值: {value}")
    if threshold is not None:
        lines.append(f"> 阈值: {threshold}")

    content = "\n".join(lines)
    return _send_wecom_markdown(f"[{severity.upper()}] {event_type}", content)


def notify_risk_summary(summary: dict) -> bool:
    """推送每日风控总结到企业微信。

    Args:
        summary: 风控摘要字典，包含:
            - date: 日期字符串 "2026-07-08"
            - total_checks: 总检查项数
            - passed: 通过数
            - warnings: 警告数
            - blockers: 阻断数
            - kill_switch_state: kill switch 状态
            - top_events: 重要事件列表（最多 5 条）

    Returns:
        True 发送成功，False 发送失败。
    """
    date_str = summary.get("date", datetime.now(CST).strftime("%Y-%m-%d"))

    # 冷却检查：每日摘要一天只发一次
    if _check_cooldown(f"daily_summary:{date_str}", cooldown_seconds=86400):
        return False

    total = summary.get("total_checks", 0)
    passed = summary.get("passed", 0)
    warnings = summary.get("warnings", 0)
    blockers = summary.get("blockers", 0)
    ks_state = summary.get("kill_switch_state", "armed")

    status_icon = "🟢" if blockers == 0 else "🔴"
    lines = [
        f"**{status_icon} 每日风控摘要 — {date_str}**",
        "",
        f"> 检查总数: **{total}**",
        f"> ✅ 通过: {passed}",
        f"> ⚠️ 警告: {warnings}",
        f"> 🛑 阻断: {blockers}",
        f"> Kill Switch: **{ks_state.upper()}**",
    ]

    top_events = summary.get("top_events", [])
    if top_events:
        lines.append("")
        lines.append("**TOP 事件:**")
        for i, evt in enumerate(top_events[:5], 1):
            lines.append(f"> {i}. {evt}")

    content = "\n".join(lines)
    return _send_wecom_markdown(f"每日风控摘要 {date_str}", content)


def notify_signal_summary(
    signal_date: str,
    strategy: str,
    n_candidates: int,
    n_blocked: int,
    top5: list,
) -> bool:
    """推送盘前信号摘要到企业微信。

    Args:
        signal_date: 信号日期 "2026-07-08"
        strategy:    策略名称
        n_candidates: 候选信号总数
        n_blocked:   被风控阻断数
        top5:        前 5 信号简要列表（每项为字符串）

    Returns:
        True 发送成功，False 发送失败。
    """
    # 盘前信号可按日期冷却，一天最多发几次（设 3600s 冷却避免短时重复）
    if _check_cooldown(f"signal_summary:{signal_date}:{strategy}", cooldown_seconds=3600):
        return False

    active = n_candidates - n_blocked
    lines = [
        f"**📊 盘前信号摘要 — {signal_date}**",
        f"> 策略: **{strategy}**",
        f"> 候选信号: {n_candidates}",
        f"> 风控阻断: {n_blocked}",
        f"> 有效信号: {active}",
    ]

    if top5:
        lines.append("")
        lines.append("**TOP 5 信号:**")
        for i, sig in enumerate(top5[:5], 1):
            lines.append(f"> {i}. {sig}")

    content = "\n".join(lines)
    return _send_wecom_markdown(f"盘前信号 {strategy} {signal_date}", content)
