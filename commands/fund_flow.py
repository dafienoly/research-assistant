"""资金流向提取器 — 从东方财富 browser 提取个股/大盘资金流向"""
import json, sys, re
from pathlib import Path

BASE = Path("/home/ly/.hermes/research-assistant")

def extract_stock_fund_flow(code: str) -> dict:
    """从东方财富个股资金流向页面提取数据"""
    from browser_navigator import navigate, extract_js
    nav = navigate(f"https://data.eastmoney.com/zjlx/{code}.html")
    if not nav.get("success"):
        return {"error": "页面加载失败"}
    js = """
    var fields = document.querySelectorAll('[data-field]');
    var map = {};
    for (var f of fields) {
        var field = f.getAttribute('data-field');
        var val = f.innerText.trim();
        var prev = f.parentElement.querySelector('td:first-child');
        var label = prev ? prev.innerText.trim() : field;
        map[field] = val;
    }
    JSON.stringify(map);
    """
    data = extract_js(js)
    if not data:
        return {"error": "数据提取失败"}
    
    # 字段映射
    field_names = {
        "f62": "主力净流入(万)", "f184": "主力净比(%)",
        "f66": "超大单净流入(万)", "f69": "超大单净比(%)",
        "f72": "大单净流入(万)", "f75": "大单净比(%)",
        "f78": "中单净流入(万)", "f81": "中单净比(%)",
        "f84": "小单净流入(万)", "f87": "小单净比(%)",
    }
    result = {"code": code, "type": "stock"}
    for k, v in data.items():
        label = field_names.get(k, k)
        result[label] = v
    return result

def extract_market_fund_flow() -> dict:
    """从东方财富大盘资金流向页面提取数据"""
    from browser_navigator import navigate, extract_js
    nav = navigate("https://data.eastmoney.com/zjlx/dpzjlx.html")
    if not nav.get("success"):
        return {"error": "页面加载失败"}
    js = """
    var body = document.body.innerText;
    var lines = body.split('\\n').filter(l => l.includes('净流入') || l.includes('净流出') || l.includes('主力') || l.includes('小单'));
    var data = {};
    for (var l of lines) {
        var parts = l.split(/[：:]/);
        if (parts.length >= 2) {
            data[parts[0].trim()] = parts[1].trim();
        }
    }
    JSON.stringify(data);
    """
    data = extract_js(js)
    if not data:
        return {"error": "数据提取失败"}
    result = {"type": "market"}
    for k, v in data.items():
        result[k] = v
    return result


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "market":
        r = extract_market_fund_flow()
    elif len(sys.argv) > 1:
        r = extract_stock_fund_flow(sys.argv[1])
    else:
        print("用法: python3 fund_flow.py <代码>  |  python3 fund_flow.py market")
        sys.exit(1)
    print(json.dumps(r, ensure_ascii=False, indent=2))