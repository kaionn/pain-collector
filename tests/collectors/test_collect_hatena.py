"""collect_hatena.py の fixture テスト.

feedparser.parse は URL 文字列を渡すと内部で urllib により実ネットワークアクセスするため
（responses は requests のみをフックし urllib は対象外）、
feedparser.parse 自体をモックし、実際の RSS XML 文字列（ネットワークに出ない）を
渡して本物の feedparser パース処理を通す。
"""

import feedparser

from src import collect_hatena
from src.collect_hatena import CATEGORIES, collect

FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">
<channel>
<title>Hot Entry</title>
<item>
<title>家事が面倒で本当に困っている件</title>
<link>https://example.com/entry1</link>
<description>毎日の家事が面倒すぎて困っています。何かいい方法はないでしょうか。</description>
<hatena:bookmarkcount>120</hatena:bookmarkcount>
</item>
</channel>
</rss>
"""


def test_collect_returns_expected_post_shape(monkeypatch):
    real_parse = feedparser.parse
    monkeypatch.setattr(collect_hatena.feedparser, "parse", lambda *_a, **_k: real_parse(FIXTURE_XML))

    result = collect()

    assert len(result) == len(CATEGORIES)
    post = result[0]
    assert post["source"] == "hatena"
    assert post["title"] == "家事が面倒で本当に困っている件"
    assert post["url"] == "https://example.com/entry1"
    assert post["bookmarks"] == 120


def test_collect_returns_empty_list_on_fetch_error(monkeypatch):
    def _raise(*_a, **_k):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(collect_hatena.feedparser, "parse", _raise)

    result = collect()

    assert result == []
