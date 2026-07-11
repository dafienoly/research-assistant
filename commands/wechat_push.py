"""Hermes A股投研助手 — 企业微信推送客户端

支持 dry-run 模式，所有推送记录写入 wechat_push_log.jsonl。
"""

import uuid

from config import ENV, PATHS, now_str, append_jsonl
from factor_lab.notify import _send_wecom_markdown
from factor_lab.notification_transport import post_json


class WeChatPushError(Exception):
    pass


class WeChatPusher:
    """企业微信消息推送器

    支持:
    - 普通文本消息 (wechat_notice)
    - Markdown 消息 (wechat_urgent)
    - 摘要合并 (wechat_digest)
    - dry-run 模式
    """

    def __init__(self):
        self.webhook_url = ENV.get("WECHAT_WEBHOOK_URL", "")
        self.enabled = ENV.get("WECHAT_ENABLED", False)
        self.dry_run = ENV.get("WECHAT_DRY_RUN", True)

    def _push_id(self) -> str:
        return f"{now_str()[:19].replace(':', '').replace('T', '_')}_{uuid.uuid4().hex[:6]}"

    def _log(self, level: str, channel: str, alert_type: str,
             symbols: list, sector: str = "", sent: bool = False,
             queued: bool = False,
             deduped: bool = False, codex_escalated: bool = False,
             summary: str = ""):
        record = {
            "push_id": self._push_id(),
            "created_at": now_str(),
            "level": level,
            "channel": channel,
            "alert_type": alert_type,
            "symbols": symbols,
            "sector": sector,
            "sent": sent,
            "queued": queued,
            "deduped": deduped,
            "codex_escalated": codex_escalated,
            "message_summary": summary,
        }
        log_path = PATHS["intraday"] / "wechat_push_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(log_path, record)
        return record

    def _call_webhook(self, payload: dict) -> bool:
        """Persist a text/markdown intent for the dual-channel worker."""
        message_type = payload.get("msgtype")
        if message_type == "markdown":
            content = str((payload.get("markdown") or {}).get("content", ""))
        else:
            content = str((payload.get("text") or {}).get("content", ""))
        if not content or not _send_wecom_markdown("Hermes 风险通知", content):
            raise WeChatPushError("通知 intent 持久化失败")
        return True

    def push_notice(self, level: str, alert_type: str, symbols: list,
                    sector: str, title: str, body_lines: list,
                    codex_escalated: bool = False) -> dict:
        """推送文本消息 (L2/L3)"""
        channel = "wechat_notice"
        message = "\n".join(body_lines)
        summary = body_lines[-1] if body_lines else title

        if self.dry_run:
            record = self._log(level, channel, alert_type, symbols, sector,
                              sent=False, codex_escalated=codex_escalated,
                              summary=f"[DRY-RUN] {summary}")
            return record

        if not self.enabled:
            record = self._log(level, channel, alert_type, symbols, sector,
                              sent=False, codex_escalated=codex_escalated,
                              summary=f"[DISABLED] {summary}")
            return record

        payload = {
            "msgtype": "text",
            "text": {
                "content": message,
                "mentioned_list": [],
            }
        }

        try:
            queued = self._call_webhook(payload)
        except WeChatPushError as e:
            queued = False
            summary = f"[FAILED] {e}"

        record = self._log(level, channel, alert_type, symbols, sector,
                          sent=False, queued=queued, codex_escalated=codex_escalated,
                          summary=summary)
        return record

    def push_urgent(self, level: str, alert_type: str, symbols: list,
                    sector: str, title: str, markdown_body: str,
                    codex_escalated: bool = False) -> dict:
        """推送 Markdown 卡片 (L4 critical)"""
        channel = "wechat_urgent"

        if self.dry_run:
            record = self._log(level, channel, alert_type, symbols, sector,
                              sent=False, codex_escalated=codex_escalated,
                              summary=f"[DRY-RUN] {title}")
            return record

        if not self.enabled:
            record = self._log(level, channel, alert_type, symbols, sector,
                              sent=False, codex_escalated=codex_escalated,
                              summary=f"[DISABLED] {title}")
            return record

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": markdown_body,
            }
        }

        try:
            queued = self._call_webhook(payload)
        except WeChatPushError:
            queued = False
            title = f"[FAILED] {title}"

        record = self._log(level, channel, alert_type, symbols, sector,
                          sent=False, queued=queued, codex_escalated=codex_escalated,
                          summary=title)
        return record

    def test_connection(self) -> bool:
        """测试 webhook 连通性"""
        if not self.webhook_url:
            print("❌ WECHAT_WEBHOOK_URL 未配置")
            return False
        payload = {
            "msgtype": "text",
            "text": {
                "content": "🔔 Hermes A股监测 — 连接测试成功\n"
                           f"时间：{now_str()}\n"
                           f"模式：{'DRY-RUN' if self.dry_run else 'LIVE'}\n"
                           f"启用状态：{'已启用' if self.enabled else '已禁用'}",
            }
        }
        try:
            result = post_json(self.webhook_url, payload, timeout=10)
            ok = bool(result.get("ok") and (result.get("response") or {}).get("errcode") == 0)
            print(f"{'✅' if ok else '❌'} 企业微信 webhook 连接{'成功' if ok else '失败'}")
            return ok
        except (OSError, ValueError, TimeoutError) as e:
            print(f"❌ 连接失败: {e}")
            return False


# === 预设消息工厂 ===

def build_position_drop_notice(symbol: str, name: str, price: float,
                                change_pct: float, threshold: float,
                                data_freshness_s: int) -> list:
    """构建持仓下跌通知"""
    return [
        "⚠️ [L2 用户通知] 持仓风险初筛",
        "━━━━━━━━━━━━━━━━━━",
        f"股票：{symbol}·{name}",
        f"当前价：{price:.2f} 元",
        f"跌幅：{change_pct:.1f}%",
        f"触发规则：持仓股跌幅 > {threshold}%（R01）",
        f"数据新鲜度：{data_freshness_s}s 前 | {'✅ 正常' if data_freshness_s < 60 else '⚠️ 延迟'}",
        "━━━━━━━━━━━━━━━━━━",
        "风险等级：中等 | 建议观察",
        "下一步：关注午后能否收回",
        "是否需要 Codex 复核：否",
        "是否需要人工确认：否",
        "━━━━━━━━━━━━━━━━━━",
        f"Hermes A股监测 @ {now_str()}",
    ]


def build_position_critical_alert(symbol: str, name: str, price: float,
                                   change_pct: float, sector: str,
                                   sector_drop_count: int,
                                   data_freshness_s: int) -> str:
    """构建持仓暴跌 Markdown 卡片"""
    return (
        f"🔥 **L4 紧急预警**\n\n"
        f"**事件：持仓股暴跌 + 板块同步跳水**\n"
        f"**股票：** {symbol}·{name}\n"
        f"**当前价：** {price:.2f} 元 | **跌幅：** {change_pct:.1f}%\n"
        f"**板块：** {sector}\n"
        f"**板块状态：** {sector_drop_count} 只跌幅 > 5%，板块同步跳水确认\n\n"
        f"**触发规则：**\n"
        f"- R02：持仓股跌幅 > 5%\n"
        f"- R05：板块同步跳水（{sector_drop_count} 只 > 3%）\n"
        f"- 严重程度升级确认\n\n"
        f"**数据新鲜度：** {data_freshness_s}s 前 | ✅ 正常\n\n"
        f"**建议：** 数据已连续确认，需人工关注\n"
        f"**是否需要 Codex 复核：** 是（已升级）\n"
        f"**是否需要人工确认：** 是\n\n"
        f"**下一步观察点：**\n"
        f"1. 是否触及跌停\n"
        f"2. 板块是否继续扩散\n"
        f"3. 是否有重大利空公告\n\n"
        f"Hermes A股监测 @ {now_str()}"
    )


# === CLI 命令 ===
def cmd_test():
    pusher = WeChatPusher()
    pusher.test_connection()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        cmd_test()
    else:
        print("Usage: python wechat_push.py test")
