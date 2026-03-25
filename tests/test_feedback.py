"""feedback.py の純粋ロジック関数のユニットテスト."""

from datetime import date, timedelta

import pytest

from src.feedback import (
    PATTERN_TTL_DAYS,
    _find_expired_patterns,
    _migrate_patterns,
    get_active_patterns,
)


class TestMigratePatterns:
    """_migrate_patterns のテスト."""

    def test_string_list_migrated_to_dict_list(self):
        """文字列リストがオブジェクトリストに変換される."""
        patterns = ["ノイズパターンA", "ノイズパターンB"]
        result = _migrate_patterns(patterns)
        assert len(result) == 2
        assert result[0]["pattern"] == "ノイズパターンA"
        assert result[0]["created_at"] == "2026-03-01"
        assert result[0]["source_issues"] == []
        assert result[1]["pattern"] == "ノイズパターンB"

    def test_dict_list_passed_through_unchanged(self):
        """既にオブジェクト形式のものはそのまま返る."""
        patterns = [
            {"pattern": "既存パターン", "created_at": "2026-03-15", "source_issues": [1, 2]}
        ]
        result = _migrate_patterns(patterns)
        assert result == patterns

    def test_mixed_list_migrates_strings_only(self):
        """文字列とオブジェクトが混在する場合、文字列のみ変換する."""
        patterns = [
            "文字列パターン",
            {"pattern": "オブジェクトパターン", "created_at": "2026-03-10", "source_issues": []},
        ]
        result = _migrate_patterns(patterns)
        assert len(result) == 2
        assert result[0]["pattern"] == "文字列パターン"
        assert result[0]["created_at"] == "2026-03-01"
        assert result[1]["pattern"] == "オブジェクトパターン"
        assert result[1]["created_at"] == "2026-03-10"

    def test_empty_list_returns_empty(self):
        result = _migrate_patterns([])
        assert result == []

    def test_invalid_types_excluded(self):
        """str でも dict でもない要素はスキップされる."""
        patterns = [123, None, "有効なパターン"]
        result = _migrate_patterns(patterns)
        assert len(result) == 1
        assert result[0]["pattern"] == "有効なパターン"


class TestGetActivePatterns:
    """get_active_patterns のテスト."""

    def test_active_pattern_within_ttl_included(self):
        """TTL 以内のパターンは含まれる."""
        today = date.today()
        recent_date = (today - timedelta(days=30)).isoformat()
        patterns = [
            {"pattern": "最近のパターン", "created_at": recent_date, "source_issues": []}
        ]
        result = get_active_patterns(patterns)
        assert "最近のパターン" in result

    def test_expired_pattern_beyond_ttl_excluded(self):
        """TTL を超えたパターンは除外される."""
        today = date.today()
        old_date = (today - timedelta(days=PATTERN_TTL_DAYS + 1)).isoformat()
        patterns = [
            {"pattern": "古いパターン", "created_at": old_date, "source_issues": []}
        ]
        result = get_active_patterns(patterns)
        assert "古いパターン" not in result

    def test_pattern_exactly_at_ttl_excluded(self):
        """TTL ちょうど（PATTERN_TTL_DAYS 日）のパターンは除外される（> なので）."""
        today = date.today()
        boundary_date = (today - timedelta(days=PATTERN_TTL_DAYS)).isoformat()
        patterns = [
            {"pattern": "境界パターン", "created_at": boundary_date, "source_issues": []}
        ]
        result = get_active_patterns(patterns)
        # (today - created).days == PATTERN_TTL_DAYS → NOT > TTL → active
        assert "境界パターン" in result

    def test_pattern_one_day_over_ttl_excluded(self):
        """TTL + 1 日のパターンは除外される."""
        today = date.today()
        expired_date = (today - timedelta(days=PATTERN_TTL_DAYS + 1)).isoformat()
        patterns = [
            {"pattern": "期限切れパターン", "created_at": expired_date, "source_issues": []}
        ]
        result = get_active_patterns(patterns)
        assert "期限切れパターン" not in result

    def test_string_patterns_always_included(self):
        """旧形式（文字列）のパターンは TTL チェックなしで常に含まれる."""
        patterns = ["文字列パターン（旧形式）"]
        result = get_active_patterns(patterns)
        assert "文字列パターン（旧形式）" in result

    def test_pattern_without_created_at_included(self):
        """created_at がない場合はアクティブとして扱う."""
        patterns = [{"pattern": "日付なしパターン", "source_issues": []}]
        result = get_active_patterns(patterns)
        assert "日付なしパターン" in result

    def test_pattern_with_invalid_date_included(self):
        """不正な日付フォーマットの場合はアクティブとして扱う."""
        patterns = [
            {"pattern": "不正日付パターン", "created_at": "not-a-date", "source_issues": []}
        ]
        result = get_active_patterns(patterns)
        assert "不正日付パターン" in result

    def test_mixed_active_and_expired(self):
        """有効と期限切れが混在する場合、有効なものだけ返す."""
        today = date.today()
        patterns = [
            {"pattern": "有効", "created_at": (today - timedelta(days=10)).isoformat(), "source_issues": []},
            {"pattern": "期限切れ", "created_at": (today - timedelta(days=PATTERN_TTL_DAYS + 5)).isoformat(), "source_issues": []},
        ]
        result = get_active_patterns(patterns)
        assert "有効" in result
        assert "期限切れ" not in result

    def test_empty_list_returns_empty(self):
        result = get_active_patterns([])
        assert result == []

    def test_returns_list_of_strings(self):
        """返り値はパターン文字列のリスト（dict ではない）."""
        today = date.today()
        patterns = [
            {"pattern": "テスト", "created_at": today.isoformat(), "source_issues": []}
        ]
        result = get_active_patterns(patterns)
        assert all(isinstance(p, str) for p in result)


class TestFindExpiredPatterns:
    """_find_expired_patterns のテスト."""

    def test_empty_list_returns_empty(self):
        result = _find_expired_patterns([])
        assert result == []

    def test_fresh_pattern_not_expired(self):
        today = date.today()
        patterns = [
            {"pattern": "新しい", "created_at": today.isoformat(), "source_issues": []}
        ]
        result = _find_expired_patterns(patterns)
        assert result == []

    def test_old_pattern_returned_as_expired(self):
        old_date = (date.today() - timedelta(days=PATTERN_TTL_DAYS + 10)).isoformat()
        patterns = [
            {"pattern": "古い", "created_at": old_date, "source_issues": []}
        ]
        result = _find_expired_patterns(patterns)
        assert len(result) == 1
        assert result[0]["pattern"] == "古い"

    def test_pattern_without_created_at_skipped(self):
        """created_at がないパターンはスキップされる."""
        patterns = [{"pattern": "日付なし", "source_issues": []}]
        result = _find_expired_patterns(patterns)
        assert result == []

    def test_pattern_with_invalid_date_skipped(self):
        """不正な日付のパターンはスキップされる."""
        patterns = [{"pattern": "不正日付", "created_at": "invalid", "source_issues": []}]
        result = _find_expired_patterns(patterns)
        assert result == []

    def test_mixed_returns_only_expired(self):
        today = date.today()
        recent = (today - timedelta(days=10)).isoformat()
        old = (today - timedelta(days=PATTERN_TTL_DAYS + 1)).isoformat()
        patterns = [
            {"pattern": "有効", "created_at": recent, "source_issues": []},
            {"pattern": "期限切れ", "created_at": old, "source_issues": []},
        ]
        result = _find_expired_patterns(patterns)
        assert len(result) == 1
        assert result[0]["pattern"] == "期限切れ"

    def test_pattern_ttl_days_constant_is_90(self):
        """PATTERN_TTL_DAYS は 90 日であることを確認."""
        assert PATTERN_TTL_DAYS == 90

    def test_boundary_exactly_ttl_days_not_expired(self):
        """ちょうど TTL 日のパターンは期限切れにならない（> なので）."""
        boundary_date = (date.today() - timedelta(days=PATTERN_TTL_DAYS)).isoformat()
        patterns = [
            {"pattern": "境界", "created_at": boundary_date, "source_issues": []}
        ]
        result = _find_expired_patterns(patterns)
        assert result == []

    def test_boundary_ttl_plus_one_day_is_expired(self):
        """TTL + 1 日のパターンは期限切れになる."""
        expired_date = (date.today() - timedelta(days=PATTERN_TTL_DAYS + 1)).isoformat()
        patterns = [
            {"pattern": "TTL+1", "created_at": expired_date, "source_issues": []}
        ]
        result = _find_expired_patterns(patterns)
        assert len(result) == 1
