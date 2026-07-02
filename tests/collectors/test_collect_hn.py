"""collect_hn.py の fixture テスト."""

import re

import responses

from src.collect_hn import collect

TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL_PATTERN = re.compile(r"https://hacker-news\.firebaseio\.com/v0/item/\d+\.json")


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(responses.GET, TOPSTORIES_URL, json=[111, 222], status=200)
    responses.add(
        responses.GET,
        ITEM_URL_PATTERN,
        json={
            "id": 111,
            "type": "story",
            "title": "why can't this broken build tool work",
            "text": "I'm so frustrated, it's annoying and a waste of time.",
            "score": 99,
            "descendants": 12,
            "url": "https://example.com/broken-tool",
            "time": 1700000000,
        },
        status=200,
    )

    result = collect(max_stories=2)

    assert len(result) == 2
    post = result[0]
    assert post["source"] == "hackernews"
    assert post["title"] == "why can't this broken build tool work"
    assert post["url"] == "https://example.com/broken-tool"
    assert post["score"] == 99


@responses.activate
def test_collect_returns_empty_list_on_http_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(responses.GET, TOPSTORIES_URL, json={"error": "boom"}, status=500)

    result = collect(max_stories=2)

    assert result == []
