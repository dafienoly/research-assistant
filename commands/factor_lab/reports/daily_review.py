#!/usr/bin/env python3
"""每日复盘报告生成器

汇总 Paper Trading 模拟交易、Shadow Forward 策略对比、
Risk Sentinel 风控事件、Dry Run 管线状态，输出结构化 JSON 和
暗色主题 HTML 报告。

输入数据源:
  1. Paper Trading    — /mnt/d/HermesData/paper_trading/equity.csv
  2. Shadow Forward   — /mnt/d/HermesReports/shadow_forward/shadow_history.jsonl
  3. Risk Sentinel    — /mnt/d/HermesData/risk_sentinel/state.json
  4. Dry Run          — /mnt/d/HermesReports/dry_run/<yyyymmdd>/dry_run_result.json

输出:
  /mnt/d/HermesReports/daily_review/<yyyymmdd>/daily_review.json
  /mnt/d/HermesReports/daily_review/<yyyymmdd>/daily_review.html

用法:
    # 直接运行（使用当天日期）
    python commands/factor_lab/reports/daily_review.py

    # 指定日期
    python commands/factor_lab/reports/daily_review.py --date 2026-07-08
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 路径引导 ──────────────────────────────────────────────
_HERE = Path(__file__).parent.resolve()          # reports/
_FACTOR_LAB = _HERE.parent.resolve()             # factor_lab/
_COMMANDS = _FACTOR_LAB.parent.resolve()         # commands/
if str(_COMMANDS) not in sys.path:
    sys.path.insert(0, str(_COMMANDS))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
DATA_BASE = Path("/mnt/d/HermesData")


# ═══════════════════════════════════════════════════════════
# 每日复盘报告生成器
# ═══════════════════════════════════════════════════════════

class DailyReviewGenerator:
    """每日复盘报告生成器。

    从四个数据源加载当日快照，生成结构化 JSON 和暗色主题 HTML。
    任何数据源缺失时优雅跳过（graceful skip）。
    """

    def __init__(self, date_str: Optional[str] = None):
        """初始化。

        Args:
            date_str: 日期字符串 YYYY-MM-DD，默认当天 (CST)
        """
        now = datetime.now(CST)
        self.date = date_str or now.strftime("%Y-%m-%d")
        self.ymd = self.date.replace("-", "")
        self.generated_at = now.isoformat()
        self.output_dir = BASE / "daily_review" / self.ymd

    # ── 1. Paper Trading ──────────────────────────────────

    def load_paper_trading(self) -> dict:
        """从 Paper Trading 加载模拟交易数据。

        数据来源:
          - equity.csv: 权益曲线 (date, total_value, daily_return, cash)
          - portfolio.json: 当前持仓快照
          - trades.jsonl: 近期成交记录
        """
        pt_dir = DATA_BASE / "paper_trading"
        result: dict = {"status": "no_data", "note": "Paper trading 未运行"}

        try:
            # 1. 权益曲线
            equity_path = pt_dir / "equity.csv"
            equity = []
            if equity_path.exists():
                import pandas as pd
                df = pd.read_csv(equity_path)
                equity = df.to_dict("records")
                result["equity_curve"] = equity
                result["n_days"] = len(equity)

                if equity:
                    latest = equity[-1]
                    result["latest"] = {
                        "date": str(latest.get("date", "")),
                        "total_value": float(latest.get("total_value", 0)),
                        "daily_return": float(latest.get("daily_return", 0)),
                        "cash": float(latest.get("cash", 0)),
                    }
                    # 计算累计收益率
                    initial = float(equity[0].get("total_value", 100000))
                    current = float(latest.get("total_value", initial))
                    result["total_return_pct"] = round(
                        (current - initial) / initial * 100, 4
                    ) if initial > 0 else 0.0
            else:
                result["equity_curve"] = []

            # 2. 持仓快照
            portfolio_path = pt_dir / "portfolio.json"
            if portfolio_path.exists():
                with open(portfolio_path) as f:
                    result["portfolio"] = json.load(f)
            else:
                result["portfolio"] = {}

            # 3. 今日成交
            trades_path = pt_dir / "trades.jsonl"
            today_trades = []
            if trades_path.exists():
                with open(trades_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        trade = json.loads(line)
                        if trade.get("date", "").startswith(self.date):
                            today_trades.append(trade)
            result["today_trades"] = today_trades
            result["n_trades_today"] = len(today_trades)

            # 状态汇总
            if equity:
                result["status"] = "ok"
                result["note"] = (
                    f"{result['n_days']} 个交易日, "
                    f"今日 {result['n_trades_today']} 笔成交, "
                    f"累计收益 {result.get('total_return_pct', 0):.2f}%"
                )
            elif portfolio_path.exists():
                result["status"] = "partial"
                result["note"] = "有持仓数据但无权益曲线"
            else:
                result["status"] = "no_data"
                result["note"] = "Paper trading 未运行或无数据文件"

        except Exception as e:
            result = {
                "status": "error",
                "note": f"加载 Paper trading 失败: {type(e).__name__}: {e}",
            }

        return result

    # ── 2. Shadow Forward ─────────────────────────────────

    def load_shadow_forward(self) -> dict:
        """从 Shadow Forward 加载策略对比数据。

        查找当天 shadow_history.jsonl 中的最新条目，以及
        /mnt/d/HermesReports/shadow_forward/ 下最新的比较结果。
        """
        result: dict = {"status": "no_data", "note": "Shadow forward 未运行"}

        try:
            # 查找最新 shadow_forward 输出目录
            sf_dir = Path(str(BASE / "shadow_forward"))
            comparisons = []
            risk_events = []
            decision_logs = []

            if sf_dir.exists():
                # 查找当天输出目录（按 run_id 组织）
                today_runs = sorted([
                    d for d in sf_dir.iterdir()
                    if d.is_dir() and self.ymd in d.name
                ])
                runs = today_runs or sorted(sf_dir.iterdir())[-1:] if sf_dir.exists() else []

                for run_dir in runs if isinstance(runs, list) else [runs] if isinstance(runs, Path) else []:
                    json_path = run_dir / "shadow_forward.json"
                    if json_path.exists():
                        with open(json_path) as f:
                            sf_data = json.load(f)
                        comparisons = sf_data.get("comparisons", []) or comparisons
                        risk_events = sf_data.get("risk_events", []) or risk_events
                        decision_logs = sf_data.get("decision_logs", []) or decision_logs
                    # 补充：shadow_history.jsonl
                    history_path = run_dir / "shadow_history.jsonl"
                    if history_path.exists():
                        with open(history_path) as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                entry = json.loads(line)
                                if entry.get("date", "").startswith(self.date):
                                    comparisons = entry.get("comparisons", comparisons)
                                    risk_events = entry.get("risk_events", risk_events)

            # 备用：读取 history 聚合文件
            history_path = sf_dir / "shadow_history.jsonl"
            if history_path.exists() and not comparisons:
                with open(history_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        if entry.get("date", "").startswith(self.date):
                            comparisons = entry.get("comparisons", comparisons)
                            risk_events = entry.get("risk_events", risk_events)
                            decision_logs = entry.get("decision_logs", decision_logs)
                            break  # 取到当天第一条即止

            result["comparisons"] = comparisons
            result["risk_events"] = risk_events
            result["decision_logs"] = decision_logs
            result["n_candidates"] = len(comparisons)
            result["n_risk_events"] = len(risk_events)

            if comparisons:
                # 统计胜负
                wins = sum(
                    1 for c in comparisons
                    if c.get("shadow_return_pct", 0) > c.get("baseline_return_pct", 0)
                )
                result["n_wins"] = wins
                result["n_losses"] = len(comparisons) - wins
                result["verdicts"] = {}
                for c in comparisons:
                    v = c.get("verdict", "unknown")
                    result["verdicts"][v] = result["verdicts"].get(v, 0) + 1

                best = max(comparisons, key=lambda c: c.get("shadow_return_pct", 0))
                result["best_candidate"] = {
                    "name": best.get("candidate", "?"),
                    "shadow_return": best.get("shadow_return_pct", 0),
                    "baseline_return": best.get("baseline_return_pct", 0),
                }

                result["status"] = "ok"
                result["note"] = (
                    f"{len(comparisons)} 候选对比, "
                    f"{result['n_wins']}胜{result['n_losses']}负, "
                    f"{result['n_risk_events']} 风控事件"
                )
            else:
                result["status"] = "no_data"
                result["note"] = "Shadow forward 无当天对比数据"

        except Exception as e:
            result = {
                "status": "error",
                "note": f"加载 Shadow forward 失败: {type(e).__name__}: {e}",
            }

        return result

    # ── 3. Risk Sentinel ──────────────────────────────────

    def load_risk_sentinel(self) -> dict:
        """从 Risk Sentinel 加载风控事件数据。

        数据来源: /mnt/d/HermesData/risk_sentinel/state.json
        """
        result: dict = {"status": "no_data", "note": "Risk sentinel 未运行"}

        try:
            state_path = DATA_BASE / "risk_sentinel" / "state.json"
            if state_path.exists():
                with open(state_path) as f:
                    state = json.load(f)

                result["state"] = state
                result["overall_status"] = state.get("overall_status", "unknown")
                result["kill_switch_state"] = state.get("kill_switch_state", "armed")
                result["kill_switch_triggered"] = state.get("kill_switch_triggered", False)
                result["n_rules_checked"] = state.get("n_rules_checked", 0)
                result["n_violations"] = state.get("n_violations", 0)
                result["n_blockers"] = state.get("n_blockers", 0)
                result["n_open_incidents"] = state.get("n_open_incidents", 0)
                result["dimensions"] = state.get("dimensions", {})

                # 提取各维度详情
                dim_details = {}
                for dim, info in state.get("dimensions", {}).items():
                    dim_details[dim] = {
                        "status": info.get("status", "unknown"),
                        "violations": info.get("violations", 0),
                    }
                result["dimension_details"] = dim_details

                # 数据新鲜度
                freshness = state.get("data_freshness", {})
                result["data_freshness"] = {
                    "healthy_sources": freshness.get("healthy", 0),
                    "unhealthy_sources": freshness.get("unhealthy", 0),
                    "total_sources": freshness.get("total_sources", 0),
                    "healthy_pct": (
                        round(freshness.get("healthy", 0) / max(freshness.get("total_sources", 1), 1) * 100, 1)
                    ),
                }

                # 异常检测
                result["anomaly"] = state.get("anomaly", {})

                result["status"] = "ok"
                result["note"] = (
                    f"整体 {result['overall_status']}, "
                    f"{result['n_violations']} 违规, "
                    f"{result['n_blockers']} 阻断, "
                    f"KS={result['kill_switch_state']}"
                )
            else:
                result["note"] = "无 state.json 文件（风险监控未启动）"

        except Exception as e:
            result = {
                "status": "error",
                "note": f"加载 Risk sentinel 失败: {type(e).__name__}: {e}",
            }

        return result

    # ── 4. Dry Run ────────────────────────────────────────

    def load_dry_run(self) -> dict:
        """从 Dry Run 加载管线状态快照。

        数据来源: /mnt/d/HermesReports/dry_run/<yyyymmdd>/dry_run_result.json
        """
        result: dict = {"status": "no_data", "note": "Dry run 未运行"}

        try:
            # 查找当天 dry run 结果
            result_path = BASE / "dry_run" / self.ymd / "dry_run_result.json"
            if result_path.exists():
                with open(result_path) as f:
                    dry_run = json.load(f)

                gates = dry_run.get("gates", {})
                gate_summaries = {}

                # 解析每个 Gate
                gate_map = {
                    "gate1_signal": "Gate1 信号生成",
                    "gate2_etf": "Gate2 ETF替代",
                    "gate3_unified": "Gate3 统一报告",
                    "gate4_rebalance": "Gate4 调仓差异",
                    "gate5_order": "Gate5 委托预览",
                    "gate6_risk": "Gate6 风控审批",
                }

                total_gates = len(gates)
                passed_gates = 0
                failed_gates = 0
                skipped_gates = 0

                for gate_key, gate_info in gates.items():
                    gate_data = gate_info if isinstance(gate_info, dict) else {}
                    verdict = gate_data.get("verdict", "skip")
                    gate_name = gate_map.get(gate_key, gate_key)

                    if verdict == "pass":
                        passed_gates += 1
                    elif verdict in ("skip",):
                        skipped_gates += 1
                    else:
                        failed_gates += 1

                    # 提取 check 详情
                    checks = gate_data.get("checks", [])
                    n_passed = sum(1 for c in checks if c.get("passed"))
                    n_total = len(checks)

                    gate_summaries[gate_key] = {
                        "name": gate_name,
                        "verdict": verdict,
                        "duration": gate_data.get("duration_seconds", 0),
                        "checks_passed": n_passed,
                        "checks_total": n_total,
                        "error": gate_data.get("error", ""),
                    }

                result["status"] = dry_run.get("status", "unknown")
                result["signal_date"] = dry_run.get("signal_date", "")
                result["with_risk"] = dry_run.get("with_risk", False)
                result["gates"] = gate_summaries
                result["total_gates"] = total_gates
                result["passed_gates"] = passed_gates
                result["failed_gates"] = failed_gates
                result["skipped_gates"] = skipped_gates

                pipeline_ok = passed_gates == total_gates
                result["pipeline_healthy"] = pipeline_ok
                result["note"] = (
                    f"管线{'✅ 全部通过' if pipeline_ok else f'⚠️ {passed_gates}/{total_gates} 通过'}, "
                    f"信号日期 {dry_run.get('signal_date', '?')}"
                )

            else:
                # 尝试查找最近一次 dry run
                parent = BASE / "dry_run"
                if parent.exists():
                    runs = sorted(parent.iterdir(), reverse=True)
                    if runs:
                        result["note"] = f"无 {self.ymd} Dry run 结果，最近一次: {runs[0].name}"
                    else:
                        result["note"] = "Dry run 目录存在但无运行结果"

        except Exception as e:
            result = {
                "status": "error",
                "note": f"加载 Dry run 失败: {type(e).__name__}: {e}",
            }

        return result

    # ── 汇总与输出 ────────────────────────────────────────

    def _build_summary(self, sections: dict) -> dict:
        """构建报告摘要 / 仪表板关键指标。

        Args:
            sections: 各数据源加载结果

        Returns:
            摘要字典（用于 JSON 和 HTML 的 overview）
        """
        summary = {}

        # ── 模拟交易摘要 ──
        pt = sections.get("paper_trading", {})
        if pt.get("status") == "ok" and pt.get("latest"):
            latest = pt["latest"]
            summary["daily_return"] = latest.get("daily_return", 0)
            summary["total_value"] = latest.get("total_value", 0)
            summary["cash"] = latest.get("cash", 0)
            summary["total_return_pct"] = pt.get("total_return_pct", 0)
            summary["n_trades_today"] = pt.get("n_trades_today", 0)
            summary["n_holdings"] = len(pt.get("portfolio", {}).get("holdings", {}))

        # ── Shadow forward 摘要 ──
        sf = sections.get("shadow_forward", {})
        if sf.get("status") == "ok":
            summary["sf_n_candidates"] = sf.get("n_candidates", 0)
            summary["sf_wins"] = sf.get("n_wins", 0)
            summary["sf_losses"] = sf.get("n_losses", 0)
            summary["sf_n_risk_events"] = sf.get("n_risk_events", 0)

        # ── 风控摘要 ──
        rs = sections.get("risk_sentinel", {})
        if rs.get("status") == "ok":
            summary["risk_status"] = rs.get("overall_status", "unknown")
            summary["n_violations"] = rs.get("n_violations", 0)
            summary["n_blockers"] = rs.get("n_blockers", 0)
            summary["kill_switch"] = rs.get("kill_switch_state", "armed")

        # ── 管线摘要 ──
        dr = sections.get("dry_run", {})
        if dr.get("status") != "no_data":
            summary["pipeline_status"] = dr.get("status", "unknown")
            summary["pipeline_healthy"] = dr.get("pipeline_healthy", False)
            summary["passed_gates"] = dr.get("passed_gates", 0)
            summary["total_gates"] = dr.get("total_gates", 0)

        return summary

    def generate(self) -> dict:
        """生成完整的每日复盘报告。

        Returns:
            dict: 完整的报告数据结构
        """
        sections = {
            "paper_trading": self.load_paper_trading(),
            "shadow_forward": self.load_shadow_forward(),
            "risk_sentinel": self.load_risk_sentinel(),
            "dry_run": self.load_dry_run(),
        }

        review = {
            "date": self.date,
            "ymd": self.ymd,
            "generated_at": self.generated_at,
            "sections": sections,
            "summary": self._build_summary(sections),
        }

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 输出 JSON
        json_path = self.output_dir / "daily_review.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(review, f, indent=2, ensure_ascii=False, default=str)

        # 输出 HTML
        html_path = self.output_dir / "daily_review.html"
        html_content = self._generate_html(review)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return review

    # ═══════════════════════════════════════════════════════
    # HTML 报告渲染
    # ═══════════════════════════════════════════════════════

    def _generate_html(self, review: dict) -> str:
        """生成暗色主题 HTML 报告。

        Args:
            review: 完整报告数据

        Returns:
            HTML 字符串
        """
        sections = review.get("sections", {})
        summary = review.get("summary", {})

        # ── 各章节 HTML 片段 ──
        pt_html = self._html_paper_trading(sections.get("paper_trading", {}))
        sf_html = self._html_shadow_forward(sections.get("shadow_forward", {}))
        rs_html = self._html_risk_sentinel(sections.get("risk_sentinel", {}))
        dr_html = self._html_dry_run(sections.get("dry_run", {}))

        # ── 全局概览条 ──
        overview_items = []

        # 模拟交易
        if "daily_return" in summary:
            dr = summary["daily_return"]
            cls = "pos" if dr > 0 else ("neg" if dr < 0 else "")
            sign = "+" if dr > 0 else ""
            overview_items.append(
                f'<div class="overview-item"><span class="overview-label">日收益率</span>'
                f'<span class="overview-value {cls}">{sign}{dr*100:.2f}%</span></div>'
            )
        if "total_return_pct" in summary:
            tr = summary["total_return_pct"]
            cls = "pos" if tr > 0 else ("neg" if tr < 0 else "")
            sign = "+" if tr > 0 else ""
            overview_items.append(
                f'<div class="overview-item"><span class="overview-label">累计收益</span>'
                f'<span class="overview-value {cls}">{sign}{tr:.2f}%</span></div>'
            )

        # 风控
        risk_status = summary.get("risk_status", "no_data")
        risk_icon = {"healthy": "🟢", "degraded": "🟡", "critical": "🔴", "blocked": "🛑"}.get(
            risk_status, "⚪"
        )
        overview_items.append(
            f'<div class="overview-item"><span class="overview-label">风控</span>'
            f'<span class="overview-value">{risk_icon} {risk_status}</span></div>'
        )

        # Kill Switch
        ks = summary.get("kill_switch", "armed")
        ks_icon = "🔴" if ks == "triggered" else "🟢"
        overview_items.append(
            f'<div class="overview-item"><span class="overview-label">Kill Switch</span>'
            f'<span class="overview-value">{ks_icon} {ks}</span></div>'
        )

        # 管线
        pipeline_ok = summary.get("pipeline_healthy", False)
        pipeline_icon = "✅" if pipeline_ok else "⚠️"
        overview_items.append(
            f'<div class="overview-item"><span class="overview-label">Dry Run</span>'
            f'<span class="overview-value">{pipeline_icon} '
            f'{summary.get("passed_gates", 0)}/{summary.get("total_gates", 0)}</span></div>'
        )

        # Shadow Forward
        if "sf_n_candidates" in summary:
            overview_items.append(
                f'<div class="overview-item"><span class="overview-label">Shadow Fwd</span>'
                f'<span class="overview-value">{summary["sf_wins"]}胜{summary["sf_losses"]}负</span></div>'
            )

        overview_html = "".join(overview_items) if overview_items else "<p>暂无数据</p>"

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日复盘 {self.date}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: -apple-system, "Segoe UI", "Noto Sans SC", "PingFang SC",
               "Microsoft YaHei", sans-serif;
  background: #0f0f23;
  color: #e0e0e0;
  padding: 20px;
  min-height: 100vh;
}}
h1 {{ color: #00e5ff; font-size: 1.6em; margin-bottom: 4px; }}
h2 {{ color: #00bcd4; font-size: 1.2em; margin-bottom: 10px;
      border-bottom: 1px solid #333; padding-bottom: 6px; }}
h3 {{ color: #80deea; font-size: 1em; margin-bottom: 6px; }}

/* ── 卡片 ── */
.card {{
  background: #16213e;
  border-radius: 10px;
  padding: 20px;
  margin: 10px 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}

/* ── 头部 ── */
.header {{
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px;
}}
.header-meta {{ color: #888; font-size: 0.85em; }}

/* ── 概览条 ── */
.overview-bar {{
  display: flex; flex-wrap: wrap; gap: 12px;
  background: #1a1a2e;
  border-radius: 8px;
  padding: 14px 18px;
  margin: 10px 0;
}}
.overview-item {{
  display: flex; flex-direction: column; align-items: center;
  min-width: 70px; padding: 4px 10px;
}}
.overview-label {{
  font-size: 0.7em; color: #888; text-transform: uppercase;
  margin-bottom: 2px;
}}
.overview-value {{
  font-size: 1.1em; font-weight: 600;
}}

/* ── 表格 ── */
table {{ width:100%; border-collapse:collapse; font-size:0.88em; }}
th,td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #2a2a4a; }}
th {{ color:#888; font-weight:500; }}
tr:hover {{ background:#1a2a4a; }}

/* ── 颜色 ── */
.pos {{ color:#4caf50; }}
.neg {{ color:#f44336; }}
.neutral {{ color:#ffa726; }}
.ok {{ color:#4caf50; }}
.warn {{ color:#ffa726; }}
.fail {{ color:#f44336; }}
.skip {{ color:#666; }}
.info {{ color:#42a5f5; }}

/* ── 徽章 ── */
.badge {{
  display:inline-block; padding:2px 8px; border-radius:4px;
  font-size:0.78em; font-weight:500;
}}
.badge-healthy {{ background:#1b5e20; color:#a5d6a7; }}
.badge-degraded {{ background:#e65100; color:#ffcc80; }}
.badge-critical {{ background:#b71c1c; color:#ef9a9a; }}
.badge-blocked {{ background:#880e0e; color:#ffcdd2; }}
.badge-pass {{ background:#1b5e20; color:#a5d6a7; }}
.badge-fail {{ background:#b71c1c; color:#ef9a9a; }}
.badge-skip {{ background:#37474f; color:#90a4ae; }}
.badge-passed {{ background:#1b5e20; color:#a5d6a7; }}
.badge-conditional_pass {{ background:#e65100; color:#ffcc80; }}

/* ── 状态指示器 ── */
.dot {{
  display:inline-block; width:10px; height:10px;
  border-radius:50%; margin-right:6px;
}}
.dot-healthy {{ background:#4caf50; }}
.dot-degraded {{ background:#ffa726; }}
.dot-critical {{ background:#f44336; }}
.dot-blocked {{ background:#b71c1c; }}

/* ── 网格 ── */
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
@media(max-width:768px){{ .grid-2 {{ grid-template-columns:1fr; }} }}

/* ── 进度条 ── */
.progress-bar {{
  background:#2a2a4a; border-radius:6px; height:8px;
  margin:6px 0; overflow:hidden;
}}
.progress-fill {{
  height:100%; border-radius:6px; transition:width 0.5s;
}}
.progress-healthy {{ background:#4caf50; }}
.progress-degraded {{ background:#ffa726; }}

/* ── 无数据 ── */
.no-data {{
  text-align:center; color:#666; padding:20px;
  font-size:0.9em;
}}

/* ── 页脚 ── */
.footer {{
  text-align:center; color:#444; font-size:0.75em;
  margin-top:20px; padding:10px;
}}
</style>
</head>
<body>

<!-- ════ 头部 ════ -->
<div class="card">
  <div class="header">
    <div>
      <h1>📊 每日复盘报告</h1>
      <p style="color:#888;font-size:0.9em;">{self.date} {self.generated_at.split('T')[1][:8] if 'T' in self.generated_at else ''}</p>
    </div>
    <div class="header-meta">
      生成于 {self.generated_at}
    </div>
  </div>
</div>

<!-- ════ 概览条 ════ -->
<div class="overview-bar">
  {overview_html}
</div>

<!-- ════ 各章节 ════ -->
<div class="grid-2">
  {pt_html}
  {sf_html}
</div>
<div class="grid-2">
  {rs_html}
  {dr_html}
</div>

<div class="footer">
  Hermes Factor Lab · Daily Review · {self.date}
</div>

</body>
</html>"""
        return html

    # ── HTML: Paper Trading ───────────────────────────────

    def _html_paper_trading(self, data: dict) -> str:
        """渲染模拟交易卡片 HTML。"""
        status = data.get("status", "no_data")

        if status == "no_data":
            return (
                '<div class="card"><h2>📈 模拟交易</h2>'
                '<div class="no-data">Paper trading 未运行或暂无数据</div></div>'
            )
        if status == "error":
            return (
                '<div class="card"><h2>📈 模拟交易</h2>'
                f'<div class="no-data" style="color:#f44336;">{data.get("note", "未知错误")}</div></div>'
            )

        parts = []

        # 状态标签
        latest = data.get("latest", {})
        if latest:
            dr = latest.get("daily_return", 0)
            tv = latest.get("total_value", 0)
            tr = data.get("total_return_pct", 0)
            cls_dr = "pos" if dr > 0 else ("neg" if dr < 0 else "")
            cls_tr = "pos" if tr > 0 else ("neg" if tr < 0 else "")
            sign_dr = "+" if dr > 0 else ""
            sign_tr = "+" if tr > 0 else ""
            parts.append(
                f'<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:12px;">'
                f'<div><span style="color:#888;font-size:0.78em;">总资产</span><br>'
                f'<span style="font-size:1.4em;font-weight:600;">¥{tv:,.0f}</span></div>'
                f'<div><span style="color:#888;font-size:0.78em;">日收益率</span><br>'
                f'<span class="{cls_dr}" style="font-size:1.4em;font-weight:600;">'
                f'{sign_dr}{dr*100:.2f}%</span></div>'
                f'<div><span style="color:#888;font-size:0.78em;">累计收益</span><br>'
                f'<span class="{cls_tr}" style="font-size:1.4em;font-weight:600;">'
                f'{sign_tr}{tr:.2f}%</span></div>'
                f'<div><span style="color:#888;font-size:0.78em;">现金</span><br>'
                f'<span style="font-size:1.4em;font-weight:600;">¥{latest.get("cash", 0):,.0f}</span></div>'
                '</div>'
            )

        # 今日成交
        trades = data.get("today_trades", [])
        if trades:
            rows = ""
            for t in trades[:20]:
                side_cls = "pos" if t.get("side") == "buy" else "neg"
                rows += (
                    f'<tr><td>{t.get("symbol","")}</td>'
                    f'<td class="{side_cls}">{t.get("side","")}</td>'
                    f'<td>{t.get("shares",0)}</td>'
                    f'<td>{t.get("price",0):.2f}</td>'
                    f'<td>{t.get("amount",0):.0f}</td>'
                    f'</tr>'
                )
            parts.append(
                f'<h3>今日成交 ({len(trades)} 笔)</h3>'
                f'<table><tr><th>代码</th><th>方向</th><th>数量</th><th>价格</th><th>金额</th></tr>'
                f'{rows}</table>'
            )
        else:
            parts.append('<p style="color:#666;">今日无成交</p>')

        # 持仓概览
        portfolio = data.get("portfolio", {})
        holdings = portfolio.get("holdings", {})
        if holdings:
            hrows = ""
            for sym, h in sorted(holdings.items()):
                hrows += (
                    f'<tr><td>{sym}</td>'
                    f'<td>{h.get("shares",0)}</td>'
                    f'<td>{h.get("avg_cost",0):.2f}</td>'
                    f'<td>{h.get("last_price",0):.2f}</td>'
                    f'</tr>'
                )
            parts.append(
                f'<h3>持仓 ({len(holdings)} 只)</h3>'
                f'<table><tr><th>代码</th><th>持仓</th><th>成本</th><th>最新价</th></tr>'
                f'{hrows}</table>'
            )
        else:
            parts.append('<p style="color:#666;">空仓</p>')

        # 权益曲线迷你摘要
        equity = data.get("equity_curve", [])
        if len(equity) >= 2:
            first_val = float(equity[0].get("total_value", 0))
            last_val = float(equity[-1].get("total_value", 0))
            if first_val > 0:
                total_ret = (last_val - first_val) / first_val * 100
                cls = "pos" if total_ret > 0 else ("neg" if total_ret < 0 else "")
                parts.append(
                    f'<p style="color:#666;font-size:0.8em;">'
                    f'权益曲线: {data.get("n_days", 0)} 个交易日, '
                    f'总收益 <span class="{cls}">{"+" if total_ret>0 else ""}{total_ret:.2f}%</span></p>'
                )

        body = "".join(parts)
        return f'<div class="card"><h2>📈 模拟交易</h2>{body}</div>'

    # ── HTML: Shadow Forward ──────────────────────────────

    def _html_shadow_forward(self, data: dict) -> str:
        """渲染 Shadow Forward 对比卡片 HTML。"""
        status = data.get("status", "no_data")

        if status == "no_data":
            return (
                '<div class="card"><h2>🔍 Shadow Forward</h2>'
                '<div class="no-data">Shadow forward 无当天对比数据</div></div>'
            )
        if status == "error":
            return (
                '<div class="card"><h2>🔍 Shadow Forward</h2>'
                f'<div class="no-data" style="color:#f44336;">{data.get("note", "未知错误")}</div></div>'
            )

        parts = []

        # 统计概览
        n_candidates = data.get("n_candidates", 0)
        n_wins = data.get("n_wins", 0)
        n_losses = data.get("n_losses", 0)
        win_rate = round(n_wins / max(n_candidates, 1) * 100, 1)
        parts.append(
            f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px;">'
            f'<div><span style="color:#888;font-size:0.78em;">候选数</span><br>'
            f'<span style="font-size:1.3em;">{n_candidates}</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">胜/负</span><br>'
            f'<span style="font-size:1.3em;"><span class="pos">{n_wins}</span>'
            f'/<span class="neg">{n_losses}</span></span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">胜率</span><br>'
            f'<span style="font-size:1.3em;">{win_rate}%</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">风控事件</span><br>'
            f'<span style="font-size:1.3em;">{data.get("n_risk_events", 0)}</span></div>'
            '</div>'
        )

        # 判决分布
        verdicts = data.get("verdicts", {})
        if verdicts:
            vrows = ""
            for v, cnt in sorted(verdicts.items()):
                vlabel = {
                    "promote_candidate_watch": "👀 关注",
                    "no_material_improvement": "➖ 无改善",
                    "insufficient_forward_evidence": "⏳ 证据不足",
                }.get(v, v)
                vrows += f"<tr><td>{vlabel}</td><td>{cnt}</td></tr>"
            parts.append(
                f'<h3>判决分布</h3><table><tr><th>判决</th><th>数量</th></tr>{vrows}</table>'
            )

        # 最佳候选
        best = data.get("best_candidate", {})
        if best:
            parts.append(
                f'<h3>🏆 最佳候选</h3>'
                f'<p>{best.get("name","")} — '
                f'Shadow 收益: <span class="pos">+{best.get("shadow_return",0):.2f}%</span> vs '
                f'Baseline: {best.get("baseline_return",0):.2f}%</p>'
            )

        # 对比表格
        comparisons = data.get("comparisons", [])
        if comparisons:
            rows = ""
            for c in comparisons[:10]:
                bl = c.get("baseline_return_pct", 0)
                sh = c.get("shadow_return_pct", 0)
                diff = sh - bl
                diff_cls = "pos" if diff > 0 else ("neg" if diff < 0 else "")
                sign = "+" if diff > 0 else ""
                icon = {
                    "promote_candidate_watch": "👀",
                    "no_material_improvement": "➖",
                    "insufficient_forward_evidence": "⏳",
                }.get(c.get("verdict", ""), "❓")
                rows += (
                    f'<tr><td>{icon}</td>'
                    f'<td>{c.get("candidate","")}</td>'
                    f'<td>{bl:.2f}%</td>'
                    f'<td class="{"pos" if sh>bl else ("neg" if sh<bl else "")}">{sh:.2f}%</td>'
                    f'<td class="{diff_cls}">{sign}{diff:.2f}%</td>'
                    f'<td>{c.get("verdict","")[:20]}</td></tr>'
                )
            parts.append(
                f'<h3>Baseline vs Shadow</h3>'
                f'<table><tr><th></th><th>候选</th><th>BL 收益</th><th>SH 收益</th>'
                f'<th>差值</th><th>判决</th></tr>{rows}</table>'
            )
            if len(comparisons) > 10:
                parts.append(
                    f'<p style="color:#666;font-size:0.8em;">仅显示前 10 条，共 {len(comparisons)} 条</p>'
                )

        body = "".join(parts)
        return f'<div class="card"><h2>🔍 Shadow Forward</h2>{body}</div>'

    # ── HTML: Risk Sentinel ───────────────────────────────

    def _html_risk_sentinel(self, data: dict) -> str:
        """渲染风控事件卡片 HTML。"""
        status = data.get("status", "no_data")

        if status == "no_data":
            return (
                '<div class="card"><h2>🛡️ 风控事件</h2>'
                '<div class="no-data">风险监控未启动或暂无数据</div></div>'
            )
        if status == "error":
            return (
                '<div class="card"><h2>🛡️ 风控事件</h2>'
                f'<div class="no-data" style="color:#f44336;">{data.get("note", "未知错误")}</div></div>'
            )

        parts = []

        # 整体状态
        overall = data.get("overall_status", "unknown")
        ks_state = data.get("kill_switch_state", "armed")
        ks_triggered = data.get("kill_switch_triggered", False)

        badge_cls = f"badge-{overall}"
        dot_cls = f"dot-{overall}"

        parts.append(
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
            f'<span class="{dot_cls}"></span>'
            f'<span class="badge {badge_cls}">{overall.upper()}</span>'
            f'<span style="color:#888;">Kill Switch: '
            f'<span style="color:{"#f44336" if ks_triggered else "#4caf50"};font-weight:600;">'
            f'{ks_state}</span></span>'
            f'</div>'
        )

        # 关键指标
        parts.append(
            f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px;">'
            f'<div><span style="color:#888;font-size:0.78em;">规则检查</span><br>'
            f'<span style="font-size:1.3em;">{data.get("n_rules_checked", 0)}</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">违规</span><br>'
            f'<span style="font-size:1.3em;" class="{"warn" if data.get("n_violations",0)>0 else ""}">'
            f'{data.get("n_violations", 0)}</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">阻断</span><br>'
            f'<span style="font-size:1.3em;" class="{"fail" if data.get("n_blockers",0)>0 else ""}">'
            f'{data.get("n_blockers", 0)}</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">未结事件</span><br>'
            f'<span style="font-size:1.3em;">{data.get("n_open_incidents", 0)}</span></div>'
            '</div>'
        )

        # 各维度状态
        dims = data.get("dimension_details", {})
        if dims:
            dim_rows = ""
            dim_order = ["data", "account", "execution", "loss", "system"]
            dim_labels = {
                "data": "📊 数据", "account": "🏦 账户",
                "execution": "⚡ 执行", "loss": "📉 亏损",
                "system": "🔧 系统",
            }
            for d in dim_order:
                info = dims.get(d, {})
                ds = info.get("status", "unknown")
                dv = info.get("violations", 0)
                d_dot = f"dot-{ds}" if ds in ("healthy", "degraded", "critical", "blocked") else "dot-healthy"
                dim_rows += (
                    f'<tr><td>{dim_labels.get(d, d)}</td>'
                    f'<td><span class="{d_dot}" style="display:inline-block;'
                    f'width:8px;height:8px;border-radius:50%;margin-right:4px;"></span>{ds}</td>'
                    f'<td>{dv}</td></tr>'
                )
            parts.append(
                f'<h3>维度状态</h3><table><tr><th>维度</th><th>状态</th><th>违规数</th></tr>{dim_rows}</table>'
            )

        # 数据新鲜度
        freshness = data.get("data_freshness", {})
        if freshness.get("total_sources", 0) > 0:
            healthy = freshness.get("healthy_sources", 0)
            total = freshness.get("total_sources", 1)
            pct = freshness.get("healthy_pct", 0)
            fcls = "progress-healthy" if healthy == total else "progress-degraded"
            parts.append(
                f'<h3>数据新鲜度</h3>'
                f'<div style="display:flex;justify-content:space-between;font-size:0.85em;">'
                f'<span>{healthy}/{total} 数据源健康</span>'
                f'<span>{pct}%</span></div>'
                f'<div class="progress-bar"><div class="progress-fill {fcls}" '
                f'style="width:{pct}%;"></div></div>'
            )

        body = "".join(parts)
        return f'<div class="card"><h2>🛡️ 风控事件</h2>{body}</div>'

    # ── HTML: Dry Run ─────────────────────────────────────

    def _html_dry_run(self, data: dict) -> str:
        """渲染 Dry Run 管线状态卡片 HTML。"""
        status = data.get("status", "no_data")

        if status == "no_data":
            return (
                '<div class="card"><h2>🔧 Dry Run 管线</h2>'
                f'<div class="no-data">{data.get("note", "Dry run 未运行")}</div></div>'
            )
        if status == "error":
            return (
                '<div class="card"><h2>🔧 Dry Run 管线</h2>'
                f'<div class="no-data" style="color:#f44336;">{data.get("note", "未知错误")}</div></div>'
            )

        parts = []

        # 管线概览
        pipeline_ok = data.get("pipeline_healthy", False)
        passed = data.get("passed_gates", 0)
        total = data.get("total_gates", 0)
        failed = data.get("failed_gates", 0)
        skipped = data.get("skipped_gates", 0)

        parts.append(
            f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
            f'<span style="font-size:1.5em;">{"✅" if pipeline_ok else "⚠️"}</span>'
            f'<div><span style="font-size:1.1em;font-weight:600;">'
            f'{"全部通过 ✓" if pipeline_ok else f"{passed}/{total} 通过"}</span>'
            f'<br><span style="color:#888;font-size:0.85em;">'
            f'信号日期: {data.get("signal_date", "?")}'
            f'{" · 含风控" if data.get("with_risk") else " · 不含风控"}</span></div>'
            '</div>'
        )

        # 通过/失败计数
        parts.append(
            f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px;">'
            f'<div><span style="color:#888;font-size:0.78em;">通过</span><br>'
            f'<span class="ok" style="font-size:1.3em;">{passed}</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">失败</span><br>'
            f'<span style="font-size:1.3em;" class="{"fail" if failed>0 else ""}">{failed}</span></div>'
            f'<div><span style="color:#888;font-size:0.78em;">跳过</span><br>'
            f'<span style="font-size:1.3em;color:#666;">{skipped}</span></div>'
            '</div>'
        )

        # 进度条
        pct = round(passed / max(total, 1) * 100, 0)
        pcls = "progress-healthy" if pipeline_ok else "progress-degraded"
        parts.append(
            f'<div class="progress-bar"><div class="progress-fill {pcls}" '
            f'style="width:{pct}%;"></div></div>'
        )

        # Gate 详情
        gates = data.get("gates", {})
        if gates:
            gate_order = [
                "gate1_signal", "gate2_etf", "gate3_unified",
                "gate4_rebalance", "gate5_order", "gate6_risk",
            ]
            rows = ""
            for gk in gate_order:
                g = gates.get(gk)
                if not g:
                    continue
                verdict = g.get("verdict", "skip")
                vbadge = f'badge-{verdict}' if verdict in (
                    "pass", "fail", "skip", "conditional_pass"
                ) else "badge-skip"
                vlabel = {
                    "pass": "✅ 通过", "fail": "❌ 失败",
                    "skip": "⏭️ 跳过", "conditional_pass": "⚠️ 条件通过",
                }.get(verdict, verdict)
                check_info = f'{g.get("checks_passed", 0)}/{g.get("checks_total", 0)}' if g.get("checks_total", 0) > 0 else "-"
                duration = g.get("duration", 0)
                dur_str = f"{duration:.1f}s" if duration else ""
                error_mark = "🔴" if g.get("error") else ""
                rows += (
                    f'<tr><td>{g.get("name", gk)}</td>'
                    f'<td><span class="badge {vbadge}">{vlabel}</span></td>'
                    f'<td>{check_info}</td>'
                    f'<td>{dur_str}</td>'
                    f'<td>{error_mark}</td></tr>'
                )
            parts.append(
                f'<h3>Gate 详情</h3>'
                f'<table><tr><th>Gate</th><th>判决</th><th>检查</th><th>耗时</th><th></th></tr>{rows}</table>'
            )

        body = "".join(parts)
        return f'<div class="card"><h2>🔧 Dry Run 管线</h2>{body}</div>'


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="每日复盘报告生成器")
    parser.add_argument("--date", type=str, default=None,
                        help="日期 (YYYY-MM-DD), 默认当天 CST")
    args = parser.parse_args()

    gen = DailyReviewGenerator(date_str=args.date)
    review = gen.generate()

    json_path = gen.output_dir / "daily_review.json"
    html_path = gen.output_dir / "daily_review.html"

    print(f"✅ 复盘报告已生成: {gen.output_dir}")
    print(f"   JSON: {json_path}")
    print(f"   HTML: {html_path}")
    print(f"   章节: {list(review['sections'].keys())}")
    print(f"   摘要: {json.dumps(review.get('summary', {}), ensure_ascii=False, indent=2)}")

    return review


if __name__ == "__main__":
    main()
