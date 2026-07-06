"""WeChat Notifications for version events"""
import sys, os, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.notify import notify_goal_done


def version_completed(version: str, name: str, summary: str):
    if not version or version == "unknown":
        return
    notify_goal_done(f"📦 版本 {version} 完成", f"{name}: {summary}", "completed")


def version_blocked(version: str, name: str, reason: str):
    if not version or version == "unknown":
        return
    notify_goal_done(f"⛔ 版本 {version} 需人工审批", f"{name}\n原因: {reason}", "failed")


def version_failed(version: str, name: str, reason: str):
    if not version or version == "unknown":
        return
    notify_goal_done(f"❌ 版本 {version} 失败", f"{name}\n原因: {reason}", "failed")
