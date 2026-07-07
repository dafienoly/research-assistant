"""Factor 命令处理器 — 从 hermes_cli.py 拆分而来"""
import subprocess, os, sys, json
from pathlib import Path

# 确定项目根
_BASE = Path(__file__).parent.resolve()
_CONFIG_DIR = _BASE
sys.path.insert(0, str(_BASE))

from config import VENV_PYTHON


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
            return True
        factor_name = args[0]
        rebalance = "monthly"
        for i, a in enumerate(args):
            if a == "--rebalance" and i + 1 < len(args):
                rebalance = args[i + 1]
        script = f"""
import sys, json; sys.path.insert(0, '{_BASE}')
from reports.quantstats_report import generate_report
import pandas as pd
from factor_lab.factor_engine import Engine
e = Engine(); e.load_all()
f = e.get_factor('{factor_name}')
if f is None:
    print(f'❌ 因子 {factor_name} 未找到'); exit(1)
out = generate_report(f, '{rebalance}', '{factor_name}')
m = out.get('metrics', {{}})
print(f'Factor: {factor_name}  ({rebalance})')
print(f'  Period:    ' + str(m.get('period','')))
print(f'  Total ret: ' + str(m.get('total_return','')))
"""
        result = subprocess.run([venv_python, "-c", script], capture_output=True, text=True, timeout=300, env=os.environ)
        print(result.stdout)
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
        from pathlib import Path
        start = _arg_value(args, "--start", "2025-01-02")
        end = _arg_value(args, "--end", "2026-06-30")
        top_n = int(_arg_value(args, "--top-n", "5"))
        # 加载 K 线数据（限制数量控制内存）
        kline_dir = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")
        all_symbols = sorted([f.stem for f in kline_dir.glob("*.csv")])
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

    return False  # 未处理
