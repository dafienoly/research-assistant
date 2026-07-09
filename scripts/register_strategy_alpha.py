#!/usr/bin/env python3
"""将 ret5_ma20_gate 策略注册到 Alpha Registry + 更新 ret5 验证状态"""
import sys, json
from datetime import datetime, timezone, timedelta
sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')

CST = timezone(timedelta(hours=8))

# 1. 更新 ret5 因子的 Alpha 状态 (draft → backtested)
from factor_lab.alpha.registry import list_alpha, register_alpha, get_alpha
from factor_lab.alpha.schema import AlphaSpec
from factor_lab.alpha.lifecycle import AlphaLifecycle

alphas = list_alpha()
ret5_alpha = [a for a in alphas if a.get('name') == 'ret5']
if ret5_alpha:
    aid = ret5_alpha[0]['alpha_id']
    print(f'✅ ret5 已在 Registry: {aid}')
    # 读取完整 spec
    spec = get_alpha(aid)
    if spec and isinstance(spec, dict) and 'error' not in spec:
        # 更新状态
        from pathlib import Path
        spec_path = Path(f'/mnt/d/HermesData/alpha_registry/{aid}/alpha_spec.json')
        if spec_path.exists():
            with open(spec_path) as f:
                spec_data = json.load(f)
            spec_data['status'] = 'backtested'
            spec_data['updated_at'] = datetime.now(CST).isoformat()
            spec_data['last_validated'] = datetime.now(CST).isoformat()
            # 回填验证数据
            spec_data['peer_benchmark_result'] = {
                'beats_peer': True,
                'excess_return_pct': 25.2,
                'cumulative_return_pct': 272.1,
                'max_drawdown_pct': 49.31,
                'sharpe': 1.92,
            }
            spec_data['ic_mean_history'] = spec_data.get('ic_mean_history', [])
            spec_data['ic_mean_history'].append({
                'date': datetime.now(CST).strftime('%Y-%m-%d'),
                'ic_mean': 0.0346,
                'ic_ir': 0.197,
                'pos_ratio': 0.575,
            })
            with open(spec_path, 'w') as f:
                json.dump(spec_data, f, ensure_ascii=False, indent=2)
            print(f'  → status: draft → backtested')
            print(f'  → peer_benchmark: {spec_data["peer_benchmark_result"]}')

# 2. 注册 ret5_ma20_gate 策略 Alpha
print(f'\n📝 注册 ret5_ma20_gate 策略...')

# 检查是否已存在
existing = [a for a in alphas if a.get('name') == 'ret5_ma20_gate']
if existing:
    print(f'  ret5_ma20_gate 已存在: {existing[0]["alpha_id"]}')
else:
    strategy_spec = AlphaSpec(
        name='ret5_ma20_gate',
        description='ret5 + MA20 均线上涨门控策略 — 5日动量选股, 仅当收盘价在MA20上方时开仓',
        hypothesis='在上升趋势中做动量选股能显著提升收益风险比 — 过滤掉下跌趋势中的虚假反弹, 保留趋势动量收益',
        factor_expression='ret5 * (close > ma(close, 20))',
        universe='all_watchlist',
        signal_direction='long',
        rebalance_frequency='monthly',
        status='backtested',
        author='system',
        source='factor:validate + factor:strategies pipeline',
        enabled=False,
        paper_enabled=False,
        live_enabled=False,
        tags=['strategy', 'momentum', 'trend_filter', 'ret5', 'ma20_gate'],
        risk_constraints={
            'max_position_weight': 0.25,
            'max_drawdown': 0.15,
        },
    )
    result = register_alpha(strategy_spec)
    aid = result['alpha_id']
    print(f'  ✅ 注册成功: {aid}')
    
    # 回填验证数据
    spec_path = Path(f'/mnt/d/HermesData/alpha_registry/{aid}/alpha_spec.json')
    if spec_path.exists():
        with open(spec_path) as f:
            spec_data = json.load(f)
        spec_data['peer_benchmark_result'] = {
            'beats_peer': True,
            'excess_return_pct': 50.5,
            'cumulative_return_pct': 164.35,
            'max_drawdown_pct': 14.38,
            'sharpe': 2.10,
            'benchmark_sharpe': 1.83,
            'benchmark_return_pct': 113.9,
        }
        spec_data['cost_assumption'] = {
            'commission': 0.0003,
            'slippage_bps': 10,
            'stamp_tax': 0.001,
        }
        spec_data['valid_period'] = '2025-01_to_2026-06'
        with open(spec_path, 'w') as f:
            json.dump(spec_data, f, ensure_ascii=False, indent=2)
        print(f'  → 验证数据已回填')
    
    print(f'  → status: backtested')
    print(f'  → Sharpe: 2.10, 收益: +164.4%, 回撤: -14.4%')
    print(f'  → 基准: ret5 canonical Sharpe=1.83 收益=+113.9%')

# 3. 列出所有登记的 Alpha
print(f'\n📋 Registry 中的策略类 Alpha:')
for a in list_alpha():
    tags = a.get('tags', [])
    name = a.get('name', '')
    status = a.get('status', '')
    if 'strategy' in tags or name == 'ret5_ma20_gate':
        print(f'  {a["alpha_id"]:40s} {name:30s} status={status}')
