"""Yahoo 知恵袋からペイン系の質問を収集する."""

import logging
import re
import time

from bs4 import BeautifulSoup

from src.http_utils import create_retry_session
from src.pain_keywords_ja import contains_pain_keyword

logger = logging.getLogger(__name__)

# カテゴリ別の新着質問 URL
CATEGORIES = {
    "子育て・教育": "https://chiebukuro.yahoo.co.jp/category/2078297513/question/list",
    "暮らし・生活": "https://chiebukuro.yahoo.co.jp/category/2078297283/question/list",
    "お金・保険": "https://chiebukuro.yahoo.co.jp/category/2078297811/question/list",
    "仕事・職業": "https://chiebukuro.yahoo.co.jp/category/2078297854/question/list",
    "健康・病気": "https://chiebukuro.yahoo.co.jp/category/2078297616/question/list",
    # 生活系強化
    "暮らしと生活ガイド": "https://chiebukuro.yahoo.co.jp/category/2078297937/question/list",
    "恋愛・人間関係": "https://chiebukuro.yahoo.co.jp/category/2079526977/question/list",
    "地域・旅行": "https://chiebukuro.yahoo.co.jp/category/2078297918/question/list",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

_session = create_retry_session()


def _fetch_questions(category: str, url: str) -> list[dict]:
    """カテゴリページから質問一覧を取得する."""
    try:
        resp = _session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"{category} の取得に失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    questions: list[dict] = []

    # 質問リストのリンクを取得（detail.chiebukuro.yahoo.co.jp のリンク）
    for a_tag in soup.select("a[href*='question_detail']"):
        title = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")

        if not title or not href or len(title) < 10:
            continue

        if not href.startswith("http"):
            href = f"https://chiebukuro.yahoo.co.jp{href}"

        questions.append({
            "source": "chiebukuro",
            "category": category,
            "title": title[:200],
            "url": href,
            "body": title,
        })

    return questions


def collect() -> list[dict]:
    """Yahoo 知恵袋からペイン系質問を収集する."""
    seen_urls: set[str] = set()
    all_posts: list[dict] = []

    for i, (category, url) in enumerate(CATEGORIES.items()):
        questions = _fetch_questions(category, url)

        filtered = []
        for q in questions:
            if q["url"] in seen_urls:
                continue
            seen_urls.add(q["url"])

            text = f"{q['title']} {q['body']}"
            if not contains_pain_keyword(text):
                continue
            filtered.append(q)

        all_posts.extend(filtered)
        logger.info(f"{category}: {len(filtered)}/{len(questions)} 件がペインフィルタ通過")

        if i < len(CATEGORIES) - 1:
            time.sleep(1)

    return all_posts
