"""影子观察器 — 跟踪新注册因子的 IC 衰减

流程：
  因子注册时 shadow_status="observing"
  → 每天 factor:mine 后调用 daily_tick()
  → 收集逐日 IC
  → 观察期结束后计算衰减率
  → 标记 available 或 unstable
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

_SCRIPT_DIR = Path(__file__).parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from factor_lab.pipeline_config import PipelineConfig  # noqa: E402
from factor_lab.alpha.storage import read_json, update_json, write_json  # noqa: E402


REGISTRY_INDEX = Path("/mnt/d/HermesData/alpha_registry/registry_index.json")


class ShadowObserver:
    """影子观察器"""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.cfg = config or PipelineConfig()

    # ── 公开入口 ────────────────────────────────────

    def daily_tick(self) -> list[dict]:
        """每日因子挖掘后调用

        扫描所有处于 observing 状态的 Alpha，
        检查是否有足够的观察数据，
        到期则计算衰减率并标记。

        Returns:
            状态变化的列表
        """
        registry = self._load_registry()
        if not registry:
            return []

        results = []
        for alpha in registry:
            if alpha.get("shadow_status") != "observing":
                continue

            name = alpha.get("name", "")
            alpha_id = alpha.get("alpha_id", "")
            shadow_start = alpha.get("shadow_start", "")
            holding = alpha.get("holding_period", 5)

            # 判断观察期是否到期
            days_needed = (
                self.cfg.SHADOW_DAYS_WEEKLY if holding >= 5
                else self.cfg.SHADOW_DAYS_DAILY
            )
            days_elapsed = self._days_since(shadow_start)
            if days_elapsed < days_needed:
                continue

            # 收集观察期内 IC
            ic_history = self._collect_ic_history(name, shadow_start)
            if len(ic_history) < days_needed * 0.5:
                # 数据不足，继续等待
                continue

            # 计算衰减率
            decay = self._compute_decay_rate(ic_history)
            status = "available" if decay < self.cfg.IC_DECAY_THRESHOLD else "unstable"

            # 更新注册表
            self._update_alpha_status(alpha_id, status, decay)
            results.append({
                "name": name,
                "alpha_id": alpha_id,
                "status": status,
                "decay_rate": decay,
                "days_observed": days_elapsed,
            })

            # 通知
            self._notify(alpha_id, name, status, decay)

        return results

    def mark_observing(self, alpha_id: str, holding_period: int = 5):
        """将刚注册的 Alpha 设为观察中"""
        found = False

        def mark(registry):
            nonlocal found
            for alpha in registry:
                if alpha["alpha_id"] != alpha_id:
                    continue
                alpha["shadow_status"] = "observing"
                alpha["shadow_start"] = datetime.now(CST).strftime("%Y-%m-%d")
                alpha["holding_period"] = holding_period
                found = True
            return registry

        updated = update_json(REGISTRY_INDEX, [], mark)
        if found:
            alpha = next(item for item in updated if item["alpha_id"] == alpha_id)
            print(f"  🔭 {alpha.get('name','?')} 进入影子观察期")

    # ── IC 历史采集 ─────────────────────────────────

    def _collect_ic_history(self, factor_name: str,
                            since_date: str) -> list[float]:
        """从 pipeline_results 中读取 IC 历史"""
        observations: list[tuple[str, float]] = []

        # 扫描结果目录中的 factor_meta.json
        if self.cfg.RESULT_DIR.exists():
            for d in self.cfg.RESULT_DIR.iterdir():
                if not d.is_dir():
                    continue
                meta_file = d / "factor_meta.json"
                if not meta_file.exists():
                    continue
                try:
                    meta = json.loads(meta_file.read_text())
                    if meta.get("name") != factor_name:
                        continue
                    validated = meta.get("validated_at", "")
                    if validated >= since_date:
                        ic = meta.get("ic_mean", None)
                        if ic is not None:
                            observations.append((validated, float(ic)))
                except Exception:
                    continue

        return [ic for _, ic in sorted(observations, key=lambda item: item[0])]

    # ── 衰减率计算 ──────────────────────────────────

    def _compute_decay_rate(self, ic_history: list[float]) -> float:
        """计算 IC 衰减率

        decay = (首段均值 - 末段均值) / |首段均值|
        首段 = 前 1/3 观察期
        末段 = 后 1/3 观察期
        """
        if len(ic_history) < 6:
            return 0.0  # 数据不足，不判定

        third = max(len(ic_history) // 3, 1)
        early = sum(ic_history[:third]) / third
        late = sum(ic_history[-third:]) / third
        base = abs(early)
        if base < 1e-6:
            return 0.0
        return (early - late) / base

    # ── 持久化 ──────────────────────────────────────

    def _load_registry(self) -> list[dict]:
        """加载 Alpha Registry index"""
        return read_json(REGISTRY_INDEX, [])

    def _save_registry(self, registry: list[dict]):
        write_json(REGISTRY_INDEX, registry)

    def _update_alpha_status(self, alpha_id: str, status: str,
                             decay_rate: float):
        """更新 Alpha 状态"""
        updated_alpha = None

        def update_registry(registry):
            nonlocal updated_alpha
            for alpha in registry:
                if alpha["alpha_id"] != alpha_id:
                    continue
                alpha["shadow_status"] = status
                alpha["shadow_end"] = datetime.now(CST).strftime("%Y-%m-%d")
                alpha["ic_decay_rate"] = round(decay_rate, 4)
                alpha["updated_at"] = datetime.now(CST).isoformat()
                updated_alpha = dict(alpha)
            return registry

        update_json(REGISTRY_INDEX, [], update_registry)
        if updated_alpha is None:
            return
        spec_file = REGISTRY_INDEX.parent / alpha_id / "alpha_spec.json"
        if spec_file.exists():
            def update_spec(spec):
                spec.update({
                    "shadow_status": status,
                    "shadow_end": updated_alpha["shadow_end"],
                    "ic_decay_rate": round(decay_rate, 4),
                    "updated_at": updated_alpha["updated_at"],
                })
                return spec

            update_json(spec_file, {}, update_spec)

    # ── 通知 ────────────────────────────────────────

    def _notify(self, alpha_id: str, name: str, status: str,
                decay_rate: float):
        """影子观察期结束通知"""
        try:
            from factor_lab.notify import notify_goal_done

            icon = "✅" if status == "available" else "⚠️"
            label = "可用" if status == "available" else "不稳定"
            msg = (
                f"{icon} 因子 {name} 影子观察结束\n"
                f"状态: {label}\n"
                f"IC 衰减率: {decay_rate:.1%}\n"
                f"Alpha ID: {alpha_id}"
            )
            notify_goal_done(f"影子观察: {name}", msg)
        except Exception as e:
            print(f"  ⚠️ 观察通知失败: {e}")

    # ── 辅助 ────────────────────────────────────────

    @staticmethod
    def _days_since(date_str: str) -> int:
        if not date_str:
            return 0
        try:
            start = datetime.strptime(date_str[:10], "%Y-%m-%d")
            return (datetime.now(CST) - start).days
        except Exception:
            return 0


# ── CLI 入口 ──────────────────────────────────────────


def cmd_shadow_status() -> str:
    """查看影子观察状态"""
    observer = ShadowObserver()
    registry = observer._load_registry()
    lines = ["🔭 影子观察状态:", ""]
    observing = [a for a in registry
                 if a.get("shadow_status") == "observing"]
    available = [a for a in registry
                 if a.get("shadow_status") == "available"]
    unstable = [a for a in registry
                if a.get("shadow_status") == "unstable"]
    pending = [a for a in registry
               if a.get("shadow_status") in ("", "pending")]

    lines.append(f"观察中: {len(observing)}")
    for a in observing:
        start = a.get("shadow_start", "?")[:10]
        days = observer._days_since(a.get("shadow_start", ""))
        lines.append(f"  {a.get('name','?'):30s} 自 {start} 已 {days}d")

    lines.append(f"\n可用: {len(available)}")
    for a in available:
        lines.append(f"  ✅ {a.get('name','?')}")

    lines.append(f"\n不稳定: {len(unstable)}")
    for a in unstable:
        decay = a.get("ic_decay_rate", 0)
        lines.append(f"  ⚠️ {a.get('name','?')} 衰减率={decay:.1%}")

    lines.append(f"\n待定: {len(pending)}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "tick":
        results = ShadowObserver().daily_tick()
        print(f"处理 {len(results)} 个到期因子")
        for r in results:
            print(f"  {r['name']}: {r['status']} (衰减={r['decay_rate']:.1%})")
    else:
        print(cmd_shadow_status())
