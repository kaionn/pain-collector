"""note.com から人気記事を RSS で収集する."""

import feedparser

NOTE_RSS_URLS = [
    {"url": "https://note.com/topic/technology/rss", "label": "テクノロジー"},
    {"url": "https://note.com/topic/lifestyle/rss", "label": "ライフスタイル"},
    {"url": "https://note.com/topic/business/rss", "label": "ビジネス"},
]


def collect() -> list[dict]:
    """note.com RSS から人気記事を取得する."""
    all_entries = []

    for source in NOTE_RSS_URLS:
        try:
            feed = feedparser.parse(source["url"])
        except Exception as e:
            print(f"[note] {source['label']} の取得に失敗: {e}")
            continue

        entries = []
        for entry in feed.entries[:20]:
            entries.append(
                {
                    "source": "note",
                    "category": source["label"],
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:500],
                    "author": entry.get("author", ""),
                }
            )

        all_entries.extend(entries)
        print(f"[note] {source['label']}: {len(entries)} 件のエントリを取得")

    print(f"[note] 合計: {len(all_entries)} 件")
    return all_entries
