"""はてなブックマークのホットエントリからペイン的な投稿を収集する."""

import feedparser

FEEDS = [
    {
        "url": "https://b.hatena.ne.jp/hotentry/it.rss",
        "category": "テクノロジー",
    },
    {
        "url": "https://b.hatena.ne.jp/hotentry/life.rss",
        "category": "暮らし",
    },
]


def collect() -> list[dict]:
    """はてブ RSS からホットエントリを取得する."""
    all_entries = []

    for feed_info in FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
        except Exception as e:
            print(f"[はてブ] {feed_info['category']} の取得に失敗: {e}")
            continue

        entries = []
        for entry in feed.entries[:30]:
            entries.append(
                {
                    "source": "hatena",
                    "category": feed_info["category"],
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:500],
                    "bookmarks": _extract_bookmark_count(entry),
                }
            )

        all_entries.extend(entries)
        print(
            f"[はてブ] {feed_info['category']}: {len(entries)} 件のエントリを取得"
        )

    print(f"[はてブ] 合計: {len(all_entries)} 件")
    return all_entries


def _extract_bookmark_count(entry: dict) -> int:
    """はてブ数を取得する."""
    bookmarks = entry.get("hatena_bookmarkcount", "0")
    try:
        return int(bookmarks)
    except (ValueError, TypeError):
        return 0
