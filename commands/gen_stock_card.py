"""用 Pillow 生成股票分析图片 → 推企业微信"""
import os, sys, json, hashlib, base64, time, io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from typing import Optional

FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
OUTPUT = Path("/mnt/d/HermesReports/analysis_images")

def font_s(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)

COLORS = {
    "bg": (10, 14, 23),
    "card": (19, 29, 51),
    "card2": (15, 24, 42),
    "border": (30, 50, 80),
    "text": (232, 237, 245),
    "dim": (90, 122, 170),
    "green": (46, 213, 115),
    "red": (255, 71, 87),
    "yellow": (255, 165, 2),
    "blue": (56, 132, 255),
}

def draw_card(draw, x, y, w, h, color=COLORS["card"]):
    draw.rounded_rectangle([x, y, x+w, y+h], radius=10, fill=color, outline=COLORS["border"], width=1)

def make_analysis_image(data: dict) -> Image.Image:
    W, H = 800, 1050
    img = Image.new('RGB', (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    f12, f14, f16, f20, f28, f10 = font_s(12), font_s(14), font_s(16), font_s(20), font_s(28), font_s(10)
    
    y = 20
    
    # === Header ===
    draw_card(draw, 20, y, 760, 130)
    draw.text((40, y+12), data.get("ticker", ""), fill=COLORS["dim"], font=f12)
    draw.text((40, y+36), data.get("name", ""), fill=COLORS["text"], font=f28)
    # Price
    px, py = 40, y+75
    draw.text((px, py), data.get("price", ""), fill=COLORS["text"], font=f28)
    chg = data.get("change", "")
    chg_color = COLORS["green"] if chg.startswith("+") else COLORS["red"]
    tw = draw.textlength(data.get("price", ""), font=f28)
    draw.text((px + tw + 16, py+4), chg, fill=chg_color, font=f20)
    # Tags
    tx = 40
    for tag in data.get("tags", []):
        draw.rounded_rectangle([tx, y+110, tx+80, y+128], radius=4, fill=COLORS["card2"])
        draw.text((tx+6, y+112), tag, fill=COLORS["dim"], font=f10)
        tx += 88
    
    y += 150
    
    # === Judgment ===
    jd = data.get("judgment", "")
    if jd:
        # calculate text height by wrapping
        lines = []
        words = jd
        mw = 720
        while words:
            for i in range(len(words), 0, -1):
                if draw.textlength(words[:i], font=f14) <= mw:
                    lines.append(words[:i])
                    words = words[i:]
                    break
            else:
                lines.append(words[0])
                words = words[1:]
        bh = max(80, len(lines) * 22 + 30)
        draw_card(draw, 20, y, 760, bh)
        draw.text((36, y+10), "⚡", fill=COLORS["blue"], font=f16)
        ly = y + 36
        for l in lines:
            draw.text((36, ly), l, fill=COLORS["text"], font=f14)
            ly += 22
        y += bh + 10
    
    # === MA + Fund flow 2-column ===
    col_w = 370
    # Left: MA
    draw_card(draw, 20, y, col_w, 180)
    draw.text((36, y+10), "均线状态", fill=COLORS["dim"], font=f12)
    ma_items = data.get("ma", [])
    for i, (label, val, ok) in enumerate(ma_items):
        ly2 = y + 36 + i * 28
        draw.text((36, ly2), label, fill=COLORS["dim"], font=f14)
        c = COLORS["green"] if ok else COLORS["red"]
        draw.text((col_w - 60, ly2), val, fill=c, font=f14)
        draw.line([(36, ly2+22), (col_w-10, ly2+22)], fill=COLORS["border"], width=1)
    
    # Right: Fund Flow
    draw_card(draw, 410, y, col_w, 180)
    draw.text((426, y+10), "资金流向（今日）", fill=COLORS["dim"], font=f12)
    flow = data.get("flow", [])
    for i, (label, val, pos) in enumerate(flow):
        ly2 = y + 36 + i * 28
        draw.text((426, ly2), label, fill=COLORS["dim"], font=f14)
        c = COLORS["green"] if pos else COLORS["red"]
        draw.text((760 - draw.textlength(val, font=f14), ly2), val, fill=c, font=f14)
        draw.line([(426, ly2+22), (760, ly2+22)], fill=COLORS["border"], width=1)
    
    y += 200
    
    # === Risk signals ===
    risks = data.get("risks", [])
    if risks:
        bh = len(risks) * 24 + 30
        draw_card(draw, 20, y, 760, bh)
        draw.text((36, y+10), "⚠ 风险信号", fill=COLORS["red"], font=f12)
        for i, r in enumerate(risks):
            draw.text((36, y+36+i*24), f"• {r}", fill=COLORS["text"], font=font_s(13))
        y += bh + 10
    
    # === Scenarios ===
    scenarios = data.get("scenarios", [])
    if scenarios:
        sw = 240
        for i, (label, desc, c) in enumerate(scenarios):
            sx = 20 + i * (sw + 10)
            draw_card(draw, sx, y, sw, 70, COLORS["card2"])
            draw.text((sx+12, y+8), label, fill=c, font=f14)
            draw.text((sx+12, y+32), desc, fill=COLORS["dim"], font=f12)
    
    y += 90
    
    # === Footer ===
    draw.text((20, y+10), data.get("footer", ""), fill=COLORS["dim"], font=f10)
    
    return img

def push_to_wechat(image: Image.Image, webhook_url: str) -> bool:
    """推送图片到企业微信"""
    import requests
    try:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        md5 = hashlib.md5(buf.getvalue()).hexdigest()
        r = requests.post(webhook_url, json={
            "msgtype": "image",
            "image": {"base64": img_b64, "md5": md5}
        }, timeout=15)
        return r.json().get("errcode") == 0
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return False

def build_stock_data(symbol: str, name: str, ticker: str, price: str, change: str,
                     tags: list, judgment: str, ma: list, flow: list,
                     risks: list, scenarios: list) -> dict:
    return {
        "symbol": symbol, "name": name, "ticker": ticker,
        "price": price, "change": change, "tags": tags,
        "judgment": judgment, "ma": ma, "flow": flow,
        "risks": risks, "scenarios": scenarios,
        "footer": "Hermes A股投研 · 数据: Baostock+妙想金融 · 不构成投资建议"
    }

if __name__ == "__main__":
    # 长电科技
    data = build_stock_data(
        "600584", "长电科技", "600584.SH · 半导体 · 封测",
        "90.88", "-6.07%",
        ["AI算力", "先进封装", "科创板"],
        "长电科技自4月低点38.78涨至6月高点106.64(+175%)，AI算力拉动先进封装需求爆发+78亿临港建厂。目前回撤14.8%，MA5/MA10跌破，短线获利盘兑现。今日主力净流出8.27亿，散户净流入7.17亿——机构出货散户接盘的典型结构。关键支撑在MA20(86.44)，若守住则中期趋势仍在。",
        [("MA5", "100.06 ❌", False), ("MA10", "97.74 ❌", False),
         ("MA20", "86.44 ✅", True), ("MA60", "66.69 ✅", True)],
        [("主力净流入","-8.27亿",False),("超大单","-3.91亿",False),
         ("大单","-4.36亿",False),("小单(散户)","+7.17亿",True)],
        ["主力净流出8.27亿/散户接盘7.17亿 — 机构出货结构",
         "MA5/MA10已跌破，短线趋势转弱",
         "静态PE 104倍，估值极端高位",
         "股价自低点涨175%，获利盘巨大",
         "78亿临港项目2028年一期才完成"],
        [("偏多","缩量回踩MA20不破","#2ed573"),
         ("基准","86-97震荡观望1-2周","#ffa502"),
         ("偏空","放量跌破MA20→看80-84","#ff4757")]
    )
    img = make_analysis_image(data)
    path = OUTPUT / f"{data['symbol']}_{data['name']}.png"
    img.save(str(path))
    print(f"✅ {path}")

    # 推送
    webhook = os.environ.get("WECHAT_WEBHOOK_URL", "")
    if webhook:
        if push_to_wechat(img, webhook):
            print(f"📤 已推送 {data['name']} 到企业微信")
        else:
            print(f"❌ 推送失败 {data['name']}")

    # 雷赛智能
    data2 = build_stock_data(
        "002979", "雷赛智能", "002979.SZ · 自动化设备 · 运动控制",
        "69.55", "连续2日一字涨停",
        ["业绩预增", "缩量封板", "机器人"],
        "半年报业绩预告超预期(+55~65%)驱动连续两日一字涨停。龙虎榜显示机构在7/2涨停日净卖出约1.6亿、游资接力。今日超大单+7,949万继续买入，但大单/中单均在卖出——机构对倒结构。所有均线多头发散，强势结构完整。",
        [("MA5","59.62 ✅",True),("MA10","56.25 ✅",True),
         ("MA20","54.88 ✅",True),("MA60","50.94 ✅",True)],
        [("主力净流入","+6,034万",True),("超大单","+7,949万",True),
         ("大单","-1,915万",False),("小单(散户)","-2,421万",False)],
        ["龙虎榜机构在涨停日净卖出约1.6亿",
         "连续涨停后打开可能集中抛压",
         "资产负债率70.5%偏高",
         "静态PE 94倍估值偏高"],
        [("偏多","缩量封板→趋势延续","#2ed573"),
         ("基准","打开涨停守住63+→观望","#ffa502"),
         ("偏空","跌破63→回调至57-58","#ff4757")]
    )
    img2 = make_analysis_image(data2)
    path2 = OUTPUT / f"{data2['symbol']}_{data2['name']}.png"
    img2.save(str(path2))
    print(f"✅ {path2}")
    if webhook:
        if push_to_wechat(img2, webhook):
            print(f"📤 已推送 {data2['name']} 到企业微信")
        else:
            time.sleep(3)
            push_to_wechat(img2, webhook)
            print(f"📤 重试推送 {data2['name']}")
