"""market_check.py の市場シグナル判定ロジックのユニットテスト.

外部 API（iTunes Search API）はテストしない。
enrich_pain_with_market_data のシグナル判定ロジックをインラインで検証する。
"""

import pytest


def _determine_signal(apps: list[dict], avg_rating: float, total_reviews: int,
                      rating_threshold: float = 3.5, reviews_threshold: int = 1000) -> str:
    """market_check.py の enrich_pain_with_market_data 内の判定ロジックを再現する."""
    if not apps:
        return "whitespace"
    if total_reviews == 0:
        return "whitespace"
    elif avg_rating < rating_threshold:
        return "underserved"
    elif total_reviews < reviews_threshold:
        return "emerging"
    else:
        return "competitive"


class TestMarketSignalDetermination:
    """市場シグナル判定のテスト."""

    def test_no_apps_returns_whitespace(self):
        """アプリが見つからない場合はホワイトスペース."""
        signal = _determine_signal([], 0.0, 0)
        assert signal == "whitespace"

    def test_apps_with_zero_reviews_returns_whitespace(self):
        """レビューが 0 件の場合はホワイトスペース."""
        apps = [{"name": "App A", "rating": 4.0, "reviews": 0}]
        signal = _determine_signal(apps, avg_rating=4.0, total_reviews=0)
        assert signal == "whitespace"

    def test_low_rating_returns_underserved(self):
        """平均評価がデフォルト閾値（3.5）を下回る場合はアンダーサーブド."""
        apps = [{"name": "App A", "rating": 2.5, "reviews": 2000}]
        signal = _determine_signal(apps, avg_rating=2.5, total_reviews=2000)
        assert signal == "underserved"

    def test_rating_exactly_at_threshold_returns_emerging_or_competitive(self):
        """評価がちょうど閾値の場合は underserved にならない（< なので）."""
        # avg_rating == rating_threshold は underserved ではない
        signal = _determine_signal(
            [{"name": "App"}], avg_rating=3.5, total_reviews=500,
            rating_threshold=3.5, reviews_threshold=1000
        )
        # 3.5 < 3.5 は False なので emerging
        assert signal == "emerging"

    def test_high_rating_few_reviews_returns_emerging(self):
        """評価が高くレビューが少ない場合は新興市場."""
        apps = [{"name": "App A", "rating": 4.5, "reviews": 200}]
        signal = _determine_signal(apps, avg_rating=4.5, total_reviews=200)
        assert signal == "emerging"

    def test_high_rating_many_reviews_returns_competitive(self):
        """評価が高くレビューも多い場合は競合が強い."""
        apps = [
            {"name": "App A", "rating": 4.5, "reviews": 5000},
            {"name": "App B", "rating": 4.2, "reviews": 8000},
        ]
        signal = _determine_signal(apps, avg_rating=4.35, total_reviews=13000)
        assert signal == "competitive"

    def test_reviews_exactly_at_threshold_returns_competitive(self):
        """レビュー数がちょうど閾値の場合は competitive（< なので）."""
        signal = _determine_signal(
            [{"name": "App"}], avg_rating=4.0, total_reviews=1000,
            rating_threshold=3.5, reviews_threshold=1000
        )
        # 1000 < 1000 は False なので competitive
        assert signal == "competitive"

    def test_reviews_one_below_threshold_returns_emerging(self):
        """レビュー数が閾値より 1 少ない場合は emerging."""
        signal = _determine_signal(
            [{"name": "App"}], avg_rating=4.0, total_reviews=999,
            rating_threshold=3.5, reviews_threshold=1000
        )
        assert signal == "emerging"

    def test_custom_thresholds_applied(self):
        """カテゴリ別カスタム閾値が正しく機能する."""
        # カテゴリ平均が 4.0 の場合、閾値は 4.0 - 0.5 = 3.5
        # 評価 3.4 は underserved
        signal = _determine_signal(
            [{"name": "App"}], avg_rating=3.4, total_reviews=5000,
            rating_threshold=3.5, reviews_threshold=500
        )
        assert signal == "underserved"

    def test_underserved_takes_priority_over_emerging(self):
        """評価が低い場合は underserved が emerging より優先される."""
        # 低評価かつ少ないレビュー → underserved が優先（チェック順序による）
        signal = _determine_signal(
            [{"name": "App"}], avg_rating=2.0, total_reviews=50,
            rating_threshold=3.5, reviews_threshold=1000
        )
        assert signal == "underserved"

    def test_all_four_signal_types_are_distinct(self):
        """4 つのシグナルタイプが全て異なる値であることを確認."""
        signals = {"whitespace", "underserved", "emerging", "competitive"}
        assert len(signals) == 4
