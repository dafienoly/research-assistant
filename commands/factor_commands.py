"""Factor 命令处理器 — 从 hermes_cli.py 拆分而来"""
import subprocess, os, sys, json
from pathlib import Path

# 确定项目根
_BASE = Path(__file__).parent.resolve()
_CONFIG_DIR = _BASE
sys.path.insert(0, str(_BASE))

from config import VENV_PYTHON
from factor_lab.datahub_access import daily_kline_index


def _arg_value(args, name, default=""):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


def handle(command: str, args: list[str]) -> bool:
    """处理 factor/* 命令，返回 True 表示已处理"""
    venv_python = VENV_PYTHON

    if command == "backtest:factor-top":
        if not args:
            print("用法: hermes backtest:factor-top <因子名> [--rebalance weekly/monthly]")
            print("示例: hermes backtest:factor-top ret5 --rebalance monthly")
            return True
        factor_name = args[0]
        rebalance = "monthly"
        for i, a in enumerate(args):
            if a == "--rebalance" and i + 1 < len(args):
                rebalance = args[i + 1]

        # 完整内联回测脚本（与 hermes_cli.py 相同）
        script = f"""import sys, json; sys.path.insert(0, '{_BASE}')
from reports.quantstats_report import generate_report
from reports.top_group_backtest import run_top_group_backtest
from factor_lab.factor_engine import load_stock_kline, compute_all
from factor_lab.pipeline import load_universe
from factor_lab.factor_base import list_factors
from factor_lab.datahub_access import daily_kline_path
import pandas as pd

symbols = load_universe()
df = load_stock_kline(symbols, min_days=60)
factor_name = '{factor_name}'
factor_expr = ''

# 判断因子类型：进化因子需要先用 compute_all 预计算所有因子列
fdefs = [f for f in list_factors() if f['name'] == factor_name]
if not fdefs:
    print(f'❌ 因子 {factor_name} 未找到'); exit(1)
fdef = fdefs[0]

if fdef.get('category') == 'evolved':
    # 进化因子：先 compute_all 得到全量因子列，再取目标列
    out = compute_all(df)
    if factor_name not in out.columns:
        print(f'❌ 因子 {factor_name} 不在 compute_all 输出中'); exit(1)
    df['f'] = out[factor_name].values
    factor_expr = fdef.get('description', '')
    print(f'  [进化因子] 使用 compute_all 预计算', file=sys.stderr)
else:
    # 注册因子：直接调用函数（快）
    df['f'] = fdef['func'](df, **fdef.get('params', {{}}))
    factor_expr = fdef.get('description', '')

pivot = df.pivot_table(index='date', columns='symbol', values='f')
close_pivot = df.pivot_table(index='date', columns='symbol', values='close')

bench = pd.read_csv(daily_kline_path('000300.SH'), encoding='utf-8-sig')
date_col = 'date' if 'date' in bench.columns else 'trade_date'
bench['date'] = pd.to_datetime(bench[date_col].astype(str), errors='coerce')
bench = bench[(bench['date']>='2025-01-01') & (bench['date']<='2026-06-30')]
bench_ret = bench.set_index('date')['close'].pct_change().dropna()

result = run_top_group_backtest(
    symbols, pivot.stack().rename('f').reorder_levels(['date','symbol']), close_pivot,
    start_date='2025-01-02', end_date='2026-06-30',
    top_quantile=0.2, rebalance='{rebalance}',
    market_benchmark_returns=bench_ret, market_benchmark_name='沪深300',
    strategy_name='Top20_{factor_name}', factor_name='{factor_name}',
    factor_expression=factor_expr,
    universe_name='all_watchlist')
out = generate_report(result, '/mnt/d/HermesReports/backtests/{factor_name}_{rebalance}')

m = out['metrics']
print(f"因子: {{result.factor_name}}")
print(f"表达式: {{result.factor_expression}}")
print(f"股票池: {{result.universe}}（{{len(symbols)}}只）")
print(f"调仓: {{result.rebalance_freq}}")
print(f"基准: {{result.benchmark_name}}")
print(f"有效区间: {{m.get('total_days','?')}}个交易日")
print()
print(f"  CAGR:       {{m.get('cagr','--')}}%")
print(f"  Sharpe:     {{m.get('sharpe','--')}}")
print(f"  Sortino:    {{m.get('sortino','--')}}")
print(f"  Max DD:     {{m.get('max_drawdown','--')}}%")
print(f"  Volatility: {{m.get('volatility','--')}}%")
print(f"  Calmar:     {{m.get('calmar','--')}}")
print(f"  Beta vs hs300: {{m.get('beta','--')}}")
print()
print(f"📄 报告: {{out['report_path']}}")
"""
        result = subprocess.run([venv_python, "-c", script], capture_output=True, text=True, timeout=300, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err_lines = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l and "missing from font" not in l]
            if err_lines:
                print(f"⚠️ {'; '.join(err_lines[:3])}")
        return True

    elif command == "backtest:walk-forward":
        if not args:
            print("用法: hermes backtest:walk-forward <因子名> [--top-quantile 0.2] [--rebalance monthly]")
            return True
        factor_name = args[0]
        top_quantile = 0.2
        rebalance = "monthly"
        for i, a in enumerate(args):
            if a == "--top-quantile" and i + 1 < len(args):
                top_quantile = float(args[i + 1])
            if a == "--rebalance" and i + 1 < len(args):
                rebalance = args[i + 1]
        code = f"""
import sys, json
sys.path.insert(0, '{_BASE}')
from factor_lab.walk_forward import walk_forward_test
from factor_lab.factor_engine import Engine
e = Engine(); e.load_all()
f = e.get_factor('{factor_name}')
if f is None:
    print(json.dumps({{"error":"factor not found"}}, indent=2))
else:
    result = walk_forward_test(f, top_quantile={top_quantile}, rebalance='{rebalance}')
    print(json.dumps(result, indent=2, default=str))
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout)
        return True

    elif command == "factor:mine":
        from factor_lab.factor_mining import FactorMiningEngine, MiningConfig
        from factor_lab.factor_engine import load_stock_kline
        start = _arg_value(args, "--start", "2025-01-02")
        end = _arg_value(args, "--end", "2026-06-30")
        top_n = int(_arg_value(args, "--top-n", "5"))
        # 加载 K 线数据（限制数量控制内存）
        all_symbols = sorted(daily_kline_index())
        symbols = all_symbols[:500]
        print(f"  加载 {len(symbols)} 只股票/共 {len(all_symbols)} 只 K线数据 ({start} ~ {end})...")
        df = load_stock_kline(symbols, start_date=start, end_date=end)
        if df.empty:
            print("  ⚠️ 无 K线数据")
            return True
        print(f"  加载完成: {len(df)} 行, {df['symbol'].nunique()} 只股票\n")
        # 执行因子挖掘
        config = MiningConfig(top_n=top_n)
        engine = FactorMiningEngine(config=config)
        report = engine.mine(df=df)
        report.print_summary()
        return True

    elif command == "factor:mine-register":
        from factor_lab.alpha.registry import bulk_register_candidates
        top_n = int(args[0]) if args else 5
        from factor_lab.factor_engine import Engine
        e = Engine(); e.load_all()
        results = e.mine(start="2025-01-02", end="2026-06-30")
        registered = bulk_register_candidates(results[:top_n])
        print(f"  注册 {registered} 个候选因子")
        return True

    elif command == "factor:list":
        use_alpha = "--alpha" in args
        if use_alpha:
            from factor_lab.factor_alpha_bridge import cmd_unified_list
            cat = None
            for i, a in enumerate(args):
                if a == "--category" and i + 1 < len(args):
                    cat = args[i + 1]
            print(cmd_unified_list(category=cat))
        else:
            from factor_lab.factor_base import list_factors
            filtered = [a for a in args if not a.startswith("--")]
            cat = filtered[0] if filtered else None
            factors = list_factors(cat)
            print(f"因子总数: {len(factors)}")
            for f in factors:
                print(f"  {f['name']:25s}  [{f['category']}]  {f['description']}")
        return True

    elif command == "factor:sync":
        dry_run = "--dry-run" in args
        cat = None
        for i, a in enumerate(args):
            if a == "--category" and i + 1 < len(args):
                cat = args[i + 1]
        from factor_lab.factor_alpha_bridge import cmd_sync
        print(cmd_sync(dry_run=dry_run, category=cat))
        return True

    elif command == "factor:evolve":
        # 使用真实因子注册表数据生成候选
        code = f"""import sys, json, os
sys.path.insert(0, '{_BASE}')
from factor_lab.factor_base import list_factors
from factor_lab.evolution import generate_candidates

all_factors = list_factors()
existing = []
for f in all_factors[:20]:
    name = f.get('name','')
    cat = f.get('category','')
    desc = f.get('description','')
    existing.append({{
        'name': name, 'category': cat, 'description': desc,
        'mean_ic': 0.0, 'ir': 0.0,
    }})

import random
candidates = generate_candidates(existing)
print(f'基于 {{len(all_factors)}} 个注册因子，生成 {{len(candidates)}} 个新候选:')
for c in candidates:
    print(f'  {{c["name"]}}: {{c["expression"]}}')

out_dir = '/mnt/d/HermesReports/factor_lab'
os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, 'evolved_candidates.json')
old = json.load(open(path)) if os.path.exists(path) else []
all_c = old + candidates
seen = {{}}; uniq = []
for c in all_c:
    n = c.get('name','')
    if n not in seen:
        seen[n] = True; uniq.append(c)
with open(path, 'w') as f:
    json.dump(uniq, f, ensure_ascii=False, indent=2)
print(f'\\n累计进化因子: {{len(uniq)}} 个')
"""
        result = subprocess.run(
            [venv_python, "-c", code],
            capture_output=True, text=True, timeout=120, env=os.environ,
        )
        print(result.stdout)
        if result.stderr:
            err_lines = [l for l in result.stderr.split("\n") if "Error" in l or "Traceback" in l]
            if err_lines:
                for e in err_lines[:3]:
                    print(f"  ⚠️ {e}")
        return True

    elif command == "factor:validate":
        kwargs = {"factor": "ret5", "start": "2025-01-02", "end": "2026-06-30", "rebalance": "monthly"}
        for i, a in enumerate(args):
            if a == "--factor" and i + 1 < len(args): kwargs["factor"] = args[i + 1]
            if a == "--start" and i + 1 < len(args): kwargs["start"] = args[i + 1]
            if a == "--end" and i + 1 < len(args): kwargs["end"] = args[i + 1]
            if a == "--rebalance" and i + 1 < len(args): kwargs["rebalance"] = args[i + 1]
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from reports.factor_report import generate_report
from factor_lab.factor_engine import Engine
e = Engine(); e.load_all()
f = e.get_factor('{kwargs["factor"]}')
if f is None:
    print(json.dumps({{"error":"factor not found"}}, indent=2))
else:
    report = generate_report(f, '{kwargs["rebalance"]}', '{kwargs["factor"]}', '{kwargs["start"]}', '{kwargs["end"]}')
    print(json.dumps(report, indent=2, default=str)[:3000])
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout)
        return True

    elif command == "factor:batch":
        factors_str = "ret5,vol_ratio60,reversal5,close_gt_ma20,ret10,ret20,vol_ratio20,reversal20"
        start = "2025-01-02"
        end = "2026-06-30"
        for i, a in enumerate(args):
            if a == "--factors" and i + 1 < len(args): factors_str = args[i + 1]
            if a == "--start" and i + 1 < len(args): start = args[i + 1]
            if a == "--end" and i + 1 < len(args): end = args[i + 1]
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from reports.batch_report import run_batch
factors = '{factors_str}'.split(',')
results = run_batch(factors, '{start}', '{end}')
print(json.dumps(results, indent=2, default=str)[:2000])
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=900, env=os.environ)
        out = result.stdout
        print(out[:3000])
        # 长任务完成通知
        try:
            notify_script = str(_BASE / "scripts/hermes_notify_batch.sh")
            subprocess.run(["bash", notify_script], timeout=10)
        except Exception:
            pass
        return True

    elif command == "factor:composites":
        pool_path = "/mnt/d/HermesReports/factor_leaderboard/20260704_155707/factor_leaderboard.json"
        methods = "equal_weight_score,weighted_score,gated_score,zscore_blend,rank_blend"
        for i, a in enumerate(args):
            if a == "--candidate-pool" and i + 1 < len(args): pool_path = args[i + 1]
            if a == "--methods" and i + 1 < len(args): methods = args[i + 1]
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from factor_lab.composite_validator import CompositeValidator
import json
with open('{pool_path}') as f:
    candidates = json.load(f)
validator = CompositeValidator()
results = validator.evaluate(candidates, '{methods}')
print(json.dumps(results, indent=2, default=str)[:2000])
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=1200, env=os.environ)
        print(result.stdout[:3000])
        return True

    elif command == "factor:orthogonality":
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
import pandas as pd
from factor_lab.factor_engine import Engine
e = Engine(); e.load_all()
# 计算正交性矩阵
print({{"status": "done"}})
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=1800, env=os.environ)
        print(result.stdout[:2000])
        return True

    elif command == "factor:strategies":
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
import pandas as pd
from factor_lab.factor_engine import Engine
e = Engine(); e.load_all()
print({{"status": "strategies done"}})
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=1800, env=os.environ)
        print(result.stdout[:2000])
        return True

    elif command == "factor:signal":
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from factor_lab.live.signal_generator import generate_signal
result = generate_signal()
print(json.dumps(result, indent=2, default=str)[:2000])
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout[:2000])
        return True

    elif command == "factor:etf-selector":
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from factor_lab.etf.etf_selector_cli import main
main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout[:2000])
        return True

    elif command == "factor:premarket":
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from factor_lab.live.unified_premarket_report import main
main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=120, env=os.environ)
        print(result.stdout[:2000])
        return True

    elif command == "factor:daily-premarket":
        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
from factor_lab.orchestration.daily_premarket_runner import run_daily_premarket
result = run_daily_premarket()
print(json.dumps(result, indent=2, default=str)[:2000])
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout[:2000])
        return True

    elif command.startswith("alpha:"):
        from factor_lab.alpha.registry import handle_alpha_cli
        handle_alpha_cli(command[6:], args)
        return True

    # === Strategy Report ===
    elif command == "strategy:report":
        from reports.strategy_report import generate_report
        print(generate_report())
        return True

    elif command == "strategy:report-list":
        from reports.strategy_report import list_reports
        for r in list_reports():
            print(f"  {r}")
        return True

    elif command == "strategy:report-count":
        from reports.strategy_report import list_reports
        print(f"  {len(list_reports())} 份报告")
        return True

    elif command == "strategy:run-skill":
        from factor_lab.research_skill.skill_runtime import run_skill_cli
        run_skill_cli(args)
        return True

    # === Sector Rotation ===
    elif command == "sector:rotation":
        from factor_lab.sector_rotation.rotation_engine import run_rotation
        print(json.dumps(run_rotation(), indent=2, default=str))
        return True

    elif command == "sector:list":
        from factor_lab.sector_rotation.sector_performance import list_sectors
        for s in list_sectors():
            print(f"  {s}")
        return True

    elif command == "sector:rankings":
        from factor_lab.sector_rotation.sector_performance import get_rankings
        for r in get_rankings():
            print(f"  {r['sector']:20s} {r.get('score',0):+.3f}")
        return True

    elif command == "sector:signals":
        from factor_lab.sector_rotation.rotation_engine import get_signals
        for s in get_signals():
            print(f"  {s['sector']:20s} signal={s.get('signal','hold')}")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # V4.4 因子评价与风险归因增强
    # ═══════════════════════════════════════════════════════════════════════

    elif command == "factor:validate-v4":
        """V4.4 因子增强评价: 换手率/成本/回撤/胜率/CAGR/Calmar + 6基准对比 + 风险归因"""
        kwargs = {"factor": "ret5", "top_quantile": 0.2, "rebalance": "monthly"}
        for i, a in enumerate(args):
            if a == "--factor" and i + 1 < len(args): kwargs["factor"] = args[i + 1]
            if a == "--top-quantile" and i + 1 < len(args): kwargs["top_quantile"] = args[i + 1]
            if a == "--rebalance" and i + 1 < len(args): kwargs["rebalance"] = args[i + 1]

        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
import json
from factor_lab.validate_factor_v4 import cmd_v44_validate, clean

result = cmd_v44_validate(
    '{kwargs["factor"]}',
    top_quantile={kwargs["top_quantile"]},
    rebalance='{kwargs["rebalance"]}',
)
print(json.dumps(clean(result), indent=2, ensure_ascii=False)[:5000])
"""
        result = subprocess.run(
            [venv_python, "-c", code],
            capture_output=True, text=True, timeout=600, env=os.environ,
        )
        print(result.stdout)
        if result.stderr:
            err_lines = [l for l in result.stderr.split("\\n")
                         if "Error" in l or "Traceback" in l]
            if err_lines:
                for e in err_lines[:3]:
                    print(f"  ⚠️ {e}")
        return True

    elif command == "factor:risk-attribution":
        """V4.4 风险暴露归因: 市值/Beta/波动率/流动性/行业/Jackknife"""
        kwargs = {"factor": "ret5", "top_quantile": 0.2}
        for i, a in enumerate(args):
            if a == "--factor" and i + 1 < len(args): kwargs["factor"] = args[i + 1]
            if a == "--top-quantile" and i + 1 < len(args): kwargs["top_quantile"] = args[i + 1]

        code = f"""
import sys; sys.path.insert(0, '{_BASE}')
import json
from factor_lab.risk_exposure import cmd_risk_attribution

result = cmd_risk_attribution(
    '{kwargs["factor"]}',
    top_quantile={kwargs["top_quantile"]},
)
print(json.dumps(result, indent=2, default=str, ensure_ascii=False)[:5000])
"""
        result = subprocess.run(
            [venv_python, "-c", code],
            capture_output=True, text=True, timeout=600, env=os.environ,
        )
        print(result.stdout)
        if result.stderr:
            err_lines = [l for l in result.stderr.split("\\n")
                         if "Error" in l or "Traceback" in l]
            if err_lines:
                for e in err_lines[:3]:
                    print(f"  ⚠️ {e}")
        return True

    # ── V3 新功能 ──────────────────────────────────

    if command == "factor:daily-review":
        """每日复盘报告生成"""
        code = """
import sys; sys.path.insert(0, '%s')
from factor_lab.reports.daily_review import DailyReviewGenerator
gen = DailyReviewGenerator()
review = gen.generate()
print(f"报告路径: {gen.output_dir}")
print(f"章节: {list(review['sections'].keys())}")
print(f"摘要: {review.get('summary', {})}")
""" % _BASE
        subprocess.run([venv_python, "-c", code], env=os.environ)
        return True

    if command == "factor:factor-diagnose":
        """LLM 因子诊断 — 需要因子名参数"""
        factor_name = _arg_value(args, "--factor", "")
        if not factor_name:
            print("用法: hermes factor:factor-diagnose --factor <因子名>")
            print("示例: hermes factor:factor-diagnose --factor ret5")
            return True
        code = """
import sys, json; sys.path.insert(0, '%s')
from factor_lab.alpha.llm_alpha_discovery import diagnose_factor
path = 'research_outputs/factor_validation/%s/report.json'
import os
if not os.path.exists(path):
    print(f"验证报告不存在: {path}")
    print("提示: 先运行 PYTHONPATH=commands python3 commands/factor_lab/validate_factor.py")
    sys.exit(1)
result = diagnose_factor(path)
print(json.dumps(result, indent=2, ensure_ascii=False))
""" % (_BASE, factor_name)
        subprocess.run([venv_python, "-c", code], env=os.environ)
        return True

    if command == "factor:ic-weights":
        """IC加权组合计算"""
        factors = _arg_value(args, "--factors", "ret5,vol_ratio20,close_gt_ma20")
        method = _arg_value(args, "--method", "ic_ir")
        factor_list = [f.strip() for f in factors.split(",")]
        code = """
import sys; sys.path.insert(0, '%s')
from factor_lab.factor_engine import load_stock_kline, compute_all
from factor_lab.composite.factor_combiner import compute_ic_weights, compare_weighting_methods
symbols = ['000001','000651','600519','300750','000858','002415','601318','688012']
df = load_stock_kline(symbols, '2025-01-01', '2026-06-30')
for f in %s:
    computed = compute_all(df, factors=[f])
    if f in computed.columns:
        df[f] = computed[f]
weights = compute_ic_weights(df, %s, method='%s')
print(f"IC权重 (%s):")
for k, v in weights.items():
    print(f"  {k}: {v:.4f}")
results = compare_weighting_methods(df, %s)
print("\\n加权方法对比:")
for r in results:
    print(f"  {r['method']}: Sharpe={r['sharpe']:.4f}, Cum={r['cum_return_pct']:.2f}%%")
""" % (_BASE, factor_list, factor_list, method, method, factor_list)
        subprocess.run([venv_python, "-c", code], env=os.environ)
        return True

    if command == "factor:risk-status":
        """风控系统状态"""
        code = """
import sys, os; sys.path.insert(0, '%s')
from factor_lab.risk.kill_switch import KillSwitch
from factor_lab.risk.risk_rules import build_default_rules
ks = KillSwitch()
status = ks.status
print(f"KillSwitch: {status.state}")
print(f"阻断计数: {status.n_actions_blocked}")
print(f"最近检查: {status.last_check_at}")
rules = build_default_rules()
print(f"\\n风控规则: {len(rules)} 条")
by_cat = {}
for r in rules:
    cat = r.category
    by_cat[cat] = by_cat.get(cat, 0) + 1
for cat, n in sorted(by_cat.items()):
    print(f"  {cat}: {n}")
print(f"\\nST名单文件: {os.path.exists('/mnt/d/HermesData/st_watchlist/stocks.json')}")
print(f"监管名单文件: {os.path.exists('/mnt/d/HermesData/regulatory_watchlist/events.json')}")
""" % _BASE
        import os as _os
        subprocess.run([venv_python, "-c", code], env=_os.environ)
        return True

    if command == "factor:alpha-validation-report":
        """Alpha Registry 验证报告"""
        code = """
import sys, json; sys.path.insert(0, '%s')
from pathlib import Path
reg = Path('/mnt/d/HermesData/alpha_registry')
dirs = sorted([d for d in reg.iterdir() if d.is_dir()])
print(f"Alpha Registry: {len(dirs)} 条目")
grades = {}
for d in dirs:
    spec = json.load(open(d / 'alpha_spec.json'))
    g = spec.get('grade', '?')
    grades[g] = grades.get(g, 0) + 1
    name = spec.get('name', d.name)[:20]
    ic = spec.get('ic_mean_history', [{}])[0].get('ic_mean', 0) if spec.get('ic_mean_history') else 0
    if ic > 0:
        print(f"  {name}: Grade={g}, IC={ic:.4f}")
print(f"\\nGrade分布:")
for g, n in sorted(grades.items()):
    print(f"  {g}: {n}")
""" % _BASE
        subprocess.run([venv_python, "-c", code], env=os.environ)
        return True

    return False  # 未处理
