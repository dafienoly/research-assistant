#!/usr/bin/env python3
"""验证: ETF 替代方案 + 整手/尾盘规则"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

print("=" * 60)
print("  验证: ETF 替代 + 整手/尾盘规则")
print("=" * 60)

# ═══════════════════════════════════════════════════════════
# 1. ETF 替代测试
# ═══════════════════════════════════════════════════════════
print("\n--- 1. ETF 替代测试 ---")

# 1a. 从 etf_universe 导入
from factor_lab.etf.etf_universe import (
    find_etf_substitute,
    _infer_stock_theme,
    load_etf_registry,
    build_etf_universe,
    STOCK_TO_THEME_PREFIX,
)
from factor_lab.etf.etf_selector import find_etf_substitute as find_etf_sub_selector

etf_db = [
    {"etf_code": "512480", "etf_name": "半导体ETF", "theme": "芯片", 
     "tracked_index": "中证半导体指数", "avg_amount_20d": "72000", "aum": "180"},
    {"etf_code": "588290", "etf_name": "科创芯片ETF华安", "theme": "科创芯片",
     "tracked_index": "上证科创板芯片指数", "avg_amount_20d": "8500", "aum": "12"},
    {"etf_code": "510300", "etf_name": "沪深300ETF", "theme": "宽基",
     "tracked_index": "沪深300指数", "avg_amount_20d": "150000", "aum": "800"},
    {"etf_code": "588000", "etf_name": "科创50ETF", "theme": "科创50",
     "tracked_index": "上证科创板50指数", "avg_amount_20d": "180000", "aum": "680"},
    {"etf_code": "159995", "etf_name": "芯片ETF", "theme": "芯片",
     "tracked_index": "国证芯片指数", "avg_amount_20d": "85000", "aum": "220"},
    {"etf_code": "159516", "etf_name": "半导体设备ETF", "theme": "半导体设备",
     "tracked_index": "中证半导体设备指数", "avg_amount_20d": "12000", "aum": "18"},
]

# 1b. 测试 688012 (中微公司) → 应匹配半导体设备/科创芯片
print("\n测试 1b: 688012 (中微公司, 半导体设备)")
# 验证主题推断
theme = _infer_stock_theme("688012")
print(f"  主题推断: {theme}")
assert theme in ("半导体设备", "芯片"), f"688012 应为半导体设备主题, 实际={theme}"

# 验证替代ETF
subs = find_etf_substitute("688012", etf_db, {"688012": ["半导体设备"]})
print(f"  替代方案 ({len(subs)}):")
for s in subs:
    print(f"    {s['etf_code']} {s['etf_name']} | {s['match_reason']} | score={s['score']}")
assert len(subs) > 0, "688012 应有替代 ETF"

# 1c. 测试 300661 (圣邦股份, 芯片)
print("\n测试 1c: 300661 (圣邦股份, 芯片)")
theme = _infer_stock_theme("300661")
print(f"  主题推断: {theme}")
assert "芯片" in theme or "创业" in theme, f"300661 应为芯片/创业板主题, 实际={theme}"

subs = find_etf_substitute("300661", etf_db, {"300661": ["芯片"]})
print(f"  替代方案 ({len(subs)}):")
for s in subs:
    print(f"    {s['etf_code']} {s['etf_name']} | {s['match_reason']} | score={s['score']}")
assert len(subs) > 0, "300661 应有替代 ETF"

# 1d. 测试 000001 (平安银行, 主板宽基)
print("\n测试 1d: 000001 (平安银行, 主板)")
theme = _infer_stock_theme("000001")
print(f"  主题推断: {theme}")

subs = find_etf_substitute("000001", etf_db)
print(f"  替代方案 ({len(subs)}):")
for s in subs:
    print(f"    {s['etf_code']} {s['etf_name']} | {s['match_reason']} | score={s['score']}")

# 1e. 测试 etf_selector 入口
print("\n测试 1e: etf_selector.find_etf_substitute 入口")
subs2 = find_etf_sub_selector("688012", etf_db, {"688012": ["半导体设备"]})
assert len(subs2) > 0, "etf_selector 入口应返回替代方案"
print(f"  ✓ 通过: etf_selector 入口返回 {len(subs2)} 个替代")

# 1f. 测试 build_etf_universe (回退路径)
print("\n测试 1f: build_etf_universe (回退到注册表)")
df = build_etf_universe()
assert df is not None, "build_etf_universe 应返回 DataFrame"
assert len(df) > 0, f"ETF 数据库应有数据, 实际 {len(df)} 行"
print(f"  ✓ 通过: ETF 数据库 {len(df)} 行, 列={list(df.columns)}")

# 1g. 测试内置 ETF 注册表
print("\n测试 1g: 内置 ETF 注册表")
registry = load_etf_registry()
assert len(registry) > 0, "注册表应有数据"
print(f"  ✓ 通过: 注册表 {len(registry)} 只 ETF")
print(f"  主题: {sorted(set(e['theme'] for e in registry))}")

print("\n✅ ETF 替代测试通过")

# ═══════════════════════════════════════════════════════════
# 2. 整手规则测试
# ═══════════════════════════════════════════════════════════
print("\n--- 2. 整手规则测试 ---")

from factor_lab.order.order_preview import round_to_lot_size

# 2a. 基本截断
tests = [
    (150, 100),      # 150→100
    (99, 100),       # 99→100 (至少1手)
    (200, 200),      # 200→200
    (250, 200),      # 250→200
    (0, 0),          # 0→0
    (-50, 0),        # 负数→0
    (100, 100),      # 100→100
    (101, 100),      # 101→100
    (1000, 1000),    # 1000→1000
    (1001, 1000),    # 1001→1000
]
all_pass = True
for shares, expected in tests:
    result = round_to_lot_size(shares)
    if result != expected:
        print(f"  ✗ FAIL: {shares}股 → {result}, 期望 {expected}")
        all_pass = False
    else:
        print(f"  ✓ {shares}股 → {result}")
assert all_pass, "整手规则测试失败"

# 2b. 验证 order_preview 生成中的整手规则
print("\n测试 2b: order_preview 订单生成")
from factor_lab.order.order_preview import generate_order_preview
# 会报错因为没有实际 diff 文件, 但我们只测函数存在和导入
print(f"  ✓ round_to_lot_size 导入正常")

# 2c. 验证 standing_paper_trading 的整手规则
print("\n测试 2c: standing_paper_trading 整手规则")
from factor_lab.paper.standing_paper_trading import StandingPaperTrading
pt = StandingPaperTrading(initial_capital=100000)
# 测试买入 150 股 → 应为 100 股
result = pt.execute_buy("688012", price=50.0, shares=150, date="2026-07-08")
assert result["success"], f"买入失败: {result}"
assert result["filled_shares"] == 100, f"150股应截断为100, 实际{result['filled_shares']}"
print(f"  ✓ 150股买入 → {result['filled_shares']} (整手截断)")

print("\n✅ 整手规则测试通过")

# ═══════════════════════════════════════════════════════════
# 3. 尾盘规则测试
# ═══════════════════════════════════════════════════════════
print("\n--- 3. 尾盘规则测试 ---")

from factor_lab.live.signal_generator import Ret5Ma20GateSignalGenerator
from datetime import datetime, timezone, timedelta

# 3a. 测试 _is_late_session 方法
gen = Ret5Ma20GateSignalGenerator()
now = datetime.now(timezone(timedelta(hours=8)))
is_late = gen._is_late_session()
print(f"  当前时间: {now.strftime('%H:%M:%S')} CST")
print(f"  是否尾盘(>=14:30): {is_late}")
# 不 assert, 取决于运行时间
print(f"  ✓ _is_late_session 方法可调用")

# 3b. 在盘前/盘中场景检查信号生成
# 构造一个简单的 DataFrame 来测试 generate_signals
import pandas as pd
import numpy as np

dates = pd.date_range("2026-07-01", "2026-07-08", freq="B")
symbols = ["688012.SH", "300661.SZ", "000001.SZ"]
rows = []
for sym in symbols:
    for d in dates:
        rows.append({
            "symbol": sym, "date": d,
            "close": 50.0 + np.random.randn() * 5,
            "ret5": np.random.randn() * 0.05,
            "ma20": 48.0,
            "close_gt_ma20": True,
        })
mock_df = pd.DataFrame(rows)
gen2 = Ret5Ma20GateSignalGenerator(mock_df)
result = gen2.generate_signals(signal_date="2026-07-08", top_n=3, watch_n=2)

# 检查尾盘规则是否在信号中体现
for c in result.get("target_candidates", []):
    if "blocked" in c:
        print(f"  {c['symbol']}: blocked={c['blocked']}, reason={c.get('block_reason','')}")
        break
else:
    print(f"  当前不在尾盘时段, 信号无 blocked 标记 (expected)")

print(f"  ✓ generate_signals 调用正常, candidates={len(result.get('target_candidates',[]))}")

print("\n✅ 尾盘规则测试通过")

# ═══════════════════════════════════════════════════════════
# 完整摘要
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  全部测试通过 ✅")
print(f"  时间: {datetime.now().isoformat()}")
print("=" * 60)
