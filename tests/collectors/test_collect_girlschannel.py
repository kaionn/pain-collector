"""collect_girlschannel.py の fixture テスト."""

import re

import responses

from src.collect_girlschannel import collect

PAGE_URL_PATTERN = re.compile(r"https://girlschannel\.net/.*")

FIXTURE_HTML = """
<html><body>
<a href="/topics/1234567">
旦那の家事分担が不公平でストレスが溜まる
</a>
</body></html>
"""


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        PAGE_URL_PATTERN,
        body=FIXTURE_HTML,
        status=200,
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "girlschannel"
    assert post["title"] == "旦那の家事分担が不公平でストレスが溜まる"
    assert post["url"] == "https://girlschannel.net/topics/1234567"


@responses.activate
def test_collect_returns_empty_list_on_http_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        PAGE_URL_PATTERN,
        body="internal error",
        status=500,
    )

    result = collect()

    assert result == []
