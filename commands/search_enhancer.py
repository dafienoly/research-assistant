"""搜索增强模块 — Tavily / AnySearch / Firecrawl

用于政策事件、行业新闻的搜索补充。
Hermes 的 web_search 工具在 terminal 中不可用，
此模块通过 HTTP API 直接调用各搜索服务。
"""

import os
import json
import time
import urllib.request
import urllib.parse
from typing import Optional

from config import PATHS, now_str, append_jsonl
from quota import quota_check, quota_consume


def _log(provider: str, action: str, status: str, records: int = 0, error: str = ""):
    append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
        "timestamp": now_str(), "provider": provider, "action": action,
        "status": status, "records": records, "error": str(error)[:200],
    })


# ========== Tavily Search ==========

class TavilySearch:
    """Tavily Search API — 新闻/网页搜索增强"""

    def __init__(self):
        self.api_key = os.environ.get("TAVILY_API_KEY", "")
        self.name = "tavily"

    def search(self, query: str, max_results: int = 5, days: int = 7) -> list[dict]:
        """搜索新闻/网页"""
        if not self.api_key:
            _log(self.name, "search", "no_key")
            return []
        if not quota_check(self.name):
            _log(self.name, "search", "quota_exhausted")
            return []

        url = "https://api.tavily.com/search"
        payload = json.dumps({
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "include_domains": [],
            "exclude_domains": [],
            "max_results": max_results,
            "include_answer": False,
            "topic": "news" if days <= 7 else "general",
            "days": days,
        }).encode()

        try:
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json",
            })
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            _log(self.name, "search", "ok", len(results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:500],
                    "score": r.get("score", 0),
                    "published": r.get("published_date", ""),
                    "source": self.name,
                }
                for r in results
            ]
        except Exception as e:
            _log(self.name, "search", "error", 0, str(e))
            return []

    def search_events(self, keywords: list[str], max_per_keyword: int = 3) -> list[dict]:
        """批量搜索事件相关新闻"""
        all_results = []
        for kw in keywords:
            results = self.search(kw, max_per_keyword)
            all_results.extend(results)
            time.sleep(0.5)  # 避免频率限制
        return all_results


# ========== Firecrawl Search ==========

class FirecrawlSearch:
    """Firecrawl — 网页爬取/搜索"""

    def __init__(self):
        self.api_key = os.environ.get("FIRECRAWL_API_KEY", "")
        self.name = "firecrawl"

    def scrape(self, url: str) -> Optional[str]:
        """抓取单个网页内容"""
        if not self.api_key:
            _log(self.name, "scrape", "no_key")
            return None
        if not quota_check(self.name):
            _log(self.name, "scrape", "quota_exhausted")
            return None

        api_url = "https://api.firecrawl.dev/v1/scrape"
        payload = json.dumps({"url": url, "formats": ["markdown"]}).encode()
        try:
            req = urllib.request.Request(api_url, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            })
            resp = urllib.request.urlopen(req, timeout=20)
            data = json.loads(resp.read().decode())
            content = data.get("data", {}).get("markdown", "")
            _log(self.name, "scrape", "ok" if content else "empty", 0)
            return content[:3000] if content else None
        except Exception as e:
            _log(self.name, "scrape", "error", 0, str(e))
            return None

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Firecrawl 搜索"""
        if not self.api_key:
            _log(self.name, "search", "no_key")
            return []
        if not quota_check(self.name):
            _log(self.name, "search", "quota_exhausted")
            return []

        api_url = "https://api.firecrawl.dev/v1/search"
        payload = json.dumps({
            "query": query,
            "maxResults": max_results,
        }).encode()
        try:
            req = urllib.request.Request(api_url, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            })
            resp = urllib.request.urlopen(req, timeout=20)
            data = json.loads(resp.read().decode())
            results = data.get("data", [])
            _log(self.name, "search", "ok", len(results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("description", r.get("markdown", ""))[:500],
                    "source": self.name,
                }
                for r in results
            ]
        except Exception as e:
            _log(self.name, "search", "error", 0, str(e))
            return []

    def scrape_official_page(self, url: str) -> Optional[str]:
        """抓取官方政策页面内容"""
        return self.scrape(url)


# ========== AnySearch ==========

class AnySearch:
    """AnySearch — 备用搜索"""

    def __init__(self):
        self.api_key = os.environ.get("ANYSEARCH_API_KEY", "")
        self.name = "anysearch"

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        if not self.api_key:
            _log(self.name, "search", "no_key")
            return []
        if not quota_check(self.name):
            _log(self.name, "search", "quota_exhausted")
            return []

        api_url = os.environ.get("ANYSEARCH_API_URL",
                                 "https://api.anysearch.xyz/v1/search")
        params = urllib.parse.urlencode({
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
        })
        try:
            req = urllib.request.Request(f"{api_url}?{params}",
                                          headers={"User-Agent": "Hermes-Agent/2.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            _log(self.name, "search", "ok", len(results))
            return results
        except Exception as e:
            _log(self.name, "search", "error", 0, str(e))
            return []


# === CLI 测试 ===
if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "半导体 政策 2026"

    print(f"=== Tavily 搜索: {query} ===")
    tv = TavilySearch()
    for r in tv.search(query, 3):
        print(f"  {r['title']}")
        print(f"  {r['url']}")
        print()

    print(f"=== Firecrawl 搜索: {query} ===")
    fc = FirecrawlSearch()
    for r in fc.search(query, 3):
        print(f"  {r['title']}")
        print()
