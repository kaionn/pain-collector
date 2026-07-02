"""collect_chiebukuro.py の fixture テスト."""

import re

import responses

from src.collect_chiebukuro import CATEGORIES, collect

CATEGORY_URL_PATTERN = re.compile(r"https://chiebukuro\.yahoo\.co\.jp/category/\d+/question/list.*")

FIXTURE_HTML = """
<html><body>
<a href="https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q1234567890">
子供の宿題が終わらなくて本当に困っています
</a>
</body></html>
"""


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        CATEGORY_URL_PATTERN,
        body=FIXTURE_HTML,
        status=200,
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "chiebukuro"
    assert post["title"] == "子供の宿題が終わらなくて本当に困っています"
    assert post["url"] == "https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q1234567890"
    assert post["category"] in {c for c in CATEGORIES}


@responses.activate
def test_collect_returns_empty_list_on_http_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        CATEGORY_URL_PATTERN,
        body="internal error",
        status=500,
    )

    result = collect()

    assert result == []
