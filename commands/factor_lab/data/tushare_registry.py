"""
Tushare Data Source — Data Source Registry Bridge
"""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
REGISTRY_FILE = Path("/mnt/d/HermesData/data_source_registry.json")

logger = logging.getLogger(__name__)

SOURCE_DEF = {
    "source_id": "tushare_pro",
    "name": "Tushare Pro (ts.gyzcloud.top)",
    "source_type": "market_data",
    "provider": "tushare",
    "description": "全A股票行情、财务数据、估值数据、行业分类 — 通过 ts.gyzcloud.top 代理接入",
    "status": "active",
    "refresh_frequency": "1d",
    "token_placeholder": "env:TUSHARE_TOKEN",
    "expires": "2026-08-07",
    "rate_limit": "150次/分钟",
    "stock_coverage": 5528,
    "data_types": [
        "daily_kline (前复权日线, **2000年至今**, 已验证5,528只)",
        "daily_basic (每日PE/PB/换手率/市值)",
        "fina_indicator (ROE/毛利率/净利率/负债率/EPS等 80+指标, **2012年至今**)",
        "stock_basic (上市日期/退市状态/行业/板块)",
        "concept/concept_detail (概念板块成分股)",
        "stk_limit (涨跌停价格)",
        "suspend_d (停复牌)",
        "namechange (ST标记/更名)",
        "trade_cal (交易日历)",
    ],
    "api_endpoint": "https://ts.gyzcloud.top/api",
    "doc_url": "https://ts.gyzcloud.top/docs",
}


def register_in_registry():
    """注册 Tushare Pro 数据源到中央注册表"""
    import json

    if not REGISTRY_FILE.exists():
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"sources": [], "version": "1.0"}
    else:
        data = json.loads(REGISTRY_FILE.read_text())

    # 更新或添加
    for i, s in enumerate(data["sources"]):
        if s["source_id"] == "tushare_pro":
            data["sources"][i] = SOURCE_DEF
            data["sources"][i]["last_updated"] = datetime.now(CST).isoformat()
            break
    else:
        entry = SOURCE_DEF.copy()
        entry["registered_at"] = datetime.now(CST).isoformat()
        data["sources"].append(entry)

    REGISTRY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Tushare Pro 已注册到数据源注册表")


if __name__ == "__main__":
    register_in_registry()
    print("Tushare Pro 数据源注册完成")
