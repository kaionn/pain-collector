import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location("bridge", (Path(__file__).resolve().parents[1] / ("src/notify_bridge.py" if (Path(__file__).resolve().parents[1] / "src/notify_bridge.py").exists() else "scripts/notify_bridge.py")))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"NOTIFICATION_MODE": "shadow", "GITHUB_REPOSITORY": "kaionn/signal-lab", "GITHUB_RUN_ID": "123", "SLACK_BOT_TOKEN": "synthetic-test-only", "SLACK_ALERT_CHANNEL_ID": "C0C6CBVA5TM", "SLACK_REPORT_CHANNEL_ID": "C0C6LGRJ30R", "NOTIFY_STATE_DIR": self.tmp.name}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)

    def test_default_and_unknown_modes_do_not_use_network(self):
        for mode in ("discord", "slack", "typo"):
            with patch.dict(os.environ, {"NOTIFICATION_MODE": mode}), patch.object(bridge, "api") as api:
                self.assertEqual(bridge.mirror({"content": "result"})["status"], "disabled")
                api.assert_not_called()

    def test_unapproved_repository_and_channel_are_blocked(self):
        for setting in ({"GITHUB_REPOSITORY": "kaionn/unapproved"}, {"SLACK_REPORT_CHANNEL_ID": "C_WRONG"}, {"SLACK_BOT_TOKEN": ""}):
            with patch.dict(os.environ, setting), patch.object(bridge, "api") as api:
                self.assertEqual(bridge.mirror({"content": "result"})["status"], "blocked")
                api.assert_not_called()

    def test_content_fields_links_mention_escape_and_private_error_summary(self):
        text = bridge.render({"content": "<@123> <!channel> @everyone <@UFAKE>", "embeds": [{"title": "Title", "url": "https://github.com/kaionn/life/issues/2", "description": "[read](https://example.com/a)", "fields": [{"name": "期限", "value": "2026-10-04"}, {"name": "詳細", "value": "raw stderr"}]}]}, "alerts", "kaionn/a0ba-diary-blog")[0]
        self.assertIn("期限: 2026-10-04", text)
        self.assertIn("<https://example.com/a|read>", text)
        self.assertNotIn("<@", text)
        self.assertNotIn("<!channel>", text)
        self.assertNotIn("raw stderr", text)
        self.assertIn("actions/runs/123", text)

    def test_same_run_payload_delivered_once_and_long_content_threaded(self):
        with patch.object(bridge, "api", side_effect=[{"ok": True, "ts": "1"}, {"ok": True, "ts": "2"}]) as api:
            payload = {"content": "あ" * 6000}
            self.assertEqual(bridge.mirror(payload)["status"], "sent")
            self.assertEqual(api.call_count, 2)
            self.assertEqual(api.call_args_list[1].args[1]["thread_ts"], "1")
            self.assertEqual(bridge.mirror(payload)["status"], "already_sent")
            self.assertEqual(api.call_count, 2)

    def test_api_ok_false_creates_receipt_without_leaking_token_or_payload(self):
        with patch.object(bridge, "request", return_value=b'{"ok":false,"error":"invalid_auth"}'):
            self.assertEqual(bridge.mirror({"content": "private content"})["status"], "needs_reconciliation")
        state = "\n".join(p.read_text() for p in Path(self.tmp.name).glob("*.json"))
        self.assertNotIn("synthetic-test-only", state)
        self.assertNotIn("private content", state)
        with patch.object(bridge, "api") as api:
            self.assertEqual(bridge.mirror({"content": "private content"})["status"], "needs_reconciliation")
            api.assert_not_called()

    def test_uncertain_timeout_is_not_blindly_retried(self):
        with patch.object(bridge, "api", side_effect=TimeoutError) as api:
            self.assertEqual(bridge.mirror({"content": "result"})["status"], "needs_reconciliation")
            self.assertEqual(api.call_count, 1)
        with patch.object(bridge, "api") as api:
            bridge.mirror({"content": "result"})
            api.assert_not_called()

    def test_existing_receipt_parts_not_reposted_when_upload_completes(self):
        image = Path(self.tmp.name)/"synthetic.png"; image.write_bytes(b"fake-image")
        responses = [{"ok": True, "ts": "1"}, {"ok": True, "file_id": "FTEST", "upload_url": "https://files.slack.com/upload/synthetic"}, {"ok": True}]
        with patch.object(bridge, "api", side_effect=responses) as api, patch.object(bridge, "request", return_value=b"OK") as request:
            self.assertEqual(bridge.mirror({"content": "draft"}, file=str(image))["status"], "sent")
            self.assertEqual(request.call_args.kwargs["data"], b"fake-image")
            self.assertTrue(request.call_args.kwargs["binary"])
            self.assertEqual(api.call_args.args[1]["thread_ts"], "1")
            self.assertEqual(bridge.mirror({"content": "draft"}, file=str(image))["status"], "already_sent")
            self.assertEqual(api.call_count, 3)

    def test_image_failure_is_visible_and_not_retried_automatically(self):
        image = Path(self.tmp.name)/"synthetic.png"; image.write_bytes(b"fake-image")
        with patch.object(bridge, "api", side_effect=[{"ok": True, "ts": "1"}, bridge.DeliveryError("upload failed")]):
            self.assertEqual(bridge.mirror({"content": "draft"}, file=str(image))["status"], "needs_reconciliation")
        with patch.object(bridge, "api") as api:
            bridge.mirror({"content": "draft"}, file=str(image))
            api.assert_not_called()

    def test_missing_file_and_unwritable_state_cannot_break_primary_delivery(self):
        self.assertEqual(bridge.mirror({"content": "draft"}, file=str(Path(self.tmp.name)/"missing.png"))["status"], "adapter_failed")
        with patch.object(bridge, "write_json", side_effect=OSError("disk full")):
            self.assertEqual(bridge.mirror({"content": "draft"})["status"], "adapter_failed")

    def test_429_uses_retry_after_once(self):
        error = urllib.error.HTTPError("https://slack.com", 429, "rate limited", {"Retry-After": "2"}, None)
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"ok":true,"ts":"1"}'
        with patch.object(bridge.urllib.request, "urlopen", side_effect=[error, Response()]) as urlopen, patch.object(bridge.time, "sleep") as sleep:
            self.assertEqual(bridge.api("chat.postMessage", {}, "synthetic-test-only")["ts"], "1")
            sleep.assert_called_once_with(2)
            self.assertEqual(urlopen.call_count, 2)

    def test_custom_discord_actions_become_github_guidance(self):
        rendered = "".join(bridge.render({"components": [{"components": [{"custom_id": "approve:12"}, {"custom_id": "reject:12"}, {"label": "View", "url": "https://github.com/kaionn/pain-collector/issues/12"}]}]}, "reports", "kaionn/pain-collector"))
        self.assertIn("/approve", rendered); self.assertIn("/reject", rendered)
        self.assertIn("https://github.com/kaionn/pain-collector/issues/12", rendered)


if __name__ == "__main__":
    unittest.main()
