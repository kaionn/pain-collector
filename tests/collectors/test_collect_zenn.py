"""collect_zenn.py の fixture テスト.

feedparser.parse は URL を渡すと urllib で実ネットワークアクセスするため
（responses は requests のみをフックする）、feedparser.parse 自体をモックし
実際の RSS XML 文字列を渡して本物のパース処理を通す。
"""

import feedparser

from src import collect_zenn
from src.collect_zenn import collect

FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Zenn Trend</title>
<item>
<title>デプロイが遅すぎて困っている話</title>
<link>https://zenn.dev/someone/articles/deploy-too-slow</link>
<description>CI のデプロイが遅すぎて非効率で、なんとかしたいと悩んでいます。</description>
<author>someone</author>
</item>
</channel>
</rss>
"""


def test_collect_returns_expected_post_shape(monkeypatch):
    real_parse = feedparser.parse
    monkeypatch.setattr(collect_zenn.feedparser, "parse", lambda *_a, **_k: real_parse(FIXTURE_XML))

    result = collect()

    assert len(result) == 1
    post = result[0]
    assert post["source"] == "zenn"
    assert post["title"] == "デプロイが遅すぎて困っている話"
    assert post["url"] == "https://zenn.dev/someone/articles/deploy-too-slow"
    assert post["author"] == "someone"


def test_collect_returns_empty_list_on_fetch_error(monkeypatch):
    def _raise(*_a, **_k):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(collect_zenn.feedparser, "parse", _raise)

    result = collect()

    assert result == []
