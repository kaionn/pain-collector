"""collect_producthunt.py の fixture テスト.

feedparser.parse は URL を渡すと urllib で実ネットワークアクセスするため
（responses は requests のみをフックする）、feedparser.parse 自体をモックし
実際の RSS XML 文字列を渡して本物のパース処理を通す。
"""

import feedparser

from src import collect_producthunt
from src.collect_producthunt import collect

FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Product Hunt</title>
<item>
<title>TaskFlow - simple task manager</title>
<link>https://www.producthunt.com/posts/taskflow</link>
<description>A simple task manager for busy teams.</description>
<category term="productivity"/>
</item>
</channel>
</rss>
"""


def test_collect_returns_expected_post_shape(monkeypatch):
    real_parse = feedparser.parse
    monkeypatch.setattr(
        collect_producthunt.feedparser, "parse", lambda *_a, **_k: real_parse(FIXTURE_XML)
    )

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "producthunt"
    assert post["title"] == "TaskFlow - simple task manager"
    assert post["url"] == "https://www.producthunt.com/posts/taskflow"
    assert post["tags"] == ["productivity"]


def test_collect_returns_empty_list_on_fetch_error(monkeypatch):
    def _raise(*_a, **_k):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(collect_producthunt.feedparser, "parse", _raise)

    result = collect()

    assert result == []
