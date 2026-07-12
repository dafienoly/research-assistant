"""Alpha Promotion Engine V3.9 — Alpha 晋级治理

构建在 V3.8 Governance Review 之上，提供晋级管道:
  1. PromotionEngine — 将治理批准的候选晋级到 Alpha Registry
  2. PromotionQueue — 晋级队列管理
  3. 晋级历史追踪
  4. 晋级报告生成

用法:
    from factor_lab.alpha.promotion_engine import (
        PromotionEngine,
        PromotionQueue,
        run_promotion,
        generate_promotion_report,
    )

安全边界:
    - auto_apply=False (需要显式调用 promote)
    - no_live_trade=True
    - 所有操作不下单、不改交易配置
    - promote 后 alpha 默认 enabled=False
"""

import os
import json
import csv
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

from factor_lab.alpha.storage import append_jsonl_unique, read_json, update_json, write_json

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
PROMOTION_ROOT = BASE / "alpha_promotion"
PROMOTION_ROOT.mkdir(parents=True, exist_ok=True)

# 晋级队列文件
PROMOTION_QUEUE_FILE = PROMOTION_ROOT / "promotion_queue.json"
# 晋级历史文件
PROMOTION_HISTORY_FILE = PROMOTION_ROOT / "promotion_history.jsonl"


# ═══════════════════════════════════════════════════════════════════
# PromotionQueue — 晋级队列管理
# ═══════════════════════════════════════════════════════════════════


class PromotionQueue:
    """晋级队列

    管理待晋级候选:
      - 从 Governance 接收已批准的候选
      - 按优先级排序 (基于 governance score)
      - 支持分批处理
    """

    def __init__(self):
        self.queue: list = []

    def _load_queue(self) -> list:
        queue = read_json(PROMOTION_QUEUE_FILE, [])
        if not isinstance(queue, list):
            raise ValueError("promotion queue must be a JSON list")
        return queue

    def _save_queue(self, queue: list):
        write_json(PROMOTION_QUEUE_FILE, queue)

    def add(self, candidate_id: str, priority: float = 0.5,
            notes: str = "") -> dict:
        """将候选加入晋级队列

        参数:
            candidate_id: 候选 ID
            priority: 优先级 (0-1, 越高越优先)
            notes: 备注

        返回:
            队列条目 dict
        """
        # 检查 governance review
        from factor_lab.alpha.governance import GovernanceReview
        review = GovernanceReview().get_review(candidate_id)
        if "error" in review:
            return {"error": review["error"], "candidate_id": candidate_id}

        gov = review.get("governance", {})
        if gov.get("verdict") != "approve":
            return {
                "error": f"候选未被批准 (verdict={gov.get('verdict', '?')})",
                "candidate_id": candidate_id,
            }

        # 取 governance score 作为默认优先级
        effective_priority = priority
        if priority == 0.5 and gov.get("overall_score"):
            effective_priority = round(gov["overall_score"], 4)

        entry = {
            "candidate_id": candidate_id,
            "candidate_name": review.get("candidate_name", ""),
            "governance_score": gov.get("overall_score", 0),
            "governance_verdict": gov.get("verdict", ""),
            "priority": effective_priority,
            "notes": notes,
            "added_at": datetime.now(CST).isoformat(),
            "status": "pending",  # pending / processing / promoted / failed
        }
        outcome: dict = {}

        def mutate(queue: list) -> list:
            if not isinstance(queue, list):
                raise ValueError("promotion queue must be a JSON list")
            if any(item.get("candidate_id") == candidate_id for item in queue):
                outcome.update({"error": f"候选 {candidate_id} 已在队列中", "candidate_id": candidate_id})
                return queue
            queue.append(entry)
            outcome.update({"entry": entry, "status": "queued"})
            return queue

        update_json(PROMOTION_QUEUE_FILE, [], mutate)
        return outcome

    def remove(self, candidate_id: str) -> dict:
        """从队列移除候选"""
        outcome: dict = {}

        def mutate(queue: list) -> list:
            new_queue = [item for item in queue if item.get("candidate_id") != candidate_id]
            if len(new_queue) == len(queue):
                outcome.update({"error": f"候选 {candidate_id} 不在队列中"})
            else:
                outcome.update({"status": "removed", "candidate_id": candidate_id})
            return new_queue

        update_json(PROMOTION_QUEUE_FILE, [], mutate)
        return outcome

    def list_queue(self, status: str = "") -> list:
        """列出队列

        参数:
            status: 筛选状态 (空=全部)

        返回:
            按优先级降序排列的队列
        """
        queue = self._load_queue()
        if status:
            queue = [item for item in queue if item["status"] == status]
        queue.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return queue

    def update_status(self, candidate_id: str, new_status: str) -> dict:
        """更新队列条目状态"""
        outcome: dict = {}

        def mutate(queue: list) -> list:
            for item in queue:
                if item.get("candidate_id") == candidate_id:
                    item["status"] = new_status
                    item["updated_at"] = datetime.now(CST).isoformat()
                    outcome.update({"status": "updated", "candidate_id": candidate_id, "new_status": new_status})
                    return queue
            outcome.update({"error": f"候选 {candidate_id} 不在队列中"})
            return queue

        update_json(PROMOTION_QUEUE_FILE, [], mutate)
        return outcome

    def clear_completed(self) -> dict:
        """清理已完成或失败的项目"""
        outcome: dict = {}

        def mutate(queue: list) -> list:
            active = [item for item in queue if item.get("status") in ("pending", "processing")]
            outcome.update({"removed": len(queue) - len(active), "remaining": len(active)})
            return active

        update_json(PROMOTION_QUEUE_FILE, [], mutate)
        return outcome

    def queue_stats(self) -> dict:
        """队列统计"""
        queue = self._load_queue()
        total = len(queue)
        by_status = {}
        for item in queue:
            s = item.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total": total,
            "by_status": by_status,
            "highest_priority": max((item.get("priority", 0) for item in queue),
                                     default=0),
            "lowest_priority": min((item.get("priority", 0) for item in queue),
                                    default=0),
        }


# ═══════════════════════════════════════════════════════════════════
# PromotionEngine — 晋级执行引擎
# ═══════════════════════════════════════════════════════════════════


class PromotionEngine:
    """晋级执行引擎

    将治理批准的候选晋级到 Alpha Registry:
      1. 验证 candidate 已被 governance approve
      2. 从 candidate spec 构建 AlphaSpec
      3. 注册到 Alpha Registry
      4. 更新 candidate 状态为 promoted
      5. 记录晋级历史
      6. 生成报告
    """

    def __init__(self):
        self.result: dict = {}
        self.history: list = []

    def promote(self, candidate_id: str, override: bool = False) -> dict:
        """将单个候选晋级到 Alpha Registry

        参数:
            candidate_id: 候选 ID
            override: 是否跳过 governance 批准检查 (默认 False)

        返回:
            晋级结果 dict
        """
        # 1. 加载候选
        from factor_lab.alpha.llm_alpha_discovery import (
            CANDIDATES_ROOT,
            get_candidate,
            update_candidate_status,
        )
        candidate = get_candidate(candidate_id)
        if "error" in candidate:
            return {"error": candidate["error"], "candidate_id": candidate_id}

        # 2. 检查 governance
        from factor_lab.alpha.governance import GovernanceReview
        review = GovernanceReview().get_review(candidate_id)
        if "error" not in review and not override:
            gov = review.get("governance", {})
            if gov.get("verdict") != "approve":
                return {
                    "error": f"治理审核未批准 (verdict={gov.get('verdict', '?')})",
                    "candidate_id": candidate_id,
                    "governance": gov,
                }

        # 3. 检查候选状态
        if candidate.get("status") == "promoted":
            return {
                "error": f"候选 {candidate_id} 已被晋级",
                "candidate_id": candidate_id,
            }

        # 4. 从 spec 构建 AlphaSpec
        spec = candidate.get("spec", {})
        if not spec:
            return {"error": "候选 spec 为空", "candidate_id": candidate_id}

        from factor_lab.alpha.schema import AlphaSpec
        alpha_spec = AlphaSpec(
            name=spec.get("name", f"promoted_{candidate_id[:12]}"),
            description=spec.get("description", ""),
            hypothesis=spec.get("hypothesis", ""),
            universe=spec.get("universe", "all_watchlist"),
            data_requirements=spec.get("data_requirements", ["close", "volume", "amount"]),
            factor_expression=spec.get("factor_expression", ""),
            signal_direction=spec.get("signal_direction", "long"),
            rebalance_frequency=spec.get("rebalance_frequency", "monthly"),
            risk_constraints=spec.get("risk_constraints", {"max_position_weight": 0.25, "max_drawdown": 0.15}),
            author="governance_promotion",
            source=f"promoted_from_{candidate_id}",
            version="0.0.1",
            status="registered",
            enabled=False,
            paper_enabled=False,
            live_enabled=False,
            tags=spec.get("tags", ["promoted"]),
        )

        # 5. 注册到 Alpha Registry
        from factor_lab.alpha.registry import register_alpha
        try:
            registry_result = register_alpha(alpha_spec)
        except Exception as e:
            return {"error": f"注册失败: {e}", "candidate_id": candidate_id}
        alpha_id = registry_result.get("alpha_id", "")

        # 6. 复制 governance review 到 alpha 目录
        try:
            from factor_lab.alpha.registry import REGISTRY_ROOT
            alpha_dir = REGISTRY_ROOT / alpha_id
            review_path = CANDIDATES_ROOT / candidate_id / "governance_review.json"
            if review_path.exists():
                shutil.copy2(
                    str(review_path),
                    str(alpha_dir / "promotion_history" / "governance_review.json"),
                )
        except Exception:
            pass  # 非关键错误

        # 7. 更新候选状态
        promoted_at = datetime.now(CST).isoformat()
        update_candidate_status(candidate_id, "promoted")

        # 8. 写入 promotion 审核记录
        promotion_record = {
            "candidate_id": candidate_id,
            "alpha_id": alpha_id,
            "candidate_name": spec.get("name", ""),
            "promoted_at": promoted_at,
            "governance_score": review.get("governance", {}).get("overall_score", 0),
            "governance_verdict": review.get("governance", {}).get("verdict", ""),
            "override": override,
            "enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "safety": {
                "auto_apply": False,
                "no_live_trade": True,
            },
        }

        # 持久化到候选目录
        try:
            (CANDIDATES_ROOT / candidate_id / "promotion_record.json").write_text(
                json.dumps(promotion_record, indent=2, ensure_ascii=False)
            )
        except Exception:
            pass

        # 持久化到 promotion 目录
        try:
            alpha_prom_dir = PROMOTION_ROOT / alpha_id
            alpha_prom_dir.mkdir(parents=True, exist_ok=True)
            (alpha_prom_dir / "promotion_record.json").write_text(
                json.dumps(promotion_record, indent=2, ensure_ascii=False)
            )
        except Exception:
            pass

        # 9. 追加到历史
        self._append_history(promotion_record)

        # 10. 移除晋级队列
        try:
            pq = PromotionQueue()
            pq.update_status(candidate_id, "promoted")
        except Exception:
            pass

        self.result = promotion_record
        return promotion_record

    def promote_all_approved(self, max_count: int = 0) -> list:
        """批量晋级所有已批准的候选

        参数:
            max_count: 最大晋级数 (0=不限)

        返回:
            晋级结果列表
        """
        from factor_lab.alpha.llm_alpha_discovery import list_candidates
        all_candidates = list_candidates()

        # 筛选已批准且未晋级的候选
        candidates_to_promote = []
        for entry in all_candidates:
            cid = entry.get("candidate_id", "")
            if entry.get("status") == "promoted":
                continue
            if entry.get("status") not in ("pending_review", "approved"):
                continue

            from factor_lab.alpha.governance import GovernanceReview
            review = GovernanceReview().get_review(cid)
            if "error" not in review:
                gov = review.get("governance", {})
                if gov.get("verdict") == "approve":
                    candidates_to_promote.append(cid)

        if max_count > 0:
            candidates_to_promote = candidates_to_promote[:max_count]

        results = []
        for cid in candidates_to_promote:
            result = self.promote(cid)
            results.append(result)

        return results

    def _append_history(self, record: dict):
        """追加晋级历史"""
        try:
            entry = {
                "timestamp": record.get("promoted_at", datetime.now(CST).isoformat()),
                "candidate_id": record.get("candidate_id", ""),
                "alpha_id": record.get("alpha_id", ""),
                "candidate_name": record.get("candidate_name", ""),
                "governance_score": record.get("governance_score", 0),
                "governance_verdict": record.get("governance_verdict", ""),
            }
            append_jsonl_unique(
                PROMOTION_HISTORY_FILE,
                entry,
                unique_fields=("candidate_id", "alpha_id"),
            )
        except (OSError, TypeError, ValueError) as exc:
            record.setdefault("persistence_warnings", []).append(f"promotion history append failed: {exc}")

    def get_promotion(self, alpha_id: str) -> dict:
        """获取晋级记录"""
        prom_path = PROMOTION_ROOT / alpha_id / "promotion_record.json"
        if prom_path.exists():
            return json.loads(prom_path.read_text())
        return {"error": f"晋级记录不存在: {alpha_id}"}

    def list_promotions(self, limit: int = 50) -> list:
        """列出晋级记录

        参数:
            limit: 最大返回条数
        """
        if not PROMOTION_HISTORY_FILE.exists():
            return []

        history = []
        with open(PROMOTION_HISTORY_FILE) as f:
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
# 晋级报告
# ═══════════════════════════════════════════════════════════════════


def generate_promotion_report(output_dir: str = "") -> dict:
    """生成晋级报告

    参数:
        output_dir: 输出目录 (空=自动)

    返回:
        dict 包含报告路径、统计信息
    """
    if not output_dir:
        rid = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        output_dir = str(PROMOTION_ROOT / rid)
    os.makedirs(output_dir, exist_ok=True)

    engine = PromotionEngine()
    promotions = engine.list_promotions(limit=200)

    # 统计
    total = len(promotions)
    scores = [p.get("governance_score", 0) for p in promotions if p.get("governance_score") is not None]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    stats = {
        "total_promotions": total,
        "average_governance_score": round(avg_score, 4),
        "highest_score": max(scores) if scores else 0,
        "lowest_score": min(scores) if scores else 0,
    }

    report = {
        "report_type": "alpha_promotion_report",
        "version": "V3.9",
        "generated_at": datetime.now(CST).isoformat(),
        "stats": stats,
        "promotions": promotions,
        "safety": {
            "auto_apply": False,
            "no_live_trade": True,
            "all_disabled": True,
        },
    }

    # JSON
    report_path = os.path.join(output_dir, "promotion_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # HTML
    html_path = os.path.join(output_dir, "promotion_report.html")
    _write_promotion_html(html_path, report, stats)

    # CSV
    csv_path = os.path.join(output_dir, "promotion_report.csv")
    _write_promotion_csv(csv_path, promotions)

    # Audit
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write("=== ALPHA PROMOTION AUDIT V3.9 ===\n")
        f.write(f"Report at: {report['generated_at']}\n")
        f.write(f"Total promotions: {total}\n")
        f.write(f"Avg governance score: {avg_score:.4f}\n")
        f.write("Auto apply: False\n")
        f.write("No live trade: True\n")
        f.write("=== END ===\n")

    return {
        "output_dir": output_dir,
        "report_path": report_path,
        "html_path": html_path,
        "csv_path": csv_path,
        "stats": stats,
        "safety": report["safety"],
    }


def _write_promotion_html(html_path: str, report: dict, stats: dict):
    """写入 HTML 晋级报告"""
    rows = ""
    for p in report.get("promotions", []):
        rows += (
            f"<tr>"
            f"<td>{p.get('candidate_id', '?')[:30]}</td>"
            f"<td>{p.get('alpha_id', '?')[:30]}</td>"
            f"<td>{p.get('candidate_name', '?')}</td>"
            f"<td>{p.get('governance_score', 0):.4f}</td>"
            f"<td>{p.get('governance_verdict', '?')}</td>"
            f"<td>{p.get('promoted_at', '?')[:19]}</td>"
            f"</tr>"
        )

    safety_rows = "".join(
        f"<li>{k}: {'✅' if v else '❌'}</li>"
        for k, v in report.get("safety", {}).items()
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Alpha Promotion V3.9</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>🚀 Alpha Promotion V3.9</h1>
<p style="color:#aaa;">Generated: {report['generated_at']}</p>
<p>Total promotions: {stats['total_promotions']} | Avg score: {stats['average_governance_score']:.4f}</p></div>
<div class="card"><h2>📋 Promotion History</h2>
<table>
<tr><th>Candidate</th><th>Alpha ID</th><th>Name</th><th>Score</th><th>Verdict</th><th>Promoted At</th></tr>
{rows}
</table></div>
<div class="card"><h2>🛡️ Safety</h2><ul>{safety_rows}</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.9 | Auto-apply: False | No live trade</p></div>
</body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _write_promotion_csv(csv_path: str, promotions: list):
    """写入 CSV 晋级报告"""
    fieldnames = ["candidate_id", "alpha_id", "candidate_name",
                   "governance_score", "governance_verdict", "promoted_at"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for p in promotions:
            w.writerow(p)


# ═══════════════════════════════════════════════════════════════════
# 快捷入口
# ═══════════════════════════════════════════════════════════════════


def run_promotion(candidate_id: str, override: bool = False) -> dict:
    """运行晋级 (快捷函数)"""
    engine = PromotionEngine()
    return engine.promote(candidate_id, override=override)


def run_batch_promotion(max_count: int = 0) -> dict:
    """批量晋级 (快捷函数)"""
    engine = PromotionEngine()
    results = engine.promote_all_approved(max_count=max_count)
    return {
        "total": len(results),
        "succeeded": sum(1 for r in results if "alpha_id" in r),
        "failed": sum(1 for r in results if "error" in r),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════════
# CLI 集成函数
# ═══════════════════════════════════════════════════════════════════


def cmd_promotion_queue_add(candidate_id: str, priority: float = 0.5,
                             notes: str = "") -> dict:
    """CLI 入口: alpha:promotion-queue-add"""
    pq = PromotionQueue()
    result = pq.add(candidate_id, priority=priority, notes=notes)
    if "error" in result:
        print(f"❌ {result['error']}")
        return result
    print(f"  ✅ 已加入晋级队列: {candidate_id}")
    print(f"     Priority: {result['entry']['priority']:.4f}")
    return result


def cmd_promotion_queue_list(status: str = "") -> None:
    """CLI 入口: alpha:promotion-queue-list"""
    pq = PromotionQueue()
    queue = pq.list_queue(status=status)
    if not queue:
        print("  (empty)")
        return
    print(f"\n  📋 Promotion Queue ({len(queue)} items)")
    print(f"  {'='*60}")
    for item in queue:
        tag = {"pending": "⏳", "processing": "🔄", "promoted": "✅", "failed": "❌"}.get(
            item.get("status", ""), "⚪"
        )
        print(f"  {tag} {item['candidate_id'][:35]:35s} "
              f"score={item.get('governance_score', 0):.2f} "
              f"pri={item.get('priority', 0):.2f} "
              f"state={item.get('status', '?')}")
    print()


def cmd_promotion_queue_stats() -> None:
    """CLI 入口: alpha:promotion-queue-stats"""
    pq = PromotionQueue()
    stats = pq.queue_stats()
    print("\n  📊 Promotion Queue Stats")
    print(f"  {'='*40}")
    print(f"  Total: {stats['total']}")
    for status, count in stats.get("by_status", {}).items():
        print(f"    {status}: {count}")
    print(f"  Priority range: {stats['lowest_priority']:.2f} ~ {stats['highest_priority']:.2f}")
    print()


def cmd_promote(candidate_id: str, override: bool = False) -> dict:
    """CLI 入口: alpha:promote"""
    result = run_promotion(candidate_id, override=override)
    if "error" in result:
        print(f"❌ {result['error']}")
        return result
    print(f"\n{'='*60}")
    print("  🚀 Alpha Promotion V3.9")
    print(f"  Candidate: {result.get('candidate_name', '?')} ({candidate_id})")
    print(f"  Alpha ID: {result['alpha_id']}")
    print(f"{'='*60}")
    print(f"  Governance Score: {result.get('governance_score', 0):.4f}")
    print(f"  Promoted At: {result.get('promoted_at', '?')}")
    print("  Enabled: False")
    print("  Paper/Live: Disabled")
    print(f"{'='*60}\n")
    return result


def cmd_batch_promote(max_count: int = 0) -> None:
    """CLI 入口: alpha:batch-promote"""
    result = run_batch_promotion(max_count=max_count)
    print(f"\n{'='*60}")
    print("  🚀 Batch Promotion V3.9")
    print(f"  Total: {result['total']} | "
          f"✅ Succeeded: {result['succeeded']} | "
          f"❌ Failed: {result['failed']}")
    print(f"{'='*60}\n")
    for r in result.get("results", []):
        if "alpha_id" in r:
            print(f"  ✅ {r['candidate_id'][:30]:30s} → {r['alpha_id']}")
        else:
            print(f"  ❌ {r['candidate_id'][:30]:30s} → {r.get('error', '?')}")
    print()


def cmd_promotion_report() -> None:
    """CLI 入口: alpha:promotion-report"""
    result = generate_promotion_report()
    print(f"\n{'='*60}")
    print("  📊 Promotion Report V3.9")
    print(f"  Output: {result['output_dir']}")
    print(f"  Total Promotions: {result['stats']['total_promotions']}")
    print(f"  Avg Score: {result['stats']['average_governance_score']:.4f}")
    print(f"{'='*60}\n")


def cmd_promotion_list(limit: int = 20) -> None:
    """CLI 入口: alpha:promotion-list"""
    engine = PromotionEngine()
    promotions = engine.list_promotions(limit=limit)
    if not promotions:
        print("  (empty)")
        return
    print(f"\n  📋 Promotion History (last {limit})")
    print(f"  {'='*70}")
    for p in promotions:
        print(f"  🚀 {p.get('candidate_id', '?')[:30]:30s} "
              f"→ {p.get('alpha_id', '?')[:30]:30s} "
              f"score={p.get('governance_score', 0):.2f} "
              f"at={p.get('promoted_at', '?')[:16]}")
    print()
