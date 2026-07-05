"""Core Audit V2.14.2 — 统一审计框架"""
import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

AUDIT_SCHEMA = {
    "event": "",             # event name
    "run_id": "",            # current run
    "source_run_id": "",     # parent run
    "module": "",            # factor_lab.live_readiness
    "action": "",            # check / approve / reject / apply
    "status": "",            # passed / failed / warning
    "message": "",
    "safety": {
        "auto_apply": False,
        "no_live_trade": True,
        "broker_adapter_called": False,
        "miniqmt_called": False,
        "live_config_unchanged": True,
        "paper_config_unchanged": True,
    },
    "timestamp": "",
}


class AuditTrail:
    """JSONL 审计日志"""
    def __init__(self, output_dir: str):
        self.path = Path(output_dir) / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, run_id: str = "", source_run_id: str = "", module: str = "",
            action: str = "", status: str = "passed", message: str = "", safety: dict = None):
        entry = {
            **AUDIT_SCHEMA,
            "event": event,
            "run_id": run_id,
            "source_run_id": source_run_id,
            "module": module,
            "action": action,
            "status": status,
            "message": message,
            "safety": safety or AUDIT_SCHEMA["safety"],
            "timestamp": datetime.now(CST).isoformat(),
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def get_events(self, limit=100):
        if not self.path.exists():
            return []
        with open(self.path) as f:
            return [json.loads(line) for line in f.readlines()[-limit:]]
