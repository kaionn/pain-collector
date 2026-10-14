"""notify.py への actionability ゲート統合のテスト."""

import subprocess
from unittest.mock import patch

from src import notify


def _make_pain(pain_text: str = "テストペイン") -> dict:
    return {
        "pain": pain_text,
        "category": "生産性",
        "product_type": "モバイルアプリ",
        "target_user": "一般ユーザー",
        "severity": 4,
        "willingness_to_pay": "medium",
        "app_idea": "テストアイデア",
        "source_url": "https://example.com/x",
        "source_title": "テストソース",
    }


class TestGateRejectsBeforeIssueCreation:
    """gate が reject したペインは _create_issue に到達しないことを検証."""

    def test_reject_verdict_skips_issue_creation(self):
        pain = _make_pain()
        reject_verdict = {
            "actionable": False,
            "reject_reason": "特定アプリの不具合クレームのため対象外",
            "audience": "consumer",
        }

        with (
            patch("src.notify._fetch_open_issues", return_value=[]),
            patch("src.notify.pain_gate.classify", return_value=reject_verdict) as mock_classify,
            patch("src.notify._create_issue") as mock_create_issue,
        ):
            notify.send_top_pains([pain], "2026-07-12", top_n=3)

        mock_classify.assert_called_once()
        mock_create_issue.assert_not_called()

    def test_reject_verdict_not_included_in_digest(self):
        """reject されたペインは Discord digest 送信の対象（created_for_digest）に含まれない."""
        pain = _make_pain()
        reject_verdict = {"actionable": False, "reject_reason": "対象外", "audience": None}

        with (
            patch("src.notify._fetch_open_issues", return_value=[]),
            patch("src.notify.pain_gate.classify", return_value=reject_verdict),
            patch("src.notify._create_issue") as mock_create_issue,
            patch("src.discord_notify.notify_daily_digest") as mock_digest,
        ):
            notify.send_top_pains([pain], "2026-07-12", top_n=3)

        mock_create_issue.assert_not_called()
        mock_digest.assert_not_called()


class TestGatePassAssignsAudienceLabel:
    """gate を通過したペインには audience ラベルが付与されることを検証."""

    def test_consumer_audience_label_included_in_issue(self):
        pain = _make_pain()
        pass_verdict = {"actionable": True, "reject_reason": None, "audience": "consumer"}

        def _fake_subprocess_run(cmd, **kwargs):
            if cmd[:3] == ["gh", "issue", "create"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="https://github.com/kaionn/pain-collector/issues/42\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="mocked")

        with (
            patch("src.notify._fetch_open_issues", return_value=[]),
            patch("src.notify.pain_gate.classify", return_value=pass_verdict),
            patch("src.notify.subprocess.run", side_effect=_fake_subprocess_run) as mock_run,
            patch("src.scoring.score_and_update_issue", return_value=None),
            patch("src.discord_notify.notify_daily_digest") as mock_digest,
        ):
            notify.send_top_pains([pain], "2026-07-12", top_n=3)

        create_calls = [
            call for call in mock_run.call_args_list if call.args[0][:3] == ["gh", "issue", "create"]
        ]
        assert len(create_calls) == 1
        create_cmd = create_calls[0].args[0]
        assert "👤consumer" in create_cmd
        mock_digest.assert_called_once()
