#!/usr/bin/env python3
"""每日收盘自动因子挖掘管线入口 (no_agent=True cron script)

由 cronjob 在 16:00 触发，stdout 输出即为投递内容。
"""
import sys
import os
from pathlib import Path

# 确保 commands/ 在路径中
_HERE = Path(__file__).parent.resolve()
_COMMANDS = _HERE / ".." / "commands"
if _COMMANDS.exists():
    sys.path.insert(0, str(_COMMANDS.resolve()))

from factor_lab.pipeline_orchestrator import FactorPipelineOrchestrator


def main():
    print("📊 自动因子挖掘管线 — 每日收盘")
    print(f"   时间: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S}")
    print()

    # Step 1: 编排（IC → 入队）
    orch = FactorPipelineOrchestrator()
    result = orch.run()
    print()
    if result.get("status") == "failed":
        print(f"❌ 编排失败: {result.get('error', '未知错误')}")
        sys.exit(1)

    n_queued = result.get("n_queued_quick", 0) + result.get("n_queued_full", 0)
    if n_queued == 0:
        print("ℹ️ 无待处理因子管线任务")
    else:
        # Step 2: 消费（回测 → 验证 → 注册）
        from factor_lab.pipeline_worker import FactorPipelineWorker
        worker = FactorPipelineWorker()
        results = worker.consume_once()
        print()
        print(f"管线执行完成: {len(results)} 个因子")

    # Step 3: 影子观察器每日 tick
    print("\n🔭 影子观察器...")
    from factor_lab.shadow_observer import ShadowObserver
    shadow_results = ShadowObserver().daily_tick()
    if shadow_results:
        for r in shadow_results:
            print(f"  {r['name']}: {r['status']} (衰减率={r['decay_rate']:.1%})")
    else:
        print("  无到期 Alpha")


if __name__ == "__main__":
    main()
