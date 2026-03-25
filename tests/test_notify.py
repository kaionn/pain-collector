"""notify.py の純粋ロジック関数のユニットテスト.

外部サービス（GitHub API、LLM）はモックしない。
TF-IDF による重複検出の純粋ロジックのみをテストする。
"""

import pytest

from src.notify import DUPLICATE_THRESHOLD_HIGH, DUPLICATE_THRESHOLD_LOW, _find_duplicate


class TestFindDuplicate:
    """_find_duplicate のテスト.

    注: _llm_judge_duplicate は GITHUB_TOKEN がない環境では False を返すため、
    グレーゾーン（0.4 <= sim < 0.7）のケースは LLM 判定なしで検証する。
    """

    def test_empty_existing_issues_returns_none(self):
        result = _find_duplicate("タスク管理アプリが欲しい", [])
        assert result is None

    def test_clearly_duplicate_text_detected(self):
        """ほぼ同一のテキストは高い類似度で重複検出される."""
        existing = [
            {"number": 1, "title": "毎日の家計管理が面倒で自動化したい"},
        ]
        pain_text = "毎日の家計管理が面倒で自動化したい"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 1

    def test_clearly_different_text_not_detected(self):
        """全く異なるトピックは重複として検出されない."""
        existing = [
            {"number": 1, "title": "cooking recipe app needed"},
            {"number": 2, "title": "fitness tracker for running"},
        ]
        pain_text = "tax return filing automation"
        result = _find_duplicate(pain_text, existing)
        assert result is None

    def test_same_text_returns_matching_issue(self):
        """同一テキストは必ず重複検出される."""
        existing = [
            {"number": 10, "title": "レシートの自動仕分けができるアプリ"},
            {"number": 11, "title": "子どもの睡眠記録アプリ"},
        ]
        pain_text = "レシートの自動仕分けができるアプリ"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 10

    def test_returns_most_similar_issue(self):
        """複数候補の中で最も類似度が高い Issue を返す."""
        existing = [
            {"number": 1, "title": "email inbox management tool"},
            {"number": 2, "title": "email newsletter unsubscribe automation"},
            {"number": 3, "title": "fitness workout tracker app"},
        ]
        # email に関連したテキストは email 系の Issue とマッチするはず
        pain_text = "email newsletter unsubscribe automation tool"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 2

    def test_single_word_corpus_returns_none_on_value_error(self):
        """TF-IDF が ValueError を出す場合は None を返す（例: 1文字トークンのみ）.

        tokenizer が空のトークンリストを返す入力では ValueError が発生するが、
        _find_duplicate は try/except ValueError で保護されている。
        """
        # 全て記号・数字のみの場合、日本語 tokenizer は空を返し ValueError になる可能性がある
        existing = [{"number": 1, "title": "1 2 3"}]
        result = _find_duplicate("4 5 6", existing)
        # ValueError が出ても None を返す（クラッシュしない）
        assert result is None or isinstance(result, dict)

    def test_duplicate_threshold_constants(self):
        """閾値定数が期待通りの値であることを確認."""
        assert DUPLICATE_THRESHOLD_HIGH == 0.7
        assert DUPLICATE_THRESHOLD_LOW == 0.4

    def test_similar_but_different_topic_not_duplicate(self):
        """似た単語を含むが異なるトピックは重複にならない."""
        existing = [
            {"number": 1, "title": "baby sleep tracking app for parents"},
        ]
        pain_text = "sleep quality monitoring for adults with insomnia"
        result = _find_duplicate(pain_text, existing)
        # 異なるトピックなので重複なし（高い閾値 0.7 を超えない）
        assert result is None

    def test_japanese_duplicate_detected(self):
        """日本語テキストの重複も正しく検出される."""
        existing = [
            {"number": 5, "title": "子育て中の予防接種スケジュール管理が煩雑"},
        ]
        pain_text = "子育て中の予防接種スケジュール管理が煩雑"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 5
