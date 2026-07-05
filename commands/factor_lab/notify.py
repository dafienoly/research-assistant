"""企业微信通知工具 — 任务完成时推送提醒

用法:
    from factor_lab.notify import notify_goal_done
    notify_goal_done("V1.7 策略验证", "ret5+close_gt_ma20 gate 全面超越基线")

环境变量:
    WECHAT_WEBHOOK_URL — 企业微信机器人 webhook (已在 .bashrc 中)
"""
import os, json, urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def notify_goal_done(goal_name: str, summary: str = "", status: str = "completed"):
    """推送长任务完成通知到企业微信

    仅在耗时较长的后台任务完成后调用, 通知用户回到 Hermes 会话查看结果。

    参数:
        goal_name: 任务名称 (如 "V1.7 策略验证")
        summary:   摘要 (如 "ret5+ma20_gate Sharpe+26%")
        status:    completed / failed / partial
    """
    webhook = os.environ.get("WECHAT_WEBHOOK_URL")
    if not webhook:
        # 从 .bashrc 直接读取
        import subprocess
        try:
            r = subprocess.run(
                ["bash", "-c", "source ~/.bashrc && echo $WECHAT_WEBHOOK_URL"],
                capture_output=True, text=True, timeout=5
            )
            webhook = r.stdout.strip()
        except:
            pass

    if not webhook:
        print("⚠️ WECHAT_WEBHOOK_URL 未配置, 跳过企业微信通知")
        return

    now = datetime.now(CST).strftime("%m-%d %H:%M")
    status_icon = {"completed": "✅", "failed": "❌", "partial": "⚠️"}.get(status, "✅")

    content = (
        f"**{status_icon} {goal_name}**\n"
        f"> 时间: {now}\n"
        f"> 状态: {status}\n"
    )
    if summary:
        content += f"> {summary}\n"
    content += f"> 请回到 Hermes 会话查看详细结果\n"

    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content}
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
        print(f"✅ 企业微信通知已发送: {goal_name}")
    except Exception as e:
        print(f"⚠️ 企业微信通知失败: {e}")
