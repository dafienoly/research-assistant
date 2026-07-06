"""Alpha Retirement Engine V3.9 — Alpha 退役治理

构建在 V3.8 Governance + V3.9 Promotion 之上，提供退役管道:
  1. RetirementEngine — 基于条件评估的自动/手动退役
  2. RetirementPolicy — 可配置的退役策略
  3. 退役历史追踪
  4. 退役报告生成

用法:
    from factor_lab.alpha.retirement_engine import (
        RetirementEngine,
        RetirementPolicy,
        run_retirement,
        generate_retirement_report,
    )

安全边界:
    - no_live_trade=True
    - 退役仅更新 registry 状态，不下单、不改交易配置
    - 退役后 alpha enabled=False, paper_enabled=False, live_enabled=False
"""

import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
RETIREMENT_ROOT = BASE / "alpha_retirement"
RETIREMENT_ROOT.mkdir(parents=True, exist_ok=True)

# 退役历史文件
RETIREMENT_HISTORY_FILE = RETIREMENT_ROOT / "retirement_history.jsonl"
# 退役策略文件
RETIREMENT_POLICY_FILE = RETIREMENT_ROOT / "retirement_policy.json"


# ═══════════════════════════════════════════════════════════════════
# RetirementPolicy — 退役策略
# ═══════════════════════════════════════════════════════════════════


DEFAULT_RETIREMENT_POLICY = {
    "ic_threshold": {
        "description": "IC 低于此阈值触发退役警告",
        "value": 0.02,
        "enabled": True,
    },
    "max_drawdown": {
        "description": "回撤超过此阈值触发退役",
        "value": 0.30,
        "enabled": True,
    },
    "max_stale_days": {
        "description": "超过此天数未更新触发退役",
        "value": 90,
        "enabled": True,
    },
    "min_evidence_score": {
        "description": "证据评分低于此阈值触发退役审查",
        "value": 0.3,
        "enabled": True,
    },
    "max_risk_score": {
        "description": "风险评分超过此阈值触发退役审查",
        "value": 0.7,
        "enabled": True,
    },
    "auto_retire_enabled": {
        "description": "是否启用自动退役",
        "value": True,
        "enabled": True,
    },
    "require_human_approval": {
        "description": "退役是否需要人工确认",
        "value": True,
        "enabled": True,
    },
}


class RetirementPolicy:
    """退役策略管理

    管理退役的条件阈值:
      - IC 阈值
      - 最大回撤
      - 最长无更新天数
      - 证据/风险评分阈值
    """

    def __init__(self):
        self.policy: dict = {}

    def _load(self) -> dict:
        if RETIREMENT_POLICY_FILE.exists():
            return json.loads(RETIREMENT_POLICY_FILE.read_text())
        return dict(DEFAULT_RETIREMENT_POLICY)

    def _save(self, policy: dict):
        RETIREMENT_POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        RETIREMENT_POLICY_FILE.write_text(
            json.dumps(policy, indent=2, ensure_ascii=False)
        )

    def get_policy(self) -> dict:
        """获取当前策略"""
        return self._load()

    def update_policy(self, key: str, value) -> dict:
        """更新策略参数

        参数:
            key: 策略键名
            value: 新值 (dict 包含 value 和/或 enabled)
        """
        policy = self._load()
        if key not in policy:
            return {"error": f"未知策略键: {key}", "valid_keys": list(policy.keys())}

        if isinstance(value, dict):
            if "value" in value:
                policy[key]["value"] = value["value"]
            if "enabled" in value:
                policy[key]["enabled"] = value["enabled"]
        else:
            policy[key]["value"] = value

        self._save(policy)
        return {"status": "updated", "key": key, "policy": policy[key]}

    def reset_policy(self) -> dict:
        """重置为默认策略"""
        self._save(dict(DEFAULT_RETIREMENT_POLICY))
        return {"status": "reset", "policy": dict(DEFAULT_RETIREMENT_POLICY)}


# ═══════════════════════════════════════════════════════════════════
# RetirementEngine — 退役执行引擎
# ═══════════════════════════════════════════════════════════════════


class RetirementEngine:
    """退役执行引擎

    支持:
      - 手动指定原因退役
      - 基于指标自动退役 (IC/回撤/时效性/证据/风险)
      - 退役审查与报告
    """

    def __init__(self):
        self.result: dict = {}
        self.policy = RetirementPolicy()

    def retire(self, alpha_id: str, reason: str = "",
               force: bool = False) -> dict:
        """退役单个 Alpha

        参数:
            alpha_id: Alpha ID
            reason: 退役原因
            force: 是否跳过检查强制执行

        返回:
            退役结果 dict
        """
        from factor_lab.alpha.registry import (
            REGISTRY_ROOT,
            get_alpha,
            update_alpha_status,
        )

        # 1. 加载 Alpha
        spec = get_alpha(alpha_id)
        if "error" in spec:
            return {"error": spec["error"], "alpha_id": alpha_id}

        current_status = spec.get("status", "")
        if current_status == "retired" and not force:
            return {
                "error": f"Alpha {alpha_id} 已退役",
                "alpha_id": alpha_id,
                "current_status": current_status,
            }

        # 2. 更新状态为 retired (registry)
        if force:
            # 强制: 直接修改 registry index 状态，跳过 lifecycle 检查
            from factor_lab.alpha.registry import REGISTRY_ROOT, _load_index, _save_index
            from pathlib import Path
            import json as _json
            spec_path = Path(str(REGISTRY_ROOT)) / alpha_id / "alpha_spec.json"
            if spec_path.exists():
                spec_data = _json.loads(spec_path.read_text())
                spec_data["status"] = "retired"
                spec_data["updated_at"] = datetime.now(CST).isoformat()
                spec_data["enabled"] = False
                spec_data["paper_enabled"] = False
                spec_data["live_enabled"] = False
                spec_path.write_text(_json.dumps(spec_data, indent=2, ensure_ascii=False))
            index = _load_index()
            for i, entry in enumerate(index):
                if entry["alpha_id"] == alpha_id:
                    index[i]["status"] = "retired"
            _save_index(index)
            result = {"alpha_id": alpha_id, "status": "retired", "success": True}
        else:
            result = update_alpha_status(alpha_id, "retired")
        if "error" in result:
            return result

        # 3. 写入退役审核记录
        retired_at = datetime.now(CST).isoformat()
        retirement_record = {
            "alpha_id": alpha_id,
            "alpha_name": spec.get("name", ""),
            "previous_status": current_status,
            "retired_at": retired_at,
            "reason": reason or "手动退役",
            "force": force,
            "enabled_disabled": True,
            "paper_enabled_disabled": True,
            "live_enabled_disabled": True,
            "safety": {
                "no_live_trade": True,
            },
        }

        # 持久化到 alpha 目录
        try:
            alpha_dir = REGISTRY_ROOT / alpha_id
            (alpha_dir / "retirement_record.json").write_text(
                json.dumps(retirement_record, indent=2, ensure_ascii=False)
            )
        except Exception:
            pass

        # 持久化到 retirement 目录
        try:
            alpha_ret_dir = RETIREMENT_ROOT / alpha_id
            alpha_ret_dir.mkdir(parents=True, exist_ok=True)
            (alpha_ret_dir / "retirement_record.json").write_text(
                json.dumps(retirement_record, indent=2, ensure_ascii=False)
            )
        except Exception:
            pass

        # 4. 追加到历史
        self._append_history(retirement_record)

        self.result = retirement_record
        return retirement_record

    def auto_retire(self, dry_run: bool = False) -> list:
        """自动退役评估

        根据策略评估所有 active 状态的 Alpha:
          - 检查各维度指标
          - 对触发条件的 Alpha 执行退役或发出警告

        参数:
            dry_run: True=仅报告不执行退役

        返回:
            评估结果列表
        """
        from factor_lab.alpha.registry import list_alpha, REGISTRY_ROOT

        policy = self.policy.get_policy()
        alphas = list_alpha()
        results = []

        for entry in alphas:
            alpha_id = entry.get("alpha_id", "")
            status = entry.get("status", "")
            name = entry.get("name", "")

            # 只评估 active 状态
            if status in ("retired", "rejected", "draft"):
                continue

            # 加载完整 spec
            from factor_lab.alpha.registry import get_alpha
            spec = get_alpha(alpha_id)
            if "error" in spec:
                continue

            triggers = []
            severity = "info"

            # 检查策略触发的各个维度
            # IC 阈值
            ic_pol = policy.get("ic_threshold", {})
            if ic_pol.get("enabled", True):
                ic_val = spec.get("ic", spec.get("last_ic", 0))
                ic_thresh = ic_pol.get("value", 0.02)
                if isinstance(ic_val, (int, float)) and ic_val < ic_thresh:
                    triggers.append(f"IC {ic_val:.4f} < 阈值 {ic_thresh}")
                    severity = "warning"

            # 回撤
            dd_pol = policy.get("max_drawdown", {})
            if dd_pol.get("enabled", True):
                dd_val = spec.get("max_drawdown", spec.get("drawdown", 0))
                dd_thresh = dd_pol.get("value", 0.30)
                if isinstance(dd_val, (int, float)) and abs(dd_val) > dd_thresh:
                    triggers.append(f"回撤 {abs(dd_val):.2%} > 阈值 {dd_thresh:.0%}")
                    severity = "critical"

            # 时效性
            stale_pol = policy.get("max_stale_days", {})
            if stale_pol.get("enabled", True):
                updated_at = spec.get("updated_at", spec.get("created_at", ""))
                stale_days = stale_pol.get("value", 90)
                if updated_at:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at)
                        days_since = (datetime.now(CST) - updated_dt).days
                        if days_since > stale_days:
                            triggers.append(f"{days_since} 天未更新 > 阈值 {stale_days} 天")
                            severity = "critical"
                    except Exception:
                        pass

            # 证据评分
            ev_pol = policy.get("min_evidence_score", {})
            if ev_pol.get("enabled", True):
                ev_score = spec.get("evidence_score", 1.0)
                ev_thresh = ev_pol.get("value", 0.3)
                if isinstance(ev_score, (int, float)) and ev_score < ev_thresh:
                    triggers.append(f"证据评分 {ev_score:.2f} < 阈值 {ev_thresh}")
                    if severity != "critical":
                        severity = "warning"

            # 风险评分
            risk_pol = policy.get("max_risk_score", {})
            if risk_pol.get("enabled", True):
                risk_score = spec.get("risk_score", 0)
                risk_thresh = risk_pol.get("value", 0.7)
                if isinstance(risk_score, (int, float)) and risk_score > risk_thresh:
                    triggers.append(f"风险评分 {risk_score:.2f} > 阈值 {risk_thresh}")
                    if severity != "critical":
                        severity = "warning"

            if not triggers:
                results.append({
                    "alpha_id": alpha_id,
                    "name": name,
                    "status": "ok",
                    "triggers": [],
                    "severity": "info",
                })
                continue

            assessment = {
                "alpha_id": alpha_id,
                "name": name,
                "current_status": status,
                "triggers": triggers,
                "severity": severity,
                "assessed_at": datetime.now(CST).isoformat(),
            }

            # 执行退役 (非 dry_run 且 severity 为 critical)
            if not dry_run and severity == "critical":
                auto_enabled = policy.get("auto_retire_enabled", {}).get("value", True)
                if auto_enabled:
                    reason = "; ".join(triggers)
                    need_approval = policy.get("require_human_approval", {}).get("value", True)
                    if need_approval:
                        assessment["action"] = "requires_approval"
                        assessment["note"] = f"触发退役条件，需人工确认: {reason}"
                    else:
                        retire_result = self.retire(alpha_id, reason=f"自动退役: {reason}")
                        assessment["action"] = "retired"
                        assessment["retire_result"] = retire_result
                else:
                    assessment["action"] = "auto_retire_disabled"
            elif not dry_run and severity == "warning":
                assessment["action"] = "monitoring"
                assessment["note"] = "触发退役警告，持续监控"
            else:
                assessment["action"] = "report_only" if dry_run else "no_action"

            results.append(assessment)

        return results

    def _append_history(self, record: dict):
        """追加退役历史"""
        try:
            entry = {
                "timestamp": record.get("retired_at", datetime.now(CST).isoformat()),
                "alpha_id": record.get("alpha_id", ""),
                "alpha_name": record.get("alpha_name", ""),
                "previous_status": record.get("previous_status", ""),
                "reason": record.get("reason", ""),
            }
            with open(RETIREMENT_HISTORY_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_retirement(self, alpha_id: str) -> dict:
        """获取退役记录"""
        ret_path = RETIREMENT_ROOT / alpha_id / "retirement_record.json"
        if ret_path.exists():
            return json.loads(ret_path.read_text())
        return {"error": f"退役记录不存在: {alpha_id}"}

    def list_retirements(self, limit: int = 50) -> list:
        """列出退役记录"""
        if not RETIREMENT_HISTORY_FILE.exists():
            return []

        history = []
        with open(RETIREMENT_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        history.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return history[:limit]


# ═══════════════════════════════════════════════════════════════════
# 退役报告
# ═══════════════════════════════════════════════════════════════════


def generate_retirement_report(output_dir: str = "") -> dict:
    """生成退役报告

    参数:
        output_dir: 输出目录 (空=自动)

    返回:
        dict 包含报告路径、统计信息
    """
    if not output_dir:
        rid = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        output_dir = str(RETIREMENT_ROOT / rid)
    os.makedirs(output_dir, exist_ok=True)

    engine = RetirementEngine()
    retirements = engine.list_retirements(limit=200)

    # 统计
    total = len(retirements)
    reasons = [r.get("reason", "") for r in retirements]
    by_reason = {}
    for reason in reasons:
        key = "自动退役" if "自动退役" in reason else "手动退役"
        by_reason[key] = by_reason.get(key, 0) + 1

    stats = {
        "total_retirements": total,
        "by_reason": by_reason,
    }

    report = {
        "report_type": "alpha_retirement_report",
        "version": "V3.9",
        "generated_at": datetime.now(CST).isoformat(),
        "stats": stats,
        "retirements": retirements,
        "safety": {
            "no_live_trade": True,
        },
    }

    # JSON
    report_path = os.path.join(output_dir, "retirement_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # HTML
    html_path = os.path.join(output_dir, "retirement_report.html")
    _write_retirement_html(html_path, report, stats)

    # CSV
    csv_path = os.path.join(output_dir, "retirement_report.csv")
    _write_retirement_csv(csv_path, retirements)

    # Audit
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== ALPHA RETIREMENT AUDIT V3.9 ===\n")
        f.write(f"Report at: {report['generated_at']}\n")
        f.write(f"Total retirements: {total}\n")
        f.write(f"By reason: {by_reason}\n")
        f.write(f"No live trade: True\n")
        f.write(f"=== END ===\n")

    return {
        "output_dir": output_dir,
        "report_path": report_path,
        "html_path": html_path,
        "csv_path": csv_path,
        "stats": stats,
        "safety": report["safety"],
    }


def _write_retirement_html(html_path: str, report: dict, stats: dict):
    """写入 HTML 退役报告"""
    rows = ""
    for r in report.get("retirements", []):
        auto_tag = "🤖" if "自动退役" in r.get("reason", "") else "👤"
        rows += (
            f"<tr>"
            f"<td>{r.get('alpha_id', '?')[:30]}</td>"
            f"<td>{r.get('alpha_name', '?')}</td>"
            f"<td>{r.get('previous_status', '?')}</td>"
            f"<td>{auto_tag} {r.get('reason', '?')}</td>"
            f"<td>{r.get('retired_at', '?')[:19]}</td>"
            f"</tr>"
        )

    safety_rows = "".join(
        f"<li>{k}: {'✅' if v else '❌'}</li>"
        for k, v in report.get("safety", {}).items()
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Alpha Retirement V3.9</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#ff6b6b; }} h2 {{ color:#ff6b6b; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>🗑️ Alpha Retirement V3.9</h1>
<p style="color:#aaa;">Generated: {report['generated_at']}</p>
<p>Total retirements: {stats['total_retirements']} | Reasons: {stats.get('by_reason', {})}</p></div>
<div class="card"><h2>📋 Retirement History</h2>
<table>
<tr><th>Alpha ID</th><th>Name</th><th>Previous</th><th>Reason</th><th>Retired At</th></tr>
{rows}
</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul>{safety_rows}</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.9 | No live trade</p></div>
</body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _write_retirement_csv(csv_path: str, retirements: list):
    """写入 CSV 退役报告"""
    fieldnames = ["alpha_id", "alpha_name", "previous_status",
                   "reason", "retired_at"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in retirements:
            w.writerow(r)


# ═══════════════════════════════════════════════════════════════════
# 快捷入口
# ═══════════════════════════════════════════════════════════════════


def run_retirement(alpha_id: str, reason: str = "", force: bool = False) -> dict:
    """手动退役 (快捷函数)"""
    engine = RetirementEngine()
    return engine.retire(alpha_id, reason=reason, force=force)


def run_auto_retirement(dry_run: bool = False) -> list:
    """自动退役评估 (快捷函数)"""
    engine = RetirementEngine()
    return engine.auto_retire(dry_run=dry_run)


# ═══════════════════════════════════════════════════════════════════
# CLI 集成函数
# ═══════════════════════════════════════════════════════════════════


def cmd_retire(alpha_id: str, reason: str = "", force: bool = False) -> dict:
    """CLI 入口: alpha:retire"""
    result = run_retirement(alpha_id, reason=reason, force=force)
    if "error" in result:
        print(f"❌ {result['error']}")
        return result
    print(f"\n{'='*60}")
    print(f"  🗑️ Alpha Retirement V3.9")
    print(f"  Alpha: {result.get('alpha_name', '?')} ({alpha_id})")
    print(f"{'='*60}")
    print(f"  Previous Status: {result.get('previous_status', '?')}")
    print(f"  Reason: {result.get('reason', '?')}")
    print(f"  Retired At: {result.get('retired_at', '?')}")
    print(f"  Enabled/Paper/Live: All Disabled")
    print(f"{'='*60}\n")
    return result


def cmd_auto_retire(dry_run: bool = False) -> None:
    """CLI 入口: alpha:auto-retire"""
    results = run_auto_retirement(dry_run=dry_run)
    print(f"\n{'='*60}")
    if dry_run:
        print(f"  🔍 Auto-Retirement Dry Run V3.9")
    else:
        print(f"  🤖 Auto-Retirement V3.9")
    print(f"{'='*60}")
    print(f"  Assessments: {len(results)}")
    print()

    for r in results:
        alpha_id = r.get("alpha_id", "?")[:30]
        name = r.get("name", "?")[:20]
        severity = r.get("severity", "info")
        triggers = r.get("triggers", [])
        action = r.get("action", "none")

        if severity == "critical":
            tag = "🔴"
        elif severity == "warning":
            tag = "🟡"
        else:
            tag = "🟢"

        if triggers:
            print(f"  {tag} {alpha_id:30s} {name:20s} {action:20s}")
            for t in triggers:
                print(f"       ⚠️  {t}")
        else:
            print(f"  {tag} {alpha_id:30s} {name:20s} OK")
    print(f"\n  {'='*60}\n")


def cmd_retirement_report() -> None:
    """CLI 入口: alpha:retirement-report"""
    result = generate_retirement_report()
    print(f"\n{'='*60}")
    print(f"  📊 Retirement Report V3.9")
    print(f"  Output: {result['output_dir']}")
    print(f"  Total Retirements: {result['stats']['total_retirements']}")
    print(f"  By Reason: {result['stats']['by_reason']}")
    print(f"{'='*60}\n")


def cmd_retirement_list(limit: int = 20) -> None:
    """CLI 入口: alpha:retirement-list"""
    engine = RetirementEngine()
    retirements = engine.list_retirements(limit=limit)
    if not retirements:
        print("  (empty)")
        return
    print(f"\n  📋 Retirement History (last {limit})")
    print(f"  {'='*70}")
    for r in retirements:
        auto_tag = "🤖" if "自动退役" in r.get("reason", "") else "👤"
        print(f"  🗑️ {auto_tag} {r.get('alpha_id', '?')[:30]:30s} "
              f"{r.get('alpha_name', '?')[:25]:25s} "
              f"{r.get('reason', '?')[:30]:30s} "
              f"at={r.get('timestamp', '?')[:16]}")
    print()


def cmd_retirement_policy_show() -> None:
    """CLI 入口: alpha:retirement-policy"""
    policy = RetirementPolicy()
    p = policy.get_policy()
    print(f"\n  📋 Retirement Policy")
    print(f"  {'='*50}")
    for key, val in p.items():
        enabled = val.get("enabled", True)
        value = val.get("value", "?")
        desc = val.get("description", "")
        tag = "✅" if enabled else "❌"
        print(f"  {tag} {key:30s} = {value}")
        print(f"      {desc}")
    print()


def cmd_retirement_policy_update(key: str, value) -> dict:
    """CLI 入口: alpha:retirement-policy-update"""
    policy = RetirementPolicy()
    result = policy.update_policy(key, value)
    if "error" in result:
        print(f"❌ {result['error']}")
        return result
    print(f"  ✅ 策略已更新: {key} = {result['policy']}")
    return result
