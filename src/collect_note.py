"""note.com からペイン系記事を検索 API で収集する.

/topic/*/rss は廃止済み（404）のため、v3 検索 API に置き換えている。
"""

import logging
import time

from src.collector_registry import register_collector
from src.http_utils import DEFAULT_HEADERS, create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

SEARCH_URL = "https://note.com/api/v3/searches"

SEARCH_QUERIES = ["不便", "困っている", "ストレス", "使いにくい", "面倒", "自動化したい"]

_session = create_retry_session()


def _search(query: str) -> list[dict]:
    """検索クエリで note.com の記事を取得する."""
    params = {"context": "note", "q": query, "size": 20, "sort": "new"}
    try:
        resp = _session.get(SEARCH_URL, params=params, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        contents = resp.json().get("data", {}).get("notes", {}).get("contents", [])
    except Exception as e:
        logger.warning(f"{query} の取得に失敗: {e}")
        return []

    entries = []
    for item in contents:
        key = item.get("key", "")
        user = item.get("user", {})
        urlname = user.get("urlname", "")
        if not key or not urlname:
            continue

        entries.append(
            {
                "source": "note",
                "category": query,
                "title": item.get("name", ""),
                "url": f"https://note.com/{urlname}/n/{key}",
                "summary": (item.get("highlight") or "")[:500],
                "author": user.get("name") or urlname,
            }
        )

    return entries


@register_collector(key="note", display_name="note")
def collect() -> list[dict]:
    """note.com の検索 API からペイン系記事を取得する."""
    seen_keys: set[str] = set()
    all_entries: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        entries = _search(query)

        # 全文検索は本文中の一致だけの無関係な記事を多く拾うため（実測 115 件中
        # ペイン記事は 1 割程度）、タイトルにペインキーワードがあるものに絞る
        unique = []
        for entry in entries:
            key = entry["url"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if not contains_pain_keyword(entry["title"]):
                continue
            unique.append(entry)

        all_entries.extend(unique)
        logger.info(f"{query}: {len(unique)}/{len(entries)} 件がペインフィルタ通過")

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(0.5)

    logger.info(f"合計: {len(all_entries)} 件")
    return all_entries
