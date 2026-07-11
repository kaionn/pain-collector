"""weekly_trends.cluster_pains の回帰テスト.

cluster_pains は weekly.yml でしか実行されず、TfidfVectorizer 直参照の
取り残し（NameError）が 17 週間発覚しなかった。ベクトライザ経路を
必ず通すテストで再発を防ぐ。
"""

from src.weekly_trends import cluster_pains


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
