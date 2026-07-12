"""System CLI commands retained after Agent automation retirement."""

import argparse
import json


def _ops(command: str, args: list[str]) -> bool:
    from factor_lab.leader.ops_dashboard import OpsManager

    manager = OpsManager()
    if command == "leader:ops-health":
        result = manager.health()
    elif command == "leader:ops-status":
        result = manager.service_status(args[0]) if args else manager.health()
    elif command in {"leader:ops-start", "leader:ops-stop", "leader:ops-restart"}:
        if not args:
            print(f"用法: {command} <service_id>")
            return True
        action = command.rsplit("-", 1)[-1]
        result = getattr(manager, f"{action}_service")(args[0])
    elif command == "leader:ops-backup":
        result = manager.backup()
    elif command == "leader:ops-diagnostics":
        result = manager.diagnostics()
    elif command == "leader:ops-ports":
        result = {"ports": manager.port_scan()}
    elif command == "leader:ops-all":
        result = {sid: manager.start_service(sid) for sid in ("dashboard", "mcp")}
    else:
        return False
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return True


def handle(command: str, args: list[str]) -> bool:
    if command in {"audit:code", "leader:anti-cheat-audit"}:
        from factor_lab.audit.runner import cmd_main
        raise SystemExit(cmd_main(args, deprecated=command.startswith("leader:")))

    if command == "leader:dashboard":
        parser = argparse.ArgumentParser()
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8766)
        parsed = parser.parse_args(args)
        from factor_lab.api_server.main import serve
        serve(host=parsed.host, port=parsed.port)
        return True

    if command == "architecture:audit":
        from factor_lab.architecture.architecture_audit import run_architecture_audit
        major_version = ""
        for index, value in enumerate(args):
            if value == "--major-version" and index + 1 < len(args):
                major_version = args[index + 1]
                break
        run_architecture_audit(major_version=major_version)
        return True

    if _ops(command, args):
        return True

    return False
