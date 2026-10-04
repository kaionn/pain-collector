"""Metadata-only durable notification receipts on a dedicated Git branch.

No payloads, credentials, responses or upload URLs are persisted. GitHub Contents
blob SHA provides compare-and-swap. A prior unfinished claim always requires
manual reconciliation; expiry never permits an automatic second Slack send.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.request

BRANCH = 'notification-ledger'
ALLOWED = {'schema', 'key', 'repo', 'event', 'channel', 'parts', 'status', 'stage',
           'file_id', 'file_uploaded', 'file_sent', 'run_id', 'run_attempt', 'error_class', 'mode'}

class LedgerError(Exception):
    pass

class GitLedger:
    def __init__(self, repo, key):
        if not re.fullmatch(r'kaionn/(lazy-product-lab|pain-collector|signal-lab|a0ba-diary-blog|life)', repo) or not re.fullmatch(r'[0-9a-f]{64}', key):
            raise LedgerError('Invalid ledger target')
        self.repo, self.key, self.sha = repo, key, None
        self.token = os.environ.get('NOTIFY_LEDGER_TOKEN', '')
        if not self.token:
            raise LedgerError('Ledger token missing')
        self.url = f'https://api.github.com/repos/{repo}/contents/receipts/v1/{key[:2]}/{key}.json'

    def http(self, method, body=None):
        url = self.url + ('?ref=' + BRANCH if method == 'GET' else '')
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept':'application/vnd.github+json',
                     'Content-Type':'application/json', 'X-GitHub-Api-Version':'2022-11-28'}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            code=error.code; error.close()
            if method == 'GET' and code == 404:
                return None
            raise LedgerError('Ledger conflict or unavailable') from None
        except (OSError, ValueError):
            raise LedgerError('Ledger transport outcome uncertain') from None

    def load(self):
        result = self.http('GET')
        if result is None:
            return None
        if result.get('encoding') != 'base64':
            raise LedgerError('Invalid ledger encoding')
        state = json.loads(base64.b64decode(result['content']))
        if state.get('key') != self.key or state.get('repo') != self.repo or set(state) - ALLOWED:
            raise LedgerError('Invalid ledger record')
        self.sha = result['sha']
        return state

    def save(self, state):
        if set(state) - ALLOWED or state.get('key') != self.key or state.get('repo') != self.repo:
            raise LedgerError('Unsafe ledger fields')
        safe = {k:v for k,v in state.items() if k in ALLOWED}
        body = {'message': 'Record notification delivery ' + self.key[:12], 'branch':BRANCH,
                'content':base64.b64encode(json.dumps(safe, sort_keys=True, ensure_ascii=False).encode()).decode()}
        if self.sha:
            body['sha'] = self.sha
        result=self.http('PUT',body)
        self.sha=result.get('content',{}).get('sha')
        if not self.sha:
            raise LedgerError('Ledger acknowledgement incomplete')
