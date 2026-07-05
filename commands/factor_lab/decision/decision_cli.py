#!/usr/bin/env python3
"""V1.13 Decision Log + Review CLI"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    # decision-log
    dl = sub.add_parser("decision-log")
    dl.add_argument("--date", default="latest")
    dl.add_argument("--plan", default=None)
    dl.add_argument("--action", default=None)
    dl.add_argument("--buy", default=None)
    dl.add_argument("--sell", default=None)
    dl.add_argument("--exclude", default=None)
    dl.add_argument("--notes", default=None)
    dl.add_argument("--confirm", action="store_true")

    # review
    rv = sub.add_parser("review")
    rv.add_argument("--start", required=True)
    rv.add_argument("--end", required=True)

    args = parser.parse_args()

    if args.command == "decision-log":
        _cmd_decision_log(args)
    elif args.command == "review":
        _cmd_review(args)
    else:
        parser.print_help()


def _cmd_decision_log(args):
    from factor_lab.decision.decision_logger import create_decision_log, update_decision_log

    date = args.date
    if date == "latest":
        date = datetime.now(CST).strftime("%Y-%m-%d")

    if args.action or args.plan:
        buy = args.buy.split(",") if args.buy else None
        sell = args.sell.split(",") if args.sell else None
        exclude = args.exclude.split(",") if args.exclude else None
        log = update_decision_log(date, plan=args.plan, action=args.action,
                                   buy=buy, sell=sell, exclude=exclude,
                                   notes=args.notes, confirm=args.confirm)
    else:
        log = create_decision_log(date)

    print(json.dumps(log, indent=2, ensure_ascii=False))


def _cmd_review(args):
    from factor_lab.decision.decision_review import run_decision_review, generate_review_report
    from pathlib import Path

    result = run_decision_review(args.start, args.end)
    out_dir = str(Path(f"/mnt/d/HermesReports/decision_review/{args.start}_{args.end}"))
    generate_review_report(result, out_dir)

    print(f"\n{'='*60}")
    print(f"  决策复盘完成")
    print(f"  期间: {result['period']}")
    print(f"  决策: {result['decisions_found']} 次")
    print(f"  已完成复盘: {result['reviews_completed']} 次")
    print(f"  Pending: {len(result.get('pending_dates',[]))} 次")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
