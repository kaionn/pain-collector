"""Reddit から不満・ペイン系の投稿を収集する."""

import re
import time

import requests

from src.http_utils import create_retry_session

SUBREDDITS = [
    "apps",
    "productivity",
    "webdev",
    "software",
    "iphone",
    "android",
    "LifeProTips",
    "mildlyinfuriating",
    "japanlife",
    "japanfinance",
    "personalfinance",
    "Entrepreneur",
    "careerguidance",
    "ADHD",
    "digitalnomad",
]

PAIN_KEYWORDS = re.compile(
    r"\b(wish|annoying|hate|frustrating|why can'?t|sick of|tired of|"
    r"struggle|pain point|broken|useless|awful|terrible|worst|"
    r"impossible|inconvenient|waste of time)\b",
    re.IGNORECASE,
)

# バックフィル用: Reddit 検索で使う OR クエリ（1 リクエストに統合）
SEARCH_QUERY = (
    "wish OR annoying OR frustrating OR hate OR terrible OR broken "
    "OR sick of OR tired of OR why can't"
)

USER_AGENT = "pain-collector/1.0 (GitHub Actions)"
MAX_POSTS_PER_SUB = 50


_session = create_retry_session()


def _fetch_reddit(url: str, label: str) -> list[dict]:
    """Reddit の公開 JSON エンドポイントからデータを取得する."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = _session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("children", [])
    except (requests.RequestException, ValueError) as e:
        print(f"[Reddit] {label} の取得に失敗: {e}")
        return []


def _parse_post(child: dict) -> dict:
    """Reddit の投稿データを共通フォーマットに変換する."""
    post = child.get("data", {})
    return {
        "source": "reddit",
        "subreddit": post.get("subreddit", ""),
        "title": post.get("title", ""),
        "body": post.get("selftext", "")[:1000],
        "score": post.get("score", 0),
        "num_comments": post.get("num_comments", 0),
        "url": f"https://www.reddit.com{post.get('permalink', '')}",
        "created_utc": post.get("created_utc", 0),
    }


def _fetch_hot(subreddit: str) -> list[dict]:
    """サブレディットのホット投稿を取得し、ペインキーワードでフィルタする."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={MAX_POSTS_PER_SUB}"
    children = _fetch_reddit(url, f"r/{subreddit}")

    posts = []
    for child in children:
        post = _parse_post(child)
        combined = f"{post['title']} {post['body']}"
        if PAIN_KEYWORDS.search(combined):
            posts.append(post)
    return posts


def _search(subreddit: str, time_filter: str = "week") -> list[dict]:
    """サブレディットをキーワード検索する（バックフィル用）."""
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        f"?q={SEARCH_QUERY}&restrict_sr=1&sort=relevance&t={time_filter}&limit={MAX_POSTS_PER_SUB}"
    )
    children = _fetch_reddit(url, f"r/{subreddit} (検索)")
    return [_parse_post(child) for child in children]


def collect(backfill: bool = False) -> list[dict]:
    """全サブレディットからペイン系投稿を収集する."""
    all_posts = []
    seen_urls: set[str] = set()

    for i, sub in enumerate(SUBREDDITS):
        if backfill:
            posts = _search(sub)
            label = "検索"
        else:
            posts = _fetch_hot(sub)
            label = "取得"

        # URL で重複排除（クロスポスト対策）
        unique = []
        for p in posts:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                unique.append(p)

        all_posts.extend(unique)
        print(f"[Reddit] r/{sub}: {len(unique)} 件のペイン投稿を{label}")

        # 最後のサブレディット以外はレート制限回避で待機
        if i < len(SUBREDDITS) - 1:
            time.sleep(2)

    print(f"[Reddit] 合計: {len(all_posts)} 件")
    return all_posts
