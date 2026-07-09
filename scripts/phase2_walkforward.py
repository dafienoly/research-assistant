#!/usr/bin/env python3
"""Phase 2: Walk-Forward 验证 — 仅对 Phase 1 通过门禁的因子"""
import sys, json
sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')

# 读取 Phase 1 结果
with open('/tmp/phase1_results.json') as f:
    phase1 = json.load(f)

promoted = phase1.get('promoted', [])
print(f'Phase 2: Walk-Forward 验证 {len(promoted)} 个因子')
print(f'因子: {promoted}')
print()

from factor_lab.scoring.leaderboard import run_batch_validation
result = run_batch_validation(
    factors=promoted,
    start_date='2025-01-02', end_date='2026-06-30',
    rebalance='monthly', top_n=20,
    run_anti_overfit=False,         # 已跑过
    run_walk_forward=True,          # 只跑 Walk-Forward
)

print(f'\n✅ Phase 2 完成')
print(f'📁 输出目录: {result.get("output_dir","?")}')
entries = result.get('entries', [])
promoted_final = [e for e in entries if e.get('walk_forward_pass') == True]
print(f'🏆 Walk-Forward 通过: {len(promoted_final)}/{len(entries)}')

print(f'\n=== Walk-Forward 结果 ===')
header = f'{"#":>3}  {"因子":<34}  {"得分":>5}  {"评级":>4}  {"WF通过":>6}  {"WF收益":>8}  {"累计收益":>8}  {"最大回撤":>8}  {"IC均值":>8}'
print(header)
print('-' * len(header))
for i, e in enumerate(entries):
    wf_pass = e.get('walk_forward_pass')
    wf_s = '✅PASS' if wf_pass else '❌FAIL' if wf_pass is False else '  N/A  '
    wf_ret = e.get('walk_forward_test_return')
    wf_ret_s = f'{wf_ret:>7.1f}%' if wf_ret is not None else '  N/A  '
    cum = e.get('cumulative_return')
    cum_s = f'{cum:>7.1f}%' if cum is not None else '  N/A  '
    dd = e.get('max_drawdown')
    dd_s = f'{dd:>7.2f}%' if dd else '  N/A  '
    ic = e.get('ic_mean')
    ic_s = f'{ic:>+.4f}' if ic else '   N/A '
    print(f'{i+1:>3}  {e["factor_name"]:<34}  {e["score"]:>5.1f}  {e["grade"]:>4}  {wf_s:>6}  {wf_ret_s:>8}  {cum_s:>8}  {dd_s:>8}  {ic_s:>8}')
    if e.get('reject_reasons'):
        for r in e['reject_reasons'][:2]:
            print(f'      ⚠️ {r}')

# 保存最终结果
with open('/tmp/phase2_results.json', 'w') as f:
    json.dump({'entries': entries, 'output_dir': result.get('output_dir')}, f, ensure_ascii=False)
print(f'\n💾 结果已保存到 /tmp/phase2_results.json')
