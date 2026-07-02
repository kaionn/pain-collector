"""collect_appstore.py の fixture テスト."""

import re

import responses

from src.collect_appstore import TARGET_APPS, collect

REVIEWS_URL_PATTERN = re.compile(
    r"https://itunes\.apple\.com/jp/rss/customerreviews/id=\d+/sortBy=mostRecent/json"
)

FIXTURE_FEED = {
    "feed": {
        "entry": [
            {"im:name": {"label": "App Info Entry"}},
            {
                "im:rating": {"label": "1"},
                "title": {"label": "Terrible app"},
                "content": {"label": "This is broken and I'm so frustrated, it's the worst."},
            },
        ]
    }
}


@responses.activate
def test_collect_returns_expected_post_shape():
    responses.add(
        responses.GET,
        REVIEWS_URL_PATTERN,
        json=FIXTURE_FEED,
        status=200,
    )

    result = collect()

    assert len(result) == len(TARGET_APPS)
    post = result[0]
    assert post["source"] == "appstore"
    assert post["title"].endswith("Terrible app")
    assert post["score"] == 1
    assert "frustrated" in post["body"]


@responses.activate
def test_collect_returns_empty_list_on_http_error():
    responses.add(
        responses.GET,
        REVIEWS_URL_PATTERN,
        json={"error": "boom"},
        status=500,
    )

    result = collect()

    assert result == []
