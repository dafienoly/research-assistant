#!/usr/bin/env python3
"""V1.12 Daily Premarket Runner — 盘前策略全流程编排器

编排流程:
  a. 交易日检查
  b. 数据新鲜度检查 (data_freshness.json 或重新检查)
  c. 运行 account-aware signal (signal_cli)
  d. 运行 ETF selector (etf_selector_cli)
  e. 运行 unified report (unified_premarket_report)
  f. 生成 notification_message.txt
  g. 企业微信推送 (如果 no_notify=False)
  h. 生成 decision_template.md
  i. 写入 pipeline_status.json
  j. 写入 audit.log

不自动下单。非交易日仍然生成报告, 但 pipeline_status 标记为 non_trading_day。
"""
import sys
import os
import json
import argparse
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import pandas as pd

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports")
PYTHON = "/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
FACTOR_LAB_DIR = Path(
    "/home/ly/.hermes/research-assistant/commands/factor_lab"
)

# ─── Trading Calendar ────────────────────────────────────────────────


class TradingCalendar:
    """中国A股交易日历

    用 pd.bdate_range 生成交易日, 无网络环境时回退到本地周末排除。
    如果安装了 exchange_calendars 库则优先使用上交所日历。
    """

    def __init__(self):
        self._calendar: Optional[pd.DatetimeIndex] = None
        self._source = "bdate_range"
        self._status = "ok"
        self._generate_calendar()

    def _generate_calendar(self):
        """生成交易日历 (过去400天 ~ 未来30天)"""
        today = date.today()
        start = today - timedelta(days=400)
        end = today + timedelta(days=30)

        # 尝试 exchange_calendars (上交所)
        try:
            import exchange_calendars as xcals

            try:
                cn = xcals.get_calendar("XSHG")
                self._calendar = pd.bdate_range(start, end, freq=cn)
                self._source = "exchange_calendars(XSHG)"
                return
            except Exception:
                pass
        except ImportError:
            pass

        # 回退: pd.bdate_range (默认只去周末)
        try:
            self._calendar = pd.bdate_range(start, end)
            self._source = "bdate_range(default)"
        except Exception:
            self._calendar = pd.bdate_range(
                start, end, freq="C", weekmask="Mon Tue Wed Thu Fri"
            )
            self._source = "bdate_range(weekmask)"

        if self._calendar is None or len(self._calendar) == 0:
            self._status = "failed"
            self._calendar = pd.bdate_range(start, end)
            self._source = "bdate_range(fallback)"

    def is_trading_day(self, date_str: str) -> bool:
        """判断指定日期是否为交易日"""
        dt = pd.Timestamp(date_str)
        return dt in self._calendar

    def latest_trading_day(self) -> str:
        """获取最近的交易日 (今天或之前最近的)"""
        today = pd.Timestamp(date.today())
        trading_days = [d for d in self._calendar if d <= today]
        if trading_days:
            return max(trading_days).strftime("%Y-%m-%d")
        return today.strftime("%Y-%m-%d")

    def next_trading_day(self) -> str:
        """获取下一个交易日"""
        today = pd.Timestamp(date.today())
        future_days = [d for d in self._calendar if d >= today]
        if future_days:
            return min(future_days).strftime("%Y-%m-%d")
        return today.strftime("%Y-%m-%d")

    def status(self) -> dict:
        """返回日历状态

        Returns:
            {today, is_trading_day, latest_trading_day, next_trading_day,
             calendar_source, calendar_status}
        """
        today_str = date.today().strftime("%Y-%m-%d")
        return {
            "today": today_str,
            "is_trading_day": self.is_trading_day(today_str),
            "latest_trading_day": self.latest_trading_day(),
            "next_trading_day": self.next_trading_day(),
            "calendar_source": self._source,
            "calendar_status": self._status,
        }


# ─── Pipeline Helpers ───────────────────────────────────────────────


def _run_module(module_path: str, args: list, stage_name: str) -> dict:
    """通过 subprocess 运行 CLI 模块, 返回执行结果"""
    start = datetime.now(CST)
    cmd = [str(PYTHON), str(module_path)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(FACTOR_LAB_DIR),
        )
        elapsed = (datetime.now(CST) - start).total_seconds()
        out = {
            "returncode": result.returncode,
            "elapsed_seconds": round(elapsed, 2),
        }
        if result.returncode == 0:
            out["status"] = "success"
            out["stdout"] = result.stdout[-500:]
            out["stderr"] = result.stderr[-500:]
        else:
            out["status"] = "failed"
            out["stdout"] = result.stdout[-500:]
            out["stderr"] = result.stderr[-500:]
            out["error"] = (result.stderr[:500] or result.stdout[:500])
        return out
    except subprocess.TimeoutExpired:
        elapsed = (datetime.now(CST) - start).total_seconds()
        return {
            "status": "failed",
            "error": f"Timeout after {elapsed:.0f}s",
            "elapsed_seconds": round(elapsed, 2),
        }
    except Exception as e:
        elapsed = (datetime.now(CST) - start).total_seconds()
        return {
            "status": "failed",
            "error": str(e),
            "elapsed_seconds": round(elapsed, 2),
        }


def _today_output_dir(date_str: str) -> Path:
    """创建当天的统一输出目录"""
    out = BASE_OUTPUT / "daily_premarket" / date_str.replace("-", "")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_json(path: str) -> dict:
    """安全加载 JSON 文件, 不存在或损坏时返回 {}"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ─── Main Orchestrator ──────────────────────────────────────────────


def run_daily_premarket(
    date: str = "auto",
    capital: float = 50000,
    no_notify: bool = False,
    output_dir: str = None,
) -> dict:
    """盘前策略全流程编排

    对每个步骤独立 try/except, 失败不影响后续步骤。
    记录每个阶段的 status (success/warning/failed/skipped)。

    Args:
        date: 信号日期, 'auto'=自动取最新交易日
        capital: 资金量 (默认 50000)
        no_notify: 是否不推送企业微信
        output_dir: 输出目录 (None=自动创建)

    Returns:
        pipeline_status dict
    """
    run_id = uuid.uuid4().hex[:12]
    stages: dict[str, dict] = {}
    warnings: list[str] = []
    errors: list[str] = []
    output_paths: dict[str, str] = {}
    audit_log_entries: list[dict] = []

    def _log(level: str, stage: str, message: str):
        entry = {
            "timestamp": datetime.now(CST).isoformat(),
            "run_id": run_id,
            "level": level,
            "stage": stage,
            "message": message,
        }
        audit_log_entries.append(entry)
        print(f"  [{level}] {stage}: {message}")

    print(f"\n{'=' * 60}")
    print(f"  V1.12 Daily Premarket Runner")
    print(f"  Run ID: {run_id}")
    print(f"  开始时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Date: {date} | Capital: {capital} | NoNotify: {no_notify}")
    print(f"{'=' * 60}\n")

    # ── a. 交易日检查 ──────────────────────────────────────────────
    _log("INFO", "calendar", "交易日历初始化...")
    signal_date = date if date != "auto" else datetime.now(CST).strftime("%Y-%m-%d")
    try:
        cal = TradingCalendar()
        cal_status = cal.status()
        stages["calendar"] = {"status": "success", **cal_status}
        output_paths["calendar_status"] = json.dumps(cal_status)

        if date == "auto":
            signal_date = cal_status["latest_trading_day"]

        if not cal_status["is_trading_day"]:
            w = (
                f"今天({cal_status['today']})非交易日, "
                f"仍在生成报告但不发可交易结论"
            )
            warnings.append(w)
            _log("WARNING", "calendar", w)
            stages["calendar"]["status"] = "warning"
            stages["calendar"]["warning"] = w
        else:
            _log("INFO", "calendar", f"交易日 = {signal_date}")
    except Exception as e:
        _log("ERROR", "calendar", str(e))
        errors.append(f"calendar: {e}")
        stages["calendar"] = {"status": "failed", "error": str(e)}

    # ── 输出目录 ───────────────────────────────────────────────────
    out_dir = output_dir or str(_today_output_dir(signal_date))
    os.makedirs(out_dir, exist_ok=True)
    output_paths["output_dir"] = out_dir
    _log("INFO", "output", f"输出目录: {out_dir}")

    # ── b. 数据新鲜度检查 ──────────────────────────────────────────
    _log("INFO", "freshness", "数据新鲜度检查...")
    freshness = {}
    try:
        live_signal_dir = (
            BASE_OUTPUT / "live_signals" / signal_date.replace("-", "")
        )
        freshness_path = live_signal_dir / "data_freshness.json"
        if freshness_path.exists():
            freshness = _load_json(str(freshness_path))
            freshness["source"] = "cached"
            _log("INFO", "freshness", f"从已有文件加载: {freshness_path}")
        else:
            _log("INFO", "freshness", "重新检查数据新鲜度...")
            freshness = {
                "source": "rerun",
                "status": "unknown",
                "note": "未找到缓存, 后续 signal_cli 会检查",
            }

        stages["freshness"] = {"status": "success"}
        output_paths["freshness"] = json.dumps(freshness)

        freshness_status = freshness.get("status", "unknown")
        if freshness_status in ("partial", "failed"):
            w = (
                f"数据新鲜度: {freshness_status} — "
                f"{freshness.get('note', '')}"
            )
            warnings.append(w)
            _log("WARNING", "freshness", w)
            stages["freshness"]["status"] = "warning"
            stages["freshness"]["warning"] = w
        else:
            _log("INFO", "freshness", f"数据状态: {freshness_status}")
    except Exception as e:
        _log("ERROR", "freshness", str(e))
        errors.append(f"freshness: {e}")
        stages["freshness"] = {"status": "failed", "error": str(e)}

    # ── c. 运行 signal_cli ─────────────────────────────────────────
    _log("INFO", "signal_cli", "运行 account-aware signal (V1.9)...")
    try:
        signal_result = _run_module(
            str(FACTOR_LAB_DIR / "live" / "signal_cli.py"),
            ["--signal-date", signal_date, "--output", out_dir],
            "signal_cli",
        )
        stages["signal_cli"] = signal_result
        if signal_result["status"] == "success":
            signal_json_path = os.path.join(out_dir, "premarket_signal.json")
            if os.path.exists(signal_json_path):
                output_paths["signal_cli_json"] = signal_json_path
            _log(
                "INFO",
                "signal_cli",
                f"信号生成完成 ({signal_result.get('elapsed_seconds', 0)}s)",
            )
        else:
            err = signal_result.get("error", "unknown")
            errors.append(f"signal_cli: {err}")
            _log("ERROR", "signal_cli", f"信号生成失败: {err}")
    except Exception as e:
        _log("ERROR", "signal_cli", str(e))
        errors.append(f"signal_cli: {e}")
        stages["signal_cli"] = {"status": "failed", "error": str(e)}

    # ── d. 运行 ETF selector ───────────────────────────────────────
    _log("INFO", "etf_selector", "运行 ETF selector (V1.10)...")
    etf_out_dir = os.path.join(out_dir, "etf_selector")
    try:
        signal_json = output_paths.get("signal_cli_json", "")
        if signal_json and os.path.exists(signal_json):
            etf_result = _run_module(
                str(FACTOR_LAB_DIR / "etf" / "etf_selector_cli.py"),
                [
                    "--from-live-signal",
                    signal_json,
                    "--capital",
                    str(int(capital)),
                    "--output",
                    etf_out_dir,
                ],
                "etf_selector",
            )
        else:
            etf_result = {
                "status": "skipped",
                "reason": "signal_cli 未生成 premarket_signal.json",
            }
            _log("WARNING", "etf_selector", "跳过: 无 premarket_signal.json")

        stages["etf_selector"] = etf_result
        if etf_result["status"] == "success":
            etf_json_path = os.path.join(etf_out_dir, "etf_selector.json")
            if os.path.exists(etf_json_path):
                output_paths["etf_selector_json"] = etf_json_path
            _log(
                "INFO",
                "etf_selector",
                f"ETF selector 完成 ({etf_result.get('elapsed_seconds', 0)}s)",
            )
        elif etf_result["status"] == "skipped":
            pass
        else:
            err = etf_result.get("error", "unknown")
            errors.append(f"etf_selector: {err}")
            _log("ERROR", "etf_selector", f"ETF selector 失败: {err}")
    except Exception as e:
        _log("ERROR", "etf_selector", str(e))
        errors.append(f"etf_selector: {e}")
        stages["etf_selector"] = {"status": "failed", "error": str(e)}

    # ── e. 运行 unified report ─────────────────────────────────────
    _log("INFO", "unified_report", "运行 unified premarket report (V1.11)...")
    try:
        signal_json = output_paths.get("signal_cli_json", "")
        etf_json = output_paths.get("etf_selector_json", "")

        unified_args = [
            "--signal-date",
            signal_date,
            "--capital",
            str(int(capital)),
            "--from-live-signal",
            signal_json if signal_json else "/dev/null",
            "--output",
            out_dir,
        ]
        if etf_json and os.path.exists(etf_json):
            unified_args += ["--from-etf-selector", etf_json]
        else:
            unified_args += ["--from-etf-selector", "/dev/null"]

        unified_result = _run_module(
            str(FACTOR_LAB_DIR / "live" / "unified_premarket_report.py"),
            unified_args,
            "unified_report",
        )
        stages["unified_report"] = unified_result
        if unified_result["status"] == "success":
            report_paths = [
                os.path.join(out_dir, "unified_premarket_report.json"),
                os.path.join(out_dir, "unified_premarket_report.html"),
            ]
            for p in report_paths:
                if os.path.exists(p):
                    output_paths[f"unified_{os.path.basename(p)}"] = p
            _log(
                "INFO",
                "unified_report",
                f"统一报告完成 ({unified_result.get('elapsed_seconds', 0)}s)",
            )
        else:
            err = unified_result.get("error", "unknown")
            errors.append(f"unified_report: {err}")
            _log("ERROR", "unified_report", f"统一报告失败: {err}")
    except Exception as e:
        _log("ERROR", "unified_report", str(e))
        errors.append(f"unified_report: {e}")
        stages["unified_report"] = {"status": "failed", "error": str(e)}

    # ── 加载 unified_result 用于消息生成 ──────────────────────────
    unified_result = {}
    unified_json_path = output_paths.get(
        "unified_unified_premarket_report.json", ""
    )
    if unified_json_path and os.path.exists(unified_json_path):
        unified_result = _load_json(unified_json_path)

    # ── f. 生成 notification_message.txt ───────────────────────────
    _log("INFO", "notification", "生成通知消息...")
    try:
        cal_info = stages.get("calendar", {})
        notification_msg = _generate_notification_message(
            unified_result=unified_result,
            calendar=cal_info,
            warnings=warnings,
        )
        notification_path = os.path.join(out_dir, "notification_message.txt")
        with open(notification_path, "w", encoding="utf-8") as f:
            f.write(notification_msg)
        output_paths["notification_message"] = notification_path
        stages["notification"] = {"status": "success"}
        _log("INFO", "notification", "通知消息已写入")
    except Exception as e:
        _log("ERROR", "notification", str(e))
        errors.append(f"notification: {e}")
        stages["notification"] = {"status": "failed", "error": str(e)}

    # ── g. 企业微信推送 ────────────────────────────────────────────
    if not no_notify:
        _log("INFO", "wechat_push", "企业微信推送...")
        try:
            from factor_lab.notify import notify_goal_done

            cal_ok = stages.get("calendar", {}).get("status") in (
                "success",
                "warning",
            )
            signal_ok = (
                stages.get("signal_cli", {}).get("status") == "success"
            )
            report_ok = (
                stages.get("unified_report", {}).get("status") == "success"
            )

            if cal_ok and signal_ok and report_ok:
                notify_status = "completed"
            elif signal_ok or report_ok:
                notify_status = "partial"
            else:
                notify_status = "failed"

            summary_parts = []
            if signal_ok:
                self_t = len(
                    unified_result.get("self_stock_candidates", {}).get(
                        "top5", []
                    )
                )
                summary_parts.append(f"主候选{self_t}只")
            if warnings:
                summary_parts.append(f"⚠{len(warnings)}项警告")
            if errors:
                summary_parts.append(f"❌{len(errors)}项错误")

            summary = (
                " | ".join(summary_parts) if summary_parts else "盘前策略就绪"
            )

            notify_goal_done(
                goal_name=f"盘前策略 {signal_date}",
                summary=summary,
                status=notify_status,
            )
            stages["wechat_push"] = {"status": "success"}
            _log("INFO", "wechat_push", "企业微信推送已完成")
        except Exception as e:
            _log(
                "ERROR",
                "wechat_push",
                f"企业微信推送失败 (不阻塞): {e}",
            )
            stages["wechat_push"] = {
                "status": "failed",
                "error": str(e),
                "non_blocking": True,
            }
    else:
        stages["wechat_push"] = {
            "status": "skipped",
            "reason": "no_notify=True",
        }
        _log("INFO", "wechat_push", "跳过企业微信推送 (no_notify=True)")

    # ── h. 生成 decision_template.md ───────────────────────────────
    _log("INFO", "decision_template", "生成决策模板...")
    try:
        report_path = output_paths.get(
            "unified_unified_premarket_report.html", ""
        )
        decision_md = _generate_decision_template(signal_date, report_path)
        decision_path = os.path.join(out_dir, "decision_template.md")
        with open(decision_path, "w", encoding="utf-8") as f:
            f.write(decision_md)
        output_paths["decision_template"] = decision_path
        stages["decision_template"] = {"status": "success"}
        _log("INFO", "decision_template", "决策模板已生成")
    except Exception as e:
        _log("ERROR", "decision_template", str(e))
        errors.append(f"decision_template: {e}")
        stages["decision_template"] = {
            "status": "failed",
            "error": str(e),
        }

    # ── i. 写入 pipeline_status.json ───────────────────────────────
    pipeline_status = _build_pipeline_status(
        stages=stages,
        warnings=warnings,
        errors=errors,
        output_paths=output_paths,
    )
    pipeline_status["date"] = signal_date
    pipeline_status["capital"] = capital
    pipeline_status["no_notify"] = no_notify
    pipeline_status["output_dir"] = out_dir
    pipeline_status["run_id"] = run_id

    try:
        pipeline_path = os.path.join(out_dir, "pipeline_status.json")
        with open(pipeline_path, "w", encoding="utf-8") as f:
            json.dump(pipeline_status, f, indent=2, ensure_ascii=False)
        output_paths["pipeline_status"] = pipeline_path
        stages["pipeline_status"] = {"status": "success"}
        _log("INFO", "pipeline_status", "pipeline_status.json 已写入")
    except Exception as e:
        _log("ERROR", "pipeline_status", str(e))
        errors.append(f"pipeline_status: {e}")
        stages["pipeline_status"] = {"status": "failed", "error": str(e)}

    # ── j. 写入 audit.log ──────────────────────────────────────────
    try:
        audit_path = os.path.join(out_dir, "audit.log")
        with open(audit_path, "w", encoding="utf-8") as f:
            f.write(
                _build_audit_log(
                    run_id, signal_date, stages, warnings, errors, output_paths
                )
            )
        output_paths["audit_log"] = audit_path
        stages["audit_log"] = {"status": "success"}
        _log("INFO", "audit_log", "audit.log 已写入")
    except Exception as e:
        _log("ERROR", "audit_log", str(e))

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  V1.12 Daily Premarket Runner — 完成")
    print(f"  Run ID: {run_id}")
    print(f"  Signal Date: {signal_date}")
    overall = pipeline_status.get("status", "unknown")
    print(f"  Pipeline Status: {overall}")
    if warnings:
        print(f"  ⚠️ {len(warnings)} warnings")
        for w in warnings:
            print(f"    - {w}")
    if errors:
        print(f"  ❌ {len(errors)} errors")
        for e in errors[:3]:
            print(f"    - {e}")
    print(f"  📁 {out_dir}")
    print(f"{'=' * 60}\n")

    return pipeline_status


# ─── Pipeline Status Builder ────────────────────────────────────────


def _build_pipeline_status(
    stages: dict,
    warnings: list,
    errors: list,
    output_paths: dict,
) -> dict:
    """构建 pipeline_status.json 内容

    每个阶段的 status 取自 stage_status。
    总体 status 规则:
      - 非交易日 → "non_trading_day"
      - signal_cli 或 unified_report 失败 → "failed"
      - 有 warning 或任一阶段非 success → "partial"
      - 全部成功 → "success"

    Returns:
        {
            "run_id": str,
            "date": str,
            "status": "success"|"partial"|"failed"|"non_trading_day",
            "stage_status": {stage_name: status},
            "warnings": [str],
            "errors": [str],
            "output_paths": {name: path},
            "generated_at": str,
        }
    """
    calendar_stage = stages.get("calendar", {})
    is_trading_day = calendar_stage.get("is_trading_day", True)

    stage_status = {}
    for name, data in stages.items():
        stage_status[name] = data.get("status", "unknown")

    critical_stages = ["signal_cli", "unified_report"]
    critical_failures = [
        s for s in critical_stages if stage_status.get(s) == "failed"
    ]

    if not is_trading_day:
        overall_status = "non_trading_day"
    elif critical_failures:
        overall_status = "failed"
    elif warnings or any(
        stage_status.get(s) not in ("success", "skipped") for s in stages
    ):
        overall_status = "partial"
    elif all(
        stage_status.get(s) in ("success", "skipped") for s in stages
    ):
        overall_status = "success"
    else:
        overall_status = "partial"

    return {
        "run_id": "",
        "generated_at": datetime.now(CST).isoformat(),
        "date": "",
        "status": overall_status,
        "stage_status": stage_status,
        "warnings": warnings,
        "errors": errors,
        "output_paths": {k: str(v) for k, v in output_paths.items()},
    }


# ─── Notification Message Generator ─────────────────────────────────


def _generate_notification_message(
    unified_result: dict,
    calendar: dict,
    warnings: list,
) -> str:
    """生成企业微信通知消息文本

    模板:
        【盘前策略信号】YYYY-MM-DD
        状态：xxx
        主账户候选：N只
        Top5：...
        ETF替代：...
        默认资金方案：Plan B 均衡，已分配 XX，剩余 XX
        风险：xxx
        操作：人工确认，不自动下单
    """
    date_str = unified_result.get(
        "signal_date", calendar.get("today", "unknown")
    )
    status = calendar.get("status", "unknown")
    is_trading = calendar.get("is_trading_day", False)

    # 状态文本
    if not is_trading:
        status_text = "非交易日 — 仅供参考"
    elif status in ("success", "warning"):
        status_text = "策略就绪"
    else:
        status_text = "部分异常"

    # 主账户候选
    self_candidates = unified_result.get("self_stock_candidates", {})
    self_total = self_candidates.get("total", 0)
    top5 = self_candidates.get("top5", [])
    top5_text = (
        "、".join([c.get("symbol", "") for c in top5[:5]])
        if top5
        else "无"
    )

    # ETF 替代
    etf_summary = unified_result.get("etf_substitution_summary", {})
    etf_themes = etf_summary.get("themes", [])
    etf_candidates = etf_summary.get("candidates", [])
    etf_text = (
        f"{len(etf_themes)}个主题, {len(etf_candidates)}只候选"
        if etf_themes
        else "无"
    )

    # 资金方案
    plans = unified_result.get("allocation_plans", {})
    plan_b = plans.get("balanced", {})
    plan_b_used = plan_b.get("total_used", 0)
    plan_b_remain = plan_b.get("remaining_cash", 0)
    plan_b_text = (
        f"Plan B 均衡，已分配 {plan_b_used:.0f}，剩余 {plan_b_remain:.0f}"
    )

    # 风险
    risk_parts = []
    if not is_trading:
        risk_parts.append("非交易日")
    if warnings:
        risk_parts.extend(warnings[:3])
    if not risk_parts:
        risk_parts.append("常规风险 — 人工确认后再操作")
    risk_text = "；".join(risk_parts)

    lines = [
        f"【盘前策略信号】{date_str}",
        f"状态：{status_text}",
        f"主账户候选：{self_total}只",
        f"Top5：{top5_text}",
        f"ETF替代：{etf_text}",
        f"默认资金方案：{plan_b_text}",
        f"风险：{risk_text}",
        f"操作：人工确认，不自动下单",
    ]

    return "\n".join(lines) + "\n"


# ─── Decision Template Generator ────────────────────────────────────


def _generate_decision_template(date_str: str, report_path: str) -> str:
    """生成 decision_template.md — 人工确认决策模板"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    return f"""# 盘前决策确认模板

## 基本信息
- **日期**: {date_str}
- **生成时间**: {now}
- **报告路径**: {report_path}

## 决策清单

### 1. 是否执行今日策略？
- [ ] 是 — 确认信号可用
- [ ] 否 — 跳过今日
- [ ] 延后 — 等待更多信息

### 2. 资金方案选择
- [ ] Plan A — 保守 (70%股票+30%ETF)
- [ ] **Plan B — 均衡 (50%股票+50%ETF)** ← 默认
- [ ] Plan C — 进攻 (30%股票+70%ETF)
- [ ] 自定义: ___________

### 3. 主账户候选确认
- [ ] 全部按排名执行
- [ ] 手动筛选: ___________
- [ ] 减少仓位: ___________

### 4. ETF 替代确认
- [ ] 采用推荐 ETF
- [ ] 手动选择: ___________
- [ ] 不采用 ETF

### 5. 风险确认
- [ ] 已阅读风险提示
- [ ] 确认不自动下单
- [ ] 确认人工监控盘面

## 备注
{''}

---
*⚠️ 本模板由 V1.12 Daily Premarket Runner 自动生成*
*不构成投资建议，不自动下单*
"""


# ─── Audit Log Builder ──────────────────────────────────────────────


def _build_audit_log(
    run_id: str,
    signal_date: str,
    stages: dict,
    warnings: list,
    errors: list,
    output_paths: dict,
) -> str:
    """生成 audit.log 内容"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"=== DAILY PREMARKET AUDIT V1.12 ===",
        f"Run ID: {run_id}",
        f"Time: {now}",
        f"Signal Date: {signal_date}",
        "",
        "--- Stages ---",
    ]
    for name, data in stages.items():
        st = data.get("status", "?")
        extra = ""
        if "elapsed_seconds" in data:
            extra = f" ({data['elapsed_seconds']}s)"
        if "error" in data:
            extra += f" | error: {data['error']}"
        lines.append(f"  {name}: {st}{extra}")

    if warnings:
        lines.extend(["", "--- Warnings ---"])
        lines.extend(f"  ⚠ {w}" for w in warnings)

    if errors:
        lines.extend(["", "--- Errors ---"])
        lines.extend(f"  ❌ {e}" for e in errors)

    lines.extend(["", "--- Output Paths ---"])
    for k, v in output_paths.items():
        lines.append(f"  {k}: {v}")

    lines.extend(
        [
            "",
            "No auto-order: True",
            "No borrowed account: True",
            "=== END ===",
        ]
    )
    return "\n".join(lines) + "\n"


# ─── CLI ─────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """命令行参数解析"""
    p = argparse.ArgumentParser(description="V1.12 Daily Premarket Runner")
    p.add_argument(
        "--date",
        default="auto",
        help="信号日期, YYYY-MM-DD 或 auto (默认, 自动取最新交易日)",
    )
    p.add_argument(
        "--capital",
        type=float,
        default=50000,
        help="资金量 (默认 50000)",
    )
    p.add_argument(
        "--no-notify",
        action="store_true",
        help="跳过企业微信推送",
    )
    p.add_argument(
        "--output",
        default=None,
        help="输出目录 (默认 /mnt/d/HermesReports/daily_premarket/{{YYYYMMDD}})",
    )
    return p.parse_args()


def main():
    """CLI 入口"""
    args = parse_args()
    result = run_daily_premarket(
        date=args.date,
        capital=args.capital,
        no_notify=args.no_notify,
        output_dir=args.output,
    )
    return result


if __name__ == "__main__":
    main()
