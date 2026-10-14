"""One bounded, notification-only recovery of a confirmed pre-delivery failure."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.notify_bridge import mirror,audit_delivery,discord_gate,write_json
from src.notify_ledger import GitLedger
KEY='11362f3b3396264d2a7dd5b1080a2d734537fe8a0527589da0225f20632429c8'
RUN='37184445078'
ARTIFACT='slack-delivery-37184445078-1-detect-stalled'

def main():
    assert os.environ.get('GITHUB_REPOSITORY')=='kaionn/pain-collector'
    assert os.environ.get('GITHUB_RUN_ATTEMPT')=='1'
    os.environ['NOTIFICATION_MODE']='slack'
    os.environ['NOTIFY_DURABLE_LEDGER']='true'
    # gh handles authenticated artifact downloads and redirects. Never print output.
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run(['gh','run','download',RUN,'--repo','kaionn/pain-collector','--name',ARTIFACT,'--dir',temporary],env={**os.environ,'GH_TOKEN':os.environ['NOTIFY_LEDGER_TOKEN']},check=True,capture_output=True)
        root=Path(temporary)
        marker=json.loads((root/'.notification-state/last-result.json').read_text())
        assert marker=={'status':'ledger_unavailable','key':KEY}
        event=json.loads((root/'.notification-outbox'/KEY/'event.json').read_text())
        assert event['key']==KEY and event['category']=='alerts' and event['event']=='stalled-builds' and event['file_name'] is None
        payload={'content':'\n\n'.join(event['stable_chunks'])}
        identity={'repo':'kaionn/pain-collector','event':'stalled-builds','category':'alerts','run':'durable-v1','body':event['stable_chunks'],'file':None}
        assert hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==KEY
        prior=GitLedger('kaionn/pain-collector',KEY).load()
        assert prior is None or prior.get('status')=='sent'  # An unfinished claim must never be retried.
        result=mirror(payload,'alerts','stalled-builds')
        assert result['key']==KEY and result['status'] in {'sent','already_sent'}
        assert discord_gate(result) is False
        assert audit_delivery()==0
        write_json(Path('.notification-state/recovery-result.json'),{'status':'verified','original_run':RUN,'original_key':KEY,'result':result,'discord_gate':False,'business_processing':False})
        print(json.dumps({'status':'verified','key':KEY,'delivery':result['status'],'business_processing':False}))
    return 0

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('::error::Bounded notification recovery incomplete; inspect retained receipts/outbox. No automatic retry.')
        raise SystemExit(1)
