"""ママスタからペイン系のトピックを収集する."""

import logging
import re
import time

from bs4 import BeautifulSoup

from src.collector_registry import register_collector
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

# カテゴリページ（?category=N）はトピックリンクが JS 化されサーバーレンダリングされなくなった。
# 新着・ランキング一覧ページはリンクが取得できることを確認済みのためこちらに切り替える。
PAGES = {
    "新着": ("https://mamastar.jp/bbs/newlist", 3),
    "ランキング": ("https://mamastar.jp/bbs/ranking/topic", 1),
}

_session = create_retry_session()

_TOPIC_URL_RE = re.compile(r"/bbs/topic/\d+$")


def _fetch_topics(category: str, url: str) -> list[dict]:
    """カテゴリページからトピック一覧を取得する."""
    try:
        resp = _session.get(url, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"{category} の取得に失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # トピック詳細（/bbs/topic/{数字}）のみ対象にする（/bbs/topic/category/N 等のナビリンクを除外）。
    # カード型アンカーは日付・コメント数まで連結されるため、内部の h3（見出し）があれば
    # そちらをタイトルとして採用する
    titles_by_url: dict[str, str] = {}
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not _TOPIC_URL_RE.search(href):
            continue

        heading = a_tag.find("h3")
        title = (heading or a_tag).get_text(strip=True)
        if not title or len(title) < 5:
            continue

        if not href.startswith("http"):
            href = f"https://mamastar.jp{href}"

        titles_by_url.setdefault(href, title)

    return [
        {
            "source": "mamastar",
            "category": category,
            "title": title[:200],
            "url": url,
            "body": title,
        }
        for url, title in titles_by_url.items()
    ]


@register_collector(key="mamastar", display_name="ママスタ")
def collect() -> list[dict]:
    """ママスタからペイン系トピックを収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, (category, (url, page_count)) in enumerate(PAGES.items()):
        topics: list[dict] = []
        for page in range(1, page_count + 1):
            page_url = url if page == 1 else f"{url}?page={page}"
            topics.extend(_fetch_topics(category, page_url))
            if page < page_count:
                time.sleep(0.5)

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

        if i < len(PAGES) - 1:
            time.sleep(1)

    return all_posts
