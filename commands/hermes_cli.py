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

from config import ensure_dirs, now_str, VENV_PYTHON


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
  broker:qmt-health              检查 Windows QMT Bridge 状态
  broker:qmt-account             拉取 QMT 账户资金
  broker:qmt-positions           拉取 QMT 持仓并生成标准 CSV
  broker:qmt-orders              拉取 QMT 委托
  broker:qmt-trades              拉取 QMT 成交
  broker:qmt-sync                同步 QMT 资金/持仓/委托/成交
  broker:qmt-place-approved --approval-id ID --orders PATH
                                仅从已审批 order_preview.json 发起 QMT 委托
  broker:qmt-cancel --approval-id ID --qmt-order-id ID
                                撤销 QMT 委托
  broker:qmt-internal-health    检查大 QMT 内置 HTTP 执行器状态
  broker:qmt-internal-place-approved --approval-id ID --orders PATH
                                仅从已审批 order_preview.json 发起大 QMT 内置委托
  broker:qmt-internal-sync      同步大 QMT 内置执行器订单/成交
  broker:qmt-internal-disable-live
                                关闭大 QMT 内置执行器实盘开关
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
leader:roadmap-status          固定路线图进度显示
leader:task-list               列出待办任务
leader:version-report          版本开发报告
leader:backup-list             列出备份
leader:recover --backup-id <id>  从备份恢复版本状态
leader:task-submit --text "..." --title "任务标题"
                              提交新任务到 inbox
leader:auto-run-once          自动执行器: 读取路线图 cursor，执行当前版本
leader:auto-status            自动执行器状态
leader:dashboard --host 127.0.0.1 --port 8766
                              Dashboard + Agent Console Web 页面
leader:dashboard [--host 127.0.0.1] [--port 8766]
                              FastAPI 后端: Dashboard + Agent Console 统一入口 (V3)
leader:dashboard-json         输出 dashboard 使用的状态 JSON
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

投研 Skill 运行时 (V6.0):
  research:list-skills [--category analysis] [--tag data]
                                列出已注册投研 Skills
  research:show-skill --skill-id <id>
                                查看 Skill 详情
  research:run-skill --skill-id <id> [--params key=val,...]
                                执行投研 Skill
  research:run-history [--skill-id <id>] [--limit 10]
                                查看执行历史
  research:init-registry        初始化注册表并填充内置 Skills

知识库管理 (V3.0):
  research:knowledge-list [--kind rule|finding|failure]
                                列出知识条目
  research:knowledge-add --kind <type> --title <title> --hypothesis <hypothesis> --conclusion <conclusion>
                                添加知识条目
  research:knowledge-search --query <text> [--kind rule|finding|failure]
                                搜索知识库
  research:knowledge-stats       知识库统计
  research:loop [--notebook PATH] [--rounds 5] [--convergence 5]
                                启动 6 阶段自动因子研究循环

策略报告生成 (V6.5):
  strategy:report [--from-portfolio-result PATH] [--from-strategy-returns CSV]
                                生成策略报告
  strategy:report-list [--type portfolio] [--limit 10]
                                列出已生成的策略报告
  strategy:report-count          按类型统计报告数量
  strategy:run-skill [--report-title "..."] [--benchmark CSI300]
                                通过 Research Skill 生成策略报告 (演示)

后台任务管理:
  bg:list                      列出所有持久化后台任务
  bg:status <id>               查看任务状态
  bg:log <id> [--tail 100]     查看任务日志
  bg:kill <id>                 终止任务
  bg:clean [--hours 168]       清理已完成的任务
  factor:mine [top_n]
                                因子挖掘 Agent (V6.6): 自动发现+IC评估+排名
  factor:mine-register [top_n] 将 Top-N 候选注册到因子注册表
  factor:list [分类]            列出所有因子
  factor:evolve                 基于 LLM 生成新候选因子

基本面类:
  fundamentals:update-from-baostock  更新 Baostock 基本面

数据质量类:
  data:freshness-check             检查数据新鲜度
  data:gap-report                  报告数据缺口
  data:hub-rebuild [target]        补齐因子引擎时序数据 (fundamentals|fund-flow|sentiment|all)

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


def _arg_value(args, name, default=""):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


def _print_json(data):
    import json
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _handle_qmt_command(command, args):
    from factor_lab.broker.qmt_client import QMTClient
    from factor_lab.broker.qmt_execution_adapter import QMTExecutionAdapter
    from factor_lab.broker.qmt_internal_http_client import QMTInternalHTTPClient
    from factor_lab.broker.qmt_internal_execution_adapter import QMTInternalExecutionAdapter

    client = QMTClient()

    if command == "broker:qmt-internal-health":
        _print_json(QMTInternalHTTPClient().health())
        return
    if command == "broker:qmt-internal-sync":
        adapter = QMTInternalExecutionAdapter(client=QMTInternalHTTPClient())
        result = adapter.sync()
        _print_json({
            "status": result.get("status"),
            "output_dir": result.get("output_dir"),
            "files": ["qmt_internal_sync.json", "qmt_internal_orders.csv", "qmt_internal_fills.csv", "order_book.json"],
        })
        return
    if command == "broker:qmt-internal-place-approved":
        approval_id = _arg_value(args, "--approval-id")
        orders_path = _arg_value(args, "--orders")
        if not approval_id or not orders_path:
            print("用法: broker:qmt-internal-place-approved --approval-id ID --orders PATH")
            return
        adapter = QMTInternalExecutionAdapter(client=QMTInternalHTTPClient())
        result = adapter.place_approved_orders(approval_id=approval_id, orders_path=orders_path)
        _print_json({
            "status": result.get("status"),
            "summary": result.get("summary"),
            "output_dir": result.get("output_dir"),
        })
        return
    if command == "broker:qmt-internal-disable-live":
        adapter = QMTInternalExecutionAdapter(client=QMTInternalHTTPClient())
        _print_json(adapter.disable_live())
        return

    if command == "broker:qmt-health":
        _print_json(client.health())
        return
    if command == "broker:qmt-account":
        _print_json(client.get_account())
        return
    if command == "broker:qmt-positions":
        adapter = QMTExecutionAdapter(client=client)
        result = adapter.sync()
        _print_json({
            "status": result.get("status"),
            "positions_file": str(adapter.output_dir / "qmt_positions.csv"),
            "output_dir": result.get("output_dir"),
        })
        return
    if command == "broker:qmt-orders":
        _print_json(client.get_orders())
        return
    if command == "broker:qmt-trades":
        _print_json(client.get_trades())
        return
    if command == "broker:qmt-sync":
        adapter = QMTExecutionAdapter(client=client)
        result = adapter.sync()
        _print_json({
            "status": result.get("status"),
            "output_dir": result.get("output_dir"),
            "files": ["qmt_sync.json", "qmt_positions.csv", "qmt_orders.csv", "qmt_trades.csv", "order_book.json"],
        })
        return
    if command == "broker:qmt-place-approved":
        approval_id = _arg_value(args, "--approval-id")
        orders_path = _arg_value(args, "--orders")
        if not approval_id or not orders_path:
            print("用法: broker:qmt-place-approved --approval-id ID --orders PATH")
            return
        adapter = QMTExecutionAdapter(client=client)
        result = adapter.place_approved_orders(approval_id=approval_id, orders_path=orders_path)
        _print_json({
            "status": result.get("status"),
            "summary": result.get("summary"),
            "output_dir": result.get("output_dir"),
        })
        return
    if command == "broker:qmt-cancel":
        approval_id = _arg_value(args, "--approval-id")
        qmt_order_id = _arg_value(args, "--qmt-order-id")
        if not approval_id or not qmt_order_id:
            print("用法: broker:qmt-cancel --approval-id ID --qmt-order-id ID")
            return
        adapter = QMTExecutionAdapter(client=client)
        _print_json(adapter.cancel_order(approval_id=approval_id, qmt_order_id=qmt_order_id))
        return

    print(f"未知 QMT 命令: {command}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        show_help()
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    # === 分解命令: factor 和 leader 由独立模块处理 ===
    from factor_commands import handle as _hfc
    if _hfc(command, args):
        return
    from leader_commands import handle as _hlc
    if _hlc(command, args):
        return

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

    # === QMT Bridge / Broker ===
    elif command.startswith("broker:qmt-"):
        _handle_qmt_command(command, args)

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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        """因子挖掘: 因子自动发现 + IC 评估 + 排名"""
        top_n = 10
        if args:
            try:
                top_n = int(args[0])
            except ValueError:
                pass
        include_window = True
        include_xs = True
        include_combo = True

        print(f"🔬 因子挖掘 Agent (V6.6)")
        print(f"   策略: ", end="")
        strategies = []
        if include_window: strategies.append("窗口变体")
        if include_xs: strategies.append("横截面")
        if include_combo: strategies.append("组合")
        print(" + ".join(strategies))
        print(f"   Top-N: {top_n}\n")

        try:
            from factor_lab.factor_mining import FactorMiningEngine

            # 生成演示 K 线数据
            print("[1/4] 生成演示数据...")
            import numpy as np
            import pandas as pd
            rng = np.random.default_rng(42)
            dates = pd.date_range("2025-01-02", periods=252, freq="B")
            symbols = [f"{i:06d}.SZ" for i in range(1, 101)]
            rows = []
            for sym in symbols:
                price = 50.0 + rng.random() * 100
                for d in dates:
                    ret = rng.normal(0, 0.025)
                    price *= (1 + ret)
                    rows.append({
                        "date": d, "symbol": sym,
                        "close": price,
                        "volume": max(1, int(rng.exponential(5e6))),
                    })
            df = pd.DataFrame(rows)
            df["ret1"] = df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(-1)
            )
            print(f"   {len(symbols)} 只股票 x {len(dates)} 交易日")

            print("[2/4] 加载因子注册表...")
            engine = FactorMiningEngine()
            print(f"   {engine.config}")

            print("[3/4] 生成候选因子...")
            print("[4/4] 评估候选因子 (IC/ICIR/分层)...")

            report = engine.mine(df)
            report.print_summary()

            # 输出详细结果
            print(f"\n{'─'*60}")
            print(f"  Top-{top_n} 候选详情:")
            for i, cand in enumerate(report.top_candidates[:top_n], 1):
                info = cand.get("candidate", {})
                print(f"\n  [{i}] {info.get('name', '?')}")
                print(f"      分类: {info.get('category', '?')}")
                print(f"      描述: {info.get('description', '?')}")
                print(f"      方法: {info.get('generation_method', '?')}")
                print(f"      来源: {info.get('source', '?')}")
                print(f"      IC: {cand.get('ic_mean', 0):.4f}  "
                      f"ICIR: {cand.get('ic_ir', 0):.2f}  "
                      f"正IC比: {cand.get('ic_positive_ratio', 0):.0%}  "
                      f"多空差: {cand.get('spread_ret', 0):.4f}")
                print(f"      评分: {cand.get('score', 0):.2f}")

            print(f"\n{'─'*60}")
            print(f"  注册命令: python3 hermes_cli.py factor:mine-register")
            print(f"  使用 Research Skill: python3 hermes_cli.py research:run-skill --skill-id factor-mining --params top_n=10")

        except ImportError as e:
            print(f"❌ 导入失败: {e}")
            print("   请确保 factor_mining 包已正确安装")
        except Exception as e:
            import traceback
            print(f"❌ 执行失败: {e}")
            traceback.print_exc()

    elif command == "factor:mine-register":
        """注册挖掘出的 Top-N 候选到因子注册表"""
        top_n = 5
        if args:
            try:
                top_n = int(args[0])
            except ValueError:
                pass
        print(f"🔬 注册 Top-{top_n} 候选因子\n")
        try:
            from factor_lab.factor_mining import FactorMiningEngine
            engine = FactorMiningEngine()
            registered = engine.register_top_candidates(
                "demo",  # placeholder — would need a stored report
                top_n=top_n,
                confirm=False,
            )
            if registered:
                print(f"\n✅ 已注册: {', '.join(registered)}")
            else:
                print("\n⚠️ 没有注册任何因子 (可能已存在或需人工确认)")
        except Exception as e:
            print(f"❌ 注册失败: {e}")

    elif command == "factor:list":
        from factor_lab.factor_base import list_factors
        cat = args[0] if args else None
        factors = list_factors(cat)
        print(f"因子总数: {len(factors)}")
        for f in factors:
            print(f"  {f['name']:25s}  [{f['category']}]  {f['description']}")

    elif command == "factor:evolve":
        import subprocess, os
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        __import__('subprocess').run(['bash','-c',f'source ~/.bashrc && cd {BASE} && {VENV_PYTHON} -c "import sys; sys.path.insert(0,\\"commands\\"); from factor_lab.notify import notify_goal_done; notify_goal_done(\'factor:batch 批量验证\', \'8个因子验证完成, 请回Hermes查看\', \'completed\')"'])

    elif command == "factor:composites":
        import subprocess, os
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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
        venv_python = VENV_PYTHON
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

    # === 投研 Skill 运行时 (V6.0) ===
    elif command == "research:list-skills":
        from factor_lab.research_skill import SkillRegistry
        registry = SkillRegistry()
        registry.seed_defaults()
        category = None
        tag = None
        for i, a in enumerate(args):
            if a == "--category" and i + 1 < len(args):
                category = args[i + 1]
            elif a == "--tag" and i + 1 < len(args):
                tag = args[i + 1]
        skills = registry.list(category=category, tag=tag)
        print(f"\n📋 已注册 Skills ({len(skills)} 个)")
        if category:
            print(f"   分类: {category}")
        if tag:
            print(f"   标签: {tag}")
        print()
        for s in skills:
            print(f"  [{s['skill_id']}] {s['name']}")
            print(f"    分类: {s['category']}  |  参数: {len(s['params'])}  |  标签: {', '.join(s['tags'])}")
            print(f"    {s['description'][:80]}{'...' if len(s['description']) > 80 else ''}")
            print()

    elif command == "research:show-skill":
        skill_id = None
        for i, a in enumerate(args):
            if a == "--skill-id" and i + 1 < len(args):
                skill_id = args[i + 1]
        if not skill_id:
            print("用法: python3 hermes_cli.py research:show-skill --skill-id <id>")
            return
        from factor_lab.research_skill import SkillRegistry
        registry = SkillRegistry()
        registry.seed_defaults()
        spec = registry.get(skill_id)
        if not spec:
            print(f"❌ Skill '{skill_id}' 未找到")
            return
        print(f"\n📖 Skill: {spec.skill_id}")
        print(f"   名称: {spec.name}")
        print(f"   描述: {spec.description}")
        print(f"   分类: {spec.category}")
        print(f"   版本: {spec.version}")
        print(f"   标签: {', '.join(spec.tags)}")
        print(f"   参数:")
        for p in spec.params:
            req = " (必填)" if p.required else ""
            default = f" (默认: {p.default})" if p.default is not None else ""
            choices = f" [选项: {', '.join(p.choices)}]" if p.choices else ""
            print(f"     - {p.name} ({p.type}){req}{default}{choices}")
            if p.description:
                print(f"       {p.description}")
        print()

    elif command == "research:run-skill":
        skill_id = None
        params_str = ""
        for i, a in enumerate(args):
            if a == "--skill-id" and i + 1 < len(args):
                skill_id = args[i + 1]
            elif a == "--params" and i + 1 < len(args):
                params_str = args[i + 1]
        if not skill_id:
            print("用法: python3 hermes_cli.py research:run-skill --skill-id <id> [--params key=val,...]")
            return
        params = {}
        if params_str:
            for pair in params_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k.strip()] = v.strip()
        from factor_lab.research_skill import SkillRegistry, SkillRuntime
        registry = SkillRegistry()
        registry.seed_defaults()
        runtime = SkillRuntime(registry=registry)
        result = runtime.run(skill_id, params)
        print(f"\n🎯 Skill 执行结果: {skill_id}")
        print(f"   状态: {result.status}")
        print(f"   Run ID: {result.run_id}")
        print(f"   耗时: {result.duration_ms}ms")
        if result.error:
            print(f"   错误: {result.error}")
        if result.data:
            import json as _json
            print(f"   数据:")
            print(_json.dumps(result.data, indent=2, ensure_ascii=False))
        print()

    elif command == "research:run-history":
        skill_id = None
        limit = 10
        for i, a in enumerate(args):
            if a == "--skill-id" and i + 1 < len(args):
                skill_id = args[i + 1]
            elif a == "--limit" and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
        from factor_lab.research_skill import SkillRuntime
        runtime = SkillRuntime()
        runs = runtime.list_runs(skill_id=skill_id, limit=limit)
        print(f"\n📜 Skill 执行历史 ({len(runs)} 条)")
        if skill_id:
            print(f"   筛选: {skill_id}")
        print()
        for r in runs:
            print(f"  [{r['run_id']}] {r.get('skill_name', r['skill_id'])}")
            print(f"    状态: {r['status']}  |  耗时: {r.get('duration_ms', 0)}ms")
            if r.get('error'):
                print(f"    错误: {r['error']}")
            print()

    elif command == "research:init-registry":
        from factor_lab.research_skill import SkillRegistry
        registry = SkillRegistry()
        count = registry.seed_defaults()
        skills = registry.list()
        print(f"\n✅ Skill 注册表初始化完成")
        print(f"   新增: {count}")
        print(f"   总计: {len(skills)} 个注册 Skills")
        for s in skills:
            print(f"   - [{s['skill_id']}] {s['name']}")
        print()

    # ── V3.0 Knowledge Base ─────────────────────────────────────
    elif command == "research:knowledge-list":
        kind = _arg_value(args, "--kind", "")
        from factor_lab.research_skill.knowledge_base import cmd_knowledge_list
        print(cmd_knowledge_list(kind))

    elif command == "research:knowledge-add":
        kind = _arg_value(args, "--kind", "")
        title = _arg_value(args, "--title", "")
        hypothesis = _arg_value(args, "--hypothesis", "")
        conclusion = _arg_value(args, "--conclusion", "")
        evidence = _arg_value(args, "--evidence", "")
        tags = _arg_value(args, "--tags", "")
        source = _arg_value(args, "--source", "")
        conf_str = _arg_value(args, "--confidence", "0.5")
        try:
            confidence = float(conf_str)
        except ValueError:
            confidence = 0.5
        if not title or not hypothesis or not conclusion:
            print("用法: research:knowledge-add --kind <type> --title <title> --hypothesis <hypothesis> --conclusion <conclusion>")
            return
        from factor_lab.research_skill.knowledge_base import cmd_knowledge_add
        print(cmd_knowledge_add(kind, title, hypothesis, conclusion, evidence, tags, source, confidence))

    elif command == "research:knowledge-search":
        query = _arg_value(args, "--query", "")
        kind = _arg_value(args, "--kind", "")
        if not query:
            print("用法: research:knowledge-search --query <text> [--kind rule|finding|failure]")
            return
        from factor_lab.research_skill.knowledge_base import cmd_knowledge_search
        print(cmd_knowledge_search(query, kind))

    elif command == "research:knowledge-stats":
        from factor_lab.research_skill.knowledge_base import cmd_knowledge_stats
        print(cmd_knowledge_stats())

    elif command == "research:loop":
        notebook = _arg_value(args, "--notebook", "")
        rounds_str = _arg_value(args, "--rounds", "5")
        convergence_str = _arg_value(args, "--convergence", "5")
        try:
            rounds = int(rounds_str)
        except ValueError:
            rounds = 5
        try:
            convergence = int(convergence_str)
        except ValueError:
            convergence = 5
        from factor_lab.research_loop import cmd_research_loop
        print(cmd_research_loop(notebook=notebook, rounds=rounds, convergence=convergence))

    # ── V6.5 Strategy Report ─────────────────────────────────────
    elif command == "strategy:report":
        _handle_strategy_report(args)

    elif command == "strategy:report-list":
        _handle_strategy_report_list(args)

    elif command == "strategy:report-count":
        _handle_strategy_report_count()

    elif command == "strategy:run-skill":
        _handle_strategy_run_skill(args)


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
        h = health()
        for k, v in h.items():
            print(f"  {k}: {v}")

    elif command == "leader:roadmap-status":
        from factor_lab.leader.roadmap_cursor import status_text
        print(status_text())

    elif command == "leader:task-list":
        from factor_lab.leader.task_intake import intake
        inbox = intake()
        print(f"  Inbox: {inbox['inbox_count']} tasks")
        for t in inbox.get("tasks", [])[:5]:
            print(f"    - {t['id']}: {t['title'][:50] if t.get('title') else '(no title)'}")

    elif command == "leader:version-report":
        from factor_lab.leader.version_report import generate_report
        import json
        r = generate_report()
        print(f"  当前版本: {r['current_version']}")
        print(f"  已完成的版本: {r['total_completed']}")
        print(f"  失败的版本: {r['total_failed']}")
        print(f"  📁 /mnt/d/HermesReports/version_reports/")

    elif command == "leader:backup-list":
        from factor_lab.leader.roadmap_backup import list_backups
        for b in list_backups()[-10:]:
            print(f"  {b['id']}: V{b['current_version']} ({b['completed']} completed)")

    elif command == "leader:recover":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--backup-id", required=True)
        a = p.parse_args(args)
        from factor_lab.leader.roadmap_backup import recover
        r = recover(a.backup_id)
        print(f"  Status: {r.get('status', '?')}")

    elif command == "leader:task-submit":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--text", required=True)
        p.add_argument("--title", default="")
        a = p.parse_args(args)
        from factor_lab.leader.task_intake import submit
        e = submit(a.text, a.title)
        print(f"  ✅ Submitted: {e['id']}")

    elif command == "leader:auto-run-once":
        from factor_lab.leader.auto_executor import auto_run_once
        result = auto_run_once()
        status = result.get("status", "?")
        version = result.get("version", "?")
        name = result.get("name", "")
        backend = result.get("backend", "?")
        outcome = result.get("outcome", "")
        print(f"  Auto-run-once: {version} {name}")
        print(f"  Status: {status}  Backend: {backend}")
        if outcome:
            print(f"  {outcome}")
        if result.get("commit"):
            print(f"  Commit: {result['commit']}")

    elif command == "leader:auto-status":
        from factor_lab.leader.backend_policy import policy_status
        s = policy_status()
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif command == "leader:dashboard":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8766)
        a = p.parse_args(args)
        from factor_lab.api_server.main import serve
        serve(host=a.host, port=a.port)

    elif command == "leader:dashboard-json":
        import json
        from factor_lab.leader.dashboard import collect_status
        print(json.dumps(collect_status(), ensure_ascii=False, indent=2))

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

    elif command == "sector:rotation":
        _handle_sector_rotation(args)
    elif command == "sector:list":
        _handle_sector_list()
    elif command == "sector:rankings":
        _handle_sector_rankings(args)
    elif command == "sector:signals":
        _handle_sector_signals()
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

    elif command.startswith("data:hub-rebuild"):
        target = args[0] if args else "all"
        from data_hub_rebuilder import rebuild_fundamentals_timeseries, refresh_fund_flow_timeseries, rebuild_news_sentiment_timeseries
        targets = {
            "fundamentals": ("📊 基本面时序", rebuild_fundamentals_timeseries),
            "fund-flow": ("💰 资金流向时序", lambda: refresh_fund_flow_timeseries(batch_size=20)),
            "sentiment": ("📰 新闻情感时序", lambda: rebuild_news_sentiment_timeseries(top_n=20)),
        }
        if target not in ("all", *targets.keys()):
            print(f"未知目标: {target}, 可选: all, {', '.join(targets.keys())}")
            return
        results = {}
        if target == "all":
            for name, (label, func) in targets.items():
                print(f"\n{'='*50}\n{label}\n{'='*50}")
                try: results[name] = func()
                except Exception as e: results[name] = {"status": "error", "error": str(e)}
        else:
            label, func = targets[target]
            print(f"\n{'='*50}\n{label}\n{'='*50}")
            try: results[target] = func()
            except Exception as e: results[target] = {"status": "error", "error": str(e)}
        print(f"\n{'='*50}\n📋 汇总\n{'='*50}")
        for name, r in results.items():
            icon = "✅" if r.get("status") == "ok" else "⚠️"
            print(f"  {icon} {name}: {r.get('status', 'unknown')}")

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



# ── V6.5 Strategy Report CLI Handlers ──────────────────────────

def _handle_strategy_report(args):
    """strategy:report — 生成策略报告"""
    from_portfolio_result = None
    from_strategy_returns = None
    title = ""
    benchmark = "CSI300"
    output_dir = ""

    for i, a in enumerate(args):
        if a == "--from-portfolio-result" and i + 1 < len(args):
            from_portfolio_result = args[i + 1]
        elif a == "--from-strategy-returns" and i + 1 < len(args):
            from_strategy_returns = args[i + 1]
        elif a == "--title" and i + 1 < len(args):
            title = args[i + 1]
        elif a == "--benchmark" and i + 1 < len(args):
            benchmark = args[i + 1]
        elif a == "--output-dir" and i + 1 < len(args):
            output_dir = args[i + 1]

    from factor_lab.strategy_report import StrategyReportGenerator

    gen = StrategyReportGenerator(output_dir=output_dir) if output_dir else StrategyReportGenerator()

    if from_portfolio_result:
        # 从 PortfolioResult JSON 文件生成
        import json
        print(f"\n📂 加载 PortfolioResult: {from_portfolio_result}")
        try:
            with open(from_portfolio_result, "r") as f:
                data = json.load(f)
            # TODO(V6.5+): 从 JSON 重建 PortfolioResult
            print("⚠ 从 JSON 文件重建 PortfolioResult 需要 V6.4 完整反序列化")
            print(f"   PortfolioResult {data.get('run_id', '?')} 已加载")
            print(f"   指标: {json.dumps(data.get('metrics', {}), indent=2, ensure_ascii=False)}")
        except Exception as e:
            print(f"❌ 加载失败: {e}")
    else:
        # 使用演示数据生成报告
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-02", periods=504, freq="B")
        n = len(dates)

        demo_ret = pd.Series(rng.normal(0.15 / 252, 0.15 / np.sqrt(252), n), index=dates)
        bm_ret = pd.Series(rng.normal(0.08 / 252, 0.18 / np.sqrt(252), n), index=dates)

        report_title = title or f"策略分析报告_{__import__('datetime').datetime.now().strftime('%Y%m%d')}"

        report = gen.from_strategy_returns(
            strategy_returns=demo_ret,
            strategy_name=report_title,
            benchmark_returns=bm_ret,
            benchmark_name=benchmark,
        )

        print(f"\n{'='*62}")
        print(f"  📊 策略报告生成完成")
        print(f"{'='*62}")
        print(f"  标题:      {report.title}")
        print(f"  类型:      {report.report_type}")
        print(f"  板块:      {len(report.sections_generated)} 个")
        print(f"  交易日:    {report.n_days}")
        print(f"  耗时:      {report.duration_ms}ms")
        print(f"  输出路径:  {report.output_path}")
        if report.warnings:
            for w in report.warnings:
                print(f"  ⚠ {w}")
        print(f"{'='*62}\n")


def _handle_strategy_report_list(args):
    """strategy:report-list — 列出已生成的策略报告"""
    report_type = None
    limit = 10

    for i, a in enumerate(args):
        if a == "--type" and i + 1 < len(args):
            report_type = args[i + 1]
        elif a == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass

    from factor_lab.strategy_report import StrategyReportGenerator
    gen = StrategyReportGenerator()
    reports = gen.list_reports(report_type=report_type, limit=limit)

    if not reports:
        print("\n📭 暂无已生成的策略报告")
        print(f"   输出目录: {gen.config.output_dir or '默认目录'}")
        return

    print(f"\n📋 策略报告列表 ({len(reports)} 个)")
    if report_type:
        print(f"   类型: {report_type}")
    print()
    for r in reports:
        print(f"  📄 {r['file_name']}")
        print(f"     路径: {r['path']}")
        print(f"     大小: {r['size_kb']} KB")
        print()


def _handle_strategy_report_count():
    """strategy:report-count — 按类型统计报告数量"""
    from factor_lab.strategy_report import StrategyReportGenerator
    gen = StrategyReportGenerator()
    counts = gen.get_report_count()

    if not counts:
        print("\n📭 暂无已生成的策略报告")
        return

    print(f"\n📊 策略报告统计")
    total = 0
    for report_type, count in counts.items():
        print(f"  {report_type}: {count} 个")
        total += count
    print(f"  总计: {total} 个")
    print()


def _handle_strategy_run_skill(args):
    """strategy:run-skill — 通过 Research Skill 生成策略报告"""
    title = "策略分析报告"
    benchmark = "CSI300"

    for i, a in enumerate(args):
        if a == "--report-title" and i + 1 < len(args):
            title = args[i + 1]
        elif a == "--benchmark" and i + 1 < len(args):
            benchmark = args[i + 1]

    from factor_lab.research_skill import SkillRegistry, SkillRuntime

    registry = SkillRegistry()
    registry.seed_defaults()

    runtime = SkillRuntime(registry=registry)
    result = runtime.run(
        "strategy-report",
        params={
            "source": "demo",
            "report_title": title,
            "benchmark_name": benchmark,
        },
    )

    print(f"\n🎯 Strategy Report Skill 执行完成")
    print(f"   Skill ID: strategy-report")
    print(f"   Run ID:   {result.run_id}")
    print(f"   状态:     {result.status}")
    print(f"   耗时:     {result.duration_ms}ms")
    if result.error:
        print(f"   错误:     {result.error}")
    if result.data:
        import json
        print(f"   数据:")
        print(json.dumps(result.data, indent=2, ensure_ascii=False))
    print()


# ── V6.8 Sector Rotation CLI Handlers ─────────────────────────────


def _parse_int(args, name, default: int) -> int:
    """解析 CLI 整数参数"""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                pass
    return default


def _parse_str(args, name, default: str) -> str:
    """解析 CLI 字符串参数"""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


def _handle_sector_rotation(args):
    """sector:rotation — 行业轮动回测

    参数:
      --top-n N:         持有行业数量 (默认 5)
      --strategy TYPE:   轮动策略 momentum/mean_reversion/composite (默认 momentum)
      --freq FREQ:       调仓频率 weekly/monthly/quarterly (默认 monthly)
      --benchmark NAME:  基准名称 CSI300/CSI500/CSI_ALL (默认 CSI300)
      --output PATH:     输出报告路径 (可选)
    """
    top_n = _parse_int(args, "--top-n", 5)
    strategy_str = _parse_str(args, "--strategy", "momentum")
    freq = _parse_str(args, "--freq", "monthly")
    benchmark = _parse_str(args, "--benchmark", "CSI300")
    output = _parse_str(args, "--output", "")

    # 映射策略名称
    strategy_map = {
        "momentum": "momentum",
        "mean_reversion": "mean_reversion",
        "mean-reversion": "mean_reversion",
        "composite": "composite",
    }
    st = strategy_map.get(strategy_str, "momentum")

    from factor_lab.sector_rotation import (
        SectorRotationConfig,
        SectorRotationEngine,
        RotationStrategyType,
    )

    config = SectorRotationConfig(
        name=f"{strategy_str}_rotation",
        strategy_type=RotationStrategyType(st),
        top_n=top_n,
        rebalance_freq=freq,
        benchmark_name=benchmark,
    )

    print(f"\n{'='*60}")
    print(f"  🔄 行业轮动回测")
    print(f"  Strategy: {strategy_str} | Top-N: {top_n} | 调仓: {freq}")
    print(f"  基准: {benchmark}")
    print(f"{'='*60}\n")

    # 生成演示数据
    print("生成演示 K 线数据...")
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-02", periods=504, freq="B")
    n = len(dates)

    # 行业分组
    sector_symbols = {
        "银行": [f"60{str(i).zfill(3)}.SH" for i in range(1, 11)],
        "科技": [f"00{str(i).zfill(3)}.SZ" for i in range(11, 21)],
        "医药": [f"30{str(i).zfill(3)}.SZ" for i in range(21, 31)],
        "消费": [f"00{str(i).zfill(3)}.SZ" for i in range(31, 41)],
        "能源": [f"60{str(i).zfill(3)}.SH" for i in range(41, 51)],
        "金融": [f"00{str(i).zfill(3)}.SZ" for i in range(51, 56)],
        "地产": [f"60{str(i).zfill(3)}.SH" for i in range(56, 61)],
    }

    sector_mapping = {}
    for sector, syms in sector_symbols.items():
        for sym in syms:
            sector_mapping[sym] = sector

    rows = {}
    for sector, symbols in sector_symbols.items():
        mu = {"银行": 0.0003, "科技": 0.0008, "医药": 0.0005,
              "消费": 0.0004, "能源": 0.0006, "金融": 0.0002,
              "地产": 0.0001}.get(sector, 0.0004)
        sigma = {"银行": 0.008, "科技": 0.025, "医药": 0.018,
                 "消费": 0.015, "能源": 0.022, "金融": 0.010,
                 "地产": 0.028}.get(sector, 0.018)
        for sym in symbols:
            noise = rng.normal(0, sigma * 0.3, n)
            ret = rng.normal(mu, sigma, n) + noise * 0.2
            rows[sym] = ret

    stock_returns = pd.DataFrame(rows, index=dates)

    # 运行引擎
    print(f"运行 {strategy_str} 轮动策略...")
    engine = SectorRotationEngine(config)
    result = engine.run(stock_returns, sector_mapping)

    # 输出结果
    print(f"\n{'='*60}")
    print(f"  回测结果")
    print(f"{'='*60}")
    print(f"  信号数:          {result.n_signals}")
    print(f"  平均持有行业数:   {result.avg_sectors_per_signal:.1f}")
    print(f"  行业换手率:       {result.sector_turnover:.2%}")
    print(f"  警告:             {len(result.warnings)}")

    if result.portfolio_result is not None:
        try:
            s = result.portfolio_result.summary()
            print(f"\n  📊 组合表现:")
            print(f"    累计收益:     {s['cumulative_return_pct']:.2f}%")
            print(f"    年化收益:     {s['annualized_return_pct']:.2f}%")
            print(f"    Sharpe:       {s['sharpe']:.2f}")
            print(f"    最大回撤:     {s['max_drawdown_pct']:.2f}%")
            print(f"    Calmar:       {s['calmar']:.2f}")
            if s['benchmark_return_pct']:
                print(f"    基准收益:     {s['benchmark_return_pct']:.2f}%")
                print(f"    超额收益:     {s['active_return_pct']:.2f}%")
                print(f"    信息比:       {s['information_ratio']:.2f}")
        except Exception as e:
            print(f"    指标计算错误: {e}")

    # 输出最近信号
    if result.signals:
        print(f"\n  📋 最近信号 (前3):")
        for sig in result.signals[-3:]:
            secs = ", ".join(sig.selected_sectors[:5])
            print(f"    {sig.date}: [{secs}]")

    if result.warnings:
        print(f"\n  ⚠️ 警告:")
        for w in result.warnings[:5]:
            print(f"    - {w}")

    print(f"{'='*60}\n")

    if output:
        import json
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str)
        )
        print(f"📁 报告已保存: {output}")


def _handle_sector_list():
    """sector:list — 列出所有行业"""
    try:
        from factor_lab.sector_rotation import (
            get_sector_list, get_sector_stock_count
        )
        sectors = get_sector_list()
        counts = get_sector_stock_count()

        if not sectors:
            print("⚠️ 行业数据不可用 (需要 Baostock 数据或缓存文件)")
            return

        print(f"\n📋 行业列表 ({len(sectors)} 个行业):")
        print(f"{'─'*50}")
        for sector in sorted(sectors):
            cnt = counts.get(sector, 0)
            print(f"  {sector:12s}  {cnt:>4d} 只股票")
        print(f"{'─'*50}")
    except Exception as e:
        print(f"❌ 获取行业列表失败: {e}")


def _handle_sector_rankings(args):
    """sector:rankings — 行业评分排名"""
    top_n = _parse_int(args, "--top-n", 10)

    try:
        from factor_lab.sector_rotation import (
            SectorRotationConfig, SectorRotationEngine,
        )
        import numpy as np
        import pandas as pd

        # 生成演示数据
        rng = np.random.default_rng(42)
        dates = pd.date_range("2025-01-02", periods=252, freq="B")
        n = len(dates)

        sector_symbols = {
            "银行": [f"60{str(i).zfill(3)}.SH" for i in range(1, 6)],
            "科技": [f"00{str(i).zfill(3)}.SZ" for i in range(11, 16)],
            "医药": [f"30{str(i).zfill(3)}.SZ" for i in range(21, 26)],
            "消费": [f"00{str(i).zfill(3)}.SZ" for i in range(31, 36)],
            "能源": [f"60{str(i).zfill(3)}.SH" for i in range(41, 46)],
        }
        sector_mapping = {}
        for sector, syms in sector_symbols.items():
            for sym in syms:
                sector_mapping[sym] = sector

        symbol_list = [s for syms in sector_symbols.values() for s in syms]
        rows = {s: rng.normal(0.0005, 0.018, n) for s in symbol_list}
        stock_returns = pd.DataFrame(rows, index=dates)

        config = SectorRotationConfig(top_n=top_n)
        engine = SectorRotationEngine(config)

        # 计算绩效
        from factor_lab.sector_rotation.sector_performance import (
            compute_sector_returns, compute_sector_performance_snapshot,
            compute_sector_rankings,
        )
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)
        perfs = compute_sector_performance_snapshot(sector_ret)
        rankings = compute_sector_rankings(perfs, top_n=top_n)

        if not rankings:
            print("⚠️ 无排名数据")
            return

        print(f"\n📊 行业评分排名 (Top-{top_n}):")
        print(f"{'─'*80}")
        print(f"  {'排名':<4} {'行业':<10} {'综合评分':<10} {'动量':<10} "
              f"{'短期收益':<10} {'中期收益':<10} {'波动率':<10}")
        print(f"{'─'*80}")
        for i, r in enumerate(rankings):
            print(f"  {i+1:<4} {r['sector']:<10} {r['composite_score']:<10.4f} "
                  f"{r['momentum']:<10.4f} {r['return_short_pct']:<10.2f} "
                  f"{r['return_medium_pct']:<10.2f} {r['volatility_pct']:<10.2f}")
        print(f"{'─'*80}")
    except Exception as e:
        print(f"❌ 获取行业排名失败: {e}")


def _handle_sector_signals():
    """sector:signals — 查看当前行业轮动信号 (预览)"""
    print("ℹ️  完整行业轮动信号需运行 sector:rotation 进行回测")
    print("   使用: python3 hermes_cli.py sector:rotation --top-n 5 --strategy momentum")


if __name__ == "__main__":
    main()
