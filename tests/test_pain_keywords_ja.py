"""pain_keywords_ja.py のユニットテスト."""

import pytest

from src.pain_keywords_ja import contains_monetization_signal, contains_pain_keyword


class TestContainsPainKeyword:
    """contains_pain_keyword のテスト."""

    def test_matches_common_pain_words(self):
        assert contains_pain_keyword("これ本当に不便だわ")
        assert contains_pain_keyword("ストレスがたまる")
        assert contains_pain_keyword("使いにくいアプリ")

    def test_no_match_for_neutral_text(self):
        assert not contains_pain_keyword("今日は天気がいい")
        assert not contains_pain_keyword("新しいカフェに行った")


class TestContainsMonetizationSignal:
    """contains_monetization_signal のテスト."""

    def test_explicit_willingness_to_pay(self):
        assert contains_monetization_signal("お金を払ってでも解決したい")
        assert contains_monetization_signal("有料でもいいから使いたい")
        assert contains_monetization_signal("課金したいくらい便利")

    def test_subscription_intent(self):
        assert contains_monetization_signal("月額500円くらいなら払うのに")
        assert contains_monetization_signal("サブスクでも欲しいサービス")
        assert contains_monetization_signal("買い切りで欲しい")

    def test_strong_purchase_intent(self):
        assert contains_monetization_signal("高くても使いたい")
        assert contains_monetization_signal("いくらでも出すから作ってほしい")
        assert contains_monetization_signal("金出してでも欲しい")

    def test_english_signals(self):
        assert contains_monetization_signal("I would pay for this feature")
        assert contains_monetization_signal("shut up and take my money")
        assert contains_monetization_signal("I'd gladly pay for a solution")

    def test_no_match_for_plain_text(self):
        assert not contains_monetization_signal("このアプリは不便だ")
        assert not contains_monetization_signal("もっと使いやすくしてほしい")
        assert not contains_monetization_signal("無料で使えるアプリを探してる")

    def test_no_match_for_empty(self):
        assert not contains_monetization_signal("")
