import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
import test_notify_ledger as fixtures
MemoryLedger,bridge,ledger=fixtures.MemoryLedger,fixtures.bridge,fixtures.ledger

class PrimaryRoutingTests(unittest.TestCase):
    def setUp(self):
        fixtures.DurableTests.setUp(self);os.environ['NOTIFICATION_MODE']='slack'

    def test_primary_success_suppresses_discord_and_has_no_shadow_prefix(self):
        with patch.object(bridge,'api',return_value={'ok':True,'ts':'1.2'}) as api:
            result=bridge.mirror({'content':'real report'})
            self.assertEqual(result['status'],'sent');self.assertFalse(bridge.discord_gate(result))
            self.assertEqual(api.call_args.args[1]['text'],'real report\n\nhttps://github.com/kaionn/lazy-product-lab/actions/runs/100')
            self.assertEqual(bridge.audit_delivery(),0)

    def test_known_rejection_reserves_one_fallback_and_ack_survives_new_run(self):
        with patch.object(bridge,'api',side_effect=bridge.DeliveryError('rejected',known_rejection=True)):
            result=bridge.mirror({'content':'result'})
        self.assertEqual(result['status'],'known_rejected')
        self.assertTrue(bridge.discord_gate(result))
        self.assertEqual(next(iter(MemoryLedger.records.values()))['status'],'fallback_sending')
        self.assertFalse(bridge.discord_gate(result))
        bridge.discord_ack(204)
        self.assertEqual(next(iter(MemoryLedger.records.values()))['status'],'fallback_sent')
        self.assertEqual(bridge.audit_delivery(),0)
        os.environ['GITHUB_RUN_ID']='newrun'
        with patch.object(bridge,'api') as api:
            replay=bridge.mirror({'content':'result'})
            self.assertEqual(replay['status'],'already_sent');self.assertFalse(bridge.discord_gate(replay));api.assert_not_called()

    def test_uncertain_slack_or_ledger_outcome_sends_no_second_provider(self):
        with patch.object(bridge,'api',side_effect=TimeoutError):result=bridge.mirror({'content':'result'})
        self.assertFalse(bridge.discord_gate(result));self.assertEqual(bridge.audit_delivery(),1)
        with patch.object(ledger,'GitLedger',side_effect=ledger.LedgerError('unavailable')):
            result=bridge.mirror({'content':'another'})
            self.assertFalse(bridge.discord_gate(result));self.assertEqual(bridge.audit_delivery(),1)

    def test_partial_text_or_image_failure_never_falls_back_whole_payload(self):
        with patch.object(bridge,'api',side_effect=[{'ok':True,'ts':'1'},bridge.DeliveryError('rejected',known_rejection=True)]):
            result=bridge.mirror({'content':'x'*5000})
        self.assertEqual(result['status'],'needs_reconciliation');self.assertFalse(bridge.discord_gate(result))

    def test_fallback_timeout_is_not_retried(self):
        with patch.object(bridge,'api',side_effect=bridge.DeliveryError('rejected',known_rejection=True)):
            result=bridge.mirror({'content':'result'})
        self.assertTrue(bridge.discord_gate(result));bridge.discord_ack('000')
        os.environ['GITHUB_RUN_ID']='newrun'
        with patch.object(bridge,'api') as api:
            self.assertEqual(bridge.mirror({'content':'result'})['status'],'needs_reconciliation');api.assert_not_called()
        self.assertFalse(bridge.discord_gate());self.assertEqual(bridge.audit_delivery(),1)

    def test_other_run_cannot_claim_rejected_fallback(self):
        with patch.object(bridge,'api',side_effect=bridge.DeliveryError('rejected',known_rejection=True)):
            result=bridge.mirror({'content':'result'})
        os.environ['GITHUB_RUN_ID']='other'
        self.assertFalse(bridge.discord_gate(result))

    def test_primary_without_ledger_is_blocked_not_disabled(self):
        os.environ['NOTIFY_DURABLE_LEDGER']='false'
        with patch.object(bridge,'api') as api:
            result=bridge.mirror({'content':'result'})
            self.assertEqual(result['status'],'blocked');self.assertFalse(bridge.discord_gate(result));api.assert_not_called()

    def test_shadow_keeps_existing_discord_on_all_outcomes(self):
        os.environ['NOTIFICATION_MODE']='shadow'
        for status in ['sent','known_rejected','needs_reconciliation','ledger_unavailable']:
            self.assertTrue(bridge.discord_gate({'status':status}))
        self.assertEqual(bridge.audit_delivery(),0)

if __name__=='__main__':unittest.main()
