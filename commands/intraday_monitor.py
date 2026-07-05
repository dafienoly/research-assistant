"""Hermes A股投研助手 — 盘中实时监测核心

包含:
- 规则引擎 (Rule)
- 事件分级 (L0-L4)
- 告警去重冷却 (Deduplicator)
- Codex 升级预算 (EscalationGate)
- 主监测循环 (IntradayMonitor)
"""

import json
import time
import copy
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

from config import (
    PATHS, CODEX_READ_ONLY, now_str, now_cst, ensure_dirs,
    read_csv_safe, append_jsonl, safe_write_json, file_rows,
)
from wechat_push import WeChatPusher, build_position_drop_notice, build_position_critical_alert
from rsscast_mcp import fetch_stock_prices, fetch_sina_quotes


# ========== 规则定义 ==========

class Rule:
    """监测规则"""

    def __init__(self, rule_id: str, name: str, priority: str,
                 description: str, level: str, default_threshold: float,
                 enabled: bool = True):
        self.rule_id = rule_id
        self.name = name
        self.priority = priority  # P0-P5
        self.description = description
        self.default_level = level
        self.default_threshold = default_threshold
        self.enabled = enabled

    def check(self, stock: dict, snapshot: dict, positions: list,
              candidates: list, watchlist: list) -> Optional[dict]:
        """检查规则是否触发。返回事件 dict 或 None。"""
        if not self.enabled:
            return None
        raise NotImplementedError


class PriceDropRule(Rule):
    """R01/R02: 持仓股跌幅规则"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        code = stock.get("code", "")
        price_info = snapshot.get(code)
        if not price_info:
            return None

        change_pct = abs(float(price_info.get("change_pct", 0)))
        if change_pct >= self.default_threshold:
            return {
                "alert_type": f"price_drop_{self.default_threshold}pct",
                "symbol": code,
                "name": stock.get("name", ""),
                "sector": stock.get("sector", ""),
                "price": float(price_info.get("price", 0)),
                "change_pct": -change_pct,
                "is_position": code in [p.get("code") for p in positions],
                "is_candidate": code in [c.get("code") for c in candidates],
                "is_watchlist": code in [w.get("code") for w in watchlist],
                "trigger_rule": f"跌幅>{self.default_threshold}% ({self.rule_id})",
                "data_freshness_seconds": int(price_info.get("delay_seconds", 0)),
            }
        return None


class PriceSurgeRule(Rule):
    """R03: 推荐池涨幅过高规则"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        code = stock.get("code", "")
        price_info = snapshot.get(code)
        if not price_info:
            return None

        change_pct = float(price_info.get("change_pct", 0))
        if change_pct >= self.default_threshold:
            return {
                "alert_type": f"price_surge_{self.default_threshold}pct",
                "symbol": code,
                "name": stock.get("name", ""),
                "sector": stock.get("sector", ""),
                "price": float(price_info.get("price", 0)),
                "change_pct": change_pct,
                "is_position": code in [p.get("code") for p in positions],
                "is_candidate": code in [c.get("code") for c in candidates],
                "is_watchlist": code in [w.get("code") for w in watchlist],
                "trigger_rule": f"涨幅>{self.default_threshold}% ({self.rule_id})",
                "data_freshness_seconds": int(price_info.get("delay_seconds", 0)),
            }
        return None


class DataStaleRule(Rule):
    """R08: 数据延迟规则"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        code = stock.get("code", "")
        price_info = snapshot.get(code)
        if not price_info:
            return None

        delay = int(price_info.get("delay_seconds", 0))
        if delay > self.default_threshold:
            return {
                "alert_type": "data_stale",
                "symbol": code,
                "name": stock.get("name", ""),
                "sector": stock.get("sector", ""),
                "price": float(price_info.get("price", 0)),
                "change_pct": float(price_info.get("change_pct", 0)),
                "is_position": False,
                "is_candidate": False,
                "is_watchlist": False,
                "trigger_rule": f"数据延迟>{self.default_threshold}s ({self.rule_id})",
                "data_freshness_seconds": delay,
            }
        return None


class WatchlistDropRule(Rule):
    """R04: 关注池跌幅规则"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        code = stock.get("code", "")
        price_info = snapshot.get(code)
        if not price_info:
            return None
        # 只对关注池生效
        if code not in [w.get("code") for w in watchlist]:
            return None

        change_pct = abs(float(price_info.get("change_pct", 0)))
        if change_pct >= self.default_threshold:
            return {
                "alert_type": f"watchlist_drop_{self.default_threshold}pct",
                "symbol": code,
                "name": stock.get("name", ""),
                "sector": stock.get("sector", ""),
                "price": float(price_info.get("price", 0)),
                "change_pct": -change_pct,
                "is_position": code in [p.get("code") for p in positions],
                "is_candidate": code in [c.get("code") for c in candidates],
                "is_watchlist": True,
                "trigger_rule": f"关注股跌幅>{self.default_threshold}% ({self.rule_id})",
                "data_freshness_seconds": int(price_info.get("delay_seconds", 0)),
            }
        return None


class SectorSyncDropRule(Rule):
    """R05/R06: 板块同步跳水规则"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        code = stock.get("code", "")
        sector = stock.get("sector", "")
        if not sector:
            return None

        # 统计同板块跌幅超过阈值的股票数
        sector_stocks = [s for s in list(snapshot.values()) if s.get("sector") == sector]
        sector_drops = [s for s in sector_stocks
                        if abs(float(s.get("change_pct", 0))) >= self.default_threshold]

        if len(sector_drops) >= 3:
            return {
                "alert_type": f"sector_sync_drop_{self.default_threshold}pct",
                "symbol": code,
                "name": stock.get("name", ""),
                "sector": sector,
                "price": float(price_info.get("price", 0)) if (price_info := snapshot.get(code)) else 0,
                "change_pct": float(price_info.get("change_pct", 0)) if (price_info := snapshot.get(code)) else 0,
                "is_position": code in [p.get("code") for p in positions],
                "is_candidate": code in [c.get("code") for c in candidates],
                "is_watchlist": code in [w.get("code") for w in watchlist],
                "sector_drop_count": len(sector_drops),
                "trigger_rule": f"板块同步跳水>{self.default_threshold}% ({len(sector_drops)}只) ({self.rule_id})",
                "data_freshness_seconds": 0,
            }
        return None


class VolumeSpikeRule(Rule):
    """R07: 成交额异常规则"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        code = stock.get("code", "")
        price_info = snapshot.get(code)
        if not price_info:
            return None

        # 简单版本: 超过5%且成交额显著
        change_pct = abs(float(price_info.get("change_pct", 0)))
        amount = float(price_info.get("amount", 0) or 0)

        if change_pct >= 3 and amount > 500_000_000:  # 5亿成交额
            return {
                "alert_type": "volume_spike",
                "symbol": code,
                "name": stock.get("name", ""),
                "sector": stock.get("sector", ""),
                "price": float(price_info.get("price", 0)),
                "change_pct": float(price_info.get("change_pct", 0)),
                "volume": price_info.get("volume", 0),
                "amount": amount,
                "is_position": code in [p.get("code") for p in positions],
                "is_candidate": code in [c.get("code") for c in candidates],
                "is_watchlist": code in [w.get("code") for w in watchlist],
                "trigger_rule": f"成交额异常: {amount/1e8:.1f}亿 ({self.rule_id})",
                "data_freshness_seconds": int(price_info.get("delay_seconds", 0)),
            }
        return None


class TailBlockRule(Rule):
    """R10: 尾盘限制规则 — 只标记不生成事件"""

    def check(self, stock, snapshot, positions, candidates, watchlist):
        # 由 check_once 中的 tail_block 直接处理
        return None


# ========== 告警去重冷却 ==========

class Deduplicator:
    """告警去重与冷却"""

    COOLDOWNS = {
        "L0": 900,     # 15 min
        "L1": 900,     # 15 min
        "L2": 600,     # 10 min
        "L3": 300,     # 5 min
        "L4": 0,       # 仅升级时重复
    }
    SECTOR_COOLDOWNS = {
        "L0": 900,
        "L1": 900,
        "L2": 600,
        "L3": 300,
        "L4": 0,
    }

    def __init__(self):
        self.state_path = PATHS["intraday"] / "alert_state.json"
        self.state = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                pass
        return {
            "last_updated": now_str(),
            "cooldowns": [],
            "budget": {
                "morning_used": 0,
                "morning_limit": 5,
                "afternoon_used": 0,
                "afternoon_limit": 5,
                "stock_daily": {},
                "sector_daily": {},
            },
        }

    def save(self):
        self.state["last_updated"] = now_str()
        safe_write_json(self.state_path, self.state)

    def _cooldown_key(self, event: dict) -> str:
        return f"{event.get('symbol', '')}|{event.get('alert_type', '')}"

    def _sector_key(self, event: dict) -> str:
        return f"{event.get('sector', '')}|{event.get('alert_type', '')}"

    def is_deduped(self, event: dict, level: str) -> bool:
        """检查事件是否在冷却期内"""
        now = now_cst()

        # 股票级冷却
        key = self._cooldown_key(event)
        cooldown_seconds = self.COOLDOWNS.get(level, 600)

        if level == "L4":
            # critical: 只有严重程度升级时才不 dedup
            for cd in self.state["cooldowns"]:
                if cd["key"] == key:
                    last = datetime.fromisoformat(cd["last_triggered"])
                    if (now - last).total_seconds() < cooldown_seconds:
                        # 检查严重程度是否升级
                        old_severity = cd.get("severity", "")
                        new_severity = event.get("severity", "")
                        if new_severity <= old_severity:
                            return True
            return False

        for cd in self.state["cooldowns"]:
            if cd["key"] == key:
                last = datetime.fromisoformat(cd["last_triggered"])
                if (now - last).total_seconds() < cooldown_seconds:
                    cd["count"] = cd.get("count", 0) + 1
                    return True

        return False

    def register_event(self, event: dict, level: str):
        """注册事件到冷却表"""
        now = now_str()
        key = self._cooldown_key(event)
        sector_key = self._sector_key(event)

        # 更新或添加冷却记录
        found = False
        for cd in self.state["cooldowns"]:
            if cd["key"] == key:
                cd["last_triggered"] = now
                cd["count"] = cd.get("count", 0) + 1
                cd["severity"] = event.get("severity", level)
                found = True
                break

        if not found:
            self.state["cooldowns"].append({
                "key": key,
                "symbol": event.get("symbol", ""),
                "alert_type": event.get("alert_type", ""),
                "last_triggered": now,
                "cooldown_seconds": self.COOLDOWNS.get(level, 600),
                "severity": event.get("severity", level),
                "count": 1,
                "escalated": False,
            })

        # 清理过期冷却（保留最近 200 条）
        if len(self.state["cooldowns"]) > 200:
            self.state["cooldowns"] = self.state["cooldowns"][-200:]


# ========== Codex 升级预算 ==========

class EscalationGate:
    """Codex 升级网关"""

    MORNING_LIMIT = 5
    AFTERNOON_LIMIT = 5
    STOCK_DAILY_LIMIT = 3
    SECTOR_DAILY_LIMIT = 3

    def __init__(self, dedup: Deduplicator):
        self.dedup = dedup
        self.escalation_path = PATHS["intraday"] / "codex_escalations.jsonl"

    def _is_morning(self) -> bool:
        now = now_cst()
        return 9 <= now.hour < 12

    def can_escalate(self, event: dict, level: str) -> bool:
        """检查是否允许升级"""
        if level == "L4":
            return True  # critical 不受预算限制

        budget = self.dedup.state.get("budget", {})
        symbol = event.get("symbol", "")
        sector = event.get("sector", "")

        if self._is_morning():
            if budget.get("morning_used", 0) >= self.MORNING_LIMIT:
                return False
        else:
            if budget.get("afternoon_used", 0) >= self.AFTERNOON_LIMIT:
                return False

        # 单只股票每日限制
        stock_used = budget.get("stock_daily", {}).get(symbol, 0)
        if stock_used >= self.STOCK_DAILY_LIMIT:
            return False

        # 同一板块每日限制
        if sector:
            sector_used = budget.get("sector_daily", {}).get(sector, 0)
            if sector_used >= self.SECTOR_DAILY_LIMIT:
                return False

        return True

    def consume_budget(self, event: dict, level: str):
        """消耗预算并写入 escalation"""
        if not self.can_escalate(event, level):
            return False

        budget = self.dedup.state["budget"]
        symbol = event.get("symbol", "")
        sector = event.get("sector", "")

        if level != "L4":
            if self._is_morning():
                budget["morning_used"] = budget.get("morning_used", 0) + 1
            else:
                budget["afternoon_used"] = budget.get("afternoon_used", 0) + 1

        if symbol:
            stock_daily = budget.setdefault("stock_daily", {})
            stock_daily[symbol] = stock_daily.get(symbol, 0) + 1

        if sector:
            sector_daily = budget.setdefault("sector_daily", {})
            sector_daily[sector] = sector_daily.get(sector, 0) + 1

        # 写入 codex_escalations.jsonl
        escalation = {
            "event_id": f"esc_{now_str()[:19].replace(':', '').replace('T', '_')}_{uuid4_short()}",
            "created_at": now_str(),
            "level": level,
            "alert_type": event.get("alert_type", ""),
            "symbol": symbol,
            "name": event.get("name", ""),
            "sector": sector,
            "price": event.get("price", 0),
            "change_pct": event.get("change_pct", 0),
            "trigger_rule": event.get("trigger_rule", ""),
            "data_freshness_seconds": event.get("data_freshness_seconds", 0),
            "reason": self._build_reason(event, level),
            "suggested_action": self._suggest_action(event, level),
            "force_judgment_blocked": event.get("data_freshness_seconds", 0) > 60,
        }
        append_jsonl(self.escalation_path, escalation)

        # 更新冷却状态的 escalated 标记
        key = f"{symbol}|{event.get('alert_type', '')}"
        for cd in self.dedup.state["cooldowns"]:
            if cd["key"] == key:
                cd["escalated"] = True
                break

        self.dedup.save()
        return True

    def _build_reason(self, event: dict, level: str) -> str:
        symbol = event.get("symbol", "")
        name = event.get("name", "")
        rule = event.get("trigger_rule", "")
        change = event.get("change_pct", 0)
        if abs(change) > 5:
            return f"{symbol}·{name} 触发 {rule}，跌幅{abs(change):.1f}%，风险等级high，需要 Codex 复核"
        return f"{symbol}·{name} 触发 {rule}，需要 Codex 复核"

    def _suggest_action(self, event: dict, level: str) -> str:
        is_pos = event.get("is_position", False)
        if is_pos and level == "L4":
            return "建议 Codex 评估是否需要调整持仓"
        elif is_pos:
            return "建议 Codex 复核是否需要调整"
        elif level == "L4":
            return "建议 Codex 紧急复核"
        return "建议 Codex 关注"

    @staticmethod
    def upgrade_conditions(event: dict) -> bool:
        """判断是否满足升级条件"""
        level = event.get("level", "")
        if level == "L4":
            return True  # L4 必须升级

        alert_type = event.get("alert_type", "")
        change_pct = abs(event.get("change_pct", 0))
        is_position = event.get("is_position", False)
        is_candidate = event.get("is_candidate", False)
        is_watchlist = event.get("is_watchlist", False)
        sector_drop_count = event.get("sector_drop_count", 0)

        return any([
            # 持仓股大跌 >5%
            is_position and change_pct >= 5,
            # 推荐池冲高回落
            is_candidate and "surge" in alert_type,
            # 持续风险未缓解（简化为同一事件第二次触发）
            event.get("consecutive_hit", False),
            # 板块暴跌 + 涉及持仓/候选
            (is_position or is_candidate) and sector_drop_count >= 5,
            # 规则冲突检查标记
            event.get("rule_conflict", False),
        ])


def uuid4_short() -> str:
    import uuid
    return uuid.uuid4().hex[:6]


# ========== 主监测器 ==========

DEFAULT_RULES = [
    PriceDropRule("R01", "持仓股大跌", "P0",
                  "持仓股跌幅 > 3%", "L2", 3.0),
    PriceDropRule("R02", "持仓股暴跌", "P0",
                  "持仓股跌幅 > 5%", "L3", 5.0),
    PriceSurgeRule("R03", "推荐池追高风险", "P1",
                   "推荐池涨幅 > 7%", "L2", 7.0),
    WatchlistDropRule("R04", "关注池跌幅", "P2",
                      "关注池跌幅 > 4%", "L2", 4.0),
    SectorSyncDropRule("R05", "板块同步跳水", "P3",
                       "板块内>3只跌幅>3%", "L2", 3.0),
    SectorSyncDropRule("R06", "板块暴跌", "P3",
                       "板块内>5只跌幅>5%", "L3", 5.0),
    VolumeSpikeRule("R07", "成交额异常", "P4",
                    "成交额异常放大", "L1", 0),
    DataStaleRule("R08", "数据延迟检查", "P5",
                  "live_snapshot 延迟 > 60s", "L0", 60),
    # R09: 数据缺失率高 — 在 check_once 中由 snapshot 完整性检查处理
    TailBlockRule("R10", "尾盘限制", "P5",
                  "14:55-15:00 禁止新开仓", "L0", 0),
]


class IntradayMonitor:
    """盘中实时监测主类"""

    def __init__(self):
        ensure_dirs()
        self.dedup = Deduplicator()
        self.gate = EscalationGate(self.dedup)
        self.pusher = WeChatPusher()
        self.rules = copy.deepcopy(DEFAULT_RULES)
        self.running = False

        # 状态
        self.events_log_path = PATHS["intraday"] / "events_log.jsonl"
        self.digest_path = PATHS["intraday"] / "intraday_digest.json"
        self.risk_path = PATHS["intraday"] / "risk_state.json"
        self.snapshot_path = PATHS["intraday"] / "live_snapshot_priority.csv"

        # 读取业务数据
        self.positions = []
        self.candidates = []
        self.watchlist = []

    def load_business_data(self):
        """读取 positions / candidates / watchlist"""
        self.positions = read_csv_safe(CODEX_READ_ONLY.get("positions", Path()), required=False)
        self.candidates = read_csv_safe(CODEX_READ_ONLY.get("today_candidates", Path()), required=False)
        self.watchlist = read_csv_safe(CODEX_READ_ONLY.get("watchlist", Path()), required=False)

        # 也读取 tags 用于板块分析
        self.theme_tags = read_csv_safe(CODEX_READ_ONLY.get("stock_theme_tags", Path()), required=False)
        print(f"📊 读取: {len(self.positions)} 持仓, {len(self.candidates)} 推荐, {len(self.watchlist)} 关注")

    def load_snapshot(self) -> dict:
        """加载实时快照 — Phase 2: 使用 RSScast MCP + Sina + 本地缓存"""
        # 收集所有关注的股票代码
        all_codes = set()
        for items in [self.positions, self.candidates, self.watchlist]:
            for item in items:
                code = str(item.get("code", "")).strip()
                if code:
                    all_codes.add(code)

        # 也加入 WSL tags 中的重点股
        tags_data = read_csv_safe(PATHS["tags"] / "semiconductor_chain_tags.csv")
        for row in tags_data:
            code = str(row.get("code", "")).strip()
            if code:
                all_codes.add(code)

        codes_list = sorted(all_codes)
        if not codes_list:
            # 没有关注的股票，尝试本地缓存
            cached = PATHS["market"] / "live_snapshot.csv"
            if cached.exists():
                rows = read_csv_safe(cached)
                codes_list = [r.get("code", "") for r in rows if r.get("code")]

        snapshot = {}
        if codes_list:
            # 1. RSScast MCP
            try:
                prices = fetch_stock_prices(codes_list[:50])  # MCP 限制
                for p in prices:
                    code = str(p.get("code", ""))
                    if code:
                        snapshot[code] = {
                            "code": code,
                            "price": p.get("last_price", 0),
                            "change_pct": p.get("change_pct", 0) * 100 if p.get("change_pct") else 0,
                            "volume": p.get("volume", 0),
                            "amount": p.get("amount", 0),
                            "amplitude": p.get("amplitude", 0),
                            "turnover_rate": p.get("turnover_rate", 0),
                            "delay_seconds": 0,  # MCP 数据无延迟
                            "source": "rsscast",
                        }
            except Exception as e:
                print(f"⚠️ RSScast 行情获取失败: {e}")

            # 2. 如果还有未覆盖的，用 Sina 补充
            missing = [c for c in codes_list if c not in snapshot]
            if missing:
                try:
                    sina = fetch_sina_quotes(missing[:200])
                    for code, data in sina.items():
                        if code not in snapshot and data.get("last_price"):
                            snapshot[code] = {
                                "code": code,
                                "price": data.get("last_price", 0),
                                "change_pct": (data.get("change_pct", 0) * 100) if data.get("change_pct") else 0,
                                "volume": data.get("volume", 0),
                                "amount": data.get("amount", 0),
                                "delay_seconds": 0,
                                "source": "sina",
                            }
                except Exception as e:
                    print(f"⚠️ Sina 行情获取失败: {e}")

        return snapshot

    def classify_event(self, event: dict) -> str:
        """对事件进行 L0-L4 分级"""
        rule_id = event.get("trigger_rule", "")
        change_pct = abs(event.get("change_pct", 0))
        is_position = event.get("is_position", False)
        is_candidate = event.get("is_candidate", False)
        is_watchlist = event.get("is_watchlist", False)
        delay = event.get("data_freshness_seconds", 0)

        # 数据延迟 > 60s → L0
        if delay > 60:
            return "L0"
        if event.get("alert_type") == "data_stale":
            return "L0"

        # 持仓股大跌 + 板块同步 → L4
        if is_position and change_pct >= 5 and event.get("sector_drop_count", 0) >= 3:
            return "L4"
        # 持仓股大跌
        if is_position and change_pct >= 5:
            return "L3"
        if is_position and change_pct >= 3:
            return "L2"

        # 板块同步跳水 >5只跌幅>5% → L3
        if event.get("sector_drop_count", 0) > 5 and change_pct >= 5:
            return "L3"

        # 板块同步跳水 >3只跌幅>3% → L2
        if event.get("sector_drop_count", 0) >= 3:
            return "L2"

        # 成交额异常 → L1
        if event.get("alert_type") == "volume_spike":
            return "L1"

        # 推荐池追高
        if is_candidate and change_pct >= 7:
            return "L2"

        # 关注池跌幅
        if is_watchlist and change_pct >= 4:
            return "L2"

        return "L1"

    def check_once(self) -> list:
        """执行一次盘中检查，返回产生的事件列表"""
        now = now_cst()
        hour = now.hour
        minute = now.minute

        # 14:55-15:00 禁止新开仓类 alert
        tail_block = (hour == 14 and minute >= 55) or (hour == 15 and minute == 0)

        snapshot = self.load_snapshot()
        if not snapshot:
            # 没有快照数据（第一阶段）
            print("⏳ 快照数据不可用（第一阶段骨架运行）")
            return []

        # R09: 数据缺失率高检查
        events = []
        if snapshot:
            missing_count = sum(1 for v in snapshot.values()
                                if v.get("price") is None or v.get("change_pct") is None)
            total = len(snapshot)
            if total > 0 and missing_count / total > 0.2:
                r09_event = {
                    "alert_type": "data_missing",
                    "symbol": "ALL",
                    "name": "全市场",
                    "sector": "",
                    "price": 0,
                    "change_pct": 0,
                    "is_position": False,
                    "is_candidate": False,
                    "is_watchlist": False,
                    "trigger_rule": f"数据缺失率>{missing_count}/{total}={missing_count/total*100:.0f}% (R09)",
                    "data_freshness_seconds": 0,
                    "level": "L1",
                }
                events.append(r09_event)

        # 合并所有需监测的股票
        all_stocks = []
        seen = set()
        for p in self.positions:
            code = p.get("code", "")
            if code and code not in seen:
                p["_priority"] = "P0"
                all_stocks.append(p)
                seen.add(code)
        for c in self.candidates:
            code = c.get("code", "")
            if code and code not in seen:
                c["_priority"] = "P1"
                all_stocks.append(c)
                seen.add(code)
        for w in self.watchlist:
            code = w.get("code", "")
            if code and code not in seen:
                w["_priority"] = "P2"
                all_stocks.append(w)
                seen.add(code)

        # 运行规则引擎
        for stock in all_stocks:
            for rule in self.rules:
                try:
                    event = rule.check(stock, snapshot, self.positions,
                                       self.candidates, self.watchlist)
                except Exception:
                    continue
                if event is None:
                    continue

                # 尾盘限制
                if tail_block and rule.rule_id in ("R01", "R03"):
                    # 降级为 L1 或丢弃
                    event["_tail_blocked"] = True
                    event["level"] = "L1"
                    events.append(event)
                    continue

                # 分类分级
                level = self.classify_event(event)
                event["level"] = level

                # 去重
                if self.dedup.is_deduped(event, level):
                    event["_deduped"] = True
                    events.append(event)
                    continue

                event["_deduped"] = False
                events.append(event)

        # 处理事件：日志、推送、升级
        for event in events:
            level = event.get("level", "L0")
            deduped = event.get("_deduped", False)
            tail_blocked = event.get("_tail_blocked", False)

            # 写 events_log.jsonl
            log_entry = {
                "created_at": now_str(),
                "level": level,
                "alert_type": event.get("alert_type", ""),
                "symbol": event.get("symbol", ""),
                "name": event.get("name", ""),
                "price": event.get("price", 0),
                "change_pct": event.get("change_pct", 0),
                "trigger_rule": event.get("trigger_rule", ""),
                "deduped": deduped,
                "tail_blocked": tail_blocked,
            }
            append_jsonl(self.events_log_path, log_entry)

            if deduped:
                continue  # 重复事件不推送不升级

            # 注册冷却
            self.dedup.register_event(event, level)

            # L0-L1 不推送
            if level in ("L0", "L1"):
                continue

            # L2 推送企业微信
            if level == "L2":
                symbol = event.get("symbol", "")
                name = event.get("name", "")
                price = event.get("price", 0)
                change = event.get("change_pct", 0)
                delay = event.get("data_freshness_seconds", 0)
                lines = build_position_drop_notice(
                    symbol, name, price, abs(change), 3.0, delay
                )
                self.pusher.push_notice(
                    level, event.get("alert_type", ""),
                    [symbol], event.get("sector", ""),
                    f"{name} 触发预警", lines,
                    codex_escalated=False,
                )

            # L3 推送 + Codex 升级
            if level == "L3" and EscalationGate.upgrade_conditions(event):
                symbol = event.get("symbol", "")
                name = event.get("name", "")
                price = event.get("price", 0)
                change = event.get("change_pct", 0)
                delay = event.get("data_freshness_seconds", 0)
                lines = build_position_drop_notice(
                    symbol, name, price, abs(change), 5.0, delay
                )
                self.pusher.push_notice(
                    level, event.get("alert_type", ""),
                    [symbol], event.get("sector", ""),
                    f"{name} 风险升级",
                    lines[:3] + [f"** 需要 Codex 复核 **"] + lines[3:],
                    codex_escalated=True,
                )
                self.gate.consume_budget(event, level)

            # L4 紧急推送 + Codex 升级（不受限）
            if level == "L4":
                symbol = event.get("symbol", "")
                name = event.get("name", "")
                price = event.get("price", 0)
                change = event.get("change_pct", 0)
                delay = event.get("data_freshness_seconds", 0)
                sector = event.get("sector", "")
                markdown = build_position_critical_alert(
                    symbol, name, price, abs(change), sector,
                    event.get("sector_drop_count", 0), delay,
                )
                self.pusher.push_urgent(
                    level, event.get("alert_type", ""),
                    [symbol], sector,
                    f"🔥 L4 {name} 紧急预警",
                    markdown,
                    codex_escalated=True,
                )
                self.gate.consume_budget(event, level)

        # 保存去重状态
        self.dedup.save()

        # 更新 digest
        if events:
            self._update_digest(events)

        return events

    def _update_digest(self, events: list):
        """更新盘中摘要"""
        digest = {
            "last_updated": now_str(),
            "total_events_today": sum(
                1 for _ in open(self.events_log_path) if self.events_log_path.exists()
            ) if self.events_log_path.exists() else len(events),
            "recent_events": [
                {
                    "time": e.get("created_at", now_str()),
                    "level": e.get("level", "L0"),
                    "symbol": e.get("symbol", ""),
                    "name": e.get("name", ""),
                    "alert_type": e.get("alert_type", ""),
                    "change_pct": e.get("change_pct", 0),
                }
                for e in events[-20:]
            ],
            "budget": self.dedup.state.get("budget", {}),
            "positions_count": len(self.positions),
        }
        safe_write_json(self.digest_path, digest)

    def prepare(self):
        """初始化盘中状态"""
        print(f"🔧 初始化盘中监测状态 @ {now_str()}")
        self.load_business_data()
        self.dedup = Deduplicator()
        self.gate = EscalationGate(self.dedup)
        budget = self.dedup.state.setdefault("budget", {})
        # 根据时段重置预算
        now = now_cst()
        if now.hour < 12:
            budget["morning_used"] = 0
        else:
            budget["afternoon_used"] = 0
        self.dedup.save()
        print(f"✅ 初始化完成。持仓: {len(self.positions)}, 推荐: {len(self.candidates)}, 关注: {len(self.watchlist)}")

    def watch(self, interval: int = 45, max_cycles: int = None):
        """盘中循环监测"""
        self.running = True
        cycle = 0
        print(f"▶️ 开始盘中循环监测（间隔 {interval}s）@ {now_str()}")

        try:
            while self.running:
                now = now_cst()
                hour = now.hour

                # 11:30-13:00 暂停
                if 11 <= hour < 13:
                    if hour == 11 and now.minute >= 30:
                        print(f"⏸️ 午休暂停 @ {now_str()}")
                        time.sleep(60)
                        continue
                    elif hour == 12:
                        time.sleep(60)
                        continue

                events = self.check_once()
                if events:
                    triggered = [e for e in events if not e.get("_deduped")]
                    print(f"🔄 [{now_str()}] 检查完成: {len(events)} 事件 ({len(triggered)} 新触发)")
                else:
                    print(f"🔄 [{now_str()}] 检查完成: 无事件")

                cycle += 1
                if max_cycles and cycle >= max_cycles:
                    print(f"⏹️ 达到最大循环次数 {max_cycles}")
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n⏹️ 监测被中断")
        finally:
            self.running = False

    def stop(self):
        """停止监测"""
        self.running = False
        print(f"⏹️ 盘中监测已停止 @ {now_str()}")


# === CLI 命令 ===
def cmd_prepare():
    monitor = IntradayMonitor()
    monitor.prepare()


def cmd_check_once():
    monitor = IntradayMonitor()
    monitor.load_business_data()
    events = monitor.check_once()
    levels = {}
    for e in events:
        l = e.get("level", "?")
        levels[l] = levels.get(l, 0) + 1
    print(f"事件统计: {levels}")
    print(f"总事件: {len(events)}")


def cmd_watch():
    import sys
    interval = 45
    if len(sys.argv) > 2:
        try:
            interval = int(sys.argv[2])
        except ValueError:
            pass
    monitor = IntradayMonitor()
    monitor.prepare()
    monitor.watch(interval=interval)


if __name__ == "__main__":
    import sys
    cmds = {
        "prepare": cmd_prepare,
        "check-once": cmd_check_once,
        "watch": cmd_watch,
    }
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print("Usage: python intraday_monitor.py <command>")
        print(f"Commands: {', '.join(cmds.keys())}")
