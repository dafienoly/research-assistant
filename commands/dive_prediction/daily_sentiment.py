"""每日新闻情感采集 — 用浏览器搜财联社半导体新闻，LLM 打分，存 CSV"""
import csv, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dive_prediction.news_sentiment import score_news_headlines

CST = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).resolve().parent / "data"
SENTIMENT_PATH = DATA_DIR / "news_sentiment_daily.csv"
HEADLINES_PATH = DATA_DIR / "latest_headlines.txt"


def load_today_headlines() -> list[str]:
    """读取浏览器抓取的当日半导体新闻标题（由 Agent 在 cron 执行前填入）"""
    if HEADLINES_PATH.exists():
        return [l.strip() for l in HEADLINES_PATH.read_text().splitlines() if l.strip()]
    return []


def save_sentiment(headlines: list[str]):
    """打分并保存到 CSV"""
    if not headlines:
        return {"status": "skipped", "reason": "无新闻标题"}
    
    r = score_news_headlines(headlines)
    today = datetime.now(CST).strftime("%Y-%m-%d")
    row = {"date": today, **{k: r[k] for k in ["total","positive","negative","neutral","net_score","positive_ratio","negative_ratio"]}}
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    exists = SENTIMENT_PATH.exists()
    with open(SENTIMENT_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists: w.writeheader()
        w.writerow(row)
    
    return {"status": "saved", "date": today, "net_score": r["net_score"], "total": r["total"]}


def load_all() -> list[dict]:
    """读取全部历史情感数据"""
    if not SENTIMENT_PATH.exists():
        return []
    with open(SENTIMENT_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_latest_feature() -> dict:
    """获取最新一天的情感特征（用于模型）"""
    all_data = load_all()
    if not all_data:
        return {"news_net_score": 0, "news_positive_ratio": 0, "news_negative_ratio": 0}
    last = all_data[-1]
    return {
        "news_net_score": float(last.get("net_score", 0)),
        "news_positive_ratio": float(last.get("positive_ratio", 0)),
        "news_negative_ratio": float(last.get("negative_ratio", 0)),
    }
