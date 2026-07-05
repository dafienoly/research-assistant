"""Decision Log — 人工决策记录"""
import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports/daily_premarket")


DECISION_SCHEMA = {
    "decision_date": "",
    "report_path": "",
    "unified_readiness": "",
    "selected_plan": "",       # A/B/C/none
    "user_action": "no_action",  # no_action / observe_only / plan_a / plan_b / plan_c / custom
    "manual_buy": [],
    "manual_sell": [],
    "manual_exclude": [],
    "manual_notes": "",
    "confirmed_by_user": False,
    "confirmed_at": None,
    "created_at": None,
    "updated_at": None,
}


def create_decision_log(date: str, output_dir: str = None) -> dict:
    """创建当日决策日志 (读取 decision_template 初始化)"""
    if output_dir is None:
        output_dir = str(BASE / date.replace("-", ""))

    log = {
        **DECISION_SCHEMA,
        "decision_date": date,
        "report_path": str(Path(output_dir) / "unified_premarket_report.html") if os.path.exists(os.path.join(output_dir, "unified_premarket_report.html")) else "",
        "created_at": datetime.now(CST).isoformat(),
    }

    # 从 unified report 读取 readiness
    report_path = os.path.join(output_dir, "unified_premarket_report.json")
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
        log["unified_readiness"] = report.get("unified_readiness", "")

    path = os.path.join(output_dir, "decision_log.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    return log


def update_decision_log(
    date: str,
    plan: str = None,
    action: str = None,
    buy: list = None,
    sell: list = None,
    exclude: list = None,
    notes: str = None,
    confirm: bool = False,
    output_dir: str = None,
) -> dict:
    """更新决策日志"""
    if output_dir is None:
        output_dir = str(BASE / date.replace("-", ""))

    log_path = os.path.join(output_dir, "decision_log.json")
    if os.path.exists(log_path):
        with open(log_path) as f:
            log = json.load(f)
    else:
        log = create_decision_log(date, output_dir)

    if plan:
        log["selected_plan"] = plan
    if action:
        log["user_action"] = action
    if buy is not None:
        log["manual_buy"] = buy
    if sell is not None:
        log["manual_sell"] = sell
    if exclude is not None:
        log["manual_exclude"] = exclude
    if notes is not None:
        log["manual_notes"] = notes
    if confirm:
        log["confirmed_by_user"] = True
        log["confirmed_at"] = datetime.now(CST).isoformat()

    log["updated_at"] = datetime.now(CST).isoformat()

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    return log


def load_decision_log(date: str, output_dir: str = None) -> dict:
    """加载决策日志"""
    if output_dir is None:
        output_dir = str(BASE / date.replace("-", ""))
    log_path = os.path.join(output_dir, "decision_log.json")
    if os.path.exists(log_path):
        with open(log_path) as f:
            return json.load(f)
    return None
