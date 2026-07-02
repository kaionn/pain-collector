"""note.com から人気記事を RSS で収集する."""

import logging

import feedparser

from src.collector_registry import register_collector
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

NOTE_RSS_URLS = [
    {"url": "https://note.com/topic/technology/rss", "label": "テクノロジー"},
    {"url": "https://note.com/topic/lifestyle/rss", "label": "ライフスタイル"},
    {"url": "https://note.com/topic/business/rss", "label": "ビジネス"},
]


@register_collector(key="note", display_name="note")
def collect() -> list[dict]:
    """note.com RSS から人気記事を取得する."""
    all_entries = []

    for source in NOTE_RSS_URLS:
        try:
            feed = feedparser.parse(source["url"])
        except Exception as e:
            logger.warning(f"{source['label']} の取得に失敗: {e}")
            continue

        raw_count = 0
        entries = []
        for entry in feed.entries[:20]:
            raw_count += 1
            title = entry.get("title", "")
            summary = entry.get("summary", "")[:500]
            text = f"{title} {summary}"
            if not contains_pain_keyword(text):
                continue
            entries.append(
                {
                    "source": "note",
                    "category": source["label"],
                    "title": title,
                    "url": entry.get("link", ""),
                    "summary": summary,
                    "author": entry.get("author", ""),
                }
            )

        all_entries.extend(entries)
        logger.info(f"{source['label']}: {len(entries)}/{raw_count} 件がペインフィルタ通過")

    logger.info(f"合計: {len(all_entries)} 件")
    return all_entries
