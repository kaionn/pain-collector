import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/slack-smoke.py'
if not SCRIPT.exists():
    SCRIPT = Path(__file__).with_name('slack-smoke.py')
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'SLACK_BOT_TOKEN': 'synthetic-test-only', 'GITHUB_REPOSITORY': 'kaionn/lazy-product-lab', 'GITHUB_RUN_ATTEMPT': '1', 'SLACK_TEST_ID': 'synthetic-unique-1', 'SLACK_SEND_SYNTHETIC': 'false', 'NOTIFY_STATE_DIR': self.tmp.name}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        capture = contextlib.redirect_stdout(self.output); capture.__enter__(); self.addCleanup(capture.__exit__, None, None, None)

    def receipt(self):
        return json.loads((Path(self.tmp.name)/'synthetic-result.json').read_text())

    def test_identity_only_performs_no_post(self):
        with patch.object(smoke, 'identity', return_value={'status': 'verified'}), patch.object(smoke, 'mirror') as mirror:
            self.assertEqual(smoke.main(), 0); mirror.assert_not_called()
        self.assertEqual(self.receipt()['status'], 'identity_verified')

    def test_bounded_two_notifications_image_and_duplicate_check(self):
        with patch.dict(os.environ, {'SLACK_SEND_SYNTHETIC': 'true'}), patch.object(smoke, 'identity', return_value={'status': 'verified'}), patch.object(smoke, 'mirror', side_effect=[{'status': 'sent'}, {'status': 'already_sent'}, {'status': 'sent'}]) as mirror:
            self.assertEqual(smoke.main(), 0)
            self.assertEqual(mirror.call_count, 3)
            self.assertEqual(mirror.call_args_list[0].args[1], 'reports')
            image = Path(mirror.call_args_list[0].args[3]); self.assertTrue(image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(mirror.call_args_list[2].args[1], 'alerts')
        self.assertEqual(self.receipt()['status'], 'api_accepted')
        self.assertNotIn('synthetic-test-only', self.output.getvalue())
        self.assertNotIn('synthetic-test-only', (Path(self.tmp.name)/'synthetic-result.json').read_text())

    def test_prior_receipt_blocks_new_network_requests(self):
        (Path(self.tmp.name)/'synthetic-result.json').write_text('{"status":"needs_review"}')
        with patch.object(smoke, 'identity') as identity, patch.object(smoke, 'mirror') as mirror:
            self.assertEqual(smoke.main(), 1); identity.assert_not_called(); mirror.assert_not_called()

    def test_rerun_blocks_synthetic_posts(self):
        with patch.dict(os.environ, {'SLACK_SEND_SYNTHETIC': 'true', 'GITHUB_RUN_ATTEMPT': '2'}), patch.object(smoke, 'identity', return_value={'status': 'verified'}), patch.object(smoke, 'mirror') as mirror:
            self.assertEqual(smoke.main(), 1); mirror.assert_not_called()

    def test_partial_delivery_stops_before_next_notification(self):
        with patch.dict(os.environ, {'SLACK_SEND_SYNTHETIC': 'true'}), patch.object(smoke, 'identity', return_value={'status': 'verified'}), patch.object(smoke, 'mirror', return_value={'status': 'needs_reconciliation'}) as mirror:
            self.assertEqual(smoke.main(), 1); self.assertEqual(mirror.call_count, 1)
        self.assertEqual(self.receipt()['status'], 'needs_review')

    def test_unexpected_sender_and_missing_scopes_are_rejected(self):
        class Response:
            def __init__(self, team, scopes):
                self.team=team; self.headers={'X-OAuth-Scopes': scopes}
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'ok': True, 'team_id': self.team, 'user_id': smoke.EXPECTED_USER}).encode()
        for response in (Response('OTHER_TEAM', 'chat:write,files:write'), Response(smoke.EXPECTED_TEAM,'chat:write')):
            with patch.object(smoke.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(RuntimeError): smoke.identity()
        with patch.object(smoke.urllib.request, 'urlopen', return_value=Response(smoke.EXPECTED_TEAM,'chat:write,files:write')):
            self.assertEqual(smoke.identity()['status'], 'verified')

    def test_error_does_not_echo_exception_or_token(self):
        with patch.object(smoke, 'identity', side_effect=RuntimeError('synthetic-test-only')):
            self.assertEqual(smoke.main(), 1)
        self.assertNotIn('synthetic-test-only', self.output.getvalue())
        self.assertNotIn('synthetic-test-only', json.dumps(self.receipt()))

    def test_invalid_test_id_blocks_network(self):
        with patch.dict(os.environ, {'SLACK_TEST_ID': '../unsafe'}), patch.object(smoke,'identity') as identity:
            self.assertEqual(smoke.main(),1); identity.assert_not_called()


if __name__ == '__main__':
    unittest.main()
