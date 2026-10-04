import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/('src' if (root/'src/notify_bridge.py').exists() else 'scripts')))
import notify_bridge as bridge
import notify_ledger as ledger

class MemoryLedger:
    records={}
    fail_stage=None
    def __init__(self,repo,key): self.key=key
    def load(self): return copy.deepcopy(self.records.get(self.key))
    def save(self,state):
        if state.get('stage')==self.fail_stage: raise ledger.LedgerError('conflict')
        self.records[self.key]=copy.deepcopy(state)

class DurableTests(unittest.TestCase):
    def setUp(self):
        MemoryLedger.records={};MemoryLedger.fail_stage=None
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'NOTIFICATION_MODE':'shadow','NOTIFY_DURABLE_LEDGER':'true','GITHUB_REPOSITORY':'kaionn/lazy-product-lab','GITHUB_RUN_ID':'100','GITHUB_RUN_ATTEMPT':'1','SLACK_BOT_TOKEN':'FAKE','SLACK_REPORT_CHANNEL_ID':'C0C6LGRJ30R','SLACK_ALERT_CHANNEL_ID':'C0C6CBVA5TM','NOTIFY_STATE_DIR':self.tmp.name},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.mock=patch.object(ledger,'GitLedger',MemoryLedger);self.mock.start();self.addCleanup(self.mock.stop)

    def test_new_run_and_fresh_workspace_same_event_is_not_reposted(self):
        with patch.object(bridge,'api',return_value={'ok':True,'ts':'1.2'}) as api:
            first=bridge.mirror({'content':'artifact revision one'},event='candidates')
            self.assertEqual(first['status'],'sent')
            for p in Path(self.tmp.name).glob('*.json'):p.unlink()
            os.environ['GITHUB_RUN_ID']='200';os.environ['GITHUB_RUN_ATTEMPT']='2'
            result=bridge.mirror({'content':'artifact revision one'},event='candidates')
            self.assertEqual(result['status'],'already_sent');self.assertEqual(result['key'],first['key']);self.assertEqual(api.call_count,1)

    def test_long_chunks_have_stable_keys_even_if_run_link_crosses_boundary(self):
        with patch.object(bridge,'api',return_value={'ok':True,'ts':'1.2'}) as api:
            first=bridge.mirror({'content':'x'*3490})
            os.environ['GITHUB_RUN_ID']='20000000'
            second=bridge.mirror({'content':'x'*3490})
            self.assertEqual(first['key'],second['key']);self.assertEqual(second['status'],'already_sent')

    def test_payload_revision_gets_separate_event(self):
        with patch.object(bridge,'api',return_value={'ok':True,'ts':'1.2'}):
            a=bridge.mirror({'content':'revision1'});b=bridge.mirror({'content':'revision2'})
            self.assertNotEqual(a['key'],b['key'])

    def test_unfinished_claim_never_expires_into_retry(self):
        with patch.object(bridge,'api',side_effect=TimeoutError) as api:
            first=bridge.mirror({'content':'result'})
            self.assertEqual(first['status'],'needs_reconciliation')
        for p in Path(self.tmp.name).glob('*.json'):p.unlink()
        os.environ['GITHUB_RUN_ID']='newrun'
        with patch.object(bridge,'api') as api:
            self.assertEqual(bridge.mirror({'content':'result'})['status'],'needs_reconciliation');api.assert_not_called()

    def test_cas_claim_failure_sends_nothing(self):
        MemoryLedger.fail_stage='reserved'
        with patch.object(bridge,'api') as api:
            self.assertEqual(bridge.mirror({'content':'result'})['status'],'ledger_unavailable');api.assert_not_called()

    def test_missing_ledger_authority_does_not_send(self):
        with patch.object(ledger,'GitLedger',side_effect=ledger.LedgerError('missing')),patch.object(bridge,'api') as api:
            self.assertEqual(bridge.mirror({'content':'result'})['status'],'ledger_unavailable');api.assert_not_called()

    def test_file_id_durable_before_transport_and_ack_before_complete(self):
        image=Path(self.tmp.name)/'x.png';image.write_bytes(b'image')
        def binary(*args,**kwargs):
            record=next(iter(MemoryLedger.records.values()))
            self.assertEqual(record['file_id'],'F1');self.assertEqual(record['stage'],'upload_bytes')
            return b'OK'
        with patch.object(bridge,'api',side_effect=[{'ok':True,'ts':'1.2'},{'ok':True,'file_id':'F1','upload_url':'https://files.slack.com/upload/x'},{'ok':True}]),patch.object(bridge,'request',side_effect=binary):
            self.assertEqual(bridge.mirror({'content':'image'},file=str(image))['status'],'sent')
        record=next(iter(MemoryLedger.records.values()));self.assertTrue(record['file_uploaded']);self.assertTrue(record['file_sent'])

    def test_ack_persistence_failure_preserves_unknown_outcome(self):
        class FailAfterSend(MemoryLedger):
            def save(self,state):
                if state.get('parts'):raise ledger.LedgerError('storage failed')
                super().save(state)
        with patch.object(ledger,'GitLedger',FailAfterSend),patch.object(bridge,'api',return_value={'ok':True,'ts':'1.2'}) as api:
            self.assertEqual(bridge.mirror({'content':'result'})['status'],'needs_reconciliation');self.assertEqual(api.call_count,1)
        self.assertEqual(next(iter(MemoryLedger.records.values()))['status'],'sending')
        with patch.object(bridge,'api') as api:
            self.assertEqual(bridge.mirror({'content':'result'})['status'],'needs_reconciliation');api.assert_not_called()

class StorageTests(unittest.TestCase):
    def test_metadata_only_and_compare_and_swap(self):
        with patch.dict(os.environ,{'NOTIFY_LEDGER_TOKEN':'FAKE'}): store=ledger.GitLedger('kaionn/life','a'*64)
        state={'key':'a'*64,'repo':'kaionn/life','parts':[],'status':'sending'}
        with patch.object(store,'http',return_value={'content':{'sha':'blob1'}}) as http:
            store.save(state)
            self.assertNotIn('sha',http.call_args.args[1]);self.assertEqual(http.call_args.args[1]['branch'],'notification-ledger')
            store.save(state);self.assertEqual(http.call_args.args[1]['sha'],'blob1')
        with self.assertRaises(ledger.LedgerError):store.save({**state,'payload':'private'})

    def test_wrong_repo_and_unapproved_record_fields_block(self):
        with patch.dict(os.environ,{'NOTIFY_LEDGER_TOKEN':'FAKE'}):
            with self.assertRaises(ledger.LedgerError):ledger.GitLedger('other/repo','a'*64)
            store=ledger.GitLedger('kaionn/life','a'*64)
        import base64
        with patch.object(store,'http',return_value={'encoding':'base64','sha':'blob1','content':base64.b64encode(json.dumps({'key':'a'*64,'repo':'kaionn/life','token':'FAKE'}).encode()).decode()}):
            with self.assertRaises(ledger.LedgerError):store.load()

if __name__=='__main__':unittest.main()
