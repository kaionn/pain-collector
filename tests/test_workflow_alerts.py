"""workflow_alerts.py のユニットテスト."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import responses

from src import workflow_alerts


def _summary() -> dict:
    return {
        "stalled_count": 1,
        "stalled": [
            {
                "issue_number": 42,
                "title": "Stuck build",
                "last_event_at": "2026-04-09T07:37:00+00:00",
                "hours_since_last_event": 30.5,
            }
        ],
    }


class TestNotifyStalledIssues:
    def test_edits_label_and_posts_comment_per_item(self):
        with patch.object(workflow_alerts.subprocess, "run") as mock_run:
            workflow_alerts.notify_stalled_issues(_summary())

        assert mock_run.call_count == 2
        edit_call = mock_run.call_args_list[0][0][0]
        assert edit_call[:3] == ["gh", "issue", "edit"]
        assert "--remove-label" in edit_call and "building" in edit_call
        assert "--add-label" in edit_call and "stalled" in edit_call

        comment_call = mock_run.call_args_list[1][0][0]
        assert comment_call[:3] == ["gh", "issue", "comment"]
        assert "42" in comment_call
        body = comment_call[comment_call.index("--body") + 1]
        assert "30.5" in body

    def test_no_calls_when_no_stalled_items(self):
        with patch.object(workflow_alerts.subprocess, "run") as mock_run:
            workflow_alerts.notify_stalled_issues({"stalled": []})
        mock_run.assert_not_called()


class TestNotifyDiscordStalled:
    def test_returns_false_when_webhook_url_missing(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert workflow_alerts.notify_discord_stalled(_summary()) is False

    @responses.activate
    def test_posts_payload_to_webhook(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
        responses.add(
            responses.POST,
            "https://discord.example/webhook",
            json={"ok": True},
            status=200,
        )

        result = workflow_alerts.notify_discord_stalled(_summary())

        assert result is True
        assert len(responses.calls) == 1
        payload = responses.calls[0].request.body
        assert b"stalled" in payload
        assert b"42" in payload

    @responses.activate
    def test_raises_on_http_error(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
        responses.add(
            responses.POST,
            "https://discord.example/webhook",
            json={"error": "boom"},
            status=500,
        )

        with pytest.raises(Exception):
            workflow_alerts.notify_discord_stalled(_summary())


def _run_list_output(
    conclusion: str,
    updated_at: str,
    url: str = "https://github.com/kaionn/pain-collector/actions/runs/1",
    title: str = "Weekly trends",
) -> str:
    return json.dumps(
        [
            {
                "conclusion": conclusion,
                "updatedAt": updated_at,
                "url": url,
                "displayTitle": title,
            }
        ]
    )


class TestCheckFailedRuns:
    def test_detects_failure_within_window(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_result = MagicMock(
            returncode=0, stdout=_run_list_output("failure", recent), stderr=""
        )
        with patch.object(workflow_alerts.subprocess, "run", return_value=mock_result):
            problems = workflow_alerts.check_failed_runs(
                "kaionn/pain-collector", window_minutes=65, workflows=["weekly.yml"]
            )

        assert len(problems) == 1
        assert "weekly.yml" in problems[0]
        assert "https://github.com/kaionn/pain-collector/actions/runs/1" in problems[0]

    def test_ignores_failure_outside_window(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_result = MagicMock(
            returncode=0, stdout=_run_list_output("failure", old), stderr=""
        )
        with patch.object(workflow_alerts.subprocess, "run", return_value=mock_result):
            problems = workflow_alerts.check_failed_runs(
                "kaionn/pain-collector", window_minutes=65, workflows=["weekly.yml"]
            )

        assert problems == []

    def test_returns_empty_list_when_gh_command_fails(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch.object(workflow_alerts.subprocess, "run", return_value=mock_result):
            problems = workflow_alerts.check_failed_runs(
                "kaionn/pain-collector", window_minutes=65, workflows=["weekly.yml"]
            )

        assert problems == []


class TestFailedRunsCli:
    def test_notifies_discord_when_problems_found(self):
        with (
            patch.object(
                workflow_alerts,
                "check_failed_runs",
                return_value=["weekly.yml が失敗: Weekly trends https://example/1"],
            ) as mock_check,
            patch.object(workflow_alerts.discord_notify, "notify_pipeline_alert") as mock_notify,
        ):
            workflow_alerts.main(["failed-runs", "--repo", "kaionn/pain-collector"])

        mock_check.assert_called_once()
        mock_notify.assert_called_once_with(
            ["weekly.yml が失敗: Weekly trends https://example/1"]
        )


class TestCli:
    def test_stalled_issues_command_dispatches(self, tmp_path):
        summary_path = tmp_path / "stalled.json"
        summary_path.write_text('{"stalled": []}', encoding="utf-8")

        with patch.object(workflow_alerts, "notify_stalled_issues") as mock_fn:
            workflow_alerts.main(["stalled-issues", "--summary", str(summary_path)])
        mock_fn.assert_called_once_with({"stalled": []})

    def test_discord_command_dispatches(self, tmp_path):
        summary_path = tmp_path / "stalled.json"
        summary_path.write_text('{"stalled": []}', encoding="utf-8")

        with patch.object(workflow_alerts, "notify_discord_stalled") as mock_fn:
            workflow_alerts.main(["discord", "--summary", str(summary_path)])
        mock_fn.assert_called_once_with({"stalled": []})
