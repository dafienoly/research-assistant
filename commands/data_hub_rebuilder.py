"""Data Hub Rebuilder — 补齐/重建因子引擎所需的时序数据文件

支持重建:
  1. fundamentals_timeseries.csv  — 从 Baostock 原始表聚合 (纯本地, 最快)
  2. fund_flow_timeseries.csv     — 从 mx:data API 逐批刷新 (需 API, 限速)
  3. news_sentiment_timeseries.csv — 从 mx:search + 情感打分重建 (需 API, 限速)

用法:
  python3 data_hub_rebuilder.py fundamentals   # 仅重建基本面时序
  python3 data_hub_rebuilder.py fund-flow      # 仅刷新资金流时序
  python3 data_hub_rebuilder.py sentiment      # 仅重建情感时序
  python3 data_hub_rebuilder.py all            # 重建全部
"""

import csv, sys, os, re, time, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

CST = timezone(timedelta(hours=8))
BASE = Path("/home/ly/.hermes/research-assistant")
DATA = BASE / "data"

sys.path.insert(0, str(BASE / "commands"))


def now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def date_id() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ===================================================================
# 1. fundamentals_timeseries.csv — 从 Baostock 原始表聚合
# ===================================================================

def rebuild_fundamentals_timeseries() -> dict:
    """从 Baostock 原始表 (profit/balance) 聚合生成基本面时序宽表"""
    print("\n📊 重建 fundamentals_timeseries.csv ...")

    profit = _read_csv(DATA / "fundamentals" / "profit_data.csv")
    balance = _read_csv(DATA / "fundamentals" / "balance_data.csv")

    if not profit:
        return {"status": "skipped", "reason": "profit_data.csv 不存在. 先运行 fundamentals:update-from-baostock"}

    # 按 (code, report_date) 索引 profit
    profit_idx = {}
    for r in profit:
        key = (r.get("code", ""), r.get("report_date", ""))
        profit_idx[key] = r

    # 按 (code, report_date) 索引 balance
    balance_idx = {}
    for r in balance:
        key = (r.get("code", ""), r.get("report_date", ""))
        balance_idx[key] = r

    # 合并
    rows = []
    keys = set(profit_idx.keys()) | set(balance_idx.keys())
    for code, report_date in sorted(keys):
        p = profit_idx.get((code, report_date), {})
        b = balance_idx.get((code, report_date), {})

        # 解析年份季度
        year, quarter = "", ""
        if report_date and "-" in report_date:
            parts = report_date.split("-")
            if len(parts) >= 2:
                year = parts[0]
                m = int(parts[1])
                quarter = str((m - 1) // 3 + 1)

        rows.append({
            "symbol": code,
            "name": "",
            "report_date": report_date,
            "pub_date": p.get("pub_date", b.get("pub_date", "")),
            "year": year,
            "quarter": quarter,
            "roe": p.get("roe", ""),
            "net_margin": p.get("net_margin", ""),
            "gross_margin": p.get("gross_margin", ""),
            "net_profit": p.get("net_profit", ""),
            "eps": p.get("eps", ""),
            "revenue": p.get("revenue", ""),
            "debt_ratio": b.get("debt_ratio", ""),
            "source": "baostock",
        })

    fields = ["symbol", "name", "report_date", "pub_date", "year", "quarter",
              "roe", "net_margin", "gross_margin", "net_profit", "eps",
              "revenue", "debt_ratio", "source"]
    _write_csv(DATA / "fundamentals" / "fundamentals_timeseries.csv", fields, rows)

    print(f"  ✅ 写入 {len(rows)} 条记录 ({len(keys)} 股票-季度组合)")
    return {"status": "ok", "rows": len(rows), "stocks": len(keys)}


# ===================================================================
# 2. fund_flow_timeseries.csv — mx:data API 批量刷新
# ===================================================================

def _parse_amount(val) -> float:
    """解析金额值 (含亿万单位)"""
    if val is None:
        return 0.0
    s = str(val).strip().replace(",", "").replace("\u200b", "")
    if not s or s in ("-", "--", ""):
        return 0.0
    m = re.match(r"([+-]?\d+\.?\d*)\s*(亿元|万元|元|亿|万)?", s)
    if m:
        num = float(m.group(1))
        unit = m.group(2) or ""
        if "亿" in unit:
            num *= 100_000_000
        elif "万" in unit:
            num *= 10_000
        return num
    try:
        return float(s)
    except ValueError:
        return 0.0


def _mx_data_query(question: str) -> dict:
    """调用 mx:data API"""
    import requests
    api_key = os.getenv("MX_APIKEY")
    if not api_key:
        return {"error": "MX_APIKEY 未设置"}
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    try:
        resp = requests.post(url, headers={"apikey": api_key, "Content-Type": "application/json"},
                             json={"toolQuery": question}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def _parse_fund_flow_from_mx(result: dict, code: str) -> list[dict]:
    """从 mx:data 主力资金流向的返回中解析时序数据

    API 返回格式 (已验证):
      - headName = 日期列表 (标准格式, 非转置)
      - nameMap = {数字编码: 指标中文名}
      - rawTable[数字编码] = 各日期的值数组 (与 headName 对齐)
    """
    records = []
    try:
        data = result.get("data", {})
        inner = data.get("data", {}) if isinstance(data, dict) else {}
        dtos = inner.get("searchDataResultDTO", {}).get("dataTableDTOList", [])
        if not dtos:
            dtos = data.get("searchDataResultDTO", {}).get("dataTableDTOList", [])
        if not dtos:
            dtos = inner.get("dataTableDTOList", [])
        if not dtos:
            return records
    except Exception:
        return records

    # 字段映射: 中文关键词 → 目标字段
    FIELD_MAP = [
        ("主力净流入", "net_main_force"),
        ("超大单净流入", "net_super_large"),
        ("大单净流入", "net_large"),
        ("中单净流入", "net_medium"),
        ("小单净流入", "net_small"),
        ("净流入天数", "days_inflow"),
        ("净流出天数", "days_outflow"),
    ]

    for table in dtos:
        try:
            # 只处理 A 股 (排除港股)
            entity_name = table.get("entityName", "") or ""
            if "(00763.HK)" in entity_name or ".HK)" in entity_name:
                continue

            secu_code = code
            if table.get("entityTagDTO"):
                secu_code = table["entityTagDTO"].get("secuCode", "") or secu_code
            elif table.get("entityTagDTOList"):
                secu_code = table["entityTagDTOList"][0].get("secuCode", "") or secu_code

            raw = table.get("table") or table.get("rawTable") or {}
            name_map = table.get("nameMap") or {}
            head_name = raw.get("headName", [])

            if not head_name or not isinstance(head_name, list):
                continue

            # 检查是否为标准日期格式
            if not re.match(r"\d{4}-\d{2}-\d{2}", str(head_name[0])):
                continue

            # 建立编码→字段的映射
            code_to_field = {}
            for raw_key, indicator_name in name_map.items():
                if raw_key == "headNameSub":
                    continue
                for keyword, field in FIELD_MAP:
                    if keyword in str(indicator_name):
                        code_to_field[raw_key] = field
                        break

            if "net_main_force" not in code_to_field.values():
                continue  # 这个 table 没有资金流向数据

            # 按日期提取数据
            for idx, date_str in enumerate(head_name):
                if not re.match(r"\d{4}-\d{2}-\d{2}", str(date_str)):
                    continue
                # 净化日期: 去除 "(日)" 等后缀
                clean_date = re.sub(r"\(.*?\)", "", str(date_str)).strip()
                rec = {
                    "symbol": secu_code,
                    "date": clean_date.replace("-", ""),
                    "net_main_force": 0.0,
                    "net_super_large": 0.0,
                    "net_large": 0.0,
                    "net_medium": 0.0,
                    "net_small": 0.0,
                    "days_inflow": 0,
                    "days_outflow": 0,
                }
                for raw_key, field in code_to_field.items():
                    vals = raw.get(raw_key, [])
                    if isinstance(vals, list) and idx < len(vals):
                        parsed = _parse_amount(vals[idx])
                        if field in ("days_inflow", "days_outflow"):
                            rec[field] = int(parsed)
                        else:
                            rec[field] = parsed
                records.append(rec)

        except Exception:
            continue

    return records


def refresh_fund_flow_timeseries(batch_size: int = 20) -> dict:
    """用 mx:data API 分批刷新资金流向时序

    参数:
        batch_size: 每次处理的股票数, 默认20 (受API配额限制)
    """
    print(f"\n💰 刷新 fund_flow_timeseries.csv (batch_size={batch_size}) ...")

    # 读取现有数据
    existing = _read_csv(DATA / "fundamentals" / "fund_flow_timeseries.csv")
    existing_by_stock = defaultdict(list)
    for r in existing:
        existing_by_stock[r.get("symbol", "")].append(r)

    print(f"  已有 {len(existing)} 条记录, {len(existing_by_stock)} 只股票")

    # 读取股票池
    pool = _read_csv(DATA / "market" / "pool.csv")
    if not pool:
        # 从现有数据回退
        codes = sorted(existing_by_stock.keys())
    else:
        codes = sorted(set(r["code"] for r in pool if r.get("code")))

    # 过滤: 已有数据的只补充最后2个交易日
    today = date_id()
    new_records = []
    updated = 0
    errors = 0

    for i, code in enumerate(codes):
        if i >= batch_size:
            print(f"  已达 batch_size={batch_size}, 剩余 {len(codes)-i} 只留待下次")
            break

        # 检查是否已有今日数据
        existing_dates = {r.get("date", "") for r in existing_by_stock.get(code, [])}
        if today.replace("-", "") in existing_dates:
            continue

        print(f"  [{i+1}/{min(batch_size, len(codes))}] {code} ...", end=" ")
        sys.stdout.flush()

        result = _mx_data_query(f"{code} 主力资金净流入 每日 2026-07-01 至 2026-07-07")
        if "error" in result:
            print(f"❌ {result['error']}")
            errors += 1
            time.sleep(3)
            continue

        records = _parse_fund_flow_from_mx(result, code)
        if records:
            # 去重: 只保留新日期
            for rec in records:
                if rec["date"] not in existing_dates:
                    new_records.append(rec)
            updated += 1
            print(f"✅ +{len(records)} 条")
        else:
            print("⚠️ 空结果")

        time.sleep(2.5)  # API 频率限制

    if new_records:
        all_rows = existing + new_records
        # 去重 (相同 symbol+date 保留后写入的)
        seen = set()
        deduped = []
        for r in reversed(all_rows):
            key = (r.get("symbol", ""), r.get("date", ""))
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        deduped.reverse()

        fields = ["symbol", "date", "net_main_force", "net_super_large",
                  "net_large", "net_medium", "net_small", "days_inflow", "days_outflow"]
        _write_csv(DATA / "fundamentals" / "fund_flow_timeseries.csv", fields, deduped)
        print(f"\n  ✅ 新增 {len(new_records)} 条, 去重后共 {len(deduped)} 条")
    else:
        print(f"  无新增数据")

    return {"status": "ok", "updated": updated, "errors": errors, "new_records": len(new_records)}


# ===================================================================
# 3. news_sentiment_timeseries.csv — mx:search + 情感打分
# ===================================================================

_SENTIMENT_KEYWORDS = {
    "positive": [
        "中标", "增长", "盈利", "突破", "签约", "采购", "订单", "合作",
        "回购", "增持", "分红", "利好", "新高", "获批", "投产", "量产",
        "交付", "出口", "扩张", "融资", "授予", "激励", "加码",
    ],
    "negative": [
        "减持", "亏损", "下跌", "风险", "违规", "处罚", "调查", "立案",
        "跌停", "st", "退市", "预警", " downgrade", "下调", "债务违约",
        "诉讼", "仲裁", "冻结", "查封", "破产", "重组失败",
    ],
}


def _score_sentiment(text: str) -> tuple[float, int, int, int]:
    """简单关键词情感打分"""
    pos_count = sum(1 for kw in _SENTIMENT_KEYWORDS["positive"] if kw in text)
    neg_count = sum(1 for kw in _SENTIMENT_KEYWORDS["negative"] if kw in text)
    total = pos_count + neg_count
    if total == 0:
        return 0.0, 0, 0, 0
    score = (pos_count - neg_count) / total
    return round(score, 2), pos_count, neg_count, 0


def rebuild_news_sentiment_timeseries(top_n: int = 50) -> dict:
    """用 mx:search + 关键词情感分析重建新闻情感时序

    参数:
        top_n: 处理多少只股票 (受 API 配额限制, 建议 20-50)
    """
    print(f"\n📰 重建 news_sentiment_timeseries.csv (top_n={top_n}) ...")

    pool = _read_csv(DATA / "market" / "pool.csv")
    if not pool:
        return {"status": "skipped", "reason": "pool.csv 不存在"}

    codes = sorted(set(r["code"] for r in pool if r.get("code")))[:top_n]
    records = []
    errors = 0
    skipped = 0

    for i, code in enumerate(codes):
        print(f"  [{i+1}/{len(codes)}] {code} ...", end=" ")
        sys.stdout.flush()

        result = _mx_data_query(f"{code} 最新公告 新闻 2026年7月")
        # Fallback: use mx:search
        try:
            import requests
            api_key = os.getenv("MX_APIKEY")
            url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search"
            resp = requests.post(url, headers={"apikey": api_key, "Content-Type": "application/json"},
                                 json={"query": f"{code} 最新公告 新闻 2026"}, timeout=30)
            resp.raise_for_status()
            search_result = resp.json()
        except Exception as e:
            print(f"❌ {e}")
            errors += 1
            time.sleep(2)
            continue

        # 提取新闻标题和摘要
        texts = []
        try:
            inner = search_result.get("data", {}).get("data", {})
            lr = inner.get("llmSearchResponse", {}).get("data", [])
            if not lr:
                lr = search_result.get("data", {}).get("llmSearchResponse", {}).get("data", [])
            for item in lr[:10]:
                title = item.get("newsTitle", "") or item.get("title", "")
                summary = item.get("summary", "") or item.get("content", "")
                if title:
                    texts.append(title + " " + summary)
        except Exception:
            pass

        if not texts:
            print("⚠️ 无新闻")
            skipped += 1
            time.sleep(2)
            continue

        # 合并所有文本做情感打分
        combined = " ".join(texts)
        score, pos, neg, neu = _score_sentiment(combined)
        today = datetime.now(CST).strftime("%Y%m%d")
        records.append({
            "symbol": code,
            "date": today,
            "sentiment_score": str(score),
            "sentiment_label": "positive" if score > 0.2 else ("negative" if score < -0.2 else "neutral"),
            "positive_count": str(pos),
            "negative_count": str(neg),
            "neutral_count": str(0),
        })
        print(f"✅ score={score} ({pos}P/{neg}N)")

        time.sleep(2)

    if records:
        # 合并现有数据
        existing = _read_csv(DATA / "news_sentiment_timeseries.csv")
        all_rows = existing + records
        fields = ["symbol", "date", "sentiment_score", "sentiment_label",
                  "positive_count", "negative_count", "neutral_count"]
        _write_csv(DATA / "news_sentiment_timeseries.csv", fields, all_rows)

    print(f"\n  ✅ 新增 {len(records)} 条情感记录, {errors} 错误, {skipped} 跳过")
    return {"status": "ok", "new_records": len(records), "errors": errors, "skipped": skipped}


# ===================================================================
# CLI
# ===================================================================

def main():
    targets = {
        "fundamentals": ("📊 基本面时序", rebuild_fundamentals_timeseries),
        "fund-flow": ("💰 资金流向时序", refresh_fund_flow_timeseries),
        "sentiment": ("📰 新闻情感时序", rebuild_news_sentiment_timeseries),
    }

    if len(sys.argv) < 2 or sys.argv[1] not in ("all", *targets.keys()):
        print("用法: python3 data_hub_rebuilder.py <target>")
        print(f"  targets: all, {', '.join(targets.keys())}")
        print(f"  示例: python3 data_hub_rebuilder.py fundamentals")
        print(f"        python3 data_hub_rebuilder.py fund-flow")
        print(f"        python3 data_hub_rebuilder.py all")
        sys.exit(1)

    cmd = sys.argv[1]
    results = {}

    if cmd == "all":
        for name, (label, func) in targets.items():
            print(f"\n{'='*50}")
            print(f"{label}")
            print(f"{'='*50}")
            try:
                results[name] = func()
            except Exception as e:
                print(f"  ❌ 错误: {e}")
                results[name] = {"status": "error", "error": str(e)}
    else:
        label, func = targets[cmd]
        print(f"\n{'='*50}")
        print(f"{label}")
        print(f"{'='*50}")
        try:
            results[cmd] = func()
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            results[cmd] = {"status": "error", "error": str(e)}

    print(f"\n{'='*50}")
    print("📋 汇总")
    print(f"{'='*50}")
    for name, r in results.items():
        status_icon = "✅" if r.get("status") == "ok" else "⚠️"
        print(f"  {status_icon} {name}: {r.get('status', 'unknown')}")
        for k, v in r.items():
            if k != "status":
                print(f"      {k}: {v}")

    return 0 if all(r.get("status") == "ok" for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
