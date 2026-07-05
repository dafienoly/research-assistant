"""DNS 解析修正 v2 — 修补 socket.gethostbyname + socket.create_connection

Clash fake-ip 模式的系统级 DNS 劫持导致 Eastmoney/Baostock 域名
被解析为不可达的 198.18.x.x。此模块用 DNS over HTTPS 覆盖所有
Python socket 层面的 DNS 解析调用。
"""

import socket
import json
import os
import urllib.request
from typing import Optional


# DOH 解析
DOH_URL = "https://cloudflare-dns.com/dns-query"
_dns_cache = {}

def _resolve_via_doh(hostname: str) -> Optional[str]:
    if hostname in _dns_cache:
        return _dns_cache[hostname]
    url = f"{DOH_URL}?name={hostname}&type=A"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode())
        for ans in data.get("Answer", []):
            if ans.get("type") == 1:  # A record
                ip = ans["data"]
                _dns_cache[hostname] = ip
                return ip
    except Exception:
        pass
    return None


# 需要修正的域名模式
FAKE_IP_SUFFIXES = (".eastmoney.com", ".baostock.com")
FAKE_IP_CACHE = {}


def _real_ip(host: str) -> Optional[str]:
    """获取域名的真实 IP，绕过 Clash fake-ip"""
    if host in FAKE_IP_CACHE:
        return FAKE_IP_CACHE[host]
    if any(host.endswith(s) for s in FAKE_IP_SUFFIXES):
        ip = _resolve_via_doh(host)
        if ip:
            FAKE_IP_CACHE[host] = ip
            return ip
    return None


# ====== 修补 socket.getaddrinfo ======
_orig_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    real = _real_ip(host)
    if real:
        host = real
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


# ====== 修补 socket.gethostbyname ======
_orig_gethostbyname = socket.gethostbyname

def _patched_gethostbyname(hostname):
    real = _real_ip(hostname)
    if real:
        return real
    return _orig_gethostbyname(hostname)


# ====== 修补 socket.create_connection ======
_orig_create_connection = socket.create_connection

def _patched_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                                source_address=None, *, all_errors=True):
    host, port = address
    real = _real_ip(host)
    if real:
        address = (real, port)
    return _orig_create_connection(address, timeout, source_address, all_errors=all_errors)


_patched = False


def patch_all():
    """一次性修补所有 socket 解析函数"""
    global _patched
    socket.getaddrinfo = _patched_getaddrinfo
    socket.gethostbyname = _patched_gethostbyname
    socket.gethostbyname_ex = lambda h: (_patched_gethostbyname(h), [], [_patched_gethostbyname(h)])
    socket.create_connection = _patched_create_connection

    # 强制 urllib3/requests 使用 IPv4 并关闭 DNS 缓存
    try:
        import requests.packages.urllib3.util.connection as uc
        uc.allowed_gai_family = lambda: socket.AF_INET
    except ImportError:
        pass

    # 设置 NO_PROXY 绕过 Eastmoney/Baostock 代理阻断
    bypass = [".eastmoney.com", ".baostock.com", "public-api.baostock.com"]
    current = os.environ.get("NO_PROXY", "")
    for d in bypass:
        if d not in current:
            current = f"{current},{d}" if current else d
    os.environ["NO_PROXY"] = current
    os.environ["no_proxy"] = current

    # 清除 ALL_PROXY SOCKS5 全覆盖代理（否则会覆盖 NO_PROXY）
    for v in ("ALL_PROXY", "all_proxy"):
        if v in os.environ:
            os.environ.pop(v, None)

    _patched = True


def unpatch():
    global _patched
    socket.getaddrinfo = _orig_getaddrinfo
    socket.gethostbyname = _orig_gethostbyname
    socket.create_connection = _orig_create_connection
    _patched = False


# ====== 自动触发 ======
if __name__ != "__main__":
    # 导入时自动检查并修补
    try:
        test_ip = socket.gethostbyname("push2.eastmoney.com")
        if test_ip.startswith("198.18."):
            patch_all()
            # 验证
            verify = socket.gethostbyname("push2.eastmoney.com")
            if not verify.startswith("198.18."):
                print(f"🔧 DNS 修补: push2.eastmoney.com {test_ip} → {verify}")
    except Exception:
        pass


# ====== CLI 测试 ======
if __name__ == "__main__":
    import sys, time

    if not _patched:
        patch_all()

    hosts = sys.argv[1:] if len(sys.argv) > 1 else [
        "push2.eastmoney.com", "79.push2.eastmoney.com",
        "data.baostock.com", "push2his.eastmoney.com",
    ]

    for host in hosts:
        t0 = time.time()
        try:
            ip = socket.gethostbyname(host)
            ms = int((time.time() - t0) * 1000)
            print(f'{host:40s} → {ip:20s} ({ms}ms)')
        except Exception as e:
            print(f'{host:40s} → ❌ {e}')

    print("\n--- 测试 AKShare 行业板块 (之前被阻断) ---")
    try:
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        if df is not None and len(df) > 0:
            print(f'✅ AKShare 行业板块: {len(df)} 个')
            print(df[['板块名称','板块涨跌幅']].head(5).to_string(index=False))
        else:
            print('❌ 返回空')
    except Exception as e:
        print(f'❌ AKShare 行业板块: {e}')

    print("\n--- 测试 AKShare 概念板块 ---")
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and len(df) > 0:
            print(f'✅ AKShare 概念板块: {len(df)} 个')
            print(df[['板块名称','上涨家数','下跌家数']].head(5).to_string(index=False))
        else:
            print('❌ 返回空')
    except Exception as e:
        print(f'❌ AKShare 概念板块: {e}')

    print("\n--- 测试 AKShare 日K线 ---")
    try:
        df = ak.stock_zh_a_hist(symbol="688012", period="daily",
                                 start_date="20260601", end_date="20260702", adjust="qfq")
        if df is not None and len(df) > 0:
            print(f'✅ 日K线 688012: {len(df)} 行')
            print(df[['日期','收盘','涨跌幅']].tail(3).to_string(index=False))
        else:
            print('❌ 返回空')
    except Exception as e:
        print(f'❌ AKShare 日K线: {e}')
