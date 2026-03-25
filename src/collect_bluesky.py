"""Bluesky からペイン系の投稿を収集する."""

import logging
import re
import time

from src.http_utils import create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

# 認証不要の公開 API（Jetstream 経由の検索は不可のため、公開フィード API を使用）
API_BASE = "https://public.api.bsky.app/xrpc"

# ペインに関連するアカウントのフィード or 検索用クエリ
SEARCH_QUERIES = [
    "frustrated",
    "annoying",
    "不便",
    "ストレス",
    "使いにくい",
]

PAIN_KEYWORDS_EN = re.compile(
    r"\b(wish|annoying|hate|frustrating|why can'?t|sick of|tired of|"
    r"struggle|pain point|broken|useless|awful|terrible|worst|"
    r"impossible|inconvenient|waste of time)\b",
    re.IGNORECASE,
)

_session = create_retry_session()


def _search_posts(query: str, limit: int = 25) -> list[dict]:
    """Bluesky の公開検索 API で投稿を取得する."""
    url = f"{API_BASE}/app.bsky.feed.searchPosts"
    params = {"q": query, "limit": limit}
    try:
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("posts", [])
    except Exception as e:
        logger.warning(f"検索 '{query}' に失敗: {e}")
        return []


def _parse_post(post: dict) -> dict:
    """Bluesky の投稿データを共通フォーマットに変換する."""
    record = post.get("record", {})
    author = post.get("author", {})
    uri = post.get("uri", "")

    handle = author.get("handle", "")
    rkey = uri.split("/")[-1] if "/" in uri else ""
    web_url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else ""

    return {
        "source": "bluesky",
        "title": "",
        "url": web_url,
        "body": record.get("text", "")[:1000],
        "author": handle,
    }


def collect() -> list[dict]:
    """Bluesky からペイン系投稿を収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        posts = _search_posts(query)

        for post in posts:
            parsed = _parse_post(post)
            url = parsed["url"]
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            text = parsed["body"]
            if not (PAIN_KEYWORDS_EN.search(text) or contains_pain_keyword(text)):
                continue

            all_posts.append(parsed)

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(0.5)

    logger.info(f"{len(all_posts)} 件のペイン投稿を取得")
    return all_posts
