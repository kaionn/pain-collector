"""collect_note.py の fixture テスト.

feedparser.parse は URL を渡すと urllib で実ネットワークアクセスするため
（responses は requests のみをフックする）、feedparser.parse 自体をモックし
実際の RSS XML 文字列を渡して本物のパース処理を通す。
"""

import feedparser

from src import collect_note
from src.collect_note import NOTE_RSS_URLS, collect

FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>note</title>
<item>
<title>在宅ワークの家事負担が辛すぎる件</title>
<link>https://note.com/someone/n/n1234567890ab</link>
<description>在宅ワークになってから家事の負担が辛くて、改善策を探しています。</description>
<author>someone</author>
</item>
</channel>
</rss>
"""


def test_collect_returns_expected_post_shape(monkeypatch):
    real_parse = feedparser.parse
    monkeypatch.setattr(collect_note.feedparser, "parse", lambda *_a, **_k: real_parse(FIXTURE_XML))

    result = collect()

    assert len(result) == len(NOTE_RSS_URLS)
    post = result[0]
    assert post["source"] == "note"
    assert post["title"] == "在宅ワークの家事負担が辛すぎる件"
    assert post["url"] == "https://note.com/someone/n/n1234567890ab"
    assert post["author"] == "someone"


def test_collect_returns_empty_list_on_fetch_error(monkeypatch):
    def _raise(*_a, **_k):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(collect_note.feedparser, "parse", _raise)

    result = collect()

    assert result == []
