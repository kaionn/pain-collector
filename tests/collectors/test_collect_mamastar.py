"""collect_mamastar.py の fixture テスト."""

import re

import responses

from src.collect_mamastar import PAGES, collect

PAGE_URL_PATTERN = re.compile(r"https://mamastar\.jp/bbs/(newlist|ranking/topic).*")

FIXTURE_HTML = """
<html><body>
<a href="/bbs/topic/998877">
旦那にイライラが止まらない、もう限界
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
    assert post["source"] == "mamastar"
    assert post["title"] == "旦那にイライラが止まらない、もう限界"
    assert post["url"] == "https://mamastar.jp/bbs/topic/998877"
    assert post["category"] in set(PAGES)


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
