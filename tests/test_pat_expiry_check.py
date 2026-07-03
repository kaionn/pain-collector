"""pat_expiry_check.py のユニットテスト."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import responses

from src import pat_expiry_check

_API_URL = pat_expiry_check._API_URL
_HEADER = pat_expiry_check.EXPIRATION_HEADER

_NOW = datetime(2026, 7, 4, 21, 0, 0, tzinfo=timezone.utc)


class TestParseExpiration:
    def test_parses_github_header_format(self):
        parsed = pat_expiry_check.parse_expiration("2026-10-01 15:04:12 UTC")
        assert parsed == datetime(2026, 10, 1, 15, 4, 12, tzinfo=timezone.utc)

    def test_parses_isoformat(self):
        parsed = pat_expiry_check.parse_expiration("2026-10-01T15:04:12+00:00")
        assert parsed == datetime(2026, 10, 1, 15, 4, 12, tzinfo=timezone.utc)

    def test_returns_none_for_garbage(self):
        assert pat_expiry_check.parse_expiration("not-a-date") is None


class TestFetchTokenStatus:
    @responses.activate
    def test_expired_on_401(self):
        responses.add(responses.GET, _API_URL, status=401)
        status, expiry = pat_expiry_check.fetch_token_status("tok")
        assert status == "expired"
        assert expiry is None

    @responses.activate
    def test_valid_with_expiration_header(self):
        responses.add(
            responses.GET,
            _API_URL,
            status=200,
            json={},
            headers={_HEADER: "2026-10-01 15:04:12 UTC"},
        )
        status, expiry = pat_expiry_check.fetch_token_status("tok")
        assert status == "valid"
        assert expiry == datetime(2026, 10, 1, 15, 4, 12, tzinfo=timezone.utc)

    @responses.activate
    def test_no_expiry_without_header(self):
        responses.add(responses.GET, _API_URL, status=200, json={})
        status, expiry = pat_expiry_check.fetch_token_status("tok")
        assert status == "no-expiry"
        assert expiry is None


class TestBuildAlert:
    def test_expired_message(self):
        msg = pat_expiry_check.build_alert("expired", None, _NOW, 7)
        assert msg is not None
        assert "失効しています" in msg
        assert "gh secret set PAT_TOKEN" in msg

    def test_warns_within_threshold(self):
        expiry = datetime(2026, 7, 9, 21, 0, 0, tzinfo=timezone.utc)  # 残り5日
        msg = pat_expiry_check.build_alert("valid", expiry, _NOW, 7)
        assert msg is not None
        assert "残り 5 日" in msg

    def test_silent_when_far_from_expiry(self):
        expiry = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert pat_expiry_check.build_alert("valid", expiry, _NOW, 7) is None

    def test_silent_for_no_expiry(self):
        assert pat_expiry_check.build_alert("no-expiry", None, _NOW, 7) is None


class TestRun:
    def _patch_status(self, status, expiry):
        return patch.object(
            pat_expiry_check,
            "fetch_token_status",
            return_value=(status, expiry),
        )

    def test_skips_without_token(self):
        with patch.dict("os.environ", {"PAT_TOKEN": ""}):
            with patch.object(pat_expiry_check, "_post_webhook") as mock_post:
                assert pat_expiry_check.run(7, None) == 0
        mock_post.assert_not_called()

    def test_notifies_when_expired_at_gate_hour(self):
        with patch.dict("os.environ", {"PAT_TOKEN": "tok"}):
            with self._patch_status("expired", None):
                with patch.object(pat_expiry_check, "_post_webhook") as mock_post:
                    pat_expiry_check.run(7, gate_hour=21, now=_NOW)
        mock_post.assert_called_once()
        assert "失効しています" in mock_post.call_args[0][0]["content"]

    def test_skips_outside_gate_hour(self):
        with patch.dict("os.environ", {"PAT_TOKEN": "tok"}):
            with self._patch_status("expired", None):
                with patch.object(pat_expiry_check, "_post_webhook") as mock_post:
                    pat_expiry_check.run(7, gate_hour=5, now=_NOW)
        mock_post.assert_not_called()

    def test_no_notification_when_healthy(self):
        expiry = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        with patch.dict("os.environ", {"PAT_TOKEN": "tok"}):
            with self._patch_status("valid", expiry):
                with patch.object(pat_expiry_check, "_post_webhook") as mock_post:
                    pat_expiry_check.run(7, gate_hour=21, now=_NOW)
        mock_post.assert_not_called()

    def test_force_notifies_even_when_healthy_outside_gate(self):
        expiry = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        with patch.dict("os.environ", {"PAT_TOKEN": "tok"}):
            with self._patch_status("valid", expiry):
                with patch.object(pat_expiry_check, "_post_webhook") as mock_post:
                    pat_expiry_check.run(7, gate_hour=5, force=True, now=_NOW)
        mock_post.assert_called_once()
        assert "疎通確認" in mock_post.call_args[0][0]["content"]
