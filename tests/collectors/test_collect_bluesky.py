"""collect_bluesky.py の fixture テスト."""

import re

import responses

from src.collect_bluesky import collect

SEARCH_URL_PATTERN = re.compile(r"https://public\.api\.bsky\.app/xrpc/app\.bsky\.feed\.searchPosts.*")


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        SEARCH_URL_PATTERN,
        json={
            "posts": [
                {
                    "uri": "at://did:plc:abc123/app.bsky.feed.post/xyz789",
                    "author": {"handle": "someone.bsky.social"},
                    "record": {"text": "I'm so annoyed, this app is broken and frustrating."},
                }
            ]
        },
        status=200,
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "bluesky"
    assert post["url"] == "https://bsky.app/profile/someone.bsky.social/post/xyz789"
    assert post["author"] == "someone.bsky.social"
    assert "frustrating" in post["body"]


@responses.activate
def test_collect_returns_empty_list_on_http_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        SEARCH_URL_PATTERN,
        json={"error": "boom"},
        status=500,
    )

    result = collect()

    assert result == []
