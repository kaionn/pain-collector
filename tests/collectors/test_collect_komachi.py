"""collect_komachi.py の fixture テスト."""

import re

import responses

from src.collect_komachi import CATEGORIES, collect

PAGE_URL_PATTERN = re.compile(r"https://komachi\.yomiuri\.co\.jp/topics/genre/.+/ranking/.*")

# 先頭がランキング番号でなく末尾も日付でないため _CLEAN_PATTERN にマッチせず、
# raw_text がそのまま title として使われる
FIXTURE_HTML = """
<html><body>
<a href="/topics/id/1234567/">
義理の両親との同居がしんどい
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
    assert post["source"] == "komachi"
    assert post["title"] == "義理の両親との同居がしんどい"
    assert post["url"] == "https://komachi.yomiuri.co.jp/topics/id/1234567/"
    assert post["category"] in set(CATEGORIES)


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
