"""Proxy 绕道 — 按数据源域名动态管理 proxy

akshare 的东方财富 API 在 Clash proxy 下会连接失败，
而 ETF 数据（fund_etf_spot_em）和个股数据（stock_zh_a_hist）
走不同的 endpoint，需要针对性绕过。

用法:
  from proxy_bypass import no_proxy_for
  with no_proxy_for("eastmoney"):
      df = ak.fund_etf_hist_em(...)

或:
  df = call_no_proxy(ak.fund_etf_hist_em, symbol="159516", ...)
"""
import os, contextlib
from urllib.parse import urlparse

# 已知数据源域名 → 需要绕过 proxy 的
# 国内数据源全部绕开 Clash proxy（境外 IP 被拒），境外 API 保持走 proxy
BYPASS_DOMAINS = {
    "eastmoney": [
        "eastmoney.com",
        "push2.eastmoney.com",
        "push2his.eastmoney.com",
        "17.push2.eastmoney.com",
        "datacenter.eastmoney.com",
        "datacenter-web.eastmoney.com",
        "quote.eastmoney.com",
        "data.eastmoney.com",
        "www.eastmoney.com",
    ],
    "sina": [
        "sina.com.cn",
        "hq.sinajs.cn",
        "vip.stock.finance.sina.com.cn",
        "finance.sina.com.cn",
    ],
    "tencent": [
        "gtimg.cn",
        "qt.gtimg.cn",
        "web.ifzq.gtimg.cn",
        "ifzq.gtimg.cn",
    ],
    "cninfo": [
        "cninfo.com.cn",
        "www.cninfo.com.cn",
    ],
    "sse": [
        "sse.com.cn",
        "www.sse.com.cn",
        "query.sse.com.cn",
    ],
    "szse": [
        "szse.cn",
        "www.szse.cn",
    ],
    "baostock": [
        "baostock.com",
        "www.baostock.com",
    ],
    "joinquant": [
        "joinquant.com",
        "dataapi.joinquant.com",
        "www.joinquant.com",
    ],
}


@contextlib.contextmanager
def no_proxy_for(*data_sources: str):
    """临时将指定数据源的域名加入 NO_PROXY

    用法:
        with no_proxy_for("eastmoney", "sina"):
            df = ak.fund_etf_hist_em(...)
    """
    domains = []
    for src in data_sources:
        domains.extend(BYPASS_DOMAINS.get(src, []))

    old_no_proxy = os.environ.get("NO_PROXY", "")
    old_no_proxy_lower = os.environ.get("no_proxy", "")

    # 合并新旧
    existing = set()
    for val in [old_no_proxy, old_no_proxy_lower]:
        for d in val.split(","):
            d = d.strip()
            if d:
                existing.add(d)
    for d in domains:
        existing.add(d)
    new_no_proxy = ",".join(sorted(existing))

    os.environ["NO_PROXY"] = new_no_proxy
    os.environ["no_proxy"] = new_no_proxy
    try:
        yield
    finally:
        # 恢复原值
        if old_no_proxy:
            os.environ["NO_PROXY"] = old_no_proxy
        else:
            os.environ.pop("NO_PROXY", None)
        if old_no_proxy_lower:
            os.environ["no_proxy"] = old_no_proxy_lower
        else:
            os.environ.pop("no_proxy", None)


def call_no_proxy(fn, *args, **kwargs):
    """调用函数时临时清除 proxy 环境变量（最彻底的做法）

    比 NO_PROXY 更激进 — 直接 unset HTTP_PROXY/HTTPS_PROXY，
    适合 akshare 这种库级 HTTP 调用。
    """
    saved = {}
    proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                  "ALL_PROXY", "all_proxy"]
    for k in proxy_vars:
        saved[k] = os.environ.pop(k, None)
    try:
        return fn(*args, **kwargs)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# 自动检测：当前是否有 proxy 在运行
def is_proxy_active() -> bool:
    """检查是否有 proxy 环境变量"""
    for k in ["HTTP_PROXY", "https_proxy"]:
        if os.environ.get(k):
            return True
    return False
