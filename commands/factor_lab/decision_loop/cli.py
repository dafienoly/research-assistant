"""Command-line entry points for local decision-loop operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import DecisionLoopService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-decision-loop")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    preview = sub.add_parser("positions-preview")
    preview.add_argument("file", type=Path)
    preview.add_argument("--source", choices=["csv", "clipboard", "ocr"], default="csv")
    confirm = sub.add_parser("positions-confirm")
    confirm.add_argument("preview_id")
    confirm.add_argument("expected_hash")
    acknowledge = sub.add_parser("ack")
    acknowledge.add_argument("event_id")
    acknowledge.add_argument("--actor", default="user")
    sub.add_parser("flush-l2")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = DecisionLoopService()
    if args.command == "status":
        result = service.status()
    elif args.command == "positions-preview":
        if args.source == "ocr":
            result = service.positions.preview_ocr(args.file).model_dump(mode="json")
        else:
            result = service.positions.preview_text(
                args.file.read_text(encoding="utf-8"), args.source
            ).model_dump(mode="json")
    elif args.command == "positions-confirm":
        result = service.positions.confirm(
            args.preview_id, args.expected_hash
        ).model_dump(mode="json")
    elif args.command == "ack":
        result = service.notifications.acknowledge(args.event_id, args.actor)
    elif args.command == "flush-l2":
        result = service.notifications.flush_l2_digest()
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
