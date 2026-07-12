"""weekly_trends.cluster_pains の回帰テスト.

cluster_pains は weekly.yml でしか実行されず、TfidfVectorizer 直参照の
取り残し（NameError）が 17 週間発覚しなかった。ベクトライザ経路を
必ず通すテストで再発を防ぐ。
"""

from src.weekly_trends import _build_trend_corpus, cluster_pains


def _pain(text: str) -> dict:
    return {"pain": text}


def test_cluster_pains_groups_similar_texts():
    pains = [
        _pain("PayPayアプリが頻繁に落ちて決済ができない"),
        _pain("PayPayアプリが落ちて決済に失敗する"),
        _pain("自炊のモチベーションが続かず外食費がかさむ"),
    ]
    clusters = cluster_pains(pains, threshold=0.3)

    assert sum(c["count"] for c in clusters) == 3
    # 類似する PayPay 系 2 件が同一クラスタに寄る
    assert clusters[0]["count"] == 2
    assert all(set(c) == {"representative", "count", "members"} for c in clusters)


def test_cluster_pains_single_item_shortcut():
    clusters = cluster_pains([_pain("唯一のペイン")])
    assert clusters == [
        {"representative": "唯一のペイン", "count": 1, "members": ["唯一のペイン"]}
    ]


def test_build_trend_corpus_includes_all_when_within_limit():
    clusters = [
        {"representative": "PayPayが落ちる", "count": 5, "members": []},
        {"representative": "自炊が続かない", "count": 2, "members": []},
    ]
    combined, dropped = _build_trend_corpus(clusters, max_chars=4000)

    assert dropped == 0
    assert "PayPayが落ちる (類似 5 件)" in combined
    assert "自炊が続かない (類似 2 件)" in combined
    assert combined.count("\n") == 1


def test_build_trend_corpus_drops_tail_when_over_limit():
    clusters = [
        {"representative": "A" * 10, "count": 3, "members": []},
        {"representative": "B" * 10, "count": 2, "members": []},
        {"representative": "C" * 10, "count": 1, "members": []},
    ]
    # 1 行目のみ収まる文字数に上限を絞る
    line_len = len(f"{'A' * 10} (類似 3 件)")
    combined, dropped = _build_trend_corpus(clusters, max_chars=line_len)

    assert combined == f"{'A' * 10} (類似 3 件)"
    assert dropped == 2


def test_build_trend_corpus_empty_list():
    assert _build_trend_corpus([], max_chars=4000) == ("", 0)
