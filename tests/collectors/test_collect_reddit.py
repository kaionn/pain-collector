"""collect_reddit.py の fixture テスト."""

import re

import responses

from src.collect_reddit import collect

HOT_URL_PATTERN = re.compile(r"https://old\.reddit\.com/r/.+/hot.*")


def _make_child(post_id: str) -> dict:
    return {
        "data": {
            "subreddit": "productivity",
            "title": f"why can't apps just work {post_id}",
            "selftext": "I'm so tired of this broken workflow, it's annoying.",
            "score": 42,
            "num_comments": 3,
            "permalink": f"/r/productivity/comments/{post_id}/why_cant_apps_work/",
            "created_utc": 1700000000,
        }
    }


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        HOT_URL_PATTERN,
        json={"data": {"children": [_make_child("abc123")]}},
        status=200,
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "reddit"
    assert post["title"] == "why can't apps just work abc123"
    assert post["url"] == "https://www.reddit.com/r/productivity/comments/abc123/why_cant_apps_work/"
    assert post["subreddit"] == "productivity"


@responses.activate
def test_collect_returns_empty_list_on_http_error(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        HOT_URL_PATTERN,
        json={"error": "internal"},
        status=500,
    )

    result = collect()

    assert result == []
