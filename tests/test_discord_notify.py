"""discord_notify.py のユニットテスト."""

from unittest.mock import MagicMock, patch

import pytest

from src.discord_notify import (
    _post_bot_message,
    _post_webhook,
    _severity_color,
    notify_issue_created,
    notify_mvp_picked,
)


# --- _severity_color ---


class TestSeverityColor:
    def test_severity_5_is_red(self):
        assert _severity_color(5) == 0xE74C3C

    def test_severity_4_is_orange(self):
        assert _severity_color(4) == 0xE67E22

    def test_severity_3_is_yellow(self):
        assert _severity_color(3) == 0xF1C40F

    def test_severity_1_is_grey(self):
        assert _severity_color(1) == 0x95A5A6

    def test_unknown_severity_is_grey(self):
        assert _severity_color(0) == 0x95A5A6


# --- _post_webhook ---


class TestPostWebhook:
    def test_skips_when_no_url(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        with patch("src.discord_notify.create_retry_session") as mock_session:
            _post_webhook({"content": "test"})
            mock_session.assert_not_called()

    def test_posts_payload(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            _post_webhook({"content": "hello"})
            mock_session.post.assert_called_once_with(
                "https://discord.com/api/webhooks/test",
                json={"content": "hello"},
                timeout=10,
            )


# --- _post_bot_message ---


class TestPostBotMessage:
    def test_skips_when_no_token(self, monkeypatch):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
        with patch("src.discord_notify.create_retry_session") as mock_session:
            _post_bot_message({"content": "test"})
            mock_session.assert_not_called()

    def test_skips_when_no_channel_id(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
        with patch("src.discord_notify.create_retry_session") as mock_session:
            _post_bot_message({"content": "test"})
            mock_session.assert_not_called()

    def test_posts_with_bot_auth(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "my-bot-token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "999888777")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            _post_bot_message({"content": "hello"})
            mock_session.post.assert_called_once_with(
                "https://discord.com/api/v10/channels/999888777/messages",
                json={"content": "hello"},
                headers={"Authorization": "Bot my-bot-token"},
                timeout=10,
            )


# --- notify_issue_created ---


class TestNotifyIssueCreated:
    SAMPLE_PAIN = {
        "pain": "予防接種のスケジュール管理が煩雑",
        "severity": 4,
        "category": "子育て",
        "product_type": "モバイルアプリ",
        "target_user": "乳幼児の保護者",
        "willingness_to_pay": "medium",
        "frequency": "毎月",
        "app_idea": "予防接種スケジュール自動管理アプリ",
        "market_signal": "underserved",
    }

    def test_builds_correct_embed(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/webhook")
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_session = MagicMock()
        mock_session.post = fake_post

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            notify_issue_created(self.SAMPLE_PAIN, 42, "https://github.com/test/issues/42")

        embed = captured["payload"]["embeds"][0]
        assert embed["title"] == "[子育て] 予防接種のスケジュール管理が煩雑"
        assert embed["color"] == 0xE67E22
        assert any(f["name"] == "市場シグナル" for f in embed["fields"])

    def test_truncates_long_pain_text(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/webhook")
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_session = MagicMock()
        mock_session.post = fake_post

        pain = {**self.SAMPLE_PAIN, "pain": "あ" * 300, "app_idea": ""}
        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            notify_issue_created(pain, 1, "https://example.com")

        assert len(captured["payload"]["embeds"][0]["description"]) == 200


# --- notify_mvp_picked ---


class TestNotifyMvpPicked:
    SAMPLE_PICKED = [
        {
            "number": 10,
            "title": "リモートワーク集中力ツール",
            "score_label": "🏆score-S",
            "reason": "市場が空いている",
            "dev_period": "2週間",
            "spec": "specs/tool-spec.md",
        },
        {
            "number": 20,
            "title": "家計自動仕分けアプリ",
            "score_label": "🥇score-A",
            "reason": "需要が高い",
            "dev_period": "3週間",
            "spec": None,
        },
    ]

    def test_bot_api_sends_individual_messages(self, monkeypatch):
        """Bot API 利用時は候補ごとに個別メッセージを送信する."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
        call_count = {"n": 0}

        def fake_post(url, json=None, headers=None, timeout=None):
            call_count["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_session = MagicMock()
        mock_session.post = fake_post

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            notify_mvp_picked(self.SAMPLE_PICKED, "2026-03-25", "https://github.com/test")

        assert call_count["n"] == 2

    def test_approve_button_only_when_spec_exists(self, monkeypatch):
        """Spec ありの候補のみ Approve ボタンが付く."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
        payloads = []

        def fake_post(url, json=None, headers=None, timeout=None):
            payloads.append(json)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_session = MagicMock()
        mock_session.post = fake_post

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            notify_mvp_picked(self.SAMPLE_PICKED, "2026-03-25", "https://github.com/test")

        # 1 件目: spec あり → Approve + Reject + View Issue
        buttons_0 = payloads[0]["components"][0]["components"]
        assert any(b.get("custom_id", "").startswith("approve:") for b in buttons_0)
        assert any(b.get("custom_id", "").startswith("reject:") for b in buttons_0)
        assert len(buttons_0) == 3

        # 2 件目: spec なし → Reject + View Issue（Approve なし）
        buttons_1 = payloads[1]["components"][0]["components"]
        assert not any(b.get("custom_id", "").startswith("approve:") for b in buttons_1)
        assert any(b.get("custom_id", "").startswith("reject:") for b in buttons_1)
        assert len(buttons_1) == 2

    def test_webhook_fallback_when_no_bot(self, monkeypatch):
        """Bot 未設定時は Webhook にフォールバックする."""
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/webhook")
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_session = MagicMock()
        mock_session.post = fake_post

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            notify_mvp_picked(self.SAMPLE_PICKED, "2026-03-25", "https://github.com/test")

        assert len(captured["payload"]["embeds"]) == 2
        assert "MVP 候補が選定されました" in captured["payload"]["content"]
        assert "<@276013234962825217>" in captured["payload"]["content"]

    def test_empty_picks_skips(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/webhook")
        with patch("src.discord_notify.create_retry_session") as mock_session:
            notify_mvp_picked([], "2026-03-25", "https://github.com/test")
            mock_session.assert_not_called()

    def test_bot_fallback_to_webhook_on_error(self, monkeypatch):
        """Bot API 失敗時は Webhook にフォールバックする."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/webhook")
        call_urls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            call_urls.append(url)
            if "discord.com/api/v10/channels" in url:
                raise Exception("bot error")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_session = MagicMock()
        mock_session.post = fake_post

        with patch("src.discord_notify.create_retry_session", return_value=mock_session):
            notify_mvp_picked(self.SAMPLE_PICKED, "2026-03-25", "https://github.com/test")

        assert any("webhook" in url for url in call_urls)
