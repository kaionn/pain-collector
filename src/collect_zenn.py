"""Zenn のトレンド記事からペイン的な投稿を収集する."""

import logging

import feedparser

from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

FEED_URL = "https://zenn.dev/feed"


def collect() -> list[dict]:
    """Zenn の RSS フィードからトレンド記事を取得する."""
    try:
        feed = feedparser.parse(FEED_URL)
    except Exception as e:
        logger.warning(f"フィードの取得に失敗: {e}")
        return []

    raw_count = 0
    entries = []
    for entry in feed.entries:
        raw_count += 1
        title = entry.get("title", "")
        summary = entry.get("summary", "")[:500]
        text = f"{title} {summary}"
        if not contains_pain_keyword(text):
            continue
        entries.append(
            {
                "source": "zenn",
                "title": title,
                "url": entry.get("link", ""),
                "summary": summary,
                "author": entry.get("author", ""),
            }
        )

    logger.info(f"{len(entries)}/{raw_count} 件がペインフィルタ通過")
    return entries
