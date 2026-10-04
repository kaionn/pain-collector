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
    def test_mvp_primary_fallback_is_one_aggregate_without_bot_cards(self):
        session=MagicMock();session.post.return_value.status_code=204
        with patch.object(discord_notify,'mirror') as mirror,patch.object(discord_notify,'discord_gate',return_value=True),patch.object(discord_notify,'discord_ack') as ack,patch.object(discord_notify,'create_retry_session',return_value=session) as factory,patch.object(discord_notify,'_send_mvp_bot_message') as bot:
            discord_notify.notify_mvp_picked([{'number':1,'title':'synthetic1'},{'number':2,'title':'synthetic2'}],'2026-10-04','https://github.com/kaionn/pain-collector');mirror.assert_called_once();factory.assert_called_once_with(retries=0);bot.assert_not_called();session.post.assert_called_once();ack.assert_called_once_with(204)
            self.assertEqual(len(session.post.call_args.kwargs['json']['embeds']),2)
    def test_stalled_primary_success_skips_original_webhook(self):
        summary={'stalled':[{'title':'synthetic','issue_number':1,'hours_since_last_event':25}]}
        with patch.object(discord_notify,'mirror'),patch.object(discord_notify,'discord_gate',return_value=False),patch.object(workflow_alerts,'create_retry_session') as factory:
            workflow_alerts.notify_discord_stalled(summary);factory.assert_not_called()
if __name__=='__main__':unittest.main()
