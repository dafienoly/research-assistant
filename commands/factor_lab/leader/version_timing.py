# Version timing — 插入版本开始/结束计时
# 在 auto_executor.py 中

# 在 auto_run_once() 开始时记录：
#   version_start_time = datetime.now(CST).isoformat()
# 在 advance() 后记录 end_time，并生成报告

_version_timings = {}

def record_start(version: str):
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))
    _version_timings[version] = {"started_at": datetime.now(CST).isoformat()}

def record_end(version: str, status: str):
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))
    if version not in _version_timings:
        _version_timings[version] = {}
    _version_timings[version]["ended_at"] = datetime.now(CST).isoformat()
    _version_timings[version]["status"] = status
    # 计算耗时
    import json
    from pathlib import Path
    timings_file = Path("/mnt/d/HermesReports/version_timings.json")
    all_timings = json.loads(timings_file.read_text()) if timings_file.exists() else {}
    all_timings[version] = _version_timings[version]
    timings_file.write_text(json.dumps(all_timings, indent=2, ensure_ascii=False))
