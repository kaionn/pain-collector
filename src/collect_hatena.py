"""はてなブックマークのホットエントリからペイン的な投稿を収集する."""

import feedparser

from src.pain_keywords_ja import contains_pain_keyword

CATEGORIES = [
    {"path": "it", "label": "テクノロジー"},
    {"path": "life", "label": "暮らし"},
    {"path": "social", "label": "社会", "min_bookmarks": 50},
    {"path": "economics", "label": "経済"},
    {"path": "knowledge", "label": "学び"},
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

        min_bookmarks = cat.get("min_bookmarks", 0)
        raw_count = 0
        entries = []
        for entry in feed.entries[:30]:
            raw_count += 1
            bookmarks = _extract_bookmark_count(entry)
            if bookmarks < min_bookmarks:
                continue
            title = entry.get("title", "")
            summary = entry.get("summary", "")[:500]
            text = f"{title} {summary}"
            if not contains_pain_keyword(text):
                continue
            entries.append(
                {
                    "source": "hatena",
                    "category": cat["label"],
                    "title": title,
                    "url": entry.get("link", ""),
                    "summary": summary,
                    "bookmarks": bookmarks,
                }
            )

        all_entries.extend(entries)
        print(
            f"[はてブ] {cat['label']}: {len(entries)}/{raw_count} 件がペインフィルタ通過"
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
