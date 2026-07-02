"""collect_devto.py の fixture テスト."""

import re

import responses

from src.collect_devto import collect

ARTICLES_URL_PATTERN = re.compile(r"https://dev\.to/api/articles\?.*")


@responses.activate
def test_collect_returns_expected_post_shape():
    responses.add(
        responses.GET,
        ARTICLES_URL_PATTERN,
        json=[
            {
                "title": "Why can't build tools stop being so annoying",
                "description": "I'm tired of this broken workflow every single day.",
                "url": "https://dev.to/someone/why-cant-build-tools-1a2b",
                "tag_list": ["discuss", "rant"],
            }
        ],
        status=200,
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "devto"
    assert post["title"] == "Why can't build tools stop being so annoying"
    assert post["url"] == "https://dev.to/someone/why-cant-build-tools-1a2b"
    assert post["tags"] == ["discuss", "rant"]


@responses.activate
def test_collect_returns_empty_list_on_http_error():
    responses.add(
        responses.GET,
        ARTICLES_URL_PATTERN,
        json={"error": "boom"},
        status=500,
    )

    result = collect()

    assert result == []
