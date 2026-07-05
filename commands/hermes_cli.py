#!/usr/bin/env python3
"""
Hermes A股投研助手 — CLI 入口

用法:
  python3 hermes_cli.py <group>:<action> [options]

示例:
  python3 hermes_cli.py market:update-daily
  python3 hermes_cli.py intraday:check-once
  python3 hermes_cli.py intraday:watch --interval 45
  python3 hermes_cli.py package:publish-all
  python3 hermes_cli.py wechat:test
"""

import sys
import os
from pathlib import Path

# 确保能在任何目录下运行
BASE = Path(__file__).parent.resolve()
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from config import ensure_dirs, now_str


def show_help():
    print("""Hermes A股投研助手 — 命令参考

行情类:
  market:update-daily              更新全 A 日 K
  market:update-live-snapshot      更新实时快照

策略实验室类:
  strategy-lab:init                 初始化实验室目录
  strategy-lab:build-universe       构建所有股票池
  strategy-lab:mine-candidates      挖掘候选策略
  strategy-lab:run-backtest         运行全部策略回测
  strategy-lab:build-latest-signals 生成最新信号
  strategy-lab:build-review-material 生成评审材料

个股分析类:
  stock:context <代码>              读取个股数据上下文

妙想金融数据（东方财富）:
  mx:data <问句>                    金融数据查询（行情/资金流）
  mx:search <关键词>                资讯搜索（公告/新闻/研报）
  mx:xuangu <条件>                  智能选股（自然语言条件）

量化策略回测类:
  backtest:factor-top <因子名> [--rebalance weekly/monthly]
                                因子 Top 组分位数回测 → 完整 HTML 报告
  backtest:walk-forward <因子名> [--top-quantile 0.2] [--rebalance monthly]
                                因子 Walk-Forward 样本外验证 → 过拟合诊断报告
  factor:validate [--factor ret5] [--start 2025-01-02] [--end 2026-06-30] [--rebalance monthly]
                                因子完整稳健性验证 → 反过拟合 + Walk-Forward + 评分
  factor:batch [--factors ret5,vol_ratio60,...] [--start 2025-01-02] [--end 2026-06-30]
                                批量因子验证 → 排行榜 HTML / CSV / JSON
  factor:composites [--candidate-pool PATH] [--methods equal_weight_score,...]
                                多因子组合验证 → 组合排行榜
  factor:orthogonality [--factors f1,f2,...] [--start 2025-01-02] [--end 2026-06-30]
                                因子正交性扩展 + ret5 过滤验证
  factor:strategies [--start 2025-01-02] [--end 2026-06-30] [--top-n 20]
                                ret5 + 过滤器策略层验证 (V1.7)
  factor:signal [--signal-date latest] [--top-n 20]
                                ret5_ma20_gate 盘前信号生成 (V1.8)
  factor:etf-selector [--from-live-signal PATH] [--capital 50000]
                                ETF Selector: 受限板块替代暴露筛选 (V1.10)
  factor:premarket [--capital 50000] [--signal-date 2026-07-03]
                                Unified 盘前决策报告: 股票+ETF+资金计划 (V1.11)
  factor:daily-premarket [--date auto] [--capital 50000] [--no-notify]
                                每日盘前编排: 信号+ETF+报告+推送+决策模板 (V1.12)
  factor:decision-log [--date latest] [--plan B] [--action plan_b] [--confirm]
                                人工决策记录 (V1.13)
  factor:review-decisions --start YYYY-MM-DD --end YYYY-MM-DD
                                决策复盘: 系统推荐 vs 人工执行表现 (V1.13)
  factor:rebalance-diff --date 2026-07-03 --positions data/positions/current_positions.csv --plan B
                                实盘持仓接入 + 调仓差异分析 (V2.0)
  factor:position-import --source manual_csv
                                持仓数据源导入 + 标准化 + 校验报告 (V2.1)
  broker:miniqmt-status          检查 miniQMT 只读持仓状态 (V2.3)
  factor:order-preview --date 2026-07-03 --plan B
                                委托预览: 从 rebalance-diff 生成人工审核订单 (V2.4)
  factor:approval --date 2026-07-03 --plan B
                                风控审批 + Kill Switch + 人工确认工作流 (V2.5)
  factor:paper-trade --date 2026-07-03 --plan B
                                模拟执行: 从 approval 生成 paper account (V2.6)
  factor:paper-review --start 2026-07-01 --end 2026-07-31
                                Paper 复盘: 模拟交易效果评估 + 对比复盘 (V2.6.1)
  factor:paper-dashboard --start 2026-07-01 --end 2026-07-31
                                Paper 看板: 连续运行绩效 + 执行质量 (V2.7)
  factor:adaptive-recommend --start 2026-07-01 --end 2026-07-31
                                策略参数自适应建议: Plan/TopN/ETF/风控 (V2.8)
  factor:recommendation-backtest --start 2026-07-01 --end 2026-07-31
                                建议 A/B 回测验证: 不自动修改配置 (V2.9)
  factor:manual-approval --latest [--approve candidate] [--reject candidate]
                                人工审批 + 配置变更草案: 不修改生产配置 (V2.10)
  factor:shadow-forward --latest [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--last N]
                                影子前向测试: 观察 candidate 未来表现 (V2.11)
  factor:paper-apply --latest [--candidate switch_to_plan_a] [--dry-run] [--confirm-paper-apply]
                                Paper Apply: 候选提升到 Paper Trading (V2.12)
  factor:paper-promotion-review --latest [--candidate switch_to_plan_a]
                                Paper 晋级评审: candidate paper 表现评估 (V2.13)
  factor:live-readiness --latest [--candidate switch_to_plan_a] [--strict]
                                实盘前门禁检查: 6 道 Gate + Checklist (V2.14)
  architecture:audit             全局架构审计: 模块/CLI/Gate/Safety/V3 Readiness (V2.14.1)
  alpha:register --spec <path>  Alpha Factory: 注册外部 AlphaSpec (V3.0)
  alpha:list                     Alpha Factory: 列出已注册 Alpha (V3.0)
  alpha:show --alpha-id <id>    Alpha Factory: 查看 Alpha 详情 (V3.0)
  alpha:retire --alpha-id <id>  Alpha Factory: 退役 Alpha (V3.0)
  alpha:evaluation-plan --alpha-id <id>
                                Alpha Factory: 生成评估计划 (V3.0)
  alpha:init-samples             初始化示例 Alpha (V3.0)
  alpha:migrate-existing-factors [--dry-run] [--category momentum]
                                因子目录迁移: 现有 88 个因子迁入 Alpha Registry (V3.0.1)
  leader:dispatch --from-latest-completion
                                Leader 自动工作循环: 从完成信号派发下一轮
  leader:consume-latest-task     Hermes 消费 latest.json 中的任务
  leader:agent-runner --once [--backend claude] [--interval 180] [--watch]
                                Hermes 自动执行器: 可插拔后端 (V2.15.2)
  leader:loop-once               Leader 循环: 读取 completion 并派发下一轮
  leader:lock-status             查看当前任务锁状态

leader:automation-status       后台自动工作流健康状态检查
Leader 自动派发:
  leader:inspect                 Leader 只读检查本地报告/代码/Registry，判断 V3 阶段
  leader:dispatch [--dry-run]    按 Alpha Factory 路线图生成 agent_tasks 任务包
  leader:accept [--full-tests]   自动验收 / local CI，生成 acceptance 报告
  leader:github-sync --version Vx.y.z [--summary TEXT]
                                版本完成后提交并推送到 GitHub
  leader:loop-once              自动工作循环单次 tick
  leader:loop-watch             自动工作循环轮询运行
  leader:agent-runner --once    Codex 后台执行器单次运行
  leader:agent-runner --watch   Codex 后台执行器轮询运行
  
后台任务管理:
  bg:list                      列出所有持久化后台任务
  bg:status <id>               查看任务状态
  bg:log <id> [--tail 100]     查看任务日志
  bg:kill <id>                 终止任务
  bg:clean [--hours 168]       清理已完成的任务
  factor:mine                   全流程因子挖掘 → HTML 报告
  factor:list [分类]            列出所有因子
  factor:evolve                 基于 LLM 生成新候选因子

基本面类:
  fundamentals:update-from-baostock  更新 Baostock 基本面

数据质量类:
  data:freshness-check             检查数据新鲜度
  data:gap-report                  报告数据缺口

盘中监测类:
  intraday:prepare                 初始化盘中状态
  intraday:check-once              单次盘中检查
  intraday:watch [interval]        盘中循环监测
  intraday:publish-alerts          发布预警包
  intraday:stop                    停止监测

企业微信类:
  wechat:test                      测试 webhook
  wechat:send-digest               发送摘要

发布类:
  package:publish-preopen          发布盘前事件
  package:publish-market           发布行情快照
  package:publish-intraday-alerts  发布盘中预警
  package:publish-all              发布所有待发数据
""")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        show_help()
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    # === 市场类 ===
    if command == "market:update-daily":
        from market_fetcher import cmd_update_daily
        cmd_update_daily()

    elif command == "market:update-live-snapshot":
        from market_fetcher import cmd_update_live_snapshot
        cmd_update_live_snapshot()

    elif command == "market:update-priority-minute":
        from market_fetcher import cmd_update_priority_minute
        cmd_update_priority_minute()

    # === 基本面类 ===
    elif command == "fundamentals:update":
        from market_fetcher import cmd_update_fundamentals
        cmd_update_fundamentals()

    elif command == "announcements:parse":
        from announcement_parser import cmd_parse
        cmd_parse()

    elif command == "policy:update-events":
        from policy_fetcher import cmd_update_events
        cmd_update_events()

    elif command == "tags:update":
        from tag_maintainer import TagMaintainer
        TagMaintainer().update_all()

    elif command == "fundamentals:update-from-baostock":
        from tag_maintainer import cmd_update_fundamentals
        cmd_update_fundamentals()

# === 策略实验室 ===
    elif command == "strategy-lab:init":
        from strategy_lab.orchestrator import init
        r = init()
        print(f"✅ Strategy Lab 初始化: {r['status']}")

    elif command == "strategy-lab:build-universe":
        from strategy_lab.universe import build, list_universes
        for u in list_universes():
            stocks, meta = build(u)
            print(f"  universe {u}: {meta['total_stocks']} 只")
        print("✅ 所有 universe 已构建")

    elif command == "strategy-lab:mine-candidates":
        from strategy_lab.orchestrator import mine_candidates
        c = mine_candidates()
        for cand in c:
            print(f"  {cand['strategy_name']:40s} {cand['category']:20s} {cand['status']}")
        print(f"✅ {len(c)} 个候选策略")

    elif command == "strategy-lab:run-backtest":
        from strategy_lab.orchestrator import run_backtest, list_strategies
        for name in list_strategies():
            r = run_backtest(name)
            print(f"  {name}: {r['status']}")
        print("✅ 回测完成")

    elif command == "strategy-lab:build-latest-signals":
        from strategy_lab.orchestrator import build_latest_signals, list_strategies
        for name in list_strategies():
            s = build_latest_signals(name)
            print(f"  {name}: {len(s)} 条信号")
        print("✅ 信号已生成")

    elif command == "strategy-lab:build-review-material":
        from strategy_lab.orchestrator import build_review_material, list_strategies
        for name in list_strategies():
            r = build_review_material(name)
            print(f"  {name}: {r['production_readiness']}")
        print("✅ 评审材料已生成")

    elif command == "strategy-lab:rank-strategies":
        from strategy_lab.ranker import rank_strategies
        registry = rank_strategies()
        print(f"{'策略':40s} {'收益':>8s} {'回撤':>8s}")
        print("-" * 60)
        for r in registry[:5]:
            print(f"{r['strategy_name']:40s} {r['total_return']*100:>7.2f}% {r['max_drawdown']*100:>7.2f}%")
        print(f"✅ {len(registry)} 个策略已排名")

    elif command == "strategy-lab:publish-results":
        from strategy_lab.publisher import publish_results
        r = publish_results()
        print(f"✅ 发布完成: {r['package_id']}")
        print(f"   路径: {r['path']}")
        print(f"   文件: {r['files']} 个")

    elif command == "strategy-lab:run-parameter-search":
        from strategy_lab.param_search import run_parameter_grid
        from strategy_lab.orchestrator import list_strategies
        for name in list_strategies():
            report = run_parameter_grid(name)
            best = report.get("best_total_return", "N/A")
            print(f"  {name}: {report['total_combinations']} 组合, 最优收益={best}")
        print("✅ 参数搜索完成")

    elif command == "strategy-lab:run-walk-forward":
        from strategy_lab.walk_forward import run_walk_forward
        from strategy_lab.orchestrator import list_strategies
        for name in list_strategies():
            report = run_walk_forward(name)
            wf = "✅" if report.get("walk_forward_pass") else "⚠️"
            print(f"  {wf} {name}: train={report['train_avg_return']}, val={report['val_avg_return']}")
        print("✅ Walk-forward 验证完成")

    elif command == "strategy-lab:run-regime-analysis":
        from strategy_lab.backtest import run as _run
        from strategy_lab.regime import analyze_regime, dump_all
        from strategy_lab.orchestrator import list_strategies, load_strategy
        all_regimes = []
        for name in list_strategies():
            cfg = load_strategy(name)
            results = analyze_regime(name, lambda s, e: _run(cfg, start_date=s, end_date=e))
            for r in results:
                print(f"  {name:40s} {r['period']:10s} ret={r['strategy_return']*100:>+6.2f}% sse={r['sse_return']*100 if r['sse_return'] else 0:>+6.2f}% {r['regime']}")
                r["strategy_name"] = name
                all_regimes.append(r)
        dump_all(all_regimes)
        print("✅ 市场环境分析完成")

    elif command.startswith("stock:context"):
        from stock_context import build_context, format_markdown
        if not args:
            print("用法: hermes stock:context <代码>")
        else:
            ctx = build_context(args[0])
            print(format_markdown(ctx))

    elif command == "stock:card":
        from gen_stock_card import build_stock_data, make_analysis_image, push_to_wechat
        import os, json

    elif command.startswith("mx:"):
        import subprocess
        mx_cmd = command[3:]
        if not args:
            print(f"用法: hermes mx:{mx_cmd} <查询词>")
        else:
            query = " ".join(args)
            result = subprocess.run(
                [sys.executable, str(BASE / "mx.py"), mx_cmd, query],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "MX_APIKEY": os.environ.get("MX_APIKEY", "")}
            )
            print(result.stdout)
            if result.stderr:
                print(f"⚠️ {result.stderr[:500]}")

    # === 量化策略回测类 ===
    elif command == "backtest:factor-top":
        if not args:
            print("用法: hermes backtest:factor-top <因子名> [--rebalance weekly/monthly]")
            print("示例: hermes backtest:factor-top ret5 --rebalance monthly")
            return
        factor_name = args[0]
        rebalance = "monthly"
        for i, a in enumerate(args):
            if a == "--rebalance" and i+1 < len(args):
                rebalance = args[i+1]
        import subprocess, os, json
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        script = f"""
import sys, json; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
from reports.quantstats_report import generate_report
from reports.top_group_backtest import run_top_group_backtest
from factor_lab.factor_engine import load_stock_kline
from factor_lab.pipeline import load_universe
from factor_lab.factor_base import list_factors
import pandas as pd

symbols = load_universe()
df = load_stock_kline(symbols, min_days=60)
factor_expr = ''
for fdef in list_factors():
    if fdef['name'] == '{factor_name}':
        df['f'] = fdef['func'](df, **fdef['params'])
        factor_expr = fdef['description']
        break

pivot = df.pivot_table(index='date', columns='symbol', values='f')
close_pivot = df.pivot_table(index='date', columns='symbol', values='close')

bench = pd.read_csv('/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline/000001.csv', encoding='utf-8-sig')
bench['date'] = pd.to_datetime(bench['date'])
bench = bench[(bench['date']>='2025-01-01') & (bench['date']<='2026-06-30')]
bench_ret = bench.set_index('date')['close'].pct_change().dropna()

result = run_top_group_backtest(
    symbols, pivot.stack().rename('f').reorder_levels(['date','symbol']), close_pivot,
    '2025-01-02', '2026-06-30', top_quantile=0.2, rebalance='{rebalance}',
    market_benchmark_returns=bench_ret, market_benchmark_name="沪深300",
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

    elif command == "backtest:walk-forward":
        if not args:
            print("用法: hermes backtest:walk-forward <因子名> [--top-quantile 0.2] [--rebalance monthly]")
            print("示例: hermes backtest:walk-forward ret5 --top-quantile 0.2 --rebalance monthly")
            return
        factor_name = args[0]
        top_quantile = 0.2
        rebalance = "monthly"
        for i, a in enumerate(args):
            if a == "--top-quantile" and i+1 < len(args):
                top_quantile = float(args[i+1])
            if a == "--rebalance" and i+1 < len(args):
                rebalance = args[i+1]
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = f"""
import sys, json
sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
from factor_lab.walk_forward import run_walk_forward
report = run_walk_forward('{factor_name}', top_quantile={top_quantile}, rebalance='{rebalance}')
print(json.dumps({{"factor": report["factor_name"], "windows": len(report["windows"]), "diagnostics": report["diagnostics"]}}, ensure_ascii=False, indent=2))
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err_lines = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l and "missing from font" not in l]
            if err_lines:
                print(f"⚠️ {'; '.join(err_lines[:3])}")

    # === 因子挖掘类 ===
    elif command == "factor:mine":
        import subprocess
        env = os.environ.copy()
        env["PATH"] = "/home/ly/.hermes/research-assistant/.venv_quant/bin:" + env.get("PATH", "")
        result = subprocess.run(
            [sys.executable, str(BASE / "factor_lab/pipeline.py")],
            capture_output=True, text=True, timeout=180, env=env
        )
        print(result.stdout)
        if result.stderr:
            print(f"⚠️ {result.stderr[:500]}")

    elif command == "factor:list":
        from factor_lab.factor_base import list_factors
        cat = args[0] if args else None
        factors = list_factors(cat)
        print(f"因子总数: {len(factors)}")
        for f in factors:
            print(f"  {f['name']:25s}  [{f['category']}]  {f['description']}")

    elif command == "factor:evolve":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        script = str(BASE / "factor_lab/evolution.py")
        # 合并已有进化因子 + 新生成
        code = f"""
import sys; sys.path.insert(0, '{BASE}')
from factor_lab.evolution import generate_candidates
import json, os

existing = [
    {{'name':'ret5','mean_ic':0.0345,'ir':0.20,'category':'momentum'}},
    {{'name':'reversal5','mean_ic':-0.0345,'ir':0.20,'category':'reversal'}},
    {{'name':'close_gt_ma20','mean_ic':0.0333,'ir':0.18,'category':'trend'}},
    {{'name':'vol_ratio60','mean_ic':0.0310,'ir':0.20,'category':'volume'}},
    {{'name':'vol_mom','mean_ic':0.0341,'ir':0.20,'category':'evolved'}},
]
candidates = generate_candidates(existing)
print(f'生成 {{len(candidates)}} 个新因子:')
for c in candidates:
    print(f'  {{c[\"name\"]}}: {{c[\"expression\"]}}')

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
print(f'运行 hermes factor:mine 查看 IC 表现')
"""
        result = subprocess.run(
            [venv_python, "-c", code],
            capture_output=True, text=True, timeout=120,
            env=os.environ
        )
        print(result.stdout)
        if result.stderr:
            print(f"⚠️ {result.stderr[:300]}")
    
    elif command == "factor:validate":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        # 解析参数
        kwargs = {"factor": "ret5", "start": "2025-01-02", "end": "2026-06-30", "rebalance": "monthly"}
        for i, a in enumerate(args):
            if a.startswith("--") and i + 1 < len(args):
                key = a.lstrip("--")
                if key in kwargs:
                    kwargs[key] = args[i + 1]
        code = f"""
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd
from factor_lab.validate_factor import run_validation
class Args: pass
a = Args()
a.factor = '{kwargs["factor"]}'
a.start = '{kwargs["start"]}'
a.end = '{kwargs["end"]}'
a.rebalance = '{kwargs["rebalance"]}'
a.benchmark = '000300.SH'
a.top_n = 20
a.run_anti_overfit = True
a.run_walk_forward = True
a.output = None
result = run_validation(a)
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:batch":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        factors_str = "ret5,vol_ratio60,reversal5,close_gt_ma20,ret10,ret20,vol_ratio20,reversal20"
        start = "2025-01-02"
        end = "2026-06-30"
        for i, a in enumerate(args):
            if a.startswith("--factors") and i+1 < len(args):
                factors_str = args[i+1]
            if a.startswith("--start") and i+1 < len(args):
                start = args[i+1]
            if a.startswith("--end") and i+1 < len(args):
                end = args[i+1]
        code = f"""
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd
from factor_lab.scoring.leaderboard import run_batch_validation
factors = '{factors_str}'.split(',')
result = run_batch_validation(
    factors=factors, start_date='{start}', end_date='{end}',
    rebalance='monthly', top_n=20,
    run_anti_overfit=True, run_walk_forward=True,
)
print(f"\\n📁 输出目录: {{result.get('output_dir','?')}}")
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=900, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")
        # 长任务完成通知
        __import__('subprocess').run(['bash','-c','source ~/.bashrc && cd /home/ly/.hermes/research-assistant/commands && /home/ly/.hermes/research-assistant/.venv_quant/bin/python3 -c "import sys; sys.path.insert(0,\".\"); from factor_lab.notify import notify_goal_done; notify_goal_done(\'factor:batch 批量验证\', \'8个因子验证完成, 请回Hermes查看\', \'completed\')"'])

    elif command == "factor:composites":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        pool_path = "/mnt/d/HermesReports/factor_leaderboard/20260704_155707/factor_leaderboard.json"
        methods = "equal_weight_score,weighted_score,gated_score,zscore_blend,rank_blend"
        for i, a in enumerate(args):
            if a.startswith("--candidate-pool") and i+1 < len(args):
                pool_path = args[i+1]
            if a.startswith("--methods") and i+1 < len(args):
                methods = args[i+1]
        code = f"""
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd
from factor_lab.validate_composites import main as comp_main
import argparse
sys.argv = ['validate_composites', '--candidate-pool', '{pool_path}', '--methods', '{methods}']
comp_main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=1200, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:orthogonality":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = f"""
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd
from factor_lab.validate_orthogonality import main
import argparse
sys.argv = ['validate_orthogonality']
main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=1800, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:strategies":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = """
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd
from factor_lab.validate_strategies import run_strategy_validation
run_strategy_validation()
import os; os.environ['WECHAT_WEBHOOK_URL'] = os.popen('source ~/.bashrc && echo $WECHAT_WEBHOOK_URL').read().strip()
from factor_lab.notify import notify_goal_done
notify_goal_done('factor:strategies V1.7', '策略验证完成', 'completed')
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=1800, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:signal":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = """
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
import pandas as pd
from factor_lab.live.signal_cli import main
main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:etf-selector":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = """
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
from factor_lab.etf.etf_selector_cli import main
main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=120, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:premarket":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = """
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
from factor_lab.live.unified_premarket_report import main
main()
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=120, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    elif command == "factor:daily-premarket":
        import subprocess, os
        venv_python = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
        code = """
import sys; sys.path.insert(0, '/home/ly/.hermes/research-assistant/commands')
from factor_lab.orchestration.daily_premarket_runner import run_daily_premarket
run_daily_premarket(no_notify=True)
"""
        result = subprocess.run([venv_python, "-c", code], capture_output=True, text=True, timeout=600, env=os.environ)
        print(result.stdout)
        if result.stderr:
            err = [l for l in result.stderr.split("\\n") if l.strip() and "Warning" not in l and "findfont" not in l]
            if err:
                print(f"⚠️ {'; '.join(err[:5])}")

    # === Alpha Factory / Leader ===
    elif command.startswith("alpha:"):
        from factor_lab.alpha.alpha_cli import main as alpha_main
        sys.argv = ["alpha_cli", command.split(":", 1)[1]] + args
        alpha_main()

    elif command == "leader:inspect":
        from factor_lab.leader.leader_cli import main as leader_main
        leader_main(["inspect"])

    elif command == "leader:dispatch":
        if "--from-latest-completion" in args:
            from factor_lab.leader.workloop import dispatch_from_completion
            dispatch_from_completion()
        else:
            from factor_lab.leader.leader_cli import main as leader_main
            leader_main(["dispatch"] + args)

    elif command == "leader:consume-latest-task":
        from factor_lab.leader.workloop import consume_latest_task
        consume_latest_task()

    elif command == "leader:lock-status":
        import json as _json
        from factor_lab.leader.workloop import is_locked, LOCK_FILE
        if is_locked():
            data = _json.loads(open(LOCK_FILE).read())
            print(f"  🔒 运行中: {data.get('run_id')}")
        else:
            print(f"  🔓 无运行中任务")

    elif command == "leader:agent-runner":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--once", action="store_true")
        p.add_argument("--watch", action="store_true")
        p.add_argument("--backend", default="claude")
        p.add_argument("--interval", type=int, default=180)
        a = p.parse_args(args)
        from factor_lab.leader.agent_runner import AgentRunner
        runner = AgentRunner(backend=a.backend, interval=a.interval)
        if a.watch:
            runner.watch()
        else:
            result = runner.run_once()
            print(f"  Status: {result.get('status', '?')}")
            if result.get("completed"):
                print(f"  ✅ Completed: {', '.join(result['completed'])}")
            if result.get("remaining"):
                print(f"  ⏳ Remaining: {', '.join(result['remaining'])}")

    elif command == "leader:loop-once":
        from factor_lab.leader.agent_runner import loop_once
        loop_once()

    elif command == "leader:automation-status":
        from factor_lab.leader.auto_health import health
        import json
        h = health()
        for k, v in h.items():
            print(f"  {k}: {v}")

    elif command == "leader:accept":
        from factor_lab.leader.leader_cli import main as leader_main
        leader_main(["accept"] + args)

    elif command == "leader:github-sync":
        from factor_lab.leader.leader_cli import main as leader_main
        leader_main(["github-sync"] + args)

    elif command == "leader:loop-once":
        from factor_lab.leader.leader_cli import main as leader_main
        leader_main(["loop-once"] + args)

    elif command == "leader:loop-watch":
        from factor_lab.leader.leader_cli import main as leader_main
        leader_main(["loop-watch"] + args)

    elif command == "leader:agent-runner":
        from factor_lab.leader.leader_cli import main as leader_main
        if "--once" in args:
            args = ["once"] + [a for a in args if a != "--once"]
        elif "--watch" in args:
            args = ["watch"] + [a for a in args if a != "--watch"]
        leader_main(["agent-runner"] + args)

    elif command == "architecture:audit":
        from factor_lab.architecture.architecture_audit import run_architecture_audit
        run_architecture_audit()

    # === 数据质量类 ===
    elif command == "data:freshness-check":
        from data_quality import FreshnessChecker
        fc = FreshnessChecker()
        fc.run()

    elif command == "data:gap-report":
        from data_quality import DataGapReporter
        dgr = DataGapReporter()
        report = dgr.report()
        summary = report["summary"]
        print(f"📋 数据缺口报告: {summary['total_gaps']} 缺口, {summary['blocking_gaps']} 阻塞")
        for g in report["gaps"]:
            icon = {'blocking': '🚫', 'partial': '⚠️', 'minor': 'ℹ️'}.get(g.get('impact', ''), '❓')
            print(f"  {icon} [{g['category']}] {g['failure_reason']}")

    # === 盘中监测类 ===
    elif command == "intraday:prepare":
        from intraday_monitor import IntradayMonitor
        m = IntradayMonitor()
        m.prepare()

    elif command == "intraday:check-once":
        from intraday_monitor import IntradayMonitor
        m = IntradayMonitor()
        m.load_business_data()
        events = m.check_once()
        levels = {}
        for e in events:
            l = e.get("level", "?")
            levels[l] = levels.get(l, 0) + 1
        if levels:
            print(f"事件统计: {levels}")
        print(f"总事件: {len(events)}")

    elif command == "intraday:watch":
        interval = 45
        if args and args[0].isdigit():
            interval = int(args[0])
        from intraday_monitor import IntradayMonitor
        m = IntradayMonitor()
        m.prepare()
        m.watch(interval=interval)

    elif command == "intraday:publish-alerts":
        from package_publisher import cmd_publish_intraday_alerts
        cmd_publish_intraday_alerts()

    elif command == "intraday:stop":
        print("⏹️ 停止监测（需在 watch 进程内按 Ctrl+C）")

    # === 企业微信类 ===
    elif command == "wechat:test":
        from wechat_push import WeChatPusher
        pusher = WeChatPusher()
        pusher.test_connection()

    elif command == "wechat:send-digest":
        print("🔧 wechat:send-digest — 待实现摘要累积发送")

    # === 后台任务管理 ===
    elif command == "bg:list":
        from factor_lab.bg import list_jobs
        jobs = list_jobs()
        if not jobs:
            print("📭 无后台任务")
        else:
            print(f"📋 {len(jobs)} 个后台任务:")
            for j in jobs:
                status_icon = {"completed": "✅", "running": "🔄", "failed": "❌"}.get(
                    j.get("status", ""), "❓")
                print(f"  {status_icon} {j['job_id']}: {j.get('name','')} [{j.get('status','?')}]")

    elif command == "bg:status":
        if not args:
            print("用法: bg:status <job_id>")
            return
        from factor_lab.bg import job_status
        s = job_status(args[0])
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif command == "bg:log":
        if not args:
            print("用法: bg:log <job_id> [--tail 100]")
            return
        tail = 100
        for i, a in enumerate(args):
            if a == "--tail" and i+1 < len(args):
                tail = int(args[i+1])
        from factor_lab.bg import job_log
        print(job_log(args[0], tail=tail))

    elif command == "bg:kill":
        if not args:
            print("用法: bg:kill <job_id>")
            return
        from factor_lab.bg import kill_job
        print(kill_job(args[0]))

    elif command == "bg:clean":
        hours = 168
        for i, a in enumerate(args):
            if a == "--hours" and i+1 < len(args):
                hours = int(args[i+1])
        from factor_lab.bg import clean_old_jobs
        n = clean_old_jobs(hours=hours)
        print(f"🧹 清理了 {n} 个已完成任务")

    # === 发布类 ===
    elif command == "package:publish-preopen":
        from package_publisher import cmd_publish_preopen
        cmd_publish_preopen()

    elif command == "package:publish-market":
        from package_publisher import cmd_publish_market
        cmd_publish_market()

    elif command == "package:publish-intraday-alerts":
        from package_publisher import cmd_publish_intraday_alerts
        cmd_publish_intraday_alerts()

    elif command == "package:publish-all":
        from package_publisher import cmd_publish_all
        cmd_publish_all()

    else:
        print(f"❌ 未知命令: {command}")
        print("使用 -h 查看帮助")
        sys.exit(1)


if __name__ == "__main__":
    main()
