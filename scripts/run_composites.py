#!/usr/bin/env python3
"""Composites: 多因子组合验证 — 使用 Phase 2 排行榜的 16 个通过因子"""
import sys, os, json
sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd

POOL_PATH = "/mnt/d/HermesReports/factor_leaderboard/20260708_183053/factor_leaderboard.json"
METHODS = "equal_weight_score,weighted_score,gated_score,zscore_blend,rank_blend"

# 加载排行榜，获取 promoted 因子
with open(POOL_PATH) as f:
    leaderboard = json.load(f)
promoted = leaderboard.get('promoted', [])
print(f'加载 {len(promoted)} 个推荐因子: {promoted}')
print()

# 直接调用 validate_composites main
sys.argv = [
    'validate_composites',
    '--candidate-pool', POOL_PATH,
    '--factors', ','.join(promoted),
    '--methods', METHODS,
    '--start', '2025-01-02',
    '--end', '2026-06-30',
    '--rebalance', 'monthly',
    '--top-n', '20',
]

from factor_lab.validate_composites import main as comp_main
comp_main()
