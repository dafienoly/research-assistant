"""新闻情感特征采集 — 浏览器搜财联社/英为财情，LLM 打分"""
import re
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))


def score_news_headlines(headlines: list[str]) -> dict:
    """对半导体新闻标题做情绪打分

    返回: {positive, negative, neutral, net_score, detail}
    """
    positive_keywords = [
        "突破", "涨价", "增长", "利好", "超预期", "新高", "供不应求",
        "加码", "扩产", "投资", "合作", "订单", "爆发", "机遇",
    ]
    negative_keywords = [
        "跌", "下跌", "利空", "制裁", "限制", "下滑", "萎缩",
        "风险", "警告", "过剩", "降价", "放缓", "管制", "脱钩",
        "禁令", "调查",
    ]

    positive_count = 0
    negative_count = 0
    neutral_count = 0
    detail = []

    for h in headlines:
        h_lower = h.lower()
        pos_score = sum(1 for kw in positive_keywords if kw in h)
        neg_score = sum(1 for kw in negative_keywords if kw in h)

        if pos_score > neg_score:
            sentiment = "positive"
            positive_count += 1
        elif neg_score > pos_score:
            sentiment = "negative"
            negative_count += 1
        else:
            # 更精确: 看跌跌幅相关
            if any(kw in h for kw in ["跌", "下跌", "利空"]):
                sentiment = "negative"
                negative_count += 1
            else:
                sentiment = "neutral"
                neutral_count += 1

        detail.append((h[:60], sentiment))

    total = len(headlines)
    net_score = (positive_count - negative_count) / max(total, 1)

    return {
        "total": total,
        "positive": positive_count,
        "negative": negative_count,
        "neutral": neutral_count,
        "net_score": round(net_score, 3),
        "positive_ratio": round(positive_count / max(total, 1), 3),
        "negative_ratio": round(negative_count / max(total, 1), 3),
    }


def collect_today_news() -> list[str]:
    """浏览器采集今日半导体新闻 (由 Agent 在 eval 前调用填充)"""
    # 实际使用时通过 browser_navigate 获取标题列表
    # 这里返回占位 — Agent 在 eval 前会替换为真实抓取的新闻
    return []


def sentiment_to_feature(news_result: dict) -> dict:
    """将新闻情绪转为数值特征"""
    return {
        "news_positive_ratio": news_result.get("positive_ratio", 0),
        "news_negative_ratio": news_result.get("negative_ratio", 0),
        "news_net_score": news_result.get("net_score", 0),
        "news_total": news_result.get("total", 0),
    }
