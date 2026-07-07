#!/usr/bin/env python3
"""mx:data 步进拉取 — 每日约 20 只，逐步补全北向/两融/事件数据

运行方式:
    cd /home/ly/.hermes/research-assistant/commands
    source /home/ly/.hermes/research-assistant/.venv_quant/bin/activate
    python3 /home/ly/.hermes/research-assistant/scripts/mx_fetch_step.py

逻辑:
  - 从关注池获取所有股票代码（~310 只）
  - 对每个表，跳过已有数据的股票
  - 每批查询 5 只，拉取 ~20 只/日/表
  - 解析 JSON 后追加写入 CSV
"""
import sys, os, csv, subprocess, json, re, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CST = timezone(timedelta(hours=8))
APIKEY = "mkt_pWU9CKf9BhFJqe3W3OXcUDOeLivCj7jWEpK-lhcrY28"
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent  # research-assistant/
_COMMANDS_DIR = _PROJECT_ROOT / "commands"
MX_DATA = str(_PROJECT_ROOT / ".hermes" / "skills" / "mx-data" / "mx_data.py")
VENV = str(_PROJECT_ROOT / ".venv_quant" / "bin" / "python3")
BASE = str(_COMMANDS_DIR)
DATA = _PROJECT_ROOT / "data"

BATCH = 5  # mx:data 每批查 5 只


def log(msg):
    ts = datetime.now(CST).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def get_pool() -> list:
    """获取关注池所有股票代码"""
    _p = BASE
    if _p not in sys.path:
        sys.path.insert(0, _p)
    from strategy_lab.universe import build
    pool = set()
    for u in ["manual_watchlist", "today_candidates"]:
        st, _ = build(u)
        for x in st:
            pool.add(x["symbol"])
    return sorted(pool)


def get_existing(path: Path) -> set:
    """获取 CSV 中已有的股票代码"""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8-sig") as f:
        return {row["symbol"] for row in csv.DictReader(f)}


def find_json(out_dir: str) -> str:
    for f in os.listdir(out_dir):
        if f.endswith("_raw.json"):
            return os.path.join(out_dir, f)
    return ""


# ─── 金额/数值解析 ────────────────────────────────────────────────

def parse_amount(val) -> float:
    """解析可能带单位的金额为 float 元"""
    if val is None:
        return 0.0
    s = str(val).strip().replace(",", "")
    if not s or s in ("-", "--", ""):
        return 0.0
    # 带单位: 亿元, 万元, 元
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


def parse_date(d) -> str:
    """统一日期格式为 YYYYMMDD"""
    if not d:
        return ""
    s = str(d).strip()
    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    # YYYYMMDD
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return s[:8]
    return s[:8]


# ═══════════════════════════════════════════════════════════════════
# 解析器 — 两融 (margin)
# ═══════════════════════════════════════════════════════════════════

def parse_margin(json_path: str) -> list[dict]:
    """
    从 mx:data JSON 解析两融数据。
    期望查询: "融资融券 融资买入额 融资偿还额 融券余量 每日"
    返回: [{symbol, date, margin_buy, margin_repay, margin_balance,
             margin_ratio, sec_lending_volume, sec_lending_balance}]
    """
    if not json_path or not os.path.exists(json_path):
        return []
    with open(json_path) as f:
        data = json.load(f)
    try:
        sd = data["data"]["data"]["searchDataResultDTO"]
    except (KeyError, TypeError):
        return []

    tbls = sd.get("dataTableDTOList", [])
    if not tbls:
        return []

    rows = []
    for tbl in tbls:
        rt = tbl.get("rawTable", {})
        nm = tbl.get("nameMap", {})
        hn = rt.get("headName", [])
        if not hn:
            continue

        # 获取股票代码
        secu_code = ""
        etd = tbl.get("entityTagDTO", {})
        if etd:
            secu_code = etd.get("secuCode", "")
        if not secu_code:
            for h in hn:
                m = re.search(r"\((\d{6})\.", h)
                if m:
                    secu_code = m.group(1)
                    break

        # 确认是两融表: 检查 nameMap 是否有融资买入额/融资余额等关键词
        nm_values = [str(v) for v in nm.values()]
        nm_keys = " ".join(nm_values)
        has_margin = any(kw in nm_keys for kw in ["融资买入", "融资偿还", "融资余额", "融券余额", "融资融券"])
        if not has_margin:
            continue

        # headName 应该是日期列表
        dates = hn
        # 映射 nameMap key -> 中文名
        key_to_name = {k: str(v) for k, v in nm.items()}
        # 找出各指标的 key
        buy_key = None      # 融资买入额
        repay_key = None    # 融资偿还额
        balance_key = None  # 融资余额
        sl_balance_key = None  # 融券余额
        sl_vol_key = None   # 融券卖出量

        for k, name in key_to_name.items():
            if k == "headNameSub":
                continue
            if "融资买入额" in name or "融资买入" in name:
                buy_key = k
            elif "融资偿还额" in name or "融资偿还" in name:
                repay_key = k
            elif "融资余额" in name:
                balance_key = k
            elif "融券余额" in name:
                sl_balance_key = k
            elif "融券卖出量" in name:
                sl_vol_key = k

        if not balance_key and not buy_key:
            continue  # 不是有效的两融数据表

        for i, dt in enumerate(dates):
            row = {"symbol": secu_code, "date": parse_date(dt)}
            row["margin_buy"] = parse_amount(rt.get(buy_key, [""])[i]) if buy_key and i < len(rt.get(buy_key, [])) else 0.0
            row["margin_repay"] = parse_amount(rt.get(repay_key, [""])[i]) if repay_key and i < len(rt.get(repay_key, [])) else 0.0
            row["margin_balance"] = parse_amount(rt.get(balance_key, [""])[i]) if balance_key and i < len(rt.get(balance_key, [])) else 0.0
            row["sec_lending_balance"] = parse_amount(rt.get(sl_balance_key, [""])[i]) if sl_balance_key and i < len(rt.get(sl_balance_key, [])) else 0.0
            # 融券卖出量和 margin_ratio 暂时不填，API 不一定有
            row["sec_lending_volume"] = parse_amount(rt.get(sl_vol_key, [""])[i]) if sl_vol_key and i < len(rt.get(sl_vol_key, [])) else 0.0
            row["margin_ratio"] = 0.0
            rows.append(row)

    return rows


# ═══════════════════════════════════════════════════════════════════
# 解析器 — 北向资金 / 资金流向
# ═══════════════════════════════════════════════════════════════════

def parse_north_flow(json_path: str) -> list[dict]:
    """
    从 mx:data JSON 解析资金流向数据 (作为北向资金代理)。
    期望查询: "沪深港通 资金流向 每日 历史" 或 "资金流向 每日 历史"
    返回: [{symbol, date, nb_net_flow, nb_total_buy, nb_total_sell,
             nb_holding_value, nb_holding_ratio}]
    """
    if not json_path or not os.path.exists(json_path):
        return []
    with open(json_path) as f:
        data = json.load(f)
    try:
        sd = data["data"]["data"]["searchDataResultDTO"]
    except (KeyError, TypeError):
        return []

    entity_list = sd.get("entityTagDTOList", [])
    tbls = sd.get("dataTableDTOList", [])
    if not tbls:
        return []

    rows = []
    for tbl in tbls:
        rt = tbl.get("rawTable", {})
        nm = tbl.get("nameMap", {})
        hn = rt.get("headName", [])
        if not hn:
            continue

        # 获取股票代码
        secu_code = ""
        etd = tbl.get("entityTagDTO", {})
        if etd:
            secu_code = etd.get("secuCode", "")
        if not secu_code and entity_list:
            secu_code = entity_list[0].get("secuCode", "")

        nm_values = [str(v) for v in nm.values()]
        nm_keys_str = " ".join(nm_values)

        # 检测是"时间"格式 (transposed: nameMap keys = dates, headName = fields)
        # 特征: nameMap 值看起来像日期 (YYYY-MM-DD)
        date_like_keys = sum(1 for v in nm_values if re.match(r"\d{4}-\d{2}-\d{2}", v))
        is_transposed = date_like_keys >= 3

        if is_transposed:
            # 格式: headName = [涨跌幅(%), 成交额(万元), 主力净流入金额(万元), ...]
            #       nameMap = {"0": "2026-07-06", "1": "2026-07-03", ...}
            #       rawTable["0"] = [涨跌幅, 成交额, 主力净流入金额, ...]
            # 找出 main_force_net (主力净流入) 在 headName 中的索引
            flow_idx = None
            for i, h in enumerate(hn):
                h_clean = str(h).strip()
                if "主力净流入" in h_clean or "主力资金净流入" in h_clean:
                    flow_idx = i
                    break
            if flow_idx is None:
                continue

            for date_key, date_val in nm.items():
                if date_key == "headNameSub":
                    continue
                dt_str = str(date_val)
                # 跳过日期区间 (如 "2026-01-05至2026-07-07")
                if "至" in dt_str or "~" in dt_str or "–" in dt_str or "—" in dt_str:
                    continue
                if not re.match(r"\d{4}-\d{2}-\d{2}", dt_str):
                    continue
                date_str = parse_date(dt_str)
                vals = rt.get(date_key, [])
                net_flow = parse_amount(vals[flow_idx]) if flow_idx < len(vals) else 0.0
                if not date_str or not (date_str.isdigit() and len(date_str) == 8):
                    continue  # skip invalid dates
                rows.append({
                    "symbol": secu_code,
                    "date": date_str,
                    "nb_net_flow": net_flow,
                    "nb_total_buy": 0.0,
                    "nb_total_sell": 0.0,
                    "nb_holding_value": 0.0,
                    "nb_holding_ratio": 0.0,
                })
        else:
            # 标准格式: headName = 日期, rawTable keys = 指标编码
            # 检查是否有资金流向数据
            has_flow = any("净流入" in str(v) or "主力" in str(v) or "沪深港通" in str(v) or "北向" in str(v) for v in nm_values)
            if not has_flow:
                continue

            dates = hn
            key_to_name = {k: str(v) for k, v in nm.items()}
            flow_key = None
            for k, name in key_to_name.items():
                if k == "headNameSub":
                    continue
                if "主力净流入" in name or "资金净流入" in name or "主力净流入资金" in name:
                    flow_key = k
                    break

            if not flow_key:
                continue

            flow_vals = rt.get(flow_key, [])
            for i, dt in enumerate(dates):
                nf = parse_amount(flow_vals[i]) if i < len(flow_vals) else 0.0
                date_str = parse_date(dt)
                if not date_str or not (date_str.isdigit() and len(date_str) == 8):
                    continue  # skip invalid dates
                rows.append({
                    "symbol": secu_code,
                    "date": date_str,
                    "nb_net_flow": nf,
                    "nb_total_buy": 0.0,
                    "nb_total_sell": 0.0,
                    "nb_holding_value": 0.0,
                    "nb_holding_ratio": 0.0,
                })

    return rows


# ═══════════════════════════════════════════════════════════════════
# 解析器 — 事件数据
# ═══════════════════════════════════════════════════════════════════

def parse_events(json_path: str) -> list[dict]:
    """
    从 mx:data JSON 解析事件数据 (限售解禁/分红/回购/业绩预告)。
    返回: [{symbol, date, event_type, event_desc, impact_score}]
    """
    if not json_path or not os.path.exists(json_path):
        return []
    with open(json_path) as f:
        data = json.load(f)
    try:
        sd = data["data"]["data"]["searchDataResultDTO"]
    except (KeyError, TypeError):
        return []

    tbls = sd.get("dataTableDTOList", [])
    entity_list = sd.get("entityTagDTOList", [])
    if not tbls:
        return []

    def _get_code(tbl) -> str:
        etd = tbl.get("entityTagDTO", {})
        if etd:
            return etd.get("secuCode", "")
        if entity_list:
            return entity_list[0].get("secuCode", "")
        return ""

    rows = []
    for tbl in tbls:
        rt = tbl.get("rawTable", {})
        nm = tbl.get("nameMap", {})
        hn = rt.get("headName", [])
        if not hn:
            continue

        secu_code = _get_code(tbl)
        nm_values = [str(v) for v in nm.values()]
        nm_str = " ".join(nm_values)

        # --- 限售解禁 ---
        if any(kw in nm_str for kw in ["解禁", "限售", "流通数量"]):
            # 格式: headName = [本期流通数量, 占A股比例, ...]
            #       nameMap = {"0": "2026-07-14", "1": "2026-07-13", ...}
            #       rt["0"] = [流通数量值, 比例值, ...]
            date_like_keys = [(k, v) for k, v in nm.items()
                              if k != "headNameSub" and re.match(r"\d{4}-\d{2}-\d{2}", str(v))]
            for k, dt_val in date_like_keys:
                vals = rt.get(k, [])
                unlock_shares = vals[0] if len(vals) > 0 else ""
                unlock_ratio = vals[1] if len(vals) > 1 else ""
                desc = f"限售解禁: {unlock_shares}万股, 占流通A股{unlock_ratio}%"
                rows.append({
                    "symbol": secu_code,
                    "date": parse_date(str(dt_val)),
                    "event_type": "share_unlock",
                    "event_desc": desc,
                    "impact_score": 0.3,
                })

        # --- 分红 ---
        elif any(kw in nm_str for kw in ["分红", "股利", "股息"]):
            # 格式: headName = ["2025年度分配", "2025中期分配", ...]
            # 或 headName = ["2025-12-31", "2025-06-30", ...]
            for i, h in enumerate(hn):
                h_str = str(h)
                # 尝试从 headName 解析日期
                dt = ""
                if re.match(r"\d{4}[-/]\d{2}[-/]\d{2}", h_str):
                    dt = parse_date(h_str)
                elif "年度" in h_str or "中期" in h_str or "季度" in h_str:
                    # 从描述文本推断: "2025年度分配" -> 2025-12-31
                    m = re.search(r"(\d{4})", h_str)
                    if m:
                        year = m.group(1)
                        if "中期" in h_str or "半年" in h_str:
                            dt = year + "0630"
                        elif "一季" in h_str:
                            dt = year + "0331"
                        elif "三季" in h_str:
                            dt = year + "0930"
                        else:
                            dt = year + "1231"
                if not dt:
                    continue
                # 获取每股股利
                div_key = None
                for k, name in nm.items():
                    if k == "headNameSub":
                        continue
                    if "股利" in str(name) or "股息" in str(name):
                        div_key = k
                        break
                div_val = ""
                if div_key:
                    vals = rt.get(div_key, [])
                    div_val = vals[i] if i < len(vals) else ""
                desc = f"分红: {h_str}"
                if div_val:
                    desc += f", 每股股利{div_val}元"
                rows.append({
                    "symbol": secu_code,
                    "date": dt,
                    "event_type": "dividend",
                    "event_desc": desc,
                    "impact_score": 0.2,
                })

        # --- 回购 ---
        elif any(kw in nm_str for kw in ["回购"]):
            # 格式: headName = 日期, rawTable keys = 指标
            dates = hn
            key_to_name = {k: str(v) for k, v in nm.items()}
            qty_key = None
            price_key = None
            for k, name in key_to_name.items():
                if k == "headNameSub":
                    continue
                if "回购数量" in name:
                    qty_key = k
                elif "平均价格" in name or "回购价格" in name:
                    price_key = k
            for i, dt in enumerate(dates):
                dt_str = parse_date(dt)
                if not dt_str:
                    continue
                qty = rt.get(qty_key, [""])[i] if qty_key and i < len(rt.get(qty_key, [])) else ""
                price = rt.get(price_key, [""])[i] if price_key and i < len(rt.get(price_key, [])) else ""
                desc = f"回购"
                if qty:
                    desc += f" {qty}股"
                if price:
                    desc += f", 均价{price}元"
                rows.append({
                    "symbol": secu_code,
                    "date": dt_str,
                    "event_type": "share_buyback",
                    "event_desc": desc,
                    "impact_score": 0.5,
                })

    return rows


# ═══════════════════════════════════════════════════════════════════
# 拉取 + 写入 (每表)
# ═══════════════════════════════════════════════════════════════════

TABLE_DEFS = [
    {
        "csv": DATA / "margin_timeseries.csv",
        "query_suffix": "融资融券 融资买入额 融资偿还额 融券余量 每日",
        "limit": 20,
        "fields": ["symbol", "date", "margin_buy", "margin_repay", "margin_balance",
                    "margin_ratio", "sec_lending_volume", "sec_lending_balance"],
        "parser": parse_margin,
        "label": "两融",
    },
    {
        "csv": DATA / "north_flow_timeseries.csv",
        "query_suffix": "沪深港通 资金流向 每日 历史",
        "limit": 20,
        "fields": ["symbol", "date", "nb_net_flow", "nb_total_buy",
                    "nb_total_sell", "nb_holding_value", "nb_holding_ratio"],
        "parser": parse_north_flow,
        "label": "北向",
    },
    {
        "csv": DATA / "event_timeseries.csv",
        "query_suffix": "限售解禁 分红 回购 业绩预告",
        "limit": 20,
        "fields": ["symbol", "date", "event_type", "event_desc", "impact_score"],
        "parser": parse_events,
        "label": "事件",
    },
]


def fetch_table(defn: dict) -> int:
    """对一个表执行增量拉取，返回新增行数"""
    csv_path = defn["csv"]
    query_suffix = defn["query_suffix"]
    limit = defn["limit"]
    expected_fields = defn["fields"]
    parser = defn["parser"]
    label = defn["label"]

    existing = get_existing(csv_path)
    pool = get_pool()
    missing = [s for s in pool if s not in existing]
    batch = missing[:limit]

    if not batch:
        log(f"  {csv_path.name}: 全部覆盖 ({len(existing)}/{len(pool)})")
        return 0

    all_new_rows = []
    for i in range(0, len(batch), BATCH):
        codes = batch[i:i + BATCH]
        query = " ".join(codes) + f" {query_suffix}"
        out_dir = f"/tmp/mx_step_{csv_path.stem}_{i}_{int(time.time())}"
        os.makedirs(out_dir, exist_ok=True)
        env = {**os.environ, "MX_APIKEY": APIKEY}

        try:
            r = subprocess.run(
                [VENV, MX_DATA, query, out_dir],
                capture_output=True, text=True, timeout=30, env=env
            )
        except subprocess.TimeoutExpired:
            log(f"    ⏰ 超时: {codes}")
            continue

        jp = find_json(out_dir)
        if jp:
            parsed = parser(jp)
            all_new_rows.extend(parsed)
            log(f"    {' '.join(codes)} → {len(parsed)} 行 ({label})")

        time.sleep(2)

    if not all_new_rows:
        log(f"  {csv_path.name}: 本批次无解析数据")
        return 0

    # 合并写入
    old_rows = []
    if csv_path.exists():
        with open(csv_path, encoding="utf-8-sig") as f:
            old_rows = list(csv.DictReader(f))

    all_rows = old_rows + all_new_rows
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=expected_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    new_symbols = len(set(r["symbol"] for r in all_new_rows))
    now_covered = len(get_existing(csv_path))
    log(f"  {csv_path.name}: +{len(all_new_rows)} 行, +{new_symbols} 只 (共 {now_covered}/{len(pool)})")
    return len(all_new_rows)


def main():
    log("=" * 50)
    log("mx:data 步进拉取")
    log("=" * 50)

    total = 0
    pool = get_pool()
    log(f"关注池: {len(pool)} 只股票")

    for defn in TABLE_DEFS:
        csv_path = defn["csv"]
        existing = get_existing(csv_path)
        missing = [s for s in pool if s not in existing]
        log(f"\n▶ {csv_path.name}  (已有 {len(existing)}/{len(pool)}, 待补 {len(missing)})")
        n = fetch_table(defn)
        total += n

    # 最终覆盖率报告
    log(f"\n{'=' * 50}")
    log(f"覆盖率报告")
    log(f"{'=' * 50}")
    for defn in TABLE_DEFS:
        csv_path = defn["csv"]
        existing = get_existing(csv_path)
        pct = len(existing) / len(pool) * 100 if pool else 0
        log(f"  {defn['label']:4s} | {csv_path.name:35s} | {len(existing):3d}/{len(pool):3d} ({pct:5.1f}%)")

    log(f"\n✅ 完成, 合计新增 {total} 行")


if __name__ == "__main__":
    main()
