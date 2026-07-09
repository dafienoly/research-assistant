"""监管事件数据库 — 监管函、立案调查、关注函、问询函等

替代人工/启发式监管风险判断，通过东方财富公告数据自动提取
涉及监管行动的公司名单。

用法:
    from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist

    rw = RegulatoryWatchlist()
    n = rw.refresh()          # 从数据源更新
    print(rw.is_blacklisted("300001"))  # True 如果有严重监管事件
    print(rw.get_events("300001"))      # 获取近期监管事件
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

_DEFAULT_CACHE_DIR = Path("/mnt/d/HermesData/regulatory_watchlist")

# 监管关键词 — 按严重程度分级
REGULATORY_KEYWORDS = {
    "blacklist": [  # 严重监管事件 — 直接影响交易决策
        "立案调查",
        "立案侦查",
        "取保候审",
        "被证监会",
        "行政处罚",
        "行政处罚决定",
        "行政处罚事先告知",
        "市场禁入",
        "公开谴责",
        "通报批评",
        "纪律处分",
        "暂停上市",
        "终止上市",
        "强制退市",
        "涉嫌信息披露违法违规",
    ],
    "warning": [  # 中等风险
        "监管函",
        "监管关注",
        "关注函",
        "问询函",
        "问询",
        "警示函",
        "警示",
        "责令改正",
        "责令整改",
        "约谈",
        "约见谈话",
        "监管谈话",
        "出具警示函",
        "监管措施",
        "监管问询",
    ],
    "notice": [  # 低风险 — 仅记录
        "股权冻结",
        "股份冻结",
        "资产冻结",
        "债务逾期",
        "债务违约",
        "业绩预告修正",
        "业绩变脸",
        "重大诉讼",
        "仲裁",
        "会计差错更正",
        "前期会计差错",
    ],
}

# 严重程度标签
SEVERITY_LABELS = {
    "blacklist": "严重",
    "warning": "警告",
    "notice": "关注",
}


class RegulatoryWatchlist:
    """监管事件数据库

    通过东方财富公告数据（data.eastmoney.com/notices）获取公司公告，
    依据标题中的监管关键词自动归类为:
      - blacklist（严重: 立案调查、行政处罚）
      - warning（中等: 监管函、关注函、问询函）
      - notice（低风险: 诉讼、冻结、债务违约）

    CACHE_PATH: 缓存文件路径，默认 /mnt/d/HermesData/regulatory_watchlist/events.json
    """

    CACHE_PATH: Path = _DEFAULT_CACHE_DIR / "events.json"

    def __init__(self, cache_path: Optional[str | Path] = None):
        if cache_path is not None:
            self.CACHE_PATH = Path(cache_path)
        self._events: list[dict] = []
        self._blacklist_symbols: set[str] = set()
        self._warning_symbols: set[str] = set()
        self._loaded = False

    # ──────────────────────────────────────────────
    # 数据获取
    # ──────────────────────────────────────────────

    def refresh(self) -> int:
        """从数据源更新监管事件

        使用 akshare.stock_notice_report() 获取最新公告，
        按标题筛选监管相关事件。

        Returns:
            int: 本次获取的监管事件数量

        Raises:
            RuntimeError: 所有数据源均不可用
        """
        records = self._fetch_from_api()
        if records is None:
            raise RuntimeError(
                "RegulatoryWatchlist.refresh: 无法获取监管事件数据，"
                "请检查网络连接"
            )

        # 写入缓存
        self.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(CST).isoformat(),
            "count": len(records),
            "events": records,
        }
        self.CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 更新内存索引
        self._build_index(records)
        self._loaded = True

        return len(records)

    def _fetch_from_api(self) -> Optional[list[dict]]:
        """从东方财富公告 API 获取数据"""
        # 方法 1: akshare
        records = self._fetch_via_akshare()
        if records is not None:
            return records

        return None

    def _fetch_via_akshare(self) -> Optional[list[dict]]:
        """通过 akshare.stock_notice_report() 获取最新公告，过滤监管事件"""
        try:
            import akshare as ak

            # 临时清除 proxy
            saved = {}
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                      "ALL_PROXY", "all_proxy"]:
                saved[k] = os.environ.pop(k, None)
            try:
                df = ak.stock_notice_report()
            except Exception:
                return None
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v

            if df is None or df.empty:
                return None

            records = []

            # 标准列名映射
            col_map = {
                "代码": "code",
                "名称": "name",
                "公告标题": "title",
                "公告类型": "announcement_type",
                "公告日期": "date",
                "网址": "url",
                "code": "code",
                "name": "name",
                "title": "title",
                "date": "date",
                "url": "url",
            }

            for _, row in df.iterrows():
                title = str(
                    row.get("公告标题", row.get("title", ""))
                )

                # 跳过空标题
                if not title or title == "nan":
                    continue

                # 检查是否包含监管关键词
                matched_keywords = self._match_keywords(title)
                if not matched_keywords:
                    continue

                code = str(
                    row.get("代码", row.get("code", ""))
                ).strip()
                name = str(
                    row.get("名称", row.get("name", ""))
                ).strip()
                date_val = str(
                    row.get("公告日期", row.get("date", ""))
                ).strip()[:10]

                severity = self._determine_severity(matched_keywords)

                records.append({
                    "symbol": code,
                    "name": name,
                    "title": title,
                    "date": date_val,
                    "matched_keywords": list(matched_keywords),
                    "severity": severity,
                    "severity_label": SEVERITY_LABELS.get(severity, "关注"),
                    "url": str(row.get("网址", row.get("url", ""))),
                })

            return records

        except ImportError:
            return None

    @staticmethod
    def _match_keywords(title: str) -> set[str]:
        """在标题中查找匹配的监管关键词"""
        matched: set[str] = set()
        for level, keywords in REGULATORY_KEYWORDS.items():
            for kw in keywords:
                if kw in title:
                    matched.add(kw)
        return matched

    @staticmethod
    def _determine_severity(matched_keywords: set[str]) -> str:
        """根据匹配的关键词确定严重级别"""
        # 按优先级: blacklist > warning > notice
        for level in ["blacklist", "warning", "notice"]:
            for kw in REGULATORY_KEYWORDS[level]:
                if kw in matched_keywords:
                    return level
        return "notice"

    def _build_index(self, records: list[dict]) -> None:
        """构建 symbol -> events 索引"""
        self._events = records
        self._blacklist_symbols.clear()
        self._warning_symbols.clear()

        for evt in records:
            sym = self._normalize_symbol(evt.get("symbol", ""))
            if not sym:
                continue

            severity = evt.get("severity", "notice")
            if severity == "blacklist":
                self._blacklist_symbols.add(sym)
            elif severity == "warning":
                self._warning_symbols.add(sym)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """标准化股票代码为 6 位数字"""
        code = "".join(ch for ch in symbol if ch.isdigit())[:6]
        if len(code) == 6 and code.isdigit():
            return code
        return ""

    # ──────────────────────────────────────────────
    # 缓存管理
    # ──────────────────────────────────────────────

    def load_cache(self) -> bool:
        """从缓存文件加载

        Returns:
            bool: 是否成功加载
        """
        if not self.CACHE_PATH.exists():
            return False

        try:
            data = json.loads(self.CACHE_PATH.read_text(encoding="utf-8"))

            cached_date = data.get("updated_at", "")[:10]
            today = date.today().isoformat()
            if cached_date == today:
                self._build_index(data.get("events", []))
                self._loaded = True
                return True

            return False
        except (json.JSONDecodeError, KeyError, OSError):
            return False

    def ensure_fresh(self) -> int:
        """确保数据是最新的

        Returns:
            int: 监管事件数量
        """
        if self.load_cache():
            return len(self._events)

        return self.refresh()

    # ──────────────────────────────────────────────
    # 查询
    # ──────────────────────────────────────────────

    def is_blacklisted(self, symbol: str) -> bool:
        """是否有严重监管事件（立案调查、行政处罚等）

        Args:
            symbol: 股票代码

        Returns:
            bool: 是否有严重监管事件
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return False

        code = self._normalize_symbol(symbol)
        if not code:
            return False

        return code in self._blacklist_symbols

    def has_recent_regulatory_risk(self, symbol: str, days: int = 30) -> bool:
        """近期是否有监管风险

        检查 days 天内是否有 blacklist 或 warning 级别的监管事件。

        Args:
            symbol: 股票代码
            days: 检查天数（默认 30 天）

        Returns:
            bool: 近期是否有监管风险
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return False

        code = self._normalize_symbol(symbol)
        if not code:
            return False

        if code in self._blacklist_symbols:
            return True

        if code in self._warning_symbols:
            # 检查是否在 days 天内
            cutoff = date.today() - timedelta(days=days)
            for evt in self._events:
                sym = self._normalize_symbol(evt.get("symbol", ""))
                if sym != code:
                    continue
                try:
                    evt_date = datetime.strptime(
                        str(evt.get("date", ""))[:10], "%Y-%m-%d"
                    ).date()
                    if evt_date >= cutoff:
                        return True
                except (ValueError, TypeError):
                    continue

        return False

    def get_events(self, symbol: str, days: Optional[int] = None) -> list[dict]:
        """获取股票的相关监管事件

        Args:
            symbol: 股票代码
            days: 可选，仅返回最近 N 天的事件

        Returns:
            list[dict]: 监管事件列表
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return []

        code = self._normalize_symbol(symbol)
        if not code:
            return []

        cutoff = None
        if days is not None:
            cutoff = date.today() - timedelta(days=days)

        results = []
        for evt in self._events:
            sym = self._normalize_symbol(evt.get("symbol", ""))
            if sym != code:
                continue

            if cutoff is not None:
                try:
                    evt_date = datetime.strptime(
                        str(evt.get("date", ""))[:10], "%Y-%m-%d"
                    ).date()
                    if evt_date < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

            results.append(evt)

        return results

    def get_all_blacklisted(self) -> list[str]:
        """获取所有严重监管事件股票代码列表

        Returns:
            list[str]: 严重监管事件股票代码
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return []

        return sorted(self._blacklist_symbols)

    def get_all_warnings(self) -> list[str]:
        """获取所有中等监管事件股票代码列表

        Returns:
            list[str]: 中等监管事件股票代码
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return []

        return sorted(self._warning_symbols)

    def get_summary(self) -> dict:
        """获取监管事件摘要统计

        Returns:
            dict: {n_blacklisted, n_warning, n_notice, total}
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return {"n_blacklisted": 0, "n_warning": 0, "n_notice": 0, "total": 0}

        n_blacklisted = len(self._blacklist_symbols)
        n_warning = len(self._warning_symbols)
        n_notice = sum(
            1 for evt in self._events if evt.get("severity") == "notice"
        )

        return {
            "n_blacklisted": n_blacklisted,
            "n_warning": n_warning,
            "n_notice": n_notice,
            "total": len(self._events),
        }
