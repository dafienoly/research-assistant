"""ST 股票名单管理器 — 从东方财富实时数据源获取 ST/*ST 名单

替代 symbol 后缀启发式推断 (_infer_st)，
直接从东方财富 API 获取准确的风险警示板股票列表。

用法:
    from factor_lab.risk.st_watchlist import STWatchlist

    wl = STWatchlist()
    n = wl.refresh()          # 从数据源更新
    print(wl.is_st("000506")) # True
    print(wl.is_st("000001")) # False
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

CST = timezone(timedelta(hours=8))

# 默认缓存路径（与项目现有 HermesData 目录保持一致）
_DEFAULT_CACHE_DIR = Path("/mnt/d/HermesData/st_watchlist")


def _get_proxy_clean_session():
    """创建一个完全取消 proxy 设置的 requests Session，用于国内数据源"""
    import urllib.request

    # 在调用时临时取消 proxy 环境变量
    saved = {}
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"]:
        saved[k] = os.environ.pop(k, None)
    try:
        # 返回一个 opener，它在没有 proxy 的情况下工作
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        return opener
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


class STWatchlist:
    """ST 股票名单管理器

    通过东方财富 API 获取当前 ST/*ST 股票列表，
    缓存到本地 JSON 文件避免重复请求。

    CACHE_PATH: 缓存文件路径，默认 /mnt/d/HermesData/st_watchlist/stocks.json
    """

    CACHE_PATH: Path = _DEFAULT_CACHE_DIR / "stocks.json"

    def __init__(self, cache_path: Optional[str | Path] = None):
        if cache_path is not None:
            self.CACHE_PATH = Path(cache_path)
        self._st_map: dict[str, dict] = {}  # symbol -> {name, st_type, ...}
        self._loaded = False

    # ──────────────────────────────────────────────
    # 数据获取
    # ──────────────────────────────────────────────

    def refresh(self) -> int:
        """从东方财富 API 拉取最新 ST/*ST 名单

        Returns:
            int: 本次获取的股票数量
        """
        df = self._fetch_from_api()
        if df is None or df.empty:
            raise RuntimeError(
                "STWatchlist.refresh: 无法从东方财富获取 ST 名单，"
                "请检查网络连接和 proxy 设置"
            )

        records = []
        for _, row in df.iterrows():
            code = str(row.get("代码", row.get("f12", ""))).strip()
            name = str(row.get("名称", row.get("f14", ""))).strip()
            if not code or not name:
                continue

            # 识别 ST 类型
            st_type = self._classify_st(name)

            records.append({
                "symbol": code,
                "name": name,
                "st_type": st_type,
                "date_added": date.today().isoformat(),
            })

        # 写入缓存
        self.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(CST).isoformat(),
            "count": len(records),
            "stocks": records,
        }
        self.CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 更新内存索引
        self._build_index(records)
        self._loaded = True

        return len(records)

    def _fetch_from_api(self) -> Optional[pd.DataFrame]:
        """从东方财富 API 获取风险警示板数据 (HTTP 直连)

        优先使用 akshare，如果 akshare 代理失败则直接调用 HTTP 接口。
        """
        # 尝试 akshare 方式（无 proxy 环境）
        df = self._fetch_via_akshare()
        if df is not None and not df.empty:
            return df

        # 回退：直接 HTTP 请求
        df = self._fetch_via_http()
        if df is not None and not df.empty:
            return df

        # 再次回退：从 stock_info_a_code_name 通过名称过滤
        return self._fetch_via_name_filter()

    def _fetch_via_akshare(self) -> Optional[pd.DataFrame]:
        """通过 akshare 获取 (需要绕过 proxy)"""
        try:
            import akshare as ak

            # 临时清除 proxy
            saved = {}
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                      "ALL_PROXY", "all_proxy"]:
                saved[k] = os.environ.pop(k, None)
            try:
                df = ak.stock_zh_a_st_em()
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
        except ImportError:
            pass
        return None

    def _fetch_via_http(self) -> Optional[pd.DataFrame]:
        """直接通过 HTTP 调用东方财富 API"""
        import json as _json
        import urllib.request

        url = "http://40.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "500",  # 500 条足够覆盖全部 ST 股票
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+f:4,m:1+f:4",  # 沪深风险警示板
            "fields": "f12,f14",  # f12=代码, f14=名称
        }

        full_url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

        # 临时清除 proxy
        saved = {}
        for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                  "ALL_PROXY", "all_proxy"]:
            saved[k] = os.environ.pop(k, None)
        try:
            req = urllib.request.Request(full_url)
            req.add_header("User-Agent",
                           "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36")
            req.add_header("Referer", "https://quote.eastmoney.com/")

            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                data = _json.loads(body)

            rows = []
            if data.get("data") and data["data"].get("diff"):
                items = data["data"]["diff"]
                for item in items:
                    code = str(item.get("f12", "")).strip()
                    name = str(item.get("f14", "")).strip()
                    if code and name:
                        rows.append({"代码": code, "名称": name})

                if rows:
                    import pandas as pd
                    return pd.DataFrame(rows)

            # 尝试分页获取（如果超过 500 只）
            total = data.get("data", {}).get("total", 0)
            all_rows = list(rows)
            if total > 500:
                page = 2
                while len(all_rows) < total:
                    params["pn"] = str(page)
                    page_url = url + "?" + "&".join(
                        f"{k}={v}" for k, v in params.items()
                    )
                    page_req = urllib.request.Request(page_url)
                    page_req.add_header("User-Agent",
                                        "Mozilla/5.0 ... Chrome/120.0.0.0 Safari/537.36")
                    page_req.add_header("Referer", "https://quote.eastmoney.com/")
                    try:
                        with urllib.request.urlopen(page_req, timeout=15) as presp:
                            pbody = presp.read().decode("utf-8")
                            pdata = _json.loads(pbody)
                        if pdata.get("data") and pdata["data"].get("diff"):
                            for item in pdata["data"]["diff"]:
                                code = str(item.get("f12", "")).strip()
                                name = str(item.get("f14", "")).strip()
                                if code and name:
                                    all_rows.append({"代码": code, "名称": name})
                        page += 1
                    except Exception:
                        break
                if all_rows:
                    import pandas as pd
                    return pd.DataFrame(all_rows)
        except Exception:
            pass
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

        return None

    def _fetch_via_name_filter(self) -> Optional[pd.DataFrame]:
        """通过 stock_info_a_code_name 获取全市场股票，按名称过滤 ST

        备选方案：从所有 A 股中过滤名字含 *ST 或 ST 前缀的股票。
        """
        try:
            import akshare as ak

            saved = {}
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                      "ALL_PROXY", "all_proxy"]:
                saved[k] = os.environ.pop(k, None)
            try:
                df = ak.stock_info_a_code_name()
                if df is None or df.empty:
                    return None

                # 筛选 ST/*ST 股票
                st_mask = df["name"].str.contains(
                    r"^\*ST|^ST", na=False, regex=True
                )
                st_df = df[st_mask].copy()
                st_df = st_df.rename(columns={"code": "代码", "name": "名称"})
                return st_df
            except Exception:
                return None
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
        except ImportError:
            return None

    @staticmethod
    def _classify_st(name: str) -> str:
        """从名称识别 ST 类型"""
        name_upper = name.upper().strip()
        if name_upper.startswith("*ST"):
            return "star_st"
        elif name_upper.startswith("ST"):
            return "st"
        elif "ST" in name_upper:
            return "st"
        return "unknown"

    def _build_index(self, records: list[dict]) -> None:
        """构建 symbol -> record 索引"""
        self._st_map = {}
        for rec in records:
            sym = rec["symbol"]
            # 存储纯代码和带后缀两种形式
            self._st_map[sym] = rec
            # 也存储 6 位数字标准形式
            code_digits = "".join(ch for ch in sym if ch.isdigit())[:6]
            if code_digits:
                self._st_map[code_digits] = rec

    # ──────────────────────────────────────────────
    # 缓存管理
    # ──────────────────────────────────────────────

    def load_cache(self) -> bool:
        """从缓存文件加载，如果缓存当天已更新则跳过 refresh

        Returns:
            bool: 是否成功加载
        """
        if not self.CACHE_PATH.exists():
            return False

        try:
            data = json.loads(self.CACHE_PATH.read_text(encoding="utf-8"))

            # 检查缓存日期：当天已更新则直接使用缓存
            cached_date = data.get("updated_at", "")[:10]
            today = date.today().isoformat()
            if cached_date == today:
                self._build_index(data.get("stocks", []))
                self._loaded = True
                return True

            # 缓存不是今天的，需要 refresh
            return False
        except (json.JSONDecodeError, KeyError, OSError):
            return False

    def ensure_fresh(self) -> int:
        """确保数据是最新的

        如果缓存当天已更新则跳过，否则刷新。

        Returns:
            int: ST 股票数量（从缓存或刷新）
        """
        if self.load_cache():
            return len(self._st_map) // 2  # /2 因为既存 6位码又存带后缀码

        return self.refresh()

    # ──────────────────────────────────────────────
    # 查询
    # ──────────────────────────────────────────────

    def is_st(self, symbol: str) -> bool:
        """判断给定股票当前是否为 ST/*ST

        支持:
          - 6 位数字代码: "000506", "600001"
          - 带后缀代码:   "000506.SZ", "600001.SH"
          - 带后缀中间格式: "000506.SZ"

        Args:
            symbol: 股票代码

        Returns:
            bool: 是否为 ST 股票
        """
        if not self._loaded and not self.load_cache():
            # 如果未加载且无法从缓存加载，自动刷新
            try:
                self.refresh()
            except RuntimeError:
                return False

        # 标准化：提取 6 位数字代码
        code = "".join(ch for ch in symbol if ch.isdigit())[:6]
        if not code or len(code) < 6:
            return False

        return code in self._st_map

    def get_st_list(self) -> list[dict]:
        """返回完整 ST 名单

        Returns:
            list[dict]: [{symbol, name, st_type, date_added}, ...]
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return []

        # 去重（_st_map 中既有 6位码又有带后缀码）
        seen_codes: set[str] = set()
        unique: list[dict] = []
        for sym, rec in self._st_map.items():
            code = "".join(ch for ch in sym if ch.isdigit())[:6]
            if code and code not in seen_codes:
                seen_codes.add(code)
                unique.append(rec)
        return unique

    def get_st_status(self, symbol: str) -> str:
        """返回给定股票的 ST 状态

        Returns:
            str: 'normal' — 非 ST
                 'st' — ST
                 'star_st' — *ST
                 'unknown' — 未知（未加载或代码无效）
        """
        if not self._loaded and not self.load_cache():
            try:
                self.refresh()
            except RuntimeError:
                return "unknown"

        code = "".join(ch for ch in symbol if ch.isdigit())[:6]
        if not code or len(code) < 6:
            return "unknown"

        rec = self._st_map.get(code)
        if rec is None:
            return "normal"

        return rec.get("st_type", "st")


# ──────────────────────────────────────────────
# 独立工具函数（供快速调用）
# ──────────────────────────────────────────────

def is_st(symbol: str) -> bool:
    """快捷判断 — 使用默认 STWatchlist 单例

    适合在不需要管理 watchlist 生命周期的场景中使用。

    Args:
        symbol: 股票代码

    Returns:
        bool: 是否为 ST 股票
    """
    if not hasattr(is_st, "_watchlist"):
        is_st._watchlist = STWatchlist()
        try:
            is_st._watchlist.ensure_fresh()
        except RuntimeError:
            return False
    return is_st._watchlist.is_st(symbol)
