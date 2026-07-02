"""発言小町からペイン系のトピックを収集する."""

import logging
import re
import time

from bs4 import BeautifulSoup

from src.collector_registry import register_collector
from src.http_utils import DEFAULT_HEADERS, create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

# サイトがランキング番号・レス数・日時・タグを <a> 内に連結するため分離が必要
# 例: "1義父からの生理予定日確認に違和感1292026年04月01日 19:01話題"
_CLEAN_PATTERN = re.compile(
    r"^\d{1,3}"  # 先頭のランキング番号
    r"(.+?)"  # タイトル本体（非貪欲）
    r"\d*\d{4}年\d{2}月\d{2}日.*$"  # レス数+日時+タグ
)

# カテゴリ別ランキング URL
CATEGORIES = {
    "生活": "https://komachi.yomiuri.co.jp/topics/genre/life/ranking/",
    "恋愛": "https://komachi.yomiuri.co.jp/topics/genre/love/ranking/",
    "夫婦": "https://komachi.yomiuri.co.jp/topics/genre/couple/ranking/",
    "子育て": "https://komachi.yomiuri.co.jp/topics/genre/child/ranking/",
    "働く": "https://komachi.yomiuri.co.jp/topics/genre/work/ranking/",
    "人間関係": "https://komachi.yomiuri.co.jp/topics/genre/people/ranking/",
    "健康": "https://komachi.yomiuri.co.jp/topics/genre/health/ranking/",
    "美容": "https://komachi.yomiuri.co.jp/topics/genre/beauty/ranking/",
}

_session = create_retry_session()

# 1 カテゴリあたり何ページ取りに行くか（生活系ペインの取得量を増やすため）
PAGES_PER_CATEGORY = 2


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

    for a_tag in soup.select("a[href*='/topics/id/']"):
        raw_text = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")

        if not raw_text or len(raw_text) < 5:
            continue

        m = _CLEAN_PATTERN.match(raw_text)
        title = m.group(1).strip() if m else raw_text

        if not href.startswith("http"):
            href = f"https://komachi.yomiuri.co.jp{href}"

        topics.append({
            "source": "komachi",
            "category": category,
            "title": title[:200],
            "url": href,
            "body": title,
        })

    return topics


@register_collector(key="komachi", display_name="発言小町")
def collect() -> list[dict]:
    """発言小町からペイン系トピックを収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, (category, url) in enumerate(CATEGORIES.items()):
        topics: list[dict] = []
        for page in range(1, PAGES_PER_CATEGORY + 1):
            page_url = url if page == 1 else f"{url.rstrip('/')}/page/{page}/"
            topics.extend(_fetch_topics(category, page_url))
            if page < PAGES_PER_CATEGORY:
                time.sleep(0.5)

        filtered = []
        for t in topics:
            if t["url"] in seen_urls:
                continue
            seen_urls.add(t["url"])

            if not contains_pain_keyword(t["title"]):
                continue
            filtered.append(t)

        all_posts.extend(filtered)
        logger.info(f"{category}: {len(filtered)}/{len(topics)} 件がペインフィルタ通過")

        if i < len(CATEGORIES) - 1:
            time.sleep(1)

    return all_posts
