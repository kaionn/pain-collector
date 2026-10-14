from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from src import opportunity_pipeline as p
from src.monitor_stalled import detect_stalled,mark_stalled

NOW=datetime(2026,10,4,12,tzinfo=timezone.utc)
ROOT=Path(__file__).resolve().parents[1]

def contract():
    c=json.loads((ROOT/'examples/opportunity.json').read_text())
    # Synthetic evidence, not a claim of real demand; only used inside tests.
    c['evidence']=[{'url':'https://example.com/'+signal,'checked_at':NOW.isoformat(),'summary':'synthetic '+signal,'signal':signal} for signal in ['pain','alternative','distribution']]
    c['distribution']={'channel':'fixture','audience':'fixture users','rationale':'fixture only'}
    return c

def move(state,target,data=None,event=None,actor='kaionn',now=NOW):
    return p.transition(state,target,event_id=event or target,expected_revision=state['revision'],actor=actor,data=data,now=now)

def approved():
    s=p.initial(contract())
    return move(s,'approved',{'digest':s['contract_digest'],'approval_reference':'fixture user consent'})

def result(s):
    return {'contract_digest':s['contract_digest'],'outcome':'passed','checks':[{'id':x['id'],'passed':True,'artifact':'local log'} for x in s['contract']['build']['acceptance']], 'preview':'http://127.0.0.1:3000/p/flag-audit','elapsed_minutes':30,'iterations':1}

class PipelineTests(unittest.TestCase):
    def test_complete_flow_and_separate_release_consent(self):
        s=move(approved(),'building');s=move(s,'review_ready',result(s))
        with self.assertRaises(ValueError):move(s,'released',{'url':'https://example.com/p','artifact':'release log'})
        s=move(s,'release_approved',{'digest':p.digest(s['result']),'approval_reference':'user approved actual preview'})
        s=move(s,'released',{'url':'https://example.com/p','artifact':'release log'})
        s=move(s,'learning',{'distribution_url':'https://example.com/post','distributed_at':NOW.isoformat(),'measured_at':NOW.isoformat(),'measurement_status':'observed','exposures':30,'primary_count':20})
        s=move(s,'graduated',{'reason':'threshold met'})
        with self.assertRaises(ValueError):move(s,'building',event='new-build')
    def test_unauthorized_hash_changed_missing_evidence(self):
        s=p.initial(contract())
        with self.assertRaises(ValueError):move(s,'approved',{'digest':s['contract_digest'],'approval_reference':'x'},actor='agent')
        with self.assertRaises(ValueError):move(s,'approved',{'digest':'bad','approval_reference':'x'})
        s['contract']['solution']='changed'
        with self.assertRaises(ValueError):move(s,'approved',{'digest':s['contract_digest'],'approval_reference':'x'})
        c=contract();c['evidence']=[]
        with self.assertRaises(ValueError):p.ready(c,NOW)
    def test_datetime_contract_matches_node_rfc3339_boundary(self):
        for value in ['2026-10-02 09:31:00+09:00','2026-10-02T09:31:00','2026-02-30T09:31:00Z']:
            c=contract();c['origin']['observed_at']=value
            with self.assertRaises(ValueError):p.validate(c)
        for value in ['2026-10-02T09:31:00+09:00','2026-10-02T00:31:00Z','2026-10-02T00:31:00.123456Z']:
            c=contract();c['origin']['observed_at']=value;p.validate(c)
    def test_draft_and_stale_future_evidence(self):
        c=json.loads((ROOT/'examples/opportunity.json').read_text())
        with self.assertRaises(ValueError):p.ready(c,NOW)
        for offset in [-31,1]:
            c=contract()
            for e in c['evidence']:e['checked_at']=(NOW+timedelta(days=offset)).isoformat()
            with self.assertRaises(ValueError):p.ready(c,NOW)
    def test_replay_and_conflicting_duplicate_and_revision(self):
        s=approved();data={'reason':'tool missing'}
        stopped=move(s,'blocked',data,event='stop')
        replay=p.transition(stopped,'blocked',event_id='stop',expected_revision=0,actor='kaionn',data=data,now=NOW)
        self.assertEqual(stopped,replay)
        with self.assertRaises(ValueError):move(stopped,'blocked',{'reason':'other'},event='stop')
        with self.assertRaises(ValueError):p.transition(s,'building',event_id='b',expected_revision=0,actor='kaionn',now=NOW)
        restarted=move(stopped,'shortlisted');self.assertEqual(restarted['approvals'],{})
        with self.assertRaises(ValueError):move(restarted,'building')
    def test_failure_and_resource_bounds(self):
        s=move(approved(),'building')
        for key,value in [('outcome','failed'),('preview','https://x:y@example.com'),('iterations',4),('elapsed_minutes',121)]:
            r=result(s);r[key]=value
            with self.assertRaises(ValueError):move(s,'review_ready',r)
        with self.assertRaises(ValueError):move(s,'review_ready',result(s),now=NOW+timedelta(hours=3))
        r=result(s);r['checks'][0]['passed']=False
        with self.assertRaises(ValueError):move(s,'review_ready',r)
        failed=move(s,'failed',{'reason':'test failed'})
        with self.assertRaises(ValueError):move(failed,'building',event='new-build')
    def test_kill_window_threshold_and_sufficient_exposure(self):
        s=move(approved(),'building');s=move(s,'review_ready',result(s));s=move(s,'release_approved',{'digest':p.digest(s['result']),'approval_reference':'user'});s=move(s,'released',{'url':'https://example.com','artifact':'log'})
        later=NOW+timedelta(days=21)
        for exposures,count,allowed in [(19,0,False),(20,2,False),(20,1,True)]:
            observing=move(s,'learning',{'distribution_url':'https://example.com/post','distributed_at':NOW.isoformat(),'measured_at':later.isoformat(),'measurement_status':'observed','exposures':exposures,'primary_count':count},now=later)
            if allowed:self.assertEqual(move(observing,'killed',{'reason':'measured low demand'},now=later)['state'],'killed')
            else:
                with self.assertRaises(ValueError):move(observing,'killed',{'reason':'measured low demand'},now=later)
    def test_unknown_measurement_never_kills(self):
        s=move(approved(),'building');s=move(s,'review_ready',result(s));s=move(s,'release_approved',{'digest':p.digest(s['result']),'approval_reference':'user'});s=move(s,'released',{'url':'https://example.com','artifact':'log'})
        s=move(s,'learning',{'distribution_url':'https://example.com/post','distributed_at':NOW.isoformat(),'measured_at':NOW.isoformat(),'measurement_status':'unknown','exposures':None,'primary_count':None})
        with self.assertRaises(ValueError):move(s,'killed',{'reason':'no signals'},now=NOW+timedelta(days=30))
    def test_validation_dedup_and_bounded_shortlist(self):
        c=contract();p.validate(c)
        bad=deepcopy(c);bad['build']['shell']='rm -rf /'
        with self.assertRaises(ValueError):p.validate(bad)
        c2=deepcopy(c);c2['id']='duplicate'
        self.assertEqual(len(p.shortlist([c,c2],NOW)),1)
        self.assertTrue(p.shortlist([c],NOW)[0]['ready'])
    def test_reconciliation_requires_fresh_terminal_proof_preserves_source(self):
        old={'picked':[{'issue_number':223,'status':'probing','events':[]}]}
        proof={'issue_number':223,'checked_at':NOW.isoformat(),'evidence_url':'https://github.com/kaionn/signal-lab/pull/1','outcome':'closed_unmerged'}
        new=p.reconcile_legacy(old,[proof],NOW)
        self.assertEqual(new['picked'][0]['status'],'cancelled')
        self.assertEqual(old['picked'][0]['status'],'probing')
        self.assertEqual(p.reconcile_legacy(new,[proof],NOW),new)
        proof['checked_at']=(NOW-timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):p.reconcile_legacy(old,[proof],NOW)
    def test_atomic_local_mutation_and_handoff(self):
        s=approved();bundle=p.handoff(s,NOW)
        self.assertIn('No publish',p.brief(bundle))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';p.atomic_write(path,s)
            new=p.mutate(path,'building',event_id='start',expected_revision=1,actor='kaionn',now=NOW)
            self.assertEqual(json.loads(path.read_text()),new)
            with self.assertRaises(ValueError):p.mutate(path,'blocked',event_id='other',expected_revision=1,actor='kaionn',data={'reason':'x'},now=NOW)
    def test_legacy_probing_is_stalled_without_claiming_failure(self):
        state={'picked':[{'issue_number':223,'title':'old','status':'probing','picked_at':'2026-07-05T00:00:00Z','events':[]}]}
        self.assertEqual(detect_stalled(state,now=NOW)[0].issue_number,223)
        new=mark_stalled(state,{223},now=NOW)
        self.assertEqual(new['picked'][0]['status'],'stalled');self.assertEqual(state['picked'][0]['status'],'probing')
        self.assertIn('成否未確認',new['picked'][0]['events'][-1]['payload']['reason'])

if __name__=='__main__':unittest.main()
