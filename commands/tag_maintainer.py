"""A 股产业链和主题标签维护 — Phase 2

维护产业链标签 CSV 文件，供盘中选择和板块分析使用。
通过 Baostock 获取行业分类数据（免费无限量）。
"""

import csv
from pathlib import Path

from config import PATHS, now_str, now_cst, date_id, read_csv_safe, append_jsonl


def baostock_login():
    """登录 Baostock（带 DNS 修补）"""
    try:
        import dns_patch
    except ImportError:
        pass
    import baostock as bs
    bs.login()
    return bs


def enrich_industry_from_baostock():
    """用 Baostock 行业分类数据丰富标签文件"""
    bs = baostock_login()
    updated = 0

    # 读取现有标签中的股票代码
    existing_codes = set()
    for tag_file in ['semiconductor_chain_tags.csv', 'stock_theme_tags.csv', 'industry_chain_tags.csv']:
        f = PATHS['tags'] / tag_file
        if f.exists():
            for row in read_csv_safe(f):
                c = row.get('code', '') or row.get('symbol', '')
                if c:
                    existing_codes.add(c)
    
    # 用 Baostock 查行业分类
    results = []
    for code in sorted(existing_codes):
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        rs = bs.query_stock_industry(f"{exchange}.{code}")
        if rs.next():
            row = rs.get_row_data()
            if row and len(row) >= 4:
                results.append({
                    "code": code,
                    "name": row[2],
                    "industry": row[3],
                    "industry_source": "baostock",
                    "updated_at": now_str(),
                })
                updated += 1

    # 写入 industry_chain_tags.csv
    tag_path = PATHS['tags'] / 'industry_chain_tags.csv'
    with open(tag_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "industry", "industry_source", "updated_at"])
        w.writeheader()
        w.writerows(results)

    bs.logout()
    return updated, len(existing_codes)


# ========== 标签维护 ==========

SEMICONDUCTOR_CHAIN_STOCKS = [
    # 设备
    {"code": "688012", "name": "中微公司", "chain_position": "设备", "sub_sector": "刻蚀", "product": "CCP/DRIE刻蚀设备"},
    {"code": "002371", "name": "北方华创", "chain_position": "设备", "sub_sector": "综合设备", "product": "刻蚀/薄膜/清洗/炉管"},
    {"code": "688037", "name": "芯源微", "chain_position": "设备", "sub_sector": "涂胶显影", "product": "光刻工序涂胶显影设备"},
    {"code": "688072", "name": "拓荆科技", "chain_position": "设备", "sub_sector": "薄膜沉积", "product": "PECVD/ALD设备"},
    {"code": "688120", "name": "华海清科", "chain_position": "设备", "sub_sector": "CMP", "product": "CMP抛光设备"},
    {"code": "688200", "name": "华峰测控", "chain_position": "封测", "sub_sector": "测试", "product": "半导体测试系统"},
    # 材料
    {"code": "688019", "name": "安集科技", "chain_position": "材料", "sub_sector": "抛光液", "product": "CMP抛光液/光刻胶去除剂"},
    {"code": "688126", "name": "沪硅产业", "chain_position": "材料", "sub_sector": "硅片", "product": "300mm大硅片"},
    {"code": "300236", "name": "上海新阳", "chain_position": "材料", "sub_sector": "电镀液", "product": "铜电镀液/光刻胶"},
    {"code": "300604", "name": "长川科技", "chain_position": "封测", "sub_sector": "测试", "product": "测试机/分选机"},
    # 设计/IP
    {"code": "688008", "name": "澜起科技", "chain_position": "设计", "sub_sector": "内存接口", "product": "DDR5内存接口芯片"},
    {"code": "603986", "name": "兆易创新", "chain_position": "设计", "sub_sector": "存储", "product": "NOR Flash/MCU"},
    {"code": "688041", "name": "海光信息", "chain_position": "设计", "sub_sector": "CPU", "product": "x86兼容CPU"},
    {"code": "688256", "name": "寒武纪", "chain_position": "设计", "sub_sector": "AI芯片", "product": "AI训练/推理芯片"},
    # 制造
    {"code": "688981", "name": "中芯国际", "chain_position": "制造", "sub_sector": "代工", "product": "晶圆代工"},
    {"code": "600703", "name": "三安光电", "chain_position": "制造", "sub_sector": "化合物半导体", "product": "GaAs/GaN/SiC"},
    # CPO/光模块
    {"code": "300502", "name": "新易盛", "chain_position": "CPO", "sub_sector": "光模块", "product": "高速光模块"},
    {"code": "300394", "name": "天孚通信", "chain_position": "CPO", "sub_sector": "光器件", "product": "光通信器件"},
    {"code": "688313", "name": "仕佳光子", "chain_position": "CPO", "sub_sector": "光芯片", "product": "PLC/AWG光芯片"},
    {"code": "300308", "name": "中际旭创", "chain_position": "CPO", "sub_sector": "光模块", "product": "高速光模块"},
]

THEME_TAGS = {
    "半导体设备": ["688012", "002371", "688037", "688072", "688120"],
    "半导体材料": ["688019", "688126", "300236"],
    "存储": ["603986", "688008", "688525"],
    "AI算力": ["688256", "688041", "300308"],
    "CPO": ["300502", "300394", "688313", "300308"],
    "光模块": ["300502", "300308"],
    "PCB": ["002916", "603228", "002938"],
    "封测": ["688200", "300604", "002156", "600584"],
    "华为链": ["002371", "688012", "688981", "688041", "688256"],
    "国产替代": ["688012", "002371", "688981", "688019", "688126"],
    "长鑫链": ["688012", "688019", "300236", "002371"],
    "长江存储链": ["688012", "688019", "688126"],
}


class TagMaintainer:
    """标签维护器"""

    def update_semiconductor_tags(self):
        """更新半导体产业链标签"""
        path = PATHS["tags"] / "semiconductor_chain_tags.csv"
        fieldnames = ["code", "name", "chain_position", "sub_sector", "product", "notes"]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for stock in SEMICONDUCTOR_CHAIN_STOCKS:
                w.writerow(stock)
        self._log("semiconductor_chain_tags", len(SEMICONDUCTOR_CHAIN_STOCKS))

    def update_theme_tags(self):
        """更新主题标签"""
        path = PATHS["tags"] / "stock_theme_tags.csv"
        fieldnames = ["code", "name", "theme", "weight", "notes"]
        # 需要 name, 从 pool 中获取
        pool = read_csv_safe(PATHS["market"] / "pool.csv")
        name_map = {r.get("code", ""): r.get("name", "") for r in pool}

        rows = []
        # 构建扁平结构
        code_themes = {}
        for theme, codes in THEME_TAGS.items():
            for code in codes:
                if code not in code_themes:
                    code_themes[code] = []
                code_themes[code].append(theme)

        for code, themes in code_themes.items():
            for theme in themes:
                rows.append({
                    "code": code,
                    "name": name_map.get(code, ""),
                    "theme": theme,
                    "weight": 1.0,  # 默认权重
                    "notes": "",
                })

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow(row)
        self._log("stock_theme_tags", len(rows))

    def update_industry_tags(self):
        """更新全产业链标签（手动 + Baostock 行业分类）"""
        path = PATHS["tags"] / "industry_chain_tags.csv"
        fieldnames = ["code", "name", "chain", "sub_chain", "notes", "baostock_industry", "industry_source"]

        # 手动维护的半导体链
        rows = []
        for stock in SEMICONDUCTOR_CHAIN_STOCKS:
            rows.append({
                "code": stock["code"], "name": stock["name"],
                "chain": "半导体", "sub_chain": stock["chain_position"],
                "notes": stock.get("product", ""),
                "baostock_industry": "", "industry_source": "manual",
            })

        # Baostock 行业分类补充
        try:
            bs = self._baostock_login()
            codes = set(r["code"] for r in rows)
            for code in sorted(codes):
                exchange = "sh" if code.startswith(("6", "9")) else "sz"
                rs = bs.query_stock_industry(f"{exchange}.{code}")
                if rs.next():
                    row_data = rs.get_row_data()
                    if row_data and len(row_data) >= 4:
                        industry = row_data[3]
                        # 更新匹配的行
                        for r in rows:
                            if r["code"] == code:
                                r["baostock_industry"] = industry
                                r["industry_source"] = "baostock"
            bs.logout()
        except Exception as e:
            print(f"  ⚠️ Baostock 行业分类失败: {e}")

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow(row)
        self._log("industry_chain_tags", len(rows))

    def _baostock_login(self):
        """登录 Baostock（带 DNS 修补）"""
        try:
            import dns_patch
        except ImportError:
            pass
        import baostock as bs
        bs.login()
        return bs

    def update_all(self):
        """更新所有标签"""
        self.update_semiconductor_tags()
        self.update_theme_tags()
        self.update_industry_tags()
        print("✅ 所有标签已更新")

    def _log(self, tag_file: str, count: int):
        append_jsonl(PATHS["audit"] / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "update_tags",
            "tag_file": tag_file,
            "records": count,
        })
        print(f"🏷️ {tag_file}: {count} 条")


# === CLI 命令 ===
def cmd_update():
    maintainer = TagMaintainer()
    maintainer.update_all()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        cmd_update()
    elif len(sys.argv) > 1 and sys.argv[1] == "fundamentals":
        cmd_update_fundamentals()
    else:
        print("Usage: python tag_maintainer.py [update|fundamentals]")


# ========== Baostock 基本面更新 ==========

def cmd_update_fundamentals():
    """用 Baostock 更新基本面数据（替换 RSScast MCP 额度消耗）"""
    import dns_patch
    import baostock as bs

    bs.login()
    print("📊 Baostock 基本面更新...")

    # 从标签文件读股票列表
    codes = set()
    for f_name in ["semiconductor_chain_tags.csv", "stock_theme_tags.csv", "industry_chain_tags.csv"]:
        f = PATHS["tags"] / f_name
        if f.exists():
            for row in read_csv_safe(f):
                c = row.get("code", "") or row.get("symbol", "")
                if c:
                    codes.add(c)
    codes.add("600519")  # 贵州茅台作为基准
    priority = sorted(codes)
    print(f"  股票数: {len(priority)}")
    results = []

    for i, code in enumerate(priority):
        exchange = "sh" if code.startswith(("6", "9")) else "sz"
        full_code = f"{exchange}.{code}"
        try:
            # 优先获取最新完整季报（2026Q1），若没有则取 2025Q4
            rs = bs.query_profit_data(full_code, year=2026, quarter=1)
            row = None
            while rs.next():
                row = rs.get_row_data()
                break
            if not row or not row[3]:  # roe 为空，取 2025Q4
                rs2 = bs.query_profit_data(full_code, year=2025, quarter=4)
                while rs2.next():
                    row = rs2.get_row_data()
                    break
            if row and len(row) > 7:
                results.append({
                    "code": code,
                    "report_date": row[2] if row[2] else "",
                    "roe": row[3] if len(row) > 3 else "",
                    "net_profit_margin": row[4] if len(row) > 4 else "",
                    "gross_profit_margin": row[5] if len(row) > 5 else "",
                    "net_profit": row[6] if len(row) > 6 else "",
                    "eps": row[7] if len(row) > 7 else "",
                    "revenue": row[8] if len(row) > 8 else "",
                    "source": "baostock",
                    "updated_at": now_str(),
                })
        except Exception:
            import logging; logging.warning('tag_maintainer: suppressed error')
        if (i + 1) % 10 == 0:
            print(f"\r  进度: {i+1}/{len(priority)} 已获:{len(results)}", end="", flush=True)

    # 写入 financial_snapshot.csv
    dest = PATHS["fundamentals"] / "financial_snapshot.csv"
    fields = ["code", "report_date", "roe", "net_profit_margin", "gross_profit_margin",
              "net_profit", "eps", "revenue", "source", "updated_at"]
    with open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in results:
            w.writerow(row)

    bs.logout()
    print(f"\n  已更新 {len(results)} 只基本面 → {dest.name}")
    return len(results)
