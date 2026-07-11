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
from datetime import datetime

from config import (
    PATHS, CODEX_READ_ONLY, now_str, now_cst,
    ensure_dirs, read_csv_safe, append_jsonl, safe_write_json,
)
from wechat_push import WeChatPusher, build_position_drop_notice, build_position_critical_alert
from factor_lab.datahub_access import read_live_snapshot, read_market_turnover

# ========== V4.11 盘中低频监测常量 ==========

# 半导体ETF跳水预警监测目标
ETF_DIVE_WATCH_CODES = [
    "512480",  # 国联安中证全指半导体ETF
    "588290",  # 华安上证科创板芯片ETF
    "159516",  # 国泰中证半导体材料设备ETF
]

# U3 半导体核心池静态回退代码（优先从 semiconductor_chain_tags 动态加载）
U3_SEMICONDUCTOR_FALLBACK_CODES = [
    "688072", "688012", "688981", "688126", "688008",
    "002371", "002049", "300604", "300661", "603986",
    "603501", "600703", "600745", "300782", "300223",
]

# 指数监测目标
INDEX_WATCH_CODES = {
    "000001": "上证指数",
    "000688": "科创50",
    "000300": "沪深300",
}

# 全A情绪代码（通过 sina 或 eastmoney 获取）
WIND_A_CODE = "881001"

# 成交额异常阈值
VOLUME_ANOMALY_THRESHOLD_PCT = 30      # 当日成交额偏离20日均值 ±30% 即告警
VOLUME_ANOMALY_ABS_THRESHOLD = 500_000_000_000  # 全A成交额低于5000亿也告警


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
        """只读 DataHub canonical 实时快照；消费者不得自行访问 provider。"""
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
            return {}
        try:
            return read_live_snapshot(codes_list)
        except (FileNotFoundError, ValueError, OSError) as error:
            print(f"⚠️ DataHub 实时快照不可用: {error}")
            return {}

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


# =============================================================================
# V4.11 盘中低频监测引擎
# =============================================================================

class LowFreqMonitor:
    """盘中低频监测引擎 — 增强 V4.11

    功能:
    - 半导体ETF跳水预警
    - U3半导体核心池扩散度（上涨占比）
    - 全A情绪指标（涨跌家数比）
    - 指数风险监测
    - 成交额异常监测（当日 vs 20日均）
    - 企业微信推送预警

    使用方式:
        monitor = LowFreqMonitor()
        report = monitor.run_all()
        print(report.summary())
        monitor.send_wechat_alert()
    """

    def __init__(self):
        self.ensure_dirs()
        self.events: list[dict] = []
        self.etf_watch_codes = ETF_DIVE_WATCH_CODES
        self.index_codes = list(INDEX_WATCH_CODES.keys())
        self.report_time = now_cst()

        # 数据缓存
        self.quotes: dict[str, dict] = {}  # code -> {price, change_pct, volume, amount}
        self.index_quotes: dict[str, dict] = {}  # index_code -> {price, change_pct}
        self.market_snapshot: dict[str, dict] = {}  # all codes snapshot

        # 结果
        self.etf_alerts: list[dict] = []
        self.u3_diffusion: dict = {"rising": 0, "total": 0, "ratio": 0.0}
        self.sentiment: dict = {"advance": 0, "decline": 0, "ratio": 0.0}
        self.index_risk: list[dict] = []
        self.volume_anomaly: dict = {}
        self.push_results: list[dict] = []

    @staticmethod
    def ensure_dirs():
        """确保监测数据目录存在"""
        PATHS["intraday"].mkdir(parents=True, exist_ok=True)

    # ── 数据获取 ──────────────────────────────────────────

    def _load_datahub_snapshot(self) -> dict[str, dict]:
        if self.market_snapshot:
            return self.market_snapshot
        try:
            self.market_snapshot = read_live_snapshot()
        except (FileNotFoundError, ValueError, OSError) as error:
            print(f"  ⚠️ DataHub 实时快照不可用: {error}")
            self.market_snapshot = {}
        return self.market_snapshot

    def fetch_quotes(self, codes: list[str]) -> dict[str, dict]:
        """从 DataHub canonical 实时快照读取行情。

        Returns:
            {code: {price, change_pct, volume, amount, source}}
        """
        if not codes:
            return {}
        snapshot = self._load_datahub_snapshot()
        quotes = {}
        for code in codes:
            key = str(code).strip()
            bare = key.lower()[2:] if key.lower().startswith(("sh", "sz", "bj")) else key.lower()
            row = snapshot.get(bare)
            if row:
                quotes[key] = {**row, "code": key}
        self.quotes.update(quotes)
        return quotes

    def fetch_u3_codes(self) -> list[str]:
        """动态加载 U3 半导体核心池代码"""
        codes = []
        try:
            tags_csv = CODEX_READ_ONLY.get("semiconductor_chain_tags",
                                            PATHS["tags"] / "semiconductor_chain_tags.csv")
            rows = read_csv_safe(tags_csv)
            for row in rows:
                code = str(row.get("code", "")).strip()
                tag = str(row.get("tag", "") or row.get("theme", "") or "")
                if code and ("半导体" in tag or "芯片" in tag or "设备" in tag or "材料" in tag):
                    codes.append(code)
        except Exception:
            pass

        if not codes:
            # 回退到静态列表
            codes = list(U3_SEMICONDUCTOR_FALLBACK_CODES)
        return codes

    # ── 监测检查项 ────────────────────────────────────────

    def check_etf_dive(self) -> list[dict]:
        """1. 半导体ETF跳水预警

        Returns:
            [{"code", "name", "price", "change_pct", "alert_level", ...}]
        """
        alerts = []
        quotes = self.fetch_quotes(self.etf_watch_codes)
        for code in self.etf_watch_codes:
            q = quotes.get(code, {})
            if q.get("price") is None:
                continue
            change_pct = float(q.get("change_pct", 0) or 0)
            price = float(q.get("price", 0) or 0)

            # 跌幅 >= 2% 预警, >= 4% 严重
            if change_pct <= -2:
                alert = {
                    "code": code,
                    "name": self._etf_name(code),
                    "price": price,
                    "change_pct": change_pct,
                    "volume": q.get("volume", 0),
                    "amount": q.get("amount", 0),
                    "alert_level": "严重" if change_pct <= -4 else "预警",
                    "source": q.get("source", "unknown"),
                    "monitor_type": "etf_dive",
                    "trigger_rule": f"半导体ETF跌幅{change_pct:.1f}%",
                }
                alerts.append(alert)
        self.etf_alerts = alerts
        return alerts

    def check_u3_diffusion(self) -> dict:
        """2. U3 半导体核心池扩散度（上涨占比）

        Returns:
            {"rising": int, "total": int, "ratio": float, "stocks": [...]}
        """
        codes = self.fetch_u3_codes()
        quotes = self.fetch_quotes(codes)
        rising = 0
        total = 0
        stocks_detail = []
        for code in codes:
            q = quotes.get(code, {})
            if q.get("change_pct") is None:
                continue
            change = float(q["change_pct"])
            total += 1
            if change > 0:
                rising += 1
            stocks_detail.append({
                "code": code,
                "change_pct": change,
                "up": change > 0,
            })

        ratio = rising / total if total > 0 else 0.0
        self.u3_diffusion = {
            "rising": rising,
            "total": total,
            "ratio": round(ratio, 4),
            "ratio_pct": round(ratio * 100, 1),
            "stocks": stocks_detail,
        }
        return self.u3_diffusion

    def check_sentiment(self) -> dict:
        """3. 全A情绪指标（涨跌家数比）

        Returns:
            {"advance": int, "decline": int, "ratio": float, "status": str}
        """
        advance = 0
        decline = 0
        total = 0

        snapshot = self._load_datahub_snapshot() or self.quotes
        for quote in snapshot.values():
            change = quote.get("change_pct")
            if change is None:
                continue
            total += 1
            if float(change) > 0:
                advance += 1
            elif float(change) < 0:
                decline += 1

        ratio = advance / decline if decline > 0 else (advance if advance > 0 else 0)
        if advance == 0 and decline == 0:
            ratio = 0.0

        status = "正常"
        if ratio < 0.3 and total > 10:
            status = "极低迷"
        elif ratio < 0.5 and total > 10:
            status = "低迷"
        elif ratio > 2.0:
            status = "过热"

        self.sentiment = {
            "advance": advance,
            "decline": decline,
            "total": total,
            "ratio": round(ratio, 2),
            "status": status,
        }
        return self.sentiment

    def check_index_risk(self) -> list[dict]:
        """4. 指数风险监测

        Returns:
            [{"code", "name", "price", "change_pct", "risk_level", ...}]
        """
        results = []
        codes_with_prefix = []
        # 上证指数 sh000001, 沪深300 sh000300, 科创50 sh000688
        for code in self.index_codes:
            prefix = "sh" if code.startswith("000") else "sz"
            codes_with_prefix.append(f"{prefix}{code}")

        quotes = self.fetch_quotes(codes_with_prefix)
        for prefixed_code in codes_with_prefix:
            q = quotes.get(prefixed_code, {})
            if q.get("price") is None:
                # 去掉前缀再试 raw code
                bare = prefixed_code[2:] if prefixed_code[:2] in ("sh", "sz") else prefixed_code
                q = self.quotes.get(bare, {})
            if q.get("price") is None:
                continue

            bare = prefixed_code[2:] if prefixed_code[:2] in ("sh", "sz") else prefixed_code
            change_pct = float(q.get("change_pct", 0) or 0)
            name = INDEX_WATCH_CODES.get(bare, prefixed_code)

            risk_level = "正常"
            if change_pct <= -2:
                risk_level = "风险"
            elif change_pct <= -1:
                risk_level = "关注"
            elif change_pct >= 3:
                risk_level = "过热"

            result = {
                "code": bare,
                "name": name,
                "price": q.get("price"),
                "change_pct": change_pct,
                "risk_level": risk_level,
                "source": q.get("source", "unknown"),
                "monitor_type": "index_risk",
            }
            results.append(result)

        self.index_risk = results
        return results

    def check_volume_anomaly(self) -> dict:
        """5. 成交额异常监测（当日 vs 20日均）

        基于同一 DataHub canonical 实时快照汇总全市场成交额。

        Returns:
            {"today_volume": float, "avg_20d": float, "pct_deviation": float, "alert": bool}
        """
        result = {
            "today_volume": 0.0,
            "avg_20d": 0.0,
            "pct_deviation": 0.0,
            "alert": False,
            "data_status": "MISSING",
            "reason": "canonical_market_turnover_unavailable",
        }

        snapshot = self._load_datahub_snapshot()
        today_vol = sum(
            float(row["amount"])
            for row in snapshot.values()
            if row.get("amount") is not None
        )
        try:
            history = read_market_turnover()
            avg_20d = float(history.tail(20)["market_amount"].mean())
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as error:
            result.update(
                {
                    "today_volume": round(today_vol, 2),
                    "volume_label": self._fmt_vol(today_vol),
                    "avg_label": self._fmt_vol(0),
                    "reason": str(error),
                }
            )
            self.volume_anomaly = result
            return result

        pct_dev = 0.0
        if avg_20d > 0 and today_vol > 0:
            pct_dev = (today_vol - avg_20d) / avg_20d * 100

        alert = False
        if today_vol > 0:
            if abs(pct_dev) >= VOLUME_ANOMALY_THRESHOLD_PCT:
                alert = True
            if today_vol < VOLUME_ANOMALY_ABS_THRESHOLD:
                alert = True

        result = {
            "today_volume": round(today_vol, 2),
            "avg_20d": round(avg_20d, 2),
            "pct_deviation": round(pct_dev, 2),
            "alert": alert,
            "volume_label": self._fmt_vol(today_vol),
            "avg_label": self._fmt_vol(avg_20d),
            "data_status": "OK",
            "source": "datahub:derived/market_turnover",
            "reason": None,
        }
        self.volume_anomaly = result
        return result

    # ── 报告生成 ──────────────────────────────────────────

    def run_all(self) -> "LowFreqReport":
        """执行所有低频检查项，返回报告对象"""
        self.report_time = now_cst()

        # 按顺序执行各项检查
        self.check_etf_dive()
        self.check_u3_diffusion()
        self.check_sentiment()
        self.check_index_risk()
        self.check_volume_anomaly()

        return LowFreqReport(self)

    def build_markdown_summary(self) -> str:
        """构建企业微信 Markdown 格式摘要"""
        lines = [f"**📊 盘中低频监测报告 — {now_str()}**", ""]
        dt_str = self.report_time.strftime("%Y-%m-%d %H:%M")
        lines.append(f"> 生成时间: {dt_str}")
        lines.append("")

        # 1. ETF跳水预警
        lines.append("**1️⃣ 半导体ETF跳水预警**")
        if self.etf_alerts:
            for a in self.etf_alerts:
                icon = "🔴" if a["alert_level"] == "严重" else "🟡"
                lines.append(
                    f"> {icon} {a['code']} {a.get('name', '')} "
                    f"跌幅 {a['change_pct']:.1f}% "
                    f"级别: {a['alert_level']}"
                )
        else:
            lines.append("> ✅ 正常")
        lines.append("")

        # 2. U3扩散度
        u3 = self.u3_diffusion
        lines.append("**2️⃣ U3半导体核心池扩散度**")
        lines.append(
            f"> 上涨 {u3.get('rising', 0)} / {u3.get('total', 0)} "
            f"= {u3.get('ratio_pct', 0)}%"
        )
        if u3.get("total", 0) > 0:
            r = u3.get("ratio", 0)
            if r < 0.3:
                lines.append("> 🔴 扩散度偏低，市场情绪弱")
            elif r < 0.5:
                lines.append("> 🟡 扩散度中等")
            else:
                lines.append("> 🟢 扩散度健康")
        lines.append("")

        # 3. 情绪指标
        s = self.sentiment
        lines.append("**3️⃣ 全A情绪指标**")
        lines.append(
            f"> 上涨 {s.get('advance', 0)} / 下跌 {s.get('decline', 0)} "
            f"= {s.get('ratio', 0):.2f} ({s.get('status', '未知')})"
        )
        lines.append("")

        # 4. 指数风险
        lines.append("**4️⃣ 指数风险监测**")
        if self.index_risk:
            for idx in self.index_risk:
                icon = {"风险": "🔴", "关注": "🟡", "过热": "🟡", "正常": "🟢"}.get(
                    idx.get("risk_level", ""), "⚪"
                )
                cp = idx.get("change_pct", 0)
                cp_str = f"+{cp:.1f}%" if cp >= 0 else f"{cp:.1f}%"
                lines.append(
                    f"> {icon} {idx.get('name', '')} ({idx['code']}) "
                    f"{cp_str}  {idx.get('risk_level', '')}"
                )
        else:
            lines.append("> ⏳ 暂无指数数据")
        lines.append("")

        # 5. 成交额异常
        v = self.volume_anomaly
        lines.append("**5️⃣ 成交额监测**")
        if v.get("today_volume", 0) > 0:
            icon = "🔴" if v.get("alert") else "🟢"
            lines.append(
                f"> {icon} 今日 {v.get('volume_label', '--')} "
                f"| 20日均 {v.get('avg_label', '--')} "
                f"| 偏离 {v.get('pct_deviation', 0):.1f}%"
            )
        else:
            lines.append("> ⏳ 数据加载中...")
        lines.append("")

        # 6. 预警汇总
        total_alerts = len(self.etf_alerts)
        risk_count = sum(1 for r in self.index_risk if r.get("risk_level") in ("风险", "关注"))
        vol_alert = self.volume_anomaly.get("alert", False)
        if total_alerts > 0 or risk_count > 0 or vol_alert:
            lines.append("**⚠️ 预警汇总**")
            if total_alerts > 0:
                lines.append(f"> ETF跳水预警: {total_alerts} 条")
            if risk_count > 0:
                lines.append(f"> 指数风险: {risk_count} 条")
            if vol_alert:
                lines.append("> 成交额异常: 是")
        else:
            lines.append("**✅ 整体评估**")
            lines.append("> 各项指标正常，无预警")

        lines.append("")
        lines.append(f"> Hermes 低频监测 @ {now_str()}")
        return "\n".join(lines)

    def send_wechat_alert(self, dry_run: bool = True) -> list[dict]:
        """通过企业微信推送低频监测报告

        Args:
            dry_run: True=仅打印, False=实际发送

        Returns:
            [{"channel", "sent", "summary", ...}]
        """
        results = []

        # 1. ETF跳水预警推送 (严重级别直接推)
        for alert in self.etf_alerts:
            if alert["alert_level"] == "严重":
                msg_lines = [
                    f"🔴 ETF跳水预警",
                    f"━━━━━━━━━━━━━━━",
                    f"ETF: {alert['code']} {alert.get('name', '')}",
                    f"跌幅: {alert['change_pct']:.1f}%",
                    f"级别: {alert['alert_level']}",
                ]

                if dry_run:
                    print("\n".join(msg_lines))
                    results.append({"channel": "etf_dive", "sent": False, "summary": f"[DRY-RUN] {alert['code']}跳水预警"})
                else:
                    try:
                        from factor_lab.notify import notify_risk_event
                        ok = notify_risk_event(
                            event_type=f"etf_dive_{alert['code']}",
                            detail=f"{alert['code']} {alert.get('name', '')} 跌幅 {alert['change_pct']:.1f}%",
                            severity="critical" if alert["alert_level"] == "严重" else "warning",
                            symbol=alert["code"],
                            value=alert["change_pct"],
                        )
                        results.append({"channel": "etf_dive", "sent": ok, "summary": alert["code"]})
                    except Exception as e:
                        results.append({"channel": "etf_dive", "sent": False, "summary": f"推送失败: {e}"})

        # 2. 指数风险推送
        for idx in self.index_risk:
            if idx.get("risk_level") in ("风险",):
                if dry_run:
                    results.append({"channel": "index_risk", "sent": False, "summary": f"[DRY-RUN] {idx['name']}风险"})
                else:
                    try:
                        from factor_lab.notify import notify_risk_event
                        ok = notify_risk_event(
                            event_type=f"index_risk_{idx['code']}",
                            detail=f"{idx['name']} 跌幅 {idx['change_pct']:.1f}%",
                            severity="warning",
                            symbol=idx["code"],
                            value=idx["change_pct"],
                        )
                        results.append({"channel": "index_risk", "sent": ok, "summary": idx["code"]})
                    except Exception as e:
                        results.append({"channel": "index_risk", "sent": False, "summary": f"推送失败: {e}"})

        # 3. 定期报告推送 (每30分钟)
        if not dry_run:
            try:
                from factor_lab.notify import _send_wecom_markdown
                md = self.build_markdown_summary()
                ok = _send_wecom_markdown("盘中低频监测报告", md)
                results.append({"channel": "periodic_report", "sent": ok, "summary": "低频监测报告"})
            except Exception as e:
                results.append({"channel": "periodic_report", "sent": False, "summary": f"推送失败: {e}"})
        else:
            results.append({"channel": "periodic_report", "sent": False, "summary": "[DRY-RUN] 低频监测报告"})
            print(f"\n🔔 [DRY-RUN] 企业微信推送预览:\n{self.build_markdown_summary()}\n")

        self.push_results = results
        return results

    # ── 辅助方法 ──────────────────────────────────────────

    @staticmethod
    def _etf_name(code: str) -> str:
        names = {
            "512480": "国联安中证全指半导体ETF",
            "588290": "华安上证科创板芯片ETF",
            "159516": "国泰中证半导体材料设备ETF",
        }
        return names.get(code, code)

    @staticmethod
    def _fmt_vol(v: float) -> str:
        if v <= 0:
            return "--"
        if v >= 1e12:
            return f"{v/1e12:.2f}万亿"
        if v >= 1e8:
            return f"{v/1e8:.2f}亿"
        return f"{v/1e4:.2f}万"


class LowFreqReport:
    """低频监测报告对象"""

    def __init__(self, monitor: LowFreqMonitor):
        self.monitor = monitor
        self.generated_at = now_str()

    def summary(self) -> str:
        """打印终端摘要"""
        m = self.monitor
        lines = []
        lines.append("=" * 62)
        lines.append(f"  📊 盘后低频监测报告 @ {m.report_time.strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 62)

        # ETF
        lines.append(f"\n📉 半导体ETF跳水预警:")
        if m.etf_alerts:
            for a in m.etf_alerts:
                lines.append(f"  {a['code']} {a.get('name','')}: {a['change_pct']:.1f}% [{a['alert_level']}]")
        else:
            lines.append("  ✅ 正常")

        # U3
        u3 = m.u3_diffusion
        lines.append(f"\n🏭 U3半导体核心池扩散度:")
        lines.append(f"  上涨 {u3.get('rising',0)}/{u3.get('total',0)} = {u3.get('ratio_pct',0)}%")

        # 情绪
        s = m.sentiment
        lines.append(f"\n📈 全A情绪:")
        lines.append(f"  上涨 {s.get('advance',0)} 下跌 {s.get('decline',0)} "
                     f"比 {s.get('ratio',0):.2f} [{s.get('status','')}]")

        # 指数
        lines.append(f"\n🏛️ 指数风险:")
        for idx in m.index_risk:
            cp = idx.get('change_pct', 0)
            lines.append(f"  {idx.get('name','')}: {cp:+.1f}% [{idx.get('risk_level','')}]")

        # 成交额
        v = m.volume_anomaly
        lines.append(f"\n💰 成交额:")
        if v.get('today_volume', 0) > 0:
            lines.append(f"  今日 {v.get('volume_label','--')} | "
                         f"20日均 {v.get('avg_label','--')} | "
                         f"偏离 {v.get('pct_deviation',0):+.1f}%")
            if v.get('alert'):
                lines.append("  ⚠️ 成交额异常!")
        else:
            lines.append("  ⏳ 数据加载中")

        lines.append(f"\n{'=' * 62}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """返回完整数据结构"""
        m = self.monitor
        return {
            "generated_at": self.generated_at,
            "etf_alerts": m.etf_alerts,
            "u3_diffusion": m.u3_diffusion,
            "sentiment": m.sentiment,
            "index_risk": m.index_risk,
            "volume_anomaly": m.volume_anomaly,
            "push_results": m.push_results,
        }


# =============================================================================
# V4.11 CLI 命令
# =============================================================================

def cmd_lowfreq_monitor():
    """intraday:monitor — 执行一次盘中低频监测"""
    monitor = LowFreqMonitor()
    report = monitor.run_all()
    print(report.summary())
    # 写入日志
    log_path = PATHS["intraday"] / "lowfreq_events.jsonl"
    append_jsonl(log_path, report.to_dict())
    print(f"📝 报告已写入: {log_path}")


def cmd_lowfreq_risk():
    """intraday:risk — 仅显示指数风险和成交额异常"""
    monitor = LowFreqMonitor()
    monitor.check_index_risk()
    monitor.check_volume_anomaly()
    report = LowFreqReport(monitor)
    print(report.summary())


def cmd_lowfreq_wechat_alert():
    """intraday:wechat-alert — 执行监测并通过企业微信推送预警"""
    import sys
    dry_run = "--live" not in sys.argv
    if dry_run:
        print("🔔 DRY-RUN 模式 (企业微信推送仅打印，不实际发送)")
        print("   使用 --live 参数开启实际发送")
    else:
        print("🔴 LIVE 模式 (将实际发送企业微信消息)")

    monitor = LowFreqMonitor()
    report = monitor.run_all()
    print(report.summary())

    # 推送
    results = monitor.send_wechat_alert(dry_run=dry_run)
    for r in results:
        icon = "✅" if r["sent"] else ("🔔" if dry_run else "❌")
        print(f"  {icon} {r['channel']}: {r['summary']}")

    # 写入日志
    log_path = PATHS["intraday"] / "lowfreq_events.jsonl"
    append_jsonl(log_path, report.to_dict())
    print(f"📝 报告已写入: {log_path}")


def cmd_lowfreq_watch():
    """intraday:monitor --watch — 循环监测模式"""
    import sys
    import time

    interval = 300  # 默认5分钟
    if len(sys.argv) > 2 and sys.argv[2].isdigit():
        interval = int(sys.argv[2])

    print(f"🔄 低频循环监测模式，每 {interval}s 刷新 (Ctrl+C 退出)")
    try:
        while True:
            monitor = LowFreqMonitor()
            report = monitor.run_all()
            print(report.summary())

            # 检查是否需要推送预警
            has_alerts = (
                len(monitor.etf_alerts) > 0
                or monitor.volume_anomaly.get("alert", False)
                or any(r.get("risk_level") == "风险" for r in monitor.index_risk)
            )
            if has_alerts:
                print("⚠️ 检测到预警，推送企业微信...")
                results = monitor.send_wechat_alert(dry_run=True)
                for r in results:
                    print(f"  {r['channel']}: {r['summary']}")

            # 写入日志
            log_path = PATHS["intraday"] / "lowfreq_events.jsonl"
            append_jsonl(log_path, report.to_dict())

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹️ 低频监测已停止")


# 保留原有 cmd_watch 兼容
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
        "monitor": cmd_lowfreq_monitor,
        "risk": cmd_lowfreq_risk,
        "wechat-alert": cmd_lowfreq_wechat_alert,
        "monitor-watch": cmd_lowfreq_watch,
    }
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print("Usage: python intraday_monitor.py <command>")
        print(f"Commands: {', '.join(cmds.keys())}")
