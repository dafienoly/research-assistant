#!/usr/bin/env python3
"""CLI for Alpha Factory Leader."""

from __future__ import annotations

import argparse
import json

from factor_lab.leader.planner import dispatch_tasks, inspect_system


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hermes Alpha Factory Leader")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("inspect", help="只读检查本地报告/代码/Registry，输出当前阶段判断")

    sp = sub.add_parser("dispatch", help="根据路线图生成 agent task 包")
    sp.add_argument("--dry-run", action="store_true", help="只输出计划，不写 agent_tasks")
    sp.add_argument("--max-tasks", type=int, default=6, help="最多生成任务数")

    sp = sub.add_parser("accept", help="运行 Leader 自动验收 / local CI")
    sp.add_argument("--full-tests", action="store_true", help="运行 pytest -q 全量测试")
    sp.add_argument("--no-smoke", action="store_true", help="跳过 CLI smoke test")

    sp = sub.add_parser("github-sync", help="版本完成后提交并推送到 GitHub")
    sp.add_argument("--version", required=True, help="版本号，例如 V2.15.1")
    sp.add_argument("--summary", default="", help="提交说明摘要")
    sp.add_argument("--dry-run", action="store_true", help="只显示将提交的变更")

    sp = sub.add_parser("loop-once")
    sp.add_argument("--consume", action="store_true")
    sp.add_argument("--no-github", action="store_true")

    sp = sub.add_parser("loop-watch")
    sp.add_argument("--interval", type=int, default=180)
    sp.add_argument("--max-ticks", type=int, default=0)
    sp.add_argument("--consume", action="store_true")
    sp.add_argument("--no-github", action="store_true")

    sp = sub.add_parser("agent-runner")
    sp.add_argument("mode", choices=["once", "watch"])
    sp.add_argument("--interval", type=int, default=180)
    sp.add_argument("--max-ticks", type=int, default=0)
    sp.add_argument("--codex-bin", default="codex")
    sp.add_argument("--model", default=None)
    sp.add_argument("--timeout", type=int, default=3600)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--no-loop", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "inspect":
        print(json.dumps(inspect_system(), indent=2, ensure_ascii=False))
    elif args.command == "dispatch":
        result = dispatch_tasks(dry_run=args.dry_run, max_tasks=args.max_tasks)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not args.dry_run and result.get("output_dir"):
            print(f"\n✅ Leader 任务包已生成: {result['output_dir']}")
    elif args.command == "accept":
        from factor_lab.leader.acceptance import run_acceptance
        result = run_acceptance(full_tests=args.full_tests, smoke=not args.no_smoke)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\n✅ Leader 验收报告已生成: {result['output_dir']}")
    elif args.command == "github-sync":
        from factor_lab.leader.github_sync import sync_version
        result = sync_version(version=args.version, summary=args.summary, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("pushed"):
            print(f"\n✅ 已推送到 GitHub: {result['remote']} @ {result['commit']}")
    elif args.command == "loop-once":
        from factor_lab.leader.auto_loop import loop_once
        result = loop_once(auto_consume=args.consume, auto_github=not args.no_github)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "loop-watch":
        from factor_lab.leader.auto_loop import loop_watch
        loop_watch(interval_seconds=args.interval, max_ticks=args.max_ticks, auto_consume=args.consume, auto_github=not args.no_github)
    elif args.command == "agent-runner":
        from factor_lab.leader.agent_runner import run_once, watch
        if args.mode == "once":
            result = run_once(codex_bin=args.codex_bin, model=args.model, timeout_seconds=args.timeout, dry_run=args.dry_run, trigger_loop=not args.no_loop)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            watch(interval_seconds=args.interval, max_ticks=args.max_ticks, codex_bin=args.codex_bin, model=args.model, timeout_seconds=args.timeout, dry_run=args.dry_run, trigger_loop=not args.no_loop)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
