"""run_health.py のユニットテスト."""

import json
import os

import pytest

from src.run_health import check_daily_run


@pytest.fixture
def health_path(tmp_path):
    return os.path.join(tmp_path, "source_health.json")


def _write_health(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestEmptySources:
    def test_flags_when_3_or_more_sources_empty(self, health_path):
        sources = {"reddit": [], "hatena": [], "zenn": [], "hn": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=1, source_health_path=health_path)
        assert any("収集 0 件のソースが 3 件" in p for p in problems)
        assert any("hatena" in p and "reddit" in p and "zenn" in p for p in problems)

    def test_not_flagged_when_fewer_than_3_empty(self, health_path):
        sources = {"reddit": [], "hatena": [], "zenn": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=1, source_health_path=health_path)
        assert not any("収集 0 件" in p for p in problems)


class TestZeroPainsExtracted:
    def test_flags_when_posts_exist_but_no_pains(self, health_path):
        sources = {"reddit": [{"title": "x"}], "hatena": [{"title": "y"}]}
        problems = check_daily_run(sources, pains_count=0, source_health_path=health_path)
        assert any("抽出されたペインが 0 件" in p for p in problems)

    def test_not_flagged_when_no_posts_and_no_pains(self, health_path):
        sources = {"reddit": [], "hatena": []}
        problems = check_daily_run(sources, pains_count=0, source_health_path=health_path)
        assert not any("抽出されたペインが 0 件" in p for p in problems)

    def test_not_flagged_when_pains_extracted(self, health_path):
        sources = {"reddit": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=5, source_health_path=health_path)
        assert not any("抽出されたペインが 0 件" in p for p in problems)


class TestConsecutiveFailures:
    def test_flags_sources_with_3_or_more_consecutive_failures(self, health_path):
        _write_health(
            health_path,
            {
                "note": {"last_success": None, "consecutive_failures": 3},
                "devto": {"last_success": None, "consecutive_failures": 5},
                "reddit": {"last_success": "2026-07-01", "consecutive_failures": 0},
            },
        )
        sources = {"reddit": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=1, source_health_path=health_path)
        assert any("連続失敗" in p for p in problems)
        matching = [p for p in problems if "連続失敗" in p]
        assert "note (3 回)" in matching[0]
        assert "devto (5 回)" in matching[0]
        assert "reddit" not in matching[0]

    def test_not_flagged_when_below_threshold(self, health_path):
        _write_health(
            health_path,
            {"note": {"last_success": "2026-07-01", "consecutive_failures": 2}},
        )
        sources = {"reddit": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=1, source_health_path=health_path)
        assert not any("連続失敗" in p for p in problems)


class TestNormalRun:
    def test_no_problems_on_healthy_run(self, health_path):
        _write_health(health_path, {"reddit": {"last_success": "2026-07-01", "consecutive_failures": 0}})
        sources = {
            "reddit": [{"title": "x"}],
            "hatena": [{"title": "y"}],
            "zenn": [{"title": "z"}],
        }
        problems = check_daily_run(sources, pains_count=3, source_health_path=health_path)
        assert problems == []


class TestMissingSourceHealthFile:
    def test_safe_when_file_missing(self, tmp_path):
        missing_path = os.path.join(tmp_path, "does_not_exist.json")
        sources = {"reddit": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=1, source_health_path=missing_path)
        assert problems == []

    def test_safe_when_file_corrupted(self, tmp_path):
        bad_path = os.path.join(tmp_path, "corrupted.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        sources = {"reddit": [{"title": "x"}]}
        problems = check_daily_run(sources, pains_count=1, source_health_path=bad_path)
        assert problems == []
