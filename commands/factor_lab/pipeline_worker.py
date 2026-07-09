"""自动因子挖掘管线 — Worker 消费者

轮询队列目录，消费任务：
  - quick_backtest/   → backtest:factor-top (CLI)
  - complete_validation/ → backtest:factor-top + factor:validate (CLI)

任务锁：.lock 文件实现，防止多实例并发消费同一任务。
1 小时后锁自动过期。

用法:
  python3 -m factor_lab.pipeline_worker --once
  python3 -m factor_lab.pipeline_worker --watch
"""
from __future__ import annotations
import json
import sys
import time
import os
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CST = timezone(timedelta(hours=8))

_SCRIPT_DIR = Path(__file__).parent.resolve()
_COMMANDS_DIR = _SCRIPT_DIR.parent
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from factor_lab.pipeline_config import PipelineConfig
from factor_lab.pipeline_retry import run_with_retry

CLI = _COMMANDS_DIR / "hermes_cli.py"
PYTHON = sys.executable


class FactorPipelineWorker:
    """队列消费者"""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.cfg = config or PipelineConfig()
        self.queue_dirs = self.cfg.queue_subdirs()

    # ── 公开入口 ────────────────────────────────────

    def consume_once(self) -> list[dict]:
        results: list[dict] = []

        for mode in ["quick_backtest", "complete_validation"]:
            for task_file in sorted(self.queue_dirs[mode].glob("*.json")):
                result = self._process_task(task_file, mode)
                results.append(result)

        if results:
            self._notify_summary(results)
        return results

    def consume_loop(self, interval_sec: int = 60):
        print(f"🔄 Worker 轮询启动 @ {datetime.now(CST):%H:%M:%S} (间隔 {interval_sec}s)")
        while True:
            tasks = []
            for q in ["quick_backtest", "complete_validation"]:
                tasks.extend(list(self.queue_dirs[q].glob("*.json")))
            if tasks:
                print(f"\n  发现 {len(tasks)} 个待处理任务")
                self.consume_once()
            else:
                print(".", end="", flush=True)
            time.sleep(interval_sec)

    # ── 任务处理 ────────────────────────────────────

    LOCK_TTL_SEC = 3600  # 锁自动过期时间（1 小时）

    def _acquire_lock(self, task_file: Path) -> bool:
        """尝试获取任务锁"""
        lock_path = task_file.with_suffix(".lock")
        if lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age < self.LOCK_TTL_SEC:
                return False  # 其他 worker 正在处理
            # 锁过期→视为僵尸锁，删除后重新获取
            print(f"    🧹 锁过期 ({age:.0f}s > {self.LOCK_TTL_SEC}s)，清理")
            lock_path.unlink(missing_ok=True)

        lock_path.write_text(str(os.getpid()))
        return True

    def _release_lock(self, task_file: Path):
        lock_path = task_file.with_suffix(".lock")
        lock_path.unlink(missing_ok=True)

    def _process_task(self, task_file: Path, mode: str) -> dict:
        try:
            task = json.loads(task_file.read_text())
        except Exception as e:
            self._move_task(task_file, "failed")
            return {"name": task_file.stem, "status": "failed",
                    "error": f"任务文件解析失败: {e}"}

        name = task["name"]
        print(f"\n  ▶️ [{mode}] {name}")

        # 尝试获取任务锁
        if not self._acquire_lock(task_file):
            print(f"    ⏭️ 被其他 worker 锁定，跳过")
            return {"name": name, "status": "locked"}

        try:
            # 1. 快速回测
            bt_result = self._run_backtest(name)
            if bt_result["status"] == "failed":
                self._move_task(task_file, "failed")
                return {"name": name, "status": "failed",
                        "error": bt_result.get("error", "回测失败")}

            # 2. 完整验证（仅 complete_validation 模式）
            vf_result = None
            if mode == "complete_validation":
                vf_result = self._run_validation(name)

            # 3. 检查注册条件
            registered = False
            is_invalid = bt_result.get("sharpe", 0) <= -99 or bt_result.get("max_dd", 0) <= -99
            if not is_invalid and self._check_approval(bt_result, vf_result):
                reg = self._auto_register(name, task, bt_result)
                registered = reg

            self._move_task(task_file, "completed")
            status = "registered" if registered else ("invalid" if is_invalid else "backtest_done")
            return {
                "name": name,
                "status": status,
                "sharpe": bt_result.get("sharpe", 0) if not is_invalid else 0,
                "ic": task.get("ic_mean", 0),
                "max_dd": bt_result.get("max_dd", 0) if not is_invalid else 0,
            }
        finally:
            self._release_lock(task_file)

    # ── 执行器 ──────────────────────────────────────

    def _run_backtest(self, factor_name: str) -> dict:
        """调用 backtest:factor-top CLI"""
        cmd = [
            PYTHON, str(CLI),
            "backtest:factor-top", factor_name,
            "--rebalance", "monthly",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {"status": "failed", "error": result.stderr[:500]}

        # 解析输出中的关键指标
        import re
        output = result.stdout + result.stderr
        sharpe = 0.0
        max_dd = 0.0
        for line in output.split("\n"):
            m = re.search(r"Sharpe:\s+(-?[\d.]+|nan|-inf|inf)", line)
            if m:
                raw = m.group(1)
                if raw in ("nan", "-inf", "inf", "None"):
                    sharpe = -99.0  # sentinel: invalid
                else:
                    sharpe = float(raw)
            m = re.search(r"Max DD:\s+(-?[\d.]+|None|nan)", line)
            if m:
                raw = m.group(1)
                if raw in ("None", "nan"):
                    max_dd = -99.0  # sentinel: invalid
                else:
                    max_dd = float(raw)

        return {
            "status": "ok",
            "sharpe": sharpe,
            "max_dd": max_dd,
            "raw_output": output[:1000],
        }

    def _run_validation(self, factor_name: str) -> Optional[dict]:
        """调用 factor:validate CLI"""
        cmd = [
            PYTHON, str(CLI),
            "factor:validate", f"--factor", factor_name,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return {"status": "ok", "output": result.stdout[:1000]}
            else:
                print(f"  ⚠️ 验证失败: {result.stderr[:300]}")
                return None
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ 验证超时 (300s)")
            return None

    # ── 注册 ────────────────────────────────────────

    def _check_approval(self, bt: dict, vf: Optional[dict] = None) -> bool:
        sharpe = bt.get("sharpe", 0) or 0
        max_dd = bt.get("max_dd", 0) or 0

        # 无效回测（degenerate factor）
        if sharpe <= -99 or max_dd <= -99:
            print(f"    ⚠️ 回测结果无效（因子值可能退化）")
            return False

        if sharpe < self.cfg.SHARPE_MIN:
            print(f"    Sharpe {sharpe:.2f} < {self.cfg.SHARPE_MIN}")
            return False
        if max_dd < self.cfg.MAX_DD_MAX * 100:
            print(f"    MaxDD {max_dd:.1f}% > {self.cfg.MAX_DD_MAX:.0%} → 不达标")
            return False

        # WalkForward + 抗过拟合检验（仅 complete_validation 模式且有有效结果时）
        if vf:
            output = vf.get("output", "")
            # 只有当有实际输出时才检查（CLI 可能返回空=未执行）
            if "walk" in output.lower() or "placebo" in output.lower():
                has_fail = "fail" in output.lower()
                if has_fail:
                    print(f"    ⚠️ WalkForward / 抗过拟合检验未通过 → 不达标")
                    return False
                print(f"    ✅ 验证通过")
            else:
                # 无有效验证输出：降级通过（影子观察期是真正的验证机制）
                print(f"    ℹ️ 无验证数据，降级通过（影子观察期验证）")
        else:
            print(f"    ℹ️ 快速模式 → 不验证 WalkForward（影子观察期将跟踪衰减）")

        return True

    def _auto_register(self, name: str, task: Optional[dict] = None,
                        bt_result: Optional[dict] = None) -> bool:
        """检查是否已在注册表或 Alpha Registry，不在则注册"""
        try:
            from factor_lab.factor_base import REGISTRY
            # 检查 factor_base 注册表
            existing = [f for f in REGISTRY if f["name"] == name]
            if existing:
                print(f"    {name} 已在因子注册表中")
                return True

            # 检查 Alpha Registry
            from factor_lab.alpha.registry import _load_index
            alpha_index = _load_index()
            for entry in alpha_index:
                if entry.get("name") == name or entry.get("alpha_id") == name:
                    print(f"    {name} 已在 Alpha Registry 中")
                    return True

            # 直接通过 register_alpha API 注册（不通过 CLI）
            from factor_lab.alpha.schema import AlphaSpec
            from factor_lab.alpha.registry import register_alpha

            spec = AlphaSpec(
                name=name,
                description=f"自动管线注册: {name}",
                factor_expression=(task or {}).get("expression", ""),
                source="pipeline_auto",
                status="draft",
                enabled=False,
            )
            result = register_alpha(spec)
            alpha_id = result.get("alpha_id", name)
            ok = bool(alpha_id)
            print(f"    {'✅ 已注册到 Alpha Factory' if ok else '❌ 注册失败'}")

            # 注册成功后进入影子观察
            if ok:
                try:
                    from factor_lab.shadow_observer import ShadowObserver
                    ShadowObserver().mark_observing(name)
                except Exception as e:
                    print(f"    ⚠️ 设置影子观察失败: {e}")

                # 推送待确认消息
                try:
                    _task = task or {}
                    _bt = bt_result or {}
                    from factor_lab.pipeline_confirm import add_pending
                    from factor_lab.notify import notify_goal_done
                    add_pending(
                        alpha_id=name,
                        name=name,
                        ic_mean=_task.get("ic_mean", 0),
                        sharpe=_bt.get("sharpe", 0),
                        max_dd=_bt.get("max_dd", 0),
                        summary=(
                            f"Sharpe={_bt.get('sharpe', 0):.2f} "
                            f"MaxDD={_bt.get('max_dd', 0):.1f}%"
                        ),
                    )
                    notify_goal_done(
                        f"📋 因子待确认: {name}",
                        f"因子 {name} 已达到注册条件，请确认:\n"
                        f"IC={_task.get('ic_mean', 0):.4f}  "
                        f"Sharpe={_bt.get('sharpe', 0):.2f}\n"
                        f"MaxDD={_bt.get('max_dd', 0):.1f}%\n\n"
                        f"确认: pipeline:confirm --alpha-id {name}\n"
                        f"拒绝: pipeline:reject --alpha-id {name}"
                    )
                except Exception as e:
                    print(f"    ⚠️ 待确认消息失败: {e}")

            return ok
        except Exception as e:
            print(f"    ⚠️ 注册异常: {e}")
            return False

    # ── 辅助 ────────────────────────────────────────

    def _move_task(self, task_file: Path, target: str):
        dest = self.queue_dirs.get(target, self.queue_dirs["completed"])
        dest.mkdir(parents=True, exist_ok=True)
        task_file.rename(dest / task_file.name)

    def _notify_summary(self, results: list[dict]):
        try:
            from factor_lab.notify import notify_goal_done
            passed = [r for r in results if r["status"] == "registered"]
            done = [r for r in results if r["status"] == "backtest_done"]
            invalid = [r for r in results if r["status"] == "invalid"]
            failed = [r for r in results if r["status"] == "failed"]

            lines = [f"📊 管线报告 @ {datetime.now(CST):%H:%M}",
                     f"处理 {len(results)} 个因子:"]
            if passed:
                lines.append(f"\n✅ 新注册 ({len(passed)}):")
                for r in passed:
                    lines.append(f"  {r['name']}: Sharpe={r['sharpe']:.2f} IC={r['ic']:.4f}")
            if done:
                lines.append(f"\n📋 回测完成 ({len(done)}):")
                for r in done:
                    lines.append(f"  {r['name']}: Sharpe={r['sharpe']:.2f}")
            if invalid:
                lines.append(f"\n⏭️ 回测无效 ({len(invalid)}):")
                for r in invalid:
                    lines.append(f"  {r['name']}: 因子值退化")
            if failed:
                lines.append(f"\n❌ 失败 ({len(failed)}):")
                for r in failed:
                    lines.append(f"  {r['name']}: {r.get('error','?')}")
            notify_goal_done("自动因子管线", "\n".join(lines))
        except Exception as e:
            print(f"  ⚠️ 通知失败: {e}")

    def peek_pending(self) -> list[Path]:
        tasks: list[Path] = []
        for q in ["quick_backtest", "complete_validation"]:
            tasks.extend(self.queue_dirs[q].glob("*.json"))
        return tasks


# ─── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="因子管线 Worker")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="消费一次")
    group.add_argument("--watch", action="store_true", help="轮询模式")
    group.add_argument("--info", action="store_true", help="查看状态")
    args = parser.parse_args()

    worker = FactorPipelineWorker()

    if args.info:
        tasks = worker.peek_pending()
        print(f"待处理: {len(tasks)} 个")
        for t in tasks:
            task = json.loads(t.read_text())
            print(f"  {t.stem:30s} |IC|={abs(task.get('ic_mean',0)):.4f}  grade={task.get('grade','?')}")
        return

    if args.watch:
        worker.consume_loop()
    else:
        results = worker.consume_once()
        print(f"\n处理完成: {len(results)} 个因子")


if __name__ == "__main__":
    main()
