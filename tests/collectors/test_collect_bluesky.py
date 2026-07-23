"""collect_bluesky.py の fixture テスト."""

import re

import responses

from src.collect_bluesky import collect

SEARCH_URL_PATTERN = re.compile(r"https://public\.api\.bsky\.app/xrpc/app\.bsky\.feed\.searchPosts.*")
AUTH_SEARCH_URL_PATTERN = re.compile(r"https://bsky\.social/xrpc/app\.bsky\.feed\.searchPosts.*")
SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    monkeypatch.delenv("BLUESKY_IDENTIFIER", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)

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
    monkeypatch.delenv("BLUESKY_IDENTIFIER", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)

    responses.add(
        responses.GET,
        SEARCH_URL_PATTERN,
        json={"error": "boom"},
        status=500,
    )

    result = collect()

    assert result == []


@responses.activate
def test_collect_uses_authenticated_session_when_credentials_set(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    monkeypatch.setenv("BLUESKY_IDENTIFIER", "kaion.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "app-password")

    responses.add(
        responses.POST,
        SESSION_URL,
        json={"accessJwt": "dummy-jwt"},
        status=200,
    )
    responses.add(
        responses.GET,
        AUTH_SEARCH_URL_PATTERN,
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
    assert result[0]["url"] == "https://bsky.app/profile/someone.bsky.social/post/xyz789"
