import os
import unittest
from unittest.mock import MagicMock,patch
from src import discord_notify,workflow_alerts
class PrimaryCallSites(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'NOTIFICATION_MODE':'slack','DISCORD_WEBHOOK_URL':'https://discord.invalid/synthetic','DISCORD_BOT_TOKEN':'synthetic-only','DISCORD_CHANNEL_ID':'synthetic'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
    def test_daily_slack_success_does_not_start_discord_session(self):
        created=[{'number':1,'title':'synthetic','url':'https://github.com/kaionn/pain-collector/issues/1','pain':{'severity':1}}]
        with patch.object(discord_notify,'mirror') as mirror,patch.object(discord_notify,'discord_gate',return_value=False),patch.object(discord_notify,'create_retry_session') as factory:
            discord_notify.notify_daily_digest(created,'2026-10-04');mirror.assert_called_once();factory.assert_not_called()
    def test_mvp_slack_only_never_uses_webhook_or_bot_on_rejected_or_unknown(self):
        for status in ['sent','known_rejected','needs_reconciliation']:
            with self.subTest(status=status),patch.object(discord_notify,'mirror',return_value={'status':status}),patch.object(discord_notify,'create_retry_session') as factory,patch.object(discord_notify,'_send_mvp_bot_message') as bot:
                discord_notify.notify_mvp_picked([{'number':1,'title':'synthetic1'},{'number':2,'title':'synthetic2'}],'2026-10-04','https://github.com/kaionn/pain-collector')
                factory.assert_not_called();bot.assert_not_called()

    def test_stalled_slack_only_works_without_discord_secret_on_failure(self):
        os.environ.pop('DISCORD_WEBHOOK_URL',None)
        summary={'stalled':[{'title':'synthetic','issue_number':1,'hours_since_last_event':25}]}
        for status in ['known_rejected','needs_reconciliation']:
            with self.subTest(status=status),patch.object(discord_notify,'mirror',return_value={'status':status}) as mirror,patch.object(workflow_alerts,'create_retry_session') as factory:
                workflow_alerts.notify_discord_stalled(summary);mirror.assert_called_once();factory.assert_not_called()

    def test_stalled_primary_success_skips_original_webhook(self):
        summary={'stalled':[{'title':'synthetic','issue_number':1,'hours_since_last_event':25}]}
        with patch.object(discord_notify,'mirror'),patch.object(discord_notify,'discord_gate',return_value=False),patch.object(workflow_alerts,'create_retry_session') as factory:
            workflow_alerts.notify_discord_stalled(summary);factory.assert_not_called()
    def test_normal_package_import_can_reach_slack_with_its_ledger(self):
        import subprocess,sys,textwrap
        script = """
import os,tempfile
from unittest.mock import patch
from src import notify_bridge,notify_ledger
class Store:
    def __init__(self,*args):pass
    def load(self):return None
    def save(self,state):pass
with tempfile.TemporaryDirectory() as td:
    os.chdir(td)
    with patch.dict(os.environ,{'NOTIFICATION_MODE':'slack','NOTIFY_DURABLE_LEDGER':'true','GITHUB_REPOSITORY':'kaionn/pain-collector','SLACK_BOT_TOKEN':'synthetic','SLACK_REPORT_CHANNEL_ID':'C0C6LGRJ30R','GITHUB_RUN_ID':'fixture'},clear=True),patch.object(notify_ledger,'GitLedger',Store),patch.object(notify_bridge,'api',return_value={'ok':True,'ts':'1.2'}) as api:
        result=notify_bridge.mirror({'content':'Synthetic package caller'})
        assert result['status']=='sent',result
        api.assert_called_once()
        assert not notify_bridge.discord_gate(result)
        assert notify_bridge.audit_delivery()==0
"""
        subprocess.run([sys.executable,'-c',textwrap.dedent(script)],check=True)

if __name__=='__main__':unittest.main()
