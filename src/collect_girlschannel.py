"""ガールズちゃんねるからペイン系のトピックを収集する."""

import logging
import time

from bs4 import BeautifulSoup

from src.http_utils import DEFAULT_HEADERS, create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

TOP_URL = "https://girlschannel.net/"

# 新着・ランキングページ（生活系ペイン取得量を増やすためページ 2 まで取得）
PAGES = {
    "新着": "https://girlschannel.net/new/",
    "新着p2": "https://girlschannel.net/new/2/",
    "ランキング": "https://girlschannel.net/rank/",
    "ランキングp2": "https://girlschannel.net/rank/2/",
}

_session = create_retry_session()


def _fetch_topics(page_name: str, url: str) -> list[dict]:
    """ページからトピック一覧を取得する."""
    try:
        resp = _session.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"{page_name} の取得に失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    topics: list[dict] = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        if "/topics/" not in href:
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        if not href.startswith("http"):
            href = f"https://girlschannel.net{href}"

        topics.append({
            "source": "girlschannel",
            "title": title[:200],
            "url": href,
            "body": title,
        })

    return topics


def collect() -> list[dict]:
    """ガールズちゃんねるからペイン系トピックを収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, (page_name, url) in enumerate(PAGES.items()):
        topics = _fetch_topics(page_name, url)

        filtered = []
        for t in topics:
            if t["url"] in seen_urls:
                continue
            seen_urls.add(t["url"])

            if not contains_pain_keyword(t["title"]):
                continue
            filtered.append(t)

        all_posts.extend(filtered)
        logger.info(f"{page_name}: {len(filtered)}/{len(topics)} 件がペインフィルタ通過")

        if i < len(PAGES) - 1:
            time.sleep(1)

    return all_posts
