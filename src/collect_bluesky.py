"""Bluesky からペイン系の投稿を収集する."""

import logging
import os
import re
import time

from src.collector_registry import register_collector
from src.http_utils import create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

# 公開 API（未認証）は searchPosts を 403 で遮断するようになったため、
# 環境変数があれば app password 認証でアクセスする
PUBLIC_API_BASE = "https://public.api.bsky.app/xrpc"
AUTH_API_BASE = "https://bsky.social/xrpc"

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


def _get_session_token() -> str | None:
    """app password 認証でアクセストークンを取得する."""
    identifier = os.environ.get("BLUESKY_IDENTIFIER", "")
    app_password = os.environ.get("BLUESKY_APP_PASSWORD", "")
    if not identifier or not app_password:
        return None

    try:
        resp = _session.post(
            f"{AUTH_API_BASE}/com.atproto.server.createSession",
            json={"identifier": identifier, "password": app_password},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json().get("accessJwt")
        if token:
            logger.info("Bluesky セッションを取得")
        return token
    except Exception as e:
        logger.warning(f"Bluesky セッション取得失敗: {e}")
        return None


def _search_posts(query: str, base_url: str, headers: dict, limit: int = 25) -> list[dict]:
    """Bluesky の検索 API で投稿を取得する."""
    url = f"{base_url}/app.bsky.feed.searchPosts"
    params = {"q": query, "limit": limit}
    try:
        resp = _session.get(url, params=params, headers=headers, timeout=15)
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


@register_collector(key="bluesky", display_name="Bluesky")
def collect() -> list[dict]:
    """Bluesky からペイン系投稿を収集する."""
    token = _get_session_token()
    if token:
        base_url = AUTH_API_BASE
        headers = {"Authorization": f"Bearer {token}"}
    else:
        base_url = PUBLIC_API_BASE
        headers = {}
        logger.info("Bluesky 認証未設定のため公開 API を使用")

    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, query in enumerate(SEARCH_QUERIES):
        posts = _search_posts(query, base_url, headers)

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
