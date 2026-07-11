"""A 股产业链和主题标签维护（canonical DataHub consumer）。"""

from pathlib import Path

import pandas as pd

from config import PATHS, append_jsonl, now_str
from data_recovery import atomic_write_frame
from factor_lab.datahub_access import read_stock_industry_map, read_stock_name_map
from factor_lab.datahub_ingestion.factor_inputs import FactorInputProjection


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
        frame = pd.DataFrame(SEMICONDUCTOR_CHAIN_STOCKS)
        frame["notes"] = ""
        atomic_write_frame(frame.loc[:, fieldnames], path)
        self._log("semiconductor_chain_tags", len(SEMICONDUCTOR_CHAIN_STOCKS))

    def update_theme_tags(self):
        """更新主题标签"""
        path = PATHS["tags"] / "stock_theme_tags.csv"
        fieldnames = ["code", "name", "theme", "weight", "notes"]
        name_map = read_stock_name_map()

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

        atomic_write_frame(pd.DataFrame(rows, columns=fieldnames), path)
        self._log("stock_theme_tags", len(rows))

    def update_industry_tags(self):
        """更新全产业链标签（手动语义 + canonical 行业分类）。"""
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

        industries = read_stock_industry_map()
        for row in rows:
            industry = industries.get(row["code"])
            if industry:
                row["baostock_industry"] = industry
                row["industry_source"] = "datahub:stock_basic"

        atomic_write_frame(pd.DataFrame(rows, columns=fieldnames), path)
        self._log("industry_chain_tags", len(rows))

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


def cmd_update_fundamentals():
    """Compatibility command for the canonical fundamentals projection."""
    result = FactorInputProjection(Path(__file__).resolve().parents[1]).build("fundamentals")
    print(f"📊 DataHub fundamentals projection: {result['status']} rows={result['rows']}")
    return int(result["rows"])


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "update":
        cmd_update()
    elif len(sys.argv) > 1 and sys.argv[1] == "fundamentals":
        cmd_update_fundamentals()
    else:
        print("Usage: python tag_maintainer.py [update|fundamentals]")
