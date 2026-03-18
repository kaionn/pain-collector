"""Hacker News から不満・ペイン系の投稿を収集する."""

import re
import time

import requests

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

PAIN_KEYWORDS = re.compile(
    r"\b(wish|annoying|hate|frustrating|why can'?t|sick of|tired of|"
    r"struggle|pain point|broken|useless|awful|terrible|worst|"
    r"impossible|inconvenient|waste of time)\b",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    """HTML タグを除去する."""
    return re.sub(r"<[^>]+>", "", text)


def _fetch_top_story_ids(max_stories: int) -> list[int]:
    """トップストーリーの ID リストを取得する."""
    url = f"{HN_API_BASE}/topstories.json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        ids: list[int] = resp.json()
        return ids[:max_stories]
    except (requests.RequestException, ValueError) as e:
        print(f"[HN] トップストーリー ID の取得に失敗: {e}")
        return []


def _fetch_item(item_id: int) -> dict | None:
    """個別ストーリーの詳細を取得する."""
    url = f"{HN_API_BASE}/item/{item_id}.json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def _parse_item(item: dict) -> dict:
    """HN のアイテムデータを共通フォーマットに変換する."""
    item_id = item.get("id", "")
    raw_text = item.get("text") or ""
    body = _strip_html(raw_text)[:1000]

    story_url = item.get("url") or f"https://news.ycombinator.com/item?id={item_id}"

    return {
        "source": "hackernews",
        "title": item.get("title", ""),
        "body": body,
        "score": item.get("score", 0),
        "num_comments": item.get("descendants", 0),
        "url": story_url,
        "created_utc": item.get("time", 0),
    }


def collect(max_stories: int = 200) -> list[dict]:
    """HN トップストーリーからペイン系投稿を収集する."""
    story_ids = _fetch_top_story_ids(max_stories)
    if not story_ids:
        return []

    pain_posts: list[dict] = []

    for i, story_id in enumerate(story_ids):
        item = _fetch_item(story_id)

        if item is None:
            time.sleep(0.1)
            continue

        # story タイプのみ対象（jobs, polls, comments は除外）
        if item.get("type") != "story":
            time.sleep(0.1)
            continue

        parsed = _parse_item(item)
        combined = f"{parsed['title']} {parsed['body']}"

        if PAIN_KEYWORDS.search(combined):
            pain_posts.append(parsed)

        # レート制限回避
        if i < len(story_ids) - 1:
            time.sleep(0.1)

    print(f"[HN] {max_stories} 件中 {len(pain_posts)} 件のペイン投稿を取得")
    return pain_posts
