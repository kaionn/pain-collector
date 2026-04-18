"""pick_idea.py のユニットテスト."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from src.pick_idea import (
    _find_related_files,
    _generate_report,
    _load_past_picks,
    _parse_llm_picks,
    _update_pipeline_state,
    _load_pipeline_state,
    _save_pipeline_state,
    _ensure_spec_exists,
    BASE_DIR,
    PIPELINE_STATE_PATH,
)


@pytest.fixture()
def tmp_dirs(tmp_path, monkeypatch):
    """テスト用の一時ディレクトリ構成を準備する."""
    monkeypatch.setattr("src.pick_idea.BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "src.pick_idea.PIPELINE_STATE_PATH",
        str(tmp_path / "data" / "pipeline_state.json"),
    )

    # ディレクトリ作成
    (tmp_path / "data").mkdir()
    (tmp_path / "picks").mkdir()
    (tmp_path / "deep_dive").mkdir()
    (tmp_path / "specs").mkdir()

    return tmp_path


class TestLoadPastPicks:
    """_load_past_picks のテスト."""

    def test_returns_empty_when_no_state_and_no_picks(self, tmp_dirs):
        assert _load_past_picks() == set()

    def test_reads_from_pipeline_state(self, tmp_dirs):
        state = {
            "picked": [
                {"issue_number": 10, "status": "awaiting_approval"},
                {"issue_number": 20, "status": "building"},
            ]
        }
        state_path = tmp_dirs / "data" / "pipeline_state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        assert _load_past_picks() == {10, 20}

    def test_falls_back_to_picks_dir(self, tmp_dirs):
        pick_file = tmp_dirs / "picks" / "2026-03-25.md"
        pick_file.write_text(
            "# MVP 候補選定\n\n## 🥇 #42 テスト\n## 🥈 #58 テスト2\n",
            encoding="utf-8",
        )

        assert _load_past_picks() == {42, 58}

    def test_pipeline_state_takes_priority(self, tmp_dirs):
        """pipeline_state.json が存在する場合は picks/ を読まない."""
        state = {"picked": [{"issue_number": 99, "status": "awaiting_approval"}]}
        state_path = tmp_dirs / "data" / "pipeline_state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        pick_file = tmp_dirs / "picks" / "2026-03-25.md"
        pick_file.write_text("## 🥇 #42 テスト\n", encoding="utf-8")

        # pipeline_state.json の値のみ返す
        assert _load_past_picks() == {99}


class TestFindRelatedFiles:
    """_find_related_files のテスト."""

    def test_no_deep_dive_returns_idea(self, tmp_dirs):
        result = _find_related_files(1, "テストペイン")
        assert result == {"deep_dive": None, "spec": None, "status": "idea"}

    def test_matches_deep_dive_by_tfidf(self, tmp_dirs):
        dd_path = tmp_dirs / "deep_dive" / "2026-03-25-リモートワーク集中力.md"
        dd_path.write_text("# Deep Dive: リモートワーク中の集中力低下\n\n内容...", encoding="utf-8")

        # 完全に同じタイトルで検索して確実にマッチさせる
        result = _find_related_files(1, "リモートワーク中の集中力低下")
        assert result["deep_dive"] is not None
        assert result["status"] == "analyzed"

    def test_matches_deep_dive_with_spec(self, tmp_dirs):
        dd_path = tmp_dirs / "deep_dive" / "2026-03-25-リモートワーク集中力.md"
        dd_path.write_text("# Deep Dive: リモートワーク集中力\n\n内容...", encoding="utf-8")

        spec_path = tmp_dirs / "specs" / "2026-03-25-リモートワーク集中力-spec.md"
        spec_path.write_text("# Technical Spec: リモートワーク集中力\n", encoding="utf-8")

        result = _find_related_files(1, "リモートワーク集中力")
        assert result["spec"] is not None
        assert result["status"] == "spec-ready"

    def test_reads_from_pipeline_state(self, tmp_dirs):
        state = {
            "picked": [{
                "issue_number": 42,
                "deep_dive": "deep_dive/test.md",
                "spec": "specs/test-spec.md",
                "status": "awaiting_approval",
            }]
        }
        state_path = tmp_dirs / "data" / "pipeline_state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        result = _find_related_files(42, "テスト")
        assert result["deep_dive"] == "deep_dive/test.md"
        assert result["spec"] == "specs/test-spec.md"
        assert result["status"] == "spec-ready"


class TestParseLlmPicks:
    """_parse_llm_picks のテスト."""

    def test_parses_valid_json(self):
        content = """```json
[
  {"number": 10, "reason": "良いアイデア", "mvp_scope": ["機能A"], "dev_period": "2週間", "acquisition": "SNS"}
]
```"""
        candidates = [{"number": 10}, {"number": 20}]
        result = _parse_llm_picks(content, candidates)
        assert len(result) == 1
        assert result[0]["number"] == 10
        assert result[0]["reason"] == "良いアイデア"

    def test_parses_json_without_codeblock(self):
        content = '[{"number": 5, "reason": "テスト", "mvp_scope": [], "dev_period": "1週間", "acquisition": "口コミ"}]'
        result = _parse_llm_picks(content, [{"number": 5}])
        assert result[0]["number"] == 5

    def test_falls_back_on_invalid_json(self):
        content = "これは JSON ではないテキストです"
        candidates = [
            {"number": 1},
            {"number": 2},
            {"number": 3},
            {"number": 4},
        ]
        result = _parse_llm_picks(content, candidates)
        assert len(result) == 3
        assert result[0]["number"] == 1
        assert result[0]["reason"] == "スコア上位のため自動選定"


class TestGenerateReport:
    """_generate_report のテスト."""

    def test_generates_report_with_all_fields(self):
        picked = [
            {
                "number": 42,
                "title": "リモート集中力ツール",
                "score_label": "🏆score-S",
                "reason": "市場が空いている",
                "mvp_scope": ["タイマー", "統計"],
                "dev_period": "2週間",
                "acquisition": "Twitter",
                "deep_dive": "deep_dive/2026-03-25-test.md",
                "spec": "specs/2026-03-25-test-spec.md",
                "status": "spec-ready",
            },
        ]
        report = _generate_report(picked, 10, "2026-03-25")

        assert "# MVP 候補選定: 2026-03-25" in report
        assert "候補数: 10 件 → 選定: 1 件" in report
        assert "🥇 #42 リモート集中力ツール" in report
        assert "✅ 2026-03-25-test.md" in report
        assert "✅ 2026-03-25-test-spec.md" in report
        assert "spec-ready" in report
        assert "/approve" in report

    def test_shows_missing_markers(self):
        picked = [
            {
                "number": 10,
                "title": "テスト",
                "score_label": "🥇score-A",
                "reason": "テスト理由",
                "mvp_scope": [],
                "dev_period": "1週間",
                "acquisition": "口コミ",
                "deep_dive": None,
                "spec": None,
                "status": "idea",
            },
        ]
        report = _generate_report(picked, 5, "2026-03-25")
        assert "❌ 未生成" in report
        assert "idea" in report


class TestUpdatePipelineState:
    """_update_pipeline_state のテスト."""

    def test_creates_state_file(self, tmp_dirs):
        picked = [
            {"number": 42, "deep_dive": "dd.md", "spec": "spec.md"},
        ]
        _update_pipeline_state(picked, "2026-03-25")

        state_path = tmp_dirs / "data" / "pipeline_state.json"
        assert state_path.exists()

        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert len(state["picked"]) == 1
        assert state["picked"][0]["issue_number"] == 42
        assert state["picked"][0]["status"] == "awaiting_approval"

    def test_appends_to_existing_state(self, tmp_dirs):
        existing = {
            "picked": [{"issue_number": 10, "status": "building", "picked_at": "2026-03-20T00:00:00+09:00", "spec": None, "deep_dive": None}]
        }
        state_path = tmp_dirs / "data" / "pipeline_state.json"
        state_path.write_text(json.dumps(existing), encoding="utf-8")

        picked = [{"number": 42, "deep_dive": None, "spec": None}]
        _update_pipeline_state(picked, "2026-03-25")

        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert len(state["picked"]) == 2
        assert state["picked"][0]["issue_number"] == 10
        assert state["picked"][1]["issue_number"] == 42


class TestEnsureSpecExists:
    """_ensure_spec_exists のテスト."""

    def test_returns_existing_spec(self):
        issue = {"number": 1, "spec": "specs/existing.md", "deep_dive": "dd.md"}
        assert _ensure_spec_exists(issue) == "specs/existing.md"

    @patch("src.generate_spec.generate_spec_from_deep_dive", return_value="specs/new-spec.md")
    def test_generates_spec_from_deep_dive(self, mock_gen):
        issue = {
            "number": 1,
            "title": "テストタイトル",
            "spec": None,
            "deep_dive": "deep_dive/test.md",
        }

        result = _ensure_spec_exists(issue)
        assert result == "specs/new-spec.md"
        mock_gen.assert_called_once_with(
            "deep_dive/test.md",
            issue_number=1,
            title="テストタイトル",
        )

    def test_skips_when_no_deep_dive(self):
        issue = {"number": 1, "spec": None, "deep_dive": None}
        assert _ensure_spec_exists(issue) is None
