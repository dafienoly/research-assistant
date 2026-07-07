#!/usr/bin/env python3
"""Hermes 投研日度自动化管线
   交易日:
     07:30  →  北向/两融/事件增量拉取（手动触发）
     16:00  →  资金流向 + 新闻情绪拉取
     16:30  →  自动 factor:mine
   周日:
     10:00  →  自动 factor:evolve + factor:mine
"""
import sys, subprocess, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
NOW = datetime.now(CST)
TODAY = NOW.strftime("%Y-%m-%d")
HOUR = NOW.hour
DOW = NOW.weekday()
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent  # research-assistant/
_COMMANDS_DIR = _PROJECT_ROOT / "commands"
VENV = str(_PROJECT_ROOT / ".venv_quant" / "bin" / "python3")
BASE = str(_COMMANDS_DIR)
LOG_DIR = Path(f"/mnt/d/HermesReports/daily_pipeline/{TODAY.replace('-','')}")

def log(msg):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(CST).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    (LOG_DIR / "pipeline.log").open("a").write(line + "\n")

def run(cmd, timeout=300):
    log(f"  $ {cmd[:100]}...")
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

def step_close_data():
    log("=== 收盘数据拉取 ===")
    for script, label in [
        ("/tmp/fetch_fundflow.py", "资金流向"),
        ("/tmp/fetch_news_sentiment.py", "新闻情绪"),
    ]:
        r = run(f"cd {BASE} && {VENV} {script}")
        log(f"  {'✅' if r.returncode==0 else '❌'} {label}")
        if r.stdout:
            for l in r.stdout.strip().split("\n")[-3:]:
                log(f"    {l}")

def step_mine():
    log("=== factor:mine ===")
    r = run(f"cd {BASE} && {VENV} {BASE}/factor_lab/pipeline.py")
    log(f"  {'✅' if r.returncode==0 else '❌'} factor:mine")
    for line in r.stdout.strip().split("\n"):
        if any(k in line for k in ["报告已生成", "因子计算完成"]):
            log(f"  {line.strip()}")

def step_evolve():
    log("=== factor:evolve ===")
    r = run(f"cd {BASE} && {VENV} /tmp/daily_evolve.py")
    log(f"  {'✅' if r.returncode==0 else '❌'} evolve")
    for line in r.stdout.strip().split("\n"):
        log(f"  {line}")
    step_mine()

def main():
    log(f"{'='*50}")
    log(f"Hermes 日度管线 | {TODAY} 周{DOW+1}")
    log(f"{'='*50}")

    if DOW == 6 and HOUR >= 9:  # 周日 09:00+
        step_evolve()
    elif DOW < 5:  # 工作日
        if 15 <= HOUR < 18:
            step_close_data()
            if HOUR >= 16:
                step_mine()
        else:
            log(f"当前 {HOUR}:00 — 非运行时段（工作日 16:00-18:00/周日 09:00+）")
    else:
        log("周末跳过")

    log("✅ 管线完成")

if __name__ == "__main__":
    main()
