"""scoring.py の純粋ロジック関数のユニットテスト."""

import json

import pytest

from src import scoring
from src.notify import _build_pain_data_comment
from src.scoring import SCORING_PROMPT, WEIGHTS, calculate_total_score, normalize_engagement


class TestScoringPrompt:
    """SCORING_PROMPT の判別力改善マーカーを検証する（プロンプト退行防止）."""

    def test_contains_scoring_examples_section(self):
        assert "採点例" in SCORING_PROMPT

    def test_contains_full_range_instruction(self):
        assert "1〜5 の全域" in SCORING_PROMPT

    def test_contains_high_score_example(self):
        assert "高評価例" in SCORING_PROMPT

    def test_contains_low_score_example(self):
        assert "低評価例" in SCORING_PROMPT

    def test_contains_self_bias_warning(self):
        assert "自己バイアス" in SCORING_PROMPT

    def test_contains_conservative_evaluation_instruction(self):
        assert "保守的評価" in SCORING_PROMPT

    def test_contains_technical_simplicity_anchor(self):
        assert "単機能CRUD" in SCORING_PROMPT

    def test_contains_scope_anchor(self):
        assert "スコープ不定" in SCORING_PROMPT

    def test_example_json_blocks_are_valid_and_have_required_keys(self):
        """採点例に埋め込んだ JSON がパース可能で必須キーを持つことを確認する（スキーマ退行防止）."""
        import re

        required_keys = set(WEIGHTS) - {"community_validation"}
        json_blocks = re.findall(
            r"\{[^{}]*\"technical_simplicity\": \d,[^{}]*\}", SCORING_PROMPT
        )
        assert len(json_blocks) >= 2
        for block in json_blocks:
            parsed = json.loads(block)
            assert required_keys <= set(parsed)


class TestNormalizeEngagement:
    """normalize_engagement のテスト."""

    def test_empty_dict_returns_3(self):
        assert normalize_engagement({}) == 3

    def test_score_zero_returns_1(self):
        assert normalize_engagement({"score": 0}) == 1

    def test_score_one_returns_2(self):
        assert normalize_engagement({"score": 1}) == 2

    def test_score_9_returns_2(self):
        assert normalize_engagement({"score": 9}) == 2

    def test_score_10_returns_3(self):
        assert normalize_engagement({"score": 10}) == 3

    def test_score_49_returns_3(self):
        assert normalize_engagement({"score": 49}) == 3

    def test_score_50_returns_4(self):
        assert normalize_engagement({"score": 50}) == 4

    def test_score_100_returns_4(self):
        assert normalize_engagement({"score": 100}) == 4

    def test_score_499_returns_4(self):
        assert normalize_engagement({"score": 499}) == 4

    def test_score_500_returns_5(self):
        assert normalize_engagement({"score": 500}) == 5

    def test_score_1000_returns_5(self):
        assert normalize_engagement({"score": 1000}) == 5

    def test_uses_max_value_across_multiple_fields(self):
        """複数フィールドがある場合、最大値で判定する."""
        engagement = {"score": 2, "num_comments": 100}
        assert normalize_engagement(engagement) == 4  # max=100 → 4

    def test_ignores_negative_values(self):
        """負の値は無視される（values >= 0 のみ使用）."""
        engagement = {"score": -1}
        # 全て無効な値 → no valid values → return 3
        assert normalize_engagement(engagement) == 3

    def test_only_negative_values_returns_3(self):
        engagement = {"score": -100, "num_comments": -5}
        assert normalize_engagement(engagement) == 3

    def test_float_values_handled(self):
        """float 値も正しく処理される."""
        assert normalize_engagement({"score": 50.5}) == 4

    def test_all_zeros_returns_1(self):
        assert normalize_engagement({"score": 0, "num_comments": 0}) == 1


class TestCalculateTotalScore:
    """calculate_total_score のテスト."""

    def test_all_zeros_returns_zero(self):
        scores = {k: 0 for k in WEIGHTS}
        assert calculate_total_score(scores) == 0

    def test_all_fives_returns_60(self):
        """全項目 5 点の場合は 60 点満点."""
        # WEIGHTS の合計: 2+2+2+2+1+3 = 12, 12 * 5 = 60
        scores = {k: 5 for k in WEIGHTS}
        assert calculate_total_score(scores) == 60

    def test_weights_applied_correctly(self):
        """加重が正しく適用されることを確認."""
        scores = {
            "technical_simplicity": 1,
            "scope": 0,
            "differentiation": 0,
            "community_validation": 0,
            "pain_intensity": 0,
            "revenue_potential": 0,
        }
        assert calculate_total_score(scores) == 2  # technical_simplicity weight=2

    def test_scope_weight(self):
        scores = {k: 0 for k in WEIGHTS}
        scores["scope"] = 1
        assert calculate_total_score(scores) == 2  # scope weight=2

    def test_differentiation_weight(self):
        scores = {k: 0 for k in WEIGHTS}
        scores["differentiation"] = 1
        assert calculate_total_score(scores) == 2  # differentiation weight=2

    def test_community_validation_weight(self):
        scores = {k: 0 for k in WEIGHTS}
        scores["community_validation"] = 1
        assert calculate_total_score(scores) == 2  # community_validation weight=2

    def test_pain_intensity_weight(self):
        scores = {k: 0 for k in WEIGHTS}
        scores["pain_intensity"] = 1
        assert calculate_total_score(scores) == 1  # pain_intensity weight=1

    def test_revenue_potential_weight(self):
        scores = {k: 0 for k in WEIGHTS}
        scores["revenue_potential"] = 1
        assert calculate_total_score(scores) == 3  # revenue_potential weight=3

    def test_revenue_focused_pain_scores_higher(self):
        """収益性が高いペインが技術的シンプルさが高いペインより上位になることを確認."""
        revenue_focused = {
            "technical_simplicity": 3,
            "scope": 3,
            "differentiation": 3,
            "community_validation": 3,
            "pain_intensity": 3,
            "revenue_potential": 5,
        }
        tech_focused = {
            "technical_simplicity": 5,
            "scope": 3,
            "differentiation": 3,
            "community_validation": 3,
            "pain_intensity": 3,
            "revenue_potential": 3,
        }
        assert calculate_total_score(revenue_focused) > calculate_total_score(tech_focused)

    def test_missing_key_treated_as_zero(self):
        """存在しないキーは 0 として扱われる."""
        assert calculate_total_score({}) == 0

    def test_partial_scores(self):
        scores = {"technical_simplicity": 3, "scope": 2}
        # 3*2 + 2*2 = 6 + 4 = 10
        assert calculate_total_score(scores) == 10

    def test_boundary_score_24(self):
        """スコア 24 のケース（B ランク境界）."""
        scores = {
            "technical_simplicity": 2,
            "scope": 2,
            "differentiation": 2,
            "community_validation": 2,
            "pain_intensity": 2,
            "revenue_potential": 2,
        }
        # 2*3 + 2*3 + 2*2 + 2*2 + 2*1 + 2*1 = 6+6+4+4+2+2 = 24
        assert calculate_total_score(scores) == 24

    def test_boundary_score_36(self):
        """スコア 36 のケース（A ランク境界）."""
        scores = {
            "technical_simplicity": 3,
            "scope": 3,
            "differentiation": 3,
            "community_validation": 3,
            "pain_intensity": 3,
            "revenue_potential": 3,
        }
        # 3*3 + 3*3 + 3*2 + 3*2 + 3*1 + 3*1 = 9+9+6+6+3+3 = 36
        assert calculate_total_score(scores) == 36

    def test_boundary_score_48(self):
        """スコア 48 のケース（S ランク境界）."""
        scores = {
            "technical_simplicity": 4,
            "scope": 4,
            "differentiation": 4,
            "community_validation": 4,
            "pain_intensity": 4,
            "revenue_potential": 4,
        }
        # 4*3 + 4*3 + 4*2 + 4*2 + 4*1 + 4*1 = 12+12+8+8+4+4 = 48
        assert calculate_total_score(scores) == 48


class TestScoreLabels:
    """スコアラベル境界値のテスト.

    score_and_update_issue の分岐:
    - total < 24  → score-C
    - total >= 24 → score-B
    - total >= 36 → score-A
    - total >= 48 → score-S
    """

    def _get_label(self, total: int) -> str:
        """scoring.py の label 判定ロジックを再現する."""
        if total >= 48:
            return "score-S"
        elif total >= 36:
            return "score-A"
        elif total >= 24:
            return "score-B"
        else:
            return "score-C"

    def test_score_0_is_C(self):
        assert self._get_label(0) == "score-C"

    def test_score_23_is_C(self):
        assert self._get_label(23) == "score-C"

    def test_score_24_is_B(self):
        assert self._get_label(24) == "score-B"

    def test_score_35_is_B(self):
        assert self._get_label(35) == "score-B"

    def test_score_36_is_A(self):
        assert self._get_label(36) == "score-A"

    def test_score_47_is_A(self):
        assert self._get_label(47) == "score-A"

    def test_score_48_is_S(self):
        assert self._get_label(48) == "score-S"

    def test_score_60_is_S(self):
        assert self._get_label(60) == "score-S"


class TestScoreOpenIssues:
    """score_open_issues() の Issue メタデータ SSOT テスト（Renovate/Sentry fingerprinting 方式）."""

    def _fake_gh_result(self, issues):
        class FakeResult:
            returncode = 0
            stdout = json.dumps(issues)
            stderr = ""

        return FakeResult()

    def test_uses_embedded_pain_data_when_present(self, monkeypatch):
        """pain-data メタデータがある Issue は元の severity / WTP でスコアされる."""
        original_pain = {
            "pain": "元のペインテキスト",
            "app_idea": "元のアイデア",
            "existing_solutions": "既存ツールA",
            "severity": 5,
            "willingness_to_pay": "high",
            "category": "健康",
        }
        body = f"## ペイン\n{original_pain['pain']}\n{_build_pain_data_comment(original_pain)}"
        issues = [
            {"number": 1, "title": "元のペインテキスト", "body": body, "labels": []},
        ]

        monkeypatch.setattr(
            scoring.subprocess, "run", lambda *a, **kw: self._fake_gh_result(issues)
        )

        captured = {}

        def fake_score_and_update_issue(pain, issue_number):
            captured["pain"] = pain
            captured["issue_number"] = issue_number

        monkeypatch.setattr(scoring, "score_and_update_issue", fake_score_and_update_issue)

        scoring.score_open_issues()

        assert captured["issue_number"] == 1
        assert captured["pain"]["severity"] == 5
        assert captured["pain"]["willingness_to_pay"] == "high"
        assert captured["pain"]["app_idea"] == "元のアイデア"

    def test_falls_back_to_title_when_no_pain_data(self, monkeypatch):
        """pain-data メタデータが無い（古い）Issue はタイトルから簡易復元する（後方互換）."""
        issues = [
            {
                "number": 2,
                "title": "古い形式の Issue タイトル",
                "body": "## ペイン\n本文のみ",
                "labels": [],
            },
        ]

        monkeypatch.setattr(
            scoring.subprocess, "run", lambda *a, **kw: self._fake_gh_result(issues)
        )

        captured = {}

        def fake_score_and_update_issue(pain, issue_number):
            captured["pain"] = pain
            captured["issue_number"] = issue_number

        monkeypatch.setattr(scoring, "score_and_update_issue", fake_score_and_update_issue)

        scoring.score_open_issues()

        assert captured["issue_number"] == 2
        assert captured["pain"]["pain"] == "古い形式の Issue タイトル"
        assert captured["pain"]["severity"] == 3
        assert captured["pain"]["willingness_to_pay"] == "medium"

    def test_already_scored_issue_is_skipped(self, monkeypatch):
        """スコアラベル済みの Issue はスキップされる（再スコアされない）."""
        issues = [
            {
                "number": 3,
                "title": "スコア済み",
                "body": "",
                "labels": [{"name": "🥇score-A"}],
            },
        ]
        monkeypatch.setattr(
            scoring.subprocess, "run", lambda *a, **kw: self._fake_gh_result(issues)
        )

        called = []
        monkeypatch.setattr(
            scoring, "score_and_update_issue", lambda pain, num: called.append(num)
        )

        scoring.score_open_issues()

        assert called == []
