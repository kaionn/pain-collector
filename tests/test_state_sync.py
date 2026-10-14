"""Offline CAS probes: auth/network failure and lost updates must fail closed."""
import base64
import json
import subprocess
from unittest.mock import patch
import pytest
from src import state_sync


def completed(code=0,stdout=''):
    return subprocess.CompletedProcess([],code,stdout,'failure')


def fetched(sha='base'):
    return completed(stdout=json.dumps({'sha':sha,'content':base64.b64encode(b'{"picked": []}').decode()}))


def test_fetch_content_and_sha_together(tmp_path):
    p=str(tmp_path/'state.json')
    with patch.object(state_sync,'_run_gh',return_value=fetched()) as gh:state_sync.fetch('o/r','state.json',p)
    assert json.load(open(p))=={'picked':[]}
    assert json.load(open(p+'.base.json'))['sha']=='base'
    gh.assert_called_once_with(['api','repos/o/r/contents/state.json'])


def test_failed_fetch_preserves_local_state(tmp_path):
    p=tmp_path/'state.json';p.write_text('{"picked":[1]}')
    with patch.object(state_sync,'_run_gh',return_value=completed(1)):
        with pytest.raises(RuntimeError):state_sync.fetch('o/r','state.json',str(p))
    assert p.read_text()=='{"picked":[1]}'
    assert not (tmp_path/'state.json.base.json').exists()


def test_push_uses_fetched_sha_not_current_remote_sha(tmp_path):
    p=str(tmp_path/'state.json')
    with patch.object(state_sync,'_run_gh',return_value=fetched()):state_sync.fetch('o/r','state.json',p)
    with patch.object(state_sync,'_run_gh',return_value=completed()) as gh:state_sync.push('o/r','state.json',p,'message')
    assert gh.call_count==1
    assert 'sha=base' in gh.call_args.args[0]
    with pytest.raises(ValueError):state_sync.push('o/r','state.json',p,'message')


def test_cas_conflict_stops_without_retrying_with_latest_sha(tmp_path):
    p=str(tmp_path/'state.json')
    with patch.object(state_sync,'_run_gh',return_value=fetched()):state_sync.fetch('o/r','state.json',p)
    with patch.object(state_sync,'_run_gh',return_value=completed(1)) as gh:
        with pytest.raises(RuntimeError,match='conflicted'):state_sync.push('o/r','state.json',p,'message')
    assert gh.call_count==1
    assert json.load(open(p+'.base.json'))['sha']=='base'


def test_destination_mismatch_no_write(tmp_path):
    p=str(tmp_path/'state.json')
    with patch.object(state_sync,'_run_gh',return_value=fetched()):state_sync.fetch('o/r','state.json',p)
    with patch.object(state_sync,'_run_gh') as gh:
        with pytest.raises(ValueError):state_sync.push('other/r','state.json',p,'message')
    gh.assert_not_called()


def test_explicit_create_has_no_sha_and_never_reads_latest(tmp_path):
    p=tmp_path/'state.json';p.write_text('{"picked":[]}')
    with patch.object(state_sync,'_run_gh',return_value=completed()) as gh:state_sync.push('o/r','state.json',str(p),'message',create_if_missing=True)
    assert gh.call_count==1
    assert not any(x.startswith('sha=') for x in gh.call_args.args[0])
