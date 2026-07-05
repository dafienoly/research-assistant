"""测试: 不存在借用账户指令"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

JSON_PATH = "/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json"
FORBIDDEN = [
    "buy_by_other_account", "borrow_account", "ask_friend_to_buy",
    "借账户买", "代买", "借他人账户", "让别人代买",
]
# allow_borrowed_account_execution=false 是政策声明, 不是指令, 允许出现
CONTEXT_ALLOWLIST = ["allow_borrowed_account_execution"]


def _scan(content, source_name):
    """扫描 content, 排除上下文允许的声明"""
    for term in FORBIDDEN:
        if term in content:
            # 检查是否在允许的上下文中
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if term in line:
                    # 如果同一行包含 allowlist 词, 跳过
                    if any(w in line for w in CONTEXT_ALLOWLIST):
                        continue
                    raise AssertionError(f"{source_name}:{i+1} 含禁用词 '{term}': {line.strip()}")


def test_no_forbidden_in_json():
    with open(JSON_PATH) as f:
        _scan(f.read(), "premarket_signal.json")


def test_no_forbidden_in_html():
    """HTML 无借用账户指令"""
    html_path = JSON_PATH.replace("premarket_signal.json", "premarket_signal.html")
    with open(html_path) as f:
        _scan(f.read(), "premarket_signal.html")


def test_no_forbidden_in_csv():
    """CSV 文件无借用账户指令"""
    import glob
    import os
    base = os.path.dirname(JSON_PATH)
    for csv_path in glob.glob(os.path.join(base, "*.csv")):
        with open(csv_path) as f:
            _scan(f.read(), os.path.basename(csv_path))
