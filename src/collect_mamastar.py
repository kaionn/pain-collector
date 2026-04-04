"""ママスタからペイン系のトピックを収集する."""

import logging
import re
import time

from bs4 import BeautifulSoup

from src.http_utils import DEFAULT_HEADERS, create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

# ママスタは生活相談サイトのため、一般的なペインキーワードに加え
# 相談・愚痴系の表現でもフィルタを通過させる
_LIFESTYLE_KEYWORDS = re.compile(
    r"(どうしたら|どうすれば|教えて|助けて|相談|愚痴|モヤモヤ|もやもや|"
    r"許せない|ゆるせない|嫌になる|やってられない|わからない|"
    r"つかれた|疲れた|泣きたい|泣ける|腹が立つ|腹立つ|ムカつく|むかつく|"
    r"どうしよう|やばい|ヤバい|後悔|離婚|転職|退職|"
    r"お金がない|給料|節約|貯金できない|赤字)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

# カテゴリ別トピック一覧 URL
CATEGORIES = {
    "育児": "https://mamastar.jp/bbs/topic?category=1",
    "家事": "https://mamastar.jp/bbs/topic?category=5",
    "夫婦": "https://mamastar.jp/bbs/topic?category=3",
    "お金": "https://mamastar.jp/bbs/topic?category=6",
    "働くママ": "https://mamastar.jp/bbs/topic?category=4",
}

_session = create_retry_session()


def _fetch_topics(category: str, url: str) -> list[dict]:
    """カテゴリページからトピック一覧を取得する."""
    try:
        resp = _session.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"{category} の取得に失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    topics: list[dict] = []

    for a_tag in soup.select("a[href*='/bbs/topic/']"):
        title = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")

        if not title or len(title) < 5:
            continue

        if not href.startswith("http"):
            href = f"https://mamastar.jp{href}"

        topics.append({
            "source": "mamastar",
            "category": category,
            "title": title[:200],
            "url": href,
            "body": title,
        })

    return topics


def collect() -> list[dict]:
    """ママスタからペイン系トピックを収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, (category, url) in enumerate(CATEGORIES.items()):
        topics = _fetch_topics(category, url)

        filtered = []
        for t in topics:
            if t["url"] in seen_urls:
                continue
            seen_urls.add(t["url"])

            title = t["title"]
            if not contains_pain_keyword(title) and not _LIFESTYLE_KEYWORDS.search(title):
                continue
            filtered.append(t)

        all_posts.extend(filtered)
        logger.info(f"{category}: {len(filtered)}/{len(topics)} 件がペインフィルタ通過")

        if i < len(CATEGORIES) - 1:
            time.sleep(1)

    return all_posts
