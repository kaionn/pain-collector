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
            self.assertEqual(api.call_args.args[1]['text'],'*[lazy-product-lab / notification / 通知]*\nreal report\n\nhttps://github.com/kaionn/lazy-product-lab/actions/runs/100')
            self.assertEqual(bridge.audit_delivery(),0)

    def test_known_rejection_is_durable_failure_with_no_discord_or_retry(self):
        summary=Path(self.tmp.name)/"summary"
        os.environ['GITHUB_STEP_SUMMARY']=str(summary)
        with patch.object(bridge,'api',side_effect=bridge.DeliveryError('rejected',known_rejection=True)):
            result=bridge.mirror({'content':'result'})
        self.assertEqual(result['status'],'known_rejected')
        self.assertFalse(bridge.discord_gate(result))
        self.assertEqual(next(iter(MemoryLedger.records.values()))['status'],'rejected')
        bridge.discord_ack(204,result)
        self.assertEqual(next(iter(MemoryLedger.records.values()))['status'],'rejected')
        self.assertEqual(bridge.audit_delivery(),1)
        self.assertIn('no Discord fallback',summary.read_text())
        os.environ['GITHUB_RUN_ID']='newrun'
        with patch.object(bridge,'api') as api:
            replay=bridge.mirror({'content':'result'})
            self.assertEqual(replay['status'],'needs_reconciliation');self.assertFalse(bridge.discord_gate(replay));api.assert_not_called()

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

    def test_unknown_slack_is_never_retried_and_never_uses_discord(self):
        with patch.object(bridge,'api',side_effect=TimeoutError):
            result=bridge.mirror({'content':'result'})
        self.assertFalse(bridge.discord_gate(result));bridge.discord_ack('000',result)
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

    def test_only_explicit_pre_delivery_api_rejections_are_classified_known(self):
        for code,expected in [("invalid_auth",True),("channel_not_found",True),("internal_error",False),("unrecognized_error",False)]:
            with self.subTest(code=code),patch.object(bridge,"request",return_value=('{"ok":false,"error":"'+code+'"}').encode()):
                with self.assertRaises(bridge.DeliveryError) as caught:
                    bridge.api("chat.postMessage",{},"synthetic-only")
                self.assertEqual(caught.exception.known_rejection,expected)

    def test_unwritable_local_receipt_flags_the_final_runner_audit(self):
        command_file=Path(self.tmp.name)/"runner-env"
        os.environ["GITHUB_ENV"]=str(command_file)
        with patch.object(bridge,"write_json",side_effect=OSError("unwritable")):
            result=bridge.mirror({"content":"synthetic"})
        self.assertEqual(result["status"],"adapter_failed")
        self.assertEqual(os.environ["NOTIFY_DELIVERY_ERROR"],"true")
        self.assertIn("NOTIFY_DELIVERY_ERROR=true",command_file.read_text())
        self.assertEqual(bridge.audit_delivery(),1)


    def test_approved_product_routes_and_files_use_selected_channel(self):
        image=Path(self.tmp.name)/"routing.png";image.write_bytes(b"synthetic image")
        for repo,channel in bridge.PRODUCT_REPORT_CHANNELS.items():
            with self.subTest(repo=repo),patch.dict(os.environ,{"GITHUB_REPOSITORY":repo,"SLACK_REPORT_CHANNEL_ID":channel}),patch.object(bridge,"api",side_effect=[{"ok":True,"ts":"1"},{"ok":True,"file_id":"F1","upload_url":"https://files.slack.com/upload/test"},{"ok":True}]) as api,patch.object(bridge,"request",return_value=b"OK"):
                result=bridge.mirror({"content":"new product report"},event="routing-file",file=str(image))
                self.assertEqual(result["status"],"sent")
                self.assertEqual(api.call_args_list[0].args[1]["channel"],channel)
                self.assertEqual(api.call_args_list[-1].args[1]["channel_id"],channel)
                self.assertIn(repo.split("/")[1]+" / routing-file / 通知",api.call_args_list[0].args[1]["text"])
                self.assertEqual(MemoryLedger.records[result["key"]]["channel"],channel)

    def test_cross_product_or_unknown_category_cannot_send(self):
        for settings,category in [({"GITHUB_REPOSITORY":"kaionn/life","SLACK_REPORT_CHANNEL_ID":"C0C706J486M"},"reports"),({"SLACK_ALERT_CHANNEL_ID":"C0C6GSL6H7Z"},"alerts"),({},"unapproved")]:
            with patch.dict(os.environ,settings),patch.object(bridge,"api") as api:
                self.assertEqual(bridge.mirror({"content":"wrong route"},category=category)["status"],"blocked")
                api.assert_not_called()

    def test_legacy_event_key_and_sent_receipt_survive_channel_cutover(self):
        key="8c8e7da052b14e62a3b606f99e1ca62a2ac3d44e53bbeb0570b30991bd56a649"
        MemoryLedger.records[key]={"key":key,"repo":"kaionn/lazy-product-lab","event":"candidates","channel":"C0C6LGRJ30R","parts":["legacy-ts"],"status":"sent"}
        os.environ["SLACK_REPORT_CHANNEL_ID"]="C0C6GSL6H7Z"
        with patch.object(bridge,"api") as api:
            result=bridge.mirror({"content":"routing revision one"},event="candidates")
            self.assertEqual(result["key"],key);self.assertEqual(result["status"],"already_sent")
            api.assert_not_called()
        self.assertEqual(MemoryLedger.records[key]["channel"],"C0C6LGRJ30R")

    def test_uncertain_old_channel_receipt_is_not_moved_or_retried(self):
        key="8c8e7da052b14e62a3b606f99e1ca62a2ac3d44e53bbeb0570b30991bd56a649"
        for status in ("sending","rejected","needs_reconciliation"):
            MemoryLedger.records[key]={"key":key,"repo":"kaionn/lazy-product-lab","event":"candidates","channel":"C0C6LGRJ30R","parts":["maybe-sent"],"status":status}
            with patch.dict(os.environ,{"SLACK_REPORT_CHANNEL_ID":"C0C6GSL6H7Z"}),patch.object(bridge,"api") as api:
                result=bridge.mirror({"content":"routing revision one"},event="candidates")
                self.assertEqual(result["status"],"needs_reconciliation");api.assert_not_called()
                self.assertFalse(bridge.discord_gate(result))
            self.assertEqual(MemoryLedger.records[key]["channel"],"C0C6LGRJ30R")

    def test_new_route_replay_and_old_route_rollback_send_no_duplicate(self):
        with patch.dict(os.environ,{"SLACK_REPORT_CHANNEL_ID":"C0C6GSL6H7Z"}),patch.object(bridge,"api",return_value={"ok":True,"ts":"new-ts"}) as api:
            first=bridge.mirror({"content":"routing revision one"},event="candidates")
            self.assertEqual(first["key"],"8c8e7da052b14e62a3b606f99e1ca62a2ac3d44e53bbeb0570b30991bd56a649")
            self.assertEqual(first["status"],"sent")
            self.assertEqual(bridge.mirror({"content":"routing revision one"},event="candidates")["status"],"already_sent")
            self.assertEqual(api.call_count,1)
        with patch.object(bridge,"api") as api:
            self.assertEqual(bridge.mirror({"content":"routing revision one"},event="candidates")["status"],"already_sent")
            api.assert_not_called()

    def test_alert_label_identifies_repo_event_without_injecting_mentions(self):
        with patch.object(bridge,"api",return_value={"ok":True,"ts":"alert-ts"}) as api:
            result=bridge.mirror({"content":"safe failure"},category="alerts",event="pipeline <!channel>")
            text=api.call_args.args[1]["text"]
            self.assertTrue(text.startswith("*[lazy-product-lab / pipeline &lt;!channel&gt; / 障害]*"))
            self.assertEqual(api.call_args.args[1]["channel"],"C0C6CBVA5TM")
            self.assertFalse(bridge.discord_gate(result))

if __name__=='__main__':unittest.main()
