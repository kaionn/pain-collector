"""workflow_alerts.py のユニットテスト."""

from __future__ import annotations

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
