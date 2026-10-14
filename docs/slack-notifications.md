# Slack notification shadow pilot

Discord remains the authoritative delivery path. Default `NOTIFICATION_MODE=discord`
performs no Slack HTTP calls. `shadow` mirrors existing notifications with
`[SHADOW TEST]`, no personal or channel mentions, and keeps all original Discord
messages, buttons and file uploads. Other values are disabled, including `slack`.
There is no production cutover flag in this PR.

Approved workspace: KaionDev (`T0C6EM7M70E`). Both destinations are public and
visible to all workspace members; private repo results and life task deadlines
were explicitly approved. Existing #dots is conversation-only and unchanged.

Repository variables:
- `SLACK_ALERT_CHANNEL_ID=C0C6CBVA5TM` (#ci-alerts)
- `SLACK_REPORT_CHANNEL_ID=C0C6LGRJ30R` (#reports)
- `NOTIFICATION_MODE=discord` until a bounded pilot is approved; then `shadow`.

Secret: `SLACK_BOT_TOKEN`, registered directly by the workspace/repo owner, never
pasted into chat, logs or files. Dedicated app scopes: `chat:write`, `files:write`.
Invite that bot to both channels. Existing dot connector credentials are not used.
Token is injected only into existing Discord notification steps, not all jobs.

Run `python3 tests/test_notify_bridge.py` for mocked notification-only checks.
There are no live Slack requests in these tests. The adapter uses stdlib Python
already present on GitHub-hosted Ubuntu runners. The source is a small vendored
v1 adapter; all five copies are kept identical in the migration patch bundle.

Long output is kept in thread replies instead of truncated. Discord mention IDs
are removed and Slack control syntax escaped. a0ba error summaries keep
classification/date/status/run URL but omit raw stderr/API response fields.
Signal draft screenshots are uploaded using the external Slack upload flow.
MVP approval in Slack uses the GitHub Issue link and /approve or /reject guidance;
existing Discord interactive approval continues during the pilot.

Receipts (keys/timestamps/progress only; no token or message body) are uploaded
as `slack-delivery-<run>-<attempt>-<job>` artifacts for 14 days. They preserve
within-run acknowledgements and allow review of incomplete delivery. This PR
**does not restore a cross-run ledger**, suppress Discord duplicates across
reruns, or provide exactly-once guarantees. A timeout/partial upload is recorded
as needs_reconciliation and is not blindly retried within the same ledger.
Do not run business generation, posting or approval workflows only to test Slack.
Use saved synthetic fixtures/notification-only tests first.

Rollback: set `NOTIFICATION_MODE=discord`; Slack mirroring stops immediately,
Discord behavior continues. Before a later cutover PR: verify live text/image
pilot and partial errors, define persistent delivery ledger/reconciliation,
separate published state from notified state, and test Discord fallback.
Signal signup notifications outside Actions remain on Discord in this PR.

## Manual synthetic verification

`Slack notifier checks` runs mocked tests on notification PRs. On main, the owner
can dispatch it with a unique `test_id`. The default `send_synthetic=false` only
checks token identity and granted scopes through `auth.test`, without posting.
The approved sender must be KaionDev T0C6EM7M70E / bot user U0C6GSWNYH4 with
chat:write and files:write. Token values are never printed or persisted.

Only one central repo needs `send_synthetic=true`: it sends one explicitly
synthetic report with a generated color-pattern PNG and one synthetic alert.
It tests within-run deduplication without an extra post. Other repo identities
can be verified without posting. This manual workflow does not change the
repository NOTIFICATION_MODE=discord variable and does not run business tasks.

The test receipt is cached under its unique ID even on failure. A prior receipt
or a rerun blocks sending: inspect its safe artifacts and Slack channel content
before deciding whether a distinct follow-up test is needed. cache eviction
means the ID must still not be reused; receipts are an operational guard, not an
exactly-once guarantee. API acceptance must be separately verified in Slack.
