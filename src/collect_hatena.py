"""はてなブックマークのホットエントリからペイン的な投稿を収集する."""

import feedparser

CATEGORIES = [
    {"path": "it", "label": "テクノロジー"},
    {"path": "life", "label": "暮らし"},
]


def collect() -> list[dict]:
    """はてブ RSS から現在のホットエントリを取得する."""
    all_entries = []

    for cat in CATEGORIES:
        url = f"https://b.hatena.ne.jp/hotentry/{cat['path']}.rss"

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[はてブ] {cat['label']} の取得に失敗: {e}")
            continue

        entries = []
        for entry in feed.entries[:30]:
            entries.append(
                {
                    "source": "hatena",
                    "category": cat["label"],
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:500],
                    "bookmarks": _extract_bookmark_count(entry),
                }
            )

        all_entries.extend(entries)
        print(
            f"[はてブ] {cat['label']}: {len(entries)} 件のエントリを取得"
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
