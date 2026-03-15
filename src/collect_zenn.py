"""Zenn のトレンド記事からペイン的な投稿を収集する."""

import feedparser

FEED_URL = "https://zenn.dev/feed"


def collect() -> list[dict]:
    """Zenn の RSS フィードからトレンド記事を取得する."""
    try:
        feed = feedparser.parse(FEED_URL)
    except Exception as e:
        print(f"[Zenn] フィードの取得に失敗: {e}")
        return []

    entries = []
    for entry in feed.entries:
        entries.append(
            {
                "source": "zenn",
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", "")[:500],
                "author": entry.get("author", ""),
            }
        )

    print(f"[Zenn] {len(entries)} 件のエントリを取得")
    return entries
