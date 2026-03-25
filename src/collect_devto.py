"""Dev.to からペイン系の記事を収集する."""

import logging
import re

from src.http_utils import create_retry_session

logger = logging.getLogger(__name__)

API_BASE = "https://dev.to/api/articles"

TAGS = ["discuss", "watercooler", "help"]

PAIN_KEYWORDS = re.compile(
    r"\b(wish|annoying|hate|frustrating|why can'?t|sick of|tired of|"
    r"struggle|pain point|broken|useless|awful|terrible|worst|"
    r"impossible|inconvenient|waste of time)\b",
    re.IGNORECASE,
)

_session = create_retry_session()


def _fetch_articles(tag: str, per_page: int = 30) -> list[dict]:
    """指定タグの記事を取得する."""
    url = f"{API_BASE}?tag={tag}&per_page={per_page}&top=7"
    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"tag={tag} の取得に失敗: {e}")
        return []


def collect() -> list[dict]:
    """Dev.to からペイン系記事を収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for tag in TAGS:
        articles = _fetch_articles(tag)

        for article in articles:
            url = article.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = article.get("title", "")
            description = article.get("description", "")[:1000]
            combined = f"{title} {description}"

            if not PAIN_KEYWORDS.search(combined):
                continue

            all_posts.append({
                "source": "devto",
                "title": title,
                "url": url,
                "body": description,
                "tags": article.get("tag_list", []),
            })

    logger.info(f"{len(all_posts)} 件のペイン記事を取得")
    return all_posts
