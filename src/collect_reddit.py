"""Reddit から不満・ペイン系の投稿を収集する.

Reddit API (OAuth2 client_credentials) を使用。
環境変数 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET が未設定の場合は
公開 JSON エンドポイントにフォールバックする。
"""

import logging
import os
import re
import time

import requests

from src.collector_registry import register_collector
from src.http_utils import create_retry_session

logger = logging.getLogger(__name__)

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
    # 生活系
    "Cooking",
    "MealPrepSunday",
    "CleaningTips",
    "Parenting",
    "povertyfinance",
    "relationship_advice",
    "HomeImprovement",
    # 生活系（追加）
    "BabyBumps",
    "beyondthebump",
    "EatCheapAndHealthy",
    "Fitness",
    "loseit",
    "SkincareAddiction",
    "FIRE",
    "Frugal",
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

USER_AGENT = "pain-collector/1.0 (by /u/kaionn)"
MAX_POSTS_PER_SUB = 50

_session = create_retry_session()


def _get_oauth_token() -> str | None:
    """Reddit OAuth2 アクセストークンを取得する（client_credentials フロー）."""
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if token:
            logger.info("Reddit OAuth トークンを取得")
        return token
    except Exception as e:
        logger.warning(f"Reddit OAuth トークン取得失敗: {e}")
        return None


def _fetch_reddit(url: str, label: str, headers: dict) -> list[dict]:
    """Reddit API からデータを取得する."""
    try:
        resp = _session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("children", [])
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"{label} の取得に失敗: {e}")
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


def _fetch_hot(subreddit: str, base_url: str, headers: dict) -> list[dict]:
    """サブレディットのホット投稿を取得し、ペインキーワードでフィルタする."""
    url = f"{base_url}/r/{subreddit}/hot?limit={MAX_POSTS_PER_SUB}"
    children = _fetch_reddit(url, f"r/{subreddit}", headers)

    posts = []
    for child in children:
        post = _parse_post(child)
        combined = f"{post['title']} {post['body']}"
        if PAIN_KEYWORDS.search(combined):
            posts.append(post)
    return posts


def _search(subreddit: str, base_url: str, headers: dict, time_filter: str = "week") -> list[dict]:
    """サブレディットをキーワード検索する（バックフィル用）."""
    url = (
        f"{base_url}/r/{subreddit}/search"
        f"?q={SEARCH_QUERY}&restrict_sr=1&sort=relevance&t={time_filter}&limit={MAX_POSTS_PER_SUB}"
    )
    children = _fetch_reddit(url, f"r/{subreddit} (検索)", headers)
    return [_parse_post(child) for child in children]


@register_collector(key="reddit", display_name="Reddit", supports_backfill=True)
def collect(backfill: bool = False) -> list[dict]:
    """全サブレディットからペイン系投稿を収集する."""
    # OAuth トークンがあれば API 経由、なければ公開エンドポイント
    token = _get_oauth_token()
    if token:
        base_url = "https://oauth.reddit.com"
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        }
        logger.info("Reddit API (OAuth) で収集")
    else:
        base_url = "https://old.reddit.com"
        headers = {"User-Agent": USER_AGENT}
        logger.info("Reddit 公開エンドポイントで収集（OAuth 未設定）")

    all_posts = []
    seen_urls: set[str] = set()

    for i, sub in enumerate(SUBREDDITS):
        if backfill:
            posts = _search(sub, base_url, headers)
            label = "検索"
        else:
            posts = _fetch_hot(sub, base_url, headers)
            label = "取得"

        # URL で重複排除（クロスポスト対策）
        unique = []
        for p in posts:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                unique.append(p)

        all_posts.extend(unique)
        logger.info(f"r/{sub}: {len(unique)} 件のペイン投稿を{label}")

        # 最後のサブレディット以外はレート制限回避で待機
        if i < len(SUBREDDITS) - 1:
            time.sleep(1)

    logger.info(f"合計: {len(all_posts)} 件")
    return all_posts
