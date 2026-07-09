"""管线重试与告警封装

提供统一的 try/retry/告警逻辑，所有消费环节共用。
"""
from __future__ import annotations
import time
import traceback
import sys
from typing import Callable, Any
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def run_with_retry(
    fn: Callable[[], Any],
    task_name: str,
    task_id: str,
    max_retries: int = 1,
    delay_sec: float = 5.0,
) -> dict:
    """带重试和企微告警的执行封装

    Args:
        fn: 要执行的无参函数
        task_name: 任务名称（用于日志/告警）
        task_id: 任务 ID（用于追踪）
        max_retries: 最大重试次数（默认 1）
        delay_sec: 重试间隔秒数

    Returns:
        {"status": "ok", "result": ...} 或 {"status": "failed", "error": "..."}
    """
    last_exc = None
    tb = ""
    for attempt in range(max_retries + 1):
        try:
            result = fn()
            return {"status": "ok", "result": result}
        except Exception as e:
            last_exc = e
            tb = traceback.format_exc()
            print(f"  ⚠️ [{task_id}] 第 {attempt + 1}/{max_retries + 1} 次失败: {e}")
            if attempt < max_retries:
                time.sleep(delay_sec)
                continue

    # 所有重试耗尽 → 推送告警
    error_msg = f"{last_exc}"
    print(f"  ❌ [{task_id}] 所有重试失败: {error_msg}")
    _notify_failure(task_name, task_id, error_msg, tb)
    return {"status": "failed", "error": error_msg, "traceback": tb}


def _notify_failure(
    task_name: str,
    task_id: str,
    error: str,
    tb: str,
) -> None:
    """推送企微告警"""
    try:
        from factor_lab.notify import notify_goal_done

        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
        summary = (
            f"任务: {task_name}\n"
            f"ID: {task_id}\n"
            f"错误: {error}\n"
            f"堆栈: {tb[:500]}"
        )
        notify_goal_done(f"⚠️ 管线失败: {task_name}", summary)
    except Exception as notify_err:
        print(f"  ⚠️ 告警推送失败: {notify_err}")
