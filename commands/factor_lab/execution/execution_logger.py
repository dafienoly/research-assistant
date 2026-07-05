"""Execution Record — 成交记录加载与校验"""
import csv, json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.broker.broker_position_adapter import DEFAULT_FIELD_MAP

CST = timezone(timedelta(hours=8))

EXECUTION_FIELDS = ["trade_date", "symbol", "name", "side", "shares", "price", "amount", "fee", "tax", "slippage", "source", "notes"]

EXECUTION_FIELD_MAP = {**DEFAULT_FIELD_MAP,
    "成交日期": "trade_date", "日期": "trade_date",
    "买卖方向": "side", "方向": "side",
    "成交数量": "shares", "成交价格": "price",
    "成交金额": "amount", "金额": "amount",
    "手续费": "fee", "印花税": "tax", "滑点": "slippage",
}


def load_executions(path: str) -> dict:
    """加载成交记录"""
    result = {
        "source_path": path,
        "executions": [],
        "errors": [],
        "warnings": [],
        "status": "ok",
    }
    if not os.path.exists(path):
        result["errors"].append(f"文件不存在: {path}")
        result["status"] = "failed"
        return result

    ext = Path(path).suffix.lower()
    rows = []
    if ext == ".csv":
        encodings = ["utf-8-sig", "utf-8", "gbk"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    rows = list(csv.DictReader(f))
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
    elif ext == ".json":
        with open(path) as f:
            data = json.load(f)
            rows = data if isinstance(data, list) else data.get("executions", [])
    else:
        result["errors"].append(f"不支持格式: {ext}")
        result["status"] = "failed"
        return result

    for i, row in enumerate(rows):
        normalized = _normalize_execution(row, i, result)
        if normalized:
            result["executions"].append(normalized)

    if result["errors"]:
        result["status"] = "failed"
    elif result["warnings"]:
        result["status"] = "partial"
    return result


def _normalize_execution(row, i, result):
    """标准化单条成交记录"""
    # 字段映射
    mapped = {}
    for k, v in row.items():
        std = EXECUTION_FIELD_MAP.get(k.strip(), k.strip())
        mapped[std] = str(v).strip() if v else ""

    sym = mapped.get("symbol", "")
    if not sym:
        result["warnings"].append(f"第{i+1}行缺少 symbol")
        return None

    trade_date = mapped.get("trade_date", "")
    if not trade_date:
        result["warnings"].append(f"{sym}: 缺少 trade_date")

    side = mapped.get("side", "").lower()
    if side not in ("buy", "sell", "买入", "卖出"):
        result["warnings"].append(f"{sym}: side={side} 异常")
    mapped["side"] = "buy" if side in ("buy", "买入") else "sell"

    try:
        shares = int(float(mapped.get("shares", 0)))
        if shares % 100 != 0:
            result["warnings"].append(f"{sym}: shares={shares} 不是100的倍数")
        mapped["shares"] = shares
    except:
        result["errors"].append(f"{sym}: shares 格式错误")
        return None

    try:
        mapped["price"] = float(mapped.get("price", 0))
    except:
        mapped["price"] = 0.0

    try:
        mapped["amount"] = float(mapped.get("amount", 0))
    except:
        mapped["amount"] = round(float(mapped.get("shares", 0)) * float(mapped.get("price", 0)), 2) if mapped.get("price") else 0.0

    for field in ("fee", "tax", "slippage"):
        try:
            mapped[field] = float(mapped.get(field, 0))
        except:
            mapped[field] = 0.0

    return mapped


def save_execution_log(executions: list, output_dir: str):
    """保存标准化成交记录"""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "execution_log.json")
    with open(path, "w") as f:
        json.dump(executions, f, indent=2, ensure_ascii=False)
    csv_path = os.path.join(output_dir, "normalized_executions.csv")
    if executions:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=EXECUTION_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(executions)
