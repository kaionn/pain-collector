"""collect_note.py の fixture テスト."""

import re

import responses

from src.collect_note import collect

SEARCH_URL_PATTERN = re.compile(r"https://note\.com/api/v3/searches.*")


@responses.activate
def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        SEARCH_URL_PATTERN,
        json={
            "data": {
                "notes": {
                    "contents": [
                        {
                            "key": "n1234567890ab",
                            "name": "在宅ワークの家事負担がつらい、困っている件",
                            "highlight": "在宅ワークになってから家事の負担が辛くて困っています。",
                            "user": {"urlname": "someone", "name": "someone-san"},
                        }
                    ]
                }
            }
        },
        status=200,
    )

    result = collect()

    # 同一記事が全クエリで返る fixture のため、key による重複排除で 1 件に集約される
    # （タイトルがペインキーワードを含むためフィルタも通過する）
    assert len(result) == 1
    post = result[0]
    assert post["source"] == "note"
    assert post["title"] == "在宅ワークの家事負担がつらい、困っている件"
    assert post["url"] == "https://note.com/someone/n/n1234567890ab"
    assert post["author"] == "someone-san"


@responses.activate
def test_collect_returns_empty_list_on_fetch_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    responses.add(
        responses.GET,
        SEARCH_URL_PATTERN,
        body="internal error",
        status=500,
    )

    result = collect()

    assert result == []
