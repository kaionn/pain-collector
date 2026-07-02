"""collect_googleplay.py の fixture テスト.

google_play_scraper は requests 経由の単純な JSON API ではなく
Google 内部の batchexecute プロトコルを直接叩くため、
responses による HTTP モックではなく collect_googleplay.reviews 関数自体を
モックしてパース・フィルタロジックを検証する。
"""

from src.collect_googleplay import TARGET_APPS, collect


def _fake_reviews_ok(app_id, lang, country, sort, count, filter_score_with):
    review = {
        "content": "アプリが重くて動かない、本当に困っています。不便すぎる。",
        "userName": "user1",
        "score": filter_score_with,
    }
    return [review], None


def _fake_reviews_error(app_id, lang, country, sort, count, filter_score_with):
    raise ConnectionError("google play scraper failed")


def test_collect_returns_expected_post_shape(monkeypatch):
    monkeypatch.setattr("src.collect_googleplay.reviews", _fake_reviews_ok)

    result = collect()

    # 1 アプリにつき score=1 / score=2 の 2 回呼ばれる
    assert len(result) == len(TARGET_APPS) * 2
    post = result[0]
    assert post["source"] == "googleplay"
    assert "困っています" in post["body"]
    assert post["score"] == 1


def test_collect_returns_empty_list_on_scraper_error(monkeypatch):
    monkeypatch.setattr("src.collect_googleplay.reviews", _fake_reviews_error)

    result = collect()

    assert result == []
