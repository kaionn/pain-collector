"""Product Hunt のトレンドプロダクトを RSS フィードから収集する."""

import logging

import feedparser

from src.collector_registry import register_collector

logger = logging.getLogger(__name__)

FEED_URL = "https://www.producthunt.com/feed"


@register_collector(key="producthunt", display_name="ProductHunt")
def collect() -> list[dict]:
    """Product Hunt の RSS フィードからトレンドプロダクトを取得する."""
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

        tags: list[str] = []
        if hasattr(entry, "tags"):
            tags = [t.get("term", "") for t in entry.tags if t.get("term")]

        entries.append(
            {
                "source": "producthunt",
                "title": title,
                "url": entry.get("link", ""),
                "body": summary,
                "tags": tags,
            }
        )

    logger.info(f"{len(entries)}/{raw_count} 件を取得")
    return entries
