"""collect_stackoverflow.py の fixture テスト."""

import re

import responses

from src.collect_stackoverflow import collect

QUESTIONS_URL_PATTERN = re.compile(r"https://api\.stackexchange\.com/2\.3/questions\?.*")


@responses.activate
def test_collect_returns_expected_post_shape():
    responses.add(
        responses.GET,
        QUESTIONS_URL_PATTERN,
        json={
            "items": [
                {
                    "question_id": 555,
                    "title": "Why is this bug not working after upgrade",
                    "body": "<p>This is broken and I can't fix the issue.</p>",
                    "link": "https://stackoverflow.com/questions/555",
                    "score": 3,
                    "view_count": 50,
                    "answer_count": 0,
                }
            ]
        },
        status=200,
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "stackoverflow"
    assert post["title"] == "Why is this bug not working after upgrade"
    assert post["url"] == "https://stackoverflow.com/questions/555"
    assert post["body"] == "This is broken and I can't fix the issue."
    assert post["view_count"] == 50


@responses.activate
def test_collect_returns_empty_list_on_http_error():
    responses.add(
        responses.GET,
        QUESTIONS_URL_PATTERN,
        json={"error": "boom"},
        status=500,
    )

    result = collect()

    assert result == []
