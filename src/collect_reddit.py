"""Reddit から不満・ペイン系の投稿を収集する."""

import re
import time

import requests

SUBREDDITS = [
    "apps",
    "productivity",
    "webdev",
    "software",
    "iphone",
    "android",
    "LifeProTips",
    "mildlyinfuriating",
]

PAIN_KEYWORDS = re.compile(
    r"\b(wish|annoying|hate|frustrating|why can'?t|sick of|tired of|"
    r"struggle|pain point|broken|useless|awful|terrible|worst|"
    r"impossible|inconvenient|waste of time)\b",
    re.IGNORECASE,
)

USER_AGENT = "pain-collector/1.0 (GitHub Actions)"
MAX_POSTS_PER_SUB = 50


def fetch_subreddit(subreddit: str) -> list[dict]:
    """サブレディットのホット投稿を公開 JSON エンドポイントで取得する."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={MAX_POSTS_PER_SUB}"
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[Reddit] r/{subreddit} の取得に失敗: {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        combined = f"{title} {selftext}"

        if PAIN_KEYWORDS.search(combined):
            posts.append(
                {
                    "source": "reddit",
                    "subreddit": subreddit,
                    "title": title,
                    "body": selftext[:1000],
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "url": f"https://www.reddit.com{post.get('permalink', '')}",
                }
            )

    return posts


def collect() -> list[dict]:
    """全サブレディットからペイン系投稿を収集する."""
    all_posts = []
    for sub in SUBREDDITS:
        posts = fetch_subreddit(sub)
        all_posts.extend(posts)
        print(f"[Reddit] r/{sub}: {len(posts)} 件のペイン投稿を取得")
        time.sleep(2)  # レート制限回避

    print(f"[Reddit] 合計: {len(all_posts)} 件")
    return all_posts
