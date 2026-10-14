"""Smoke uses a single synthetic CLI request and never emits raw provider output."""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src import llm_smoke


@pytest.fixture
def smoke_env(monkeypatch):
    for key in ('ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        monkeypatch.delenv(key, raising=False)
    for key, value in {'LLM_PROVIDER': 'claude-cli', 'LLM_MODEL': llm_smoke.MODEL, 'LLM_CLAUDE_AUTH_MODE': 'ci-oauth', 'GITHUB_ACTIONS': 'true', 'CLAUDE_CODE_OAUTH_TOKEN': 'mock-secret-never-log'}.items():
        monkeypatch.setenv(key, value)


def auth():
    return MagicMock(returncode=0, stdout=json.dumps({'loggedIn': True, 'authMethod': 'oauth_token', 'apiProvider': 'firstParty', 'email': 'mock-secret-never-log'}))


def result(**changes):
    data = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '[]', 'modelUsage': {llm_smoke.MODEL: {}}, 'extra': 'mock-secret-never-log'}
    data.update(changes)
    return MagicMock(returncode=0, stdout=json.dumps(data))


def test_single_synthetic_success_in_isolated_cwd(smoke_env, capsys):
    original_cwd = os.getcwd()
    def run(command, **kwargs):
        assert os.getcwd() != original_cwd
        if '-p' in command:
            assert kwargs['input'] == 'Synthetic fixture: no posts and no pains.'
            assert '--safe-mode' in command and '--no-session-persistence' in command
            assert command[command.index('--tools') + 1] == ''
            return result()
        return auth()
    with patch('src.llm_smoke.subprocess.run', side_effect=run) as call:
        assert llm_smoke.main() == 0
        assert call.call_count == 2
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report['success'] and report['auth_verified']
    assert report['inference_count'] == 1
    assert report['response_model'] == llm_smoke.MODEL
    assert report['parsed_json'] == []
    assert 'mock-secret-never-log' not in output
    assert os.getcwd() == original_cwd


@pytest.mark.parametrize('response', [result(result='[1]'), result(modelUsage={}), result(modelUsage={'other-model': {}}), result(is_error=True), MagicMock(returncode=1, stdout='mock-secret-never-log'), MagicMock(returncode=0, stdout='mock-secret-never-log')])
def test_failure_is_secret_safe_without_retries(smoke_env, response, capsys):
    with patch('src.llm_smoke.subprocess.run', side_effect=[auth(), response]) as call:
        assert llm_smoke.main() == 1
        assert call.call_count == 2
    assert 'mock-secret-never-log' not in capsys.readouterr().out


@pytest.mark.parametrize('key,value', [('LLM_PROVIDER', 'anthropic'), ('LLM_MODEL', 'other-model'), ('LLM_CLAUDE_AUTH_MODE', 'local-subscription'), ('CLAUDE_CODE_OAUTH_TOKEN', ''), ('ANTHROPIC_BASE_URL', 'https://company.example')])
def test_bad_config_no_inference(smoke_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with patch('src.llm_smoke.subprocess.run') as call:
        report, code = llm_smoke.run_smoke()
    assert code == 1 and report['inference_count'] == 0
    call.assert_not_called()


def test_invalid_auth_no_inference(smoke_env):
    with patch('src.llm_smoke.subprocess.run', return_value=MagicMock(returncode=0, stdout='{}')) as call:
        report, code = llm_smoke.run_smoke()
    assert code == 1 and not report['auth_verified']
    assert report['inference_count'] == 0 and call.call_count == 1


def test_smoke_workflow_read_only_and_scoped():
    workflow = yaml.load(Path('.github/workflows/llm-smoke.yml').read_text(), Loader=yaml.BaseLoader)
    assert workflow['permissions'] == {'contents': 'read'}
    assert set(workflow['on']) == {'pull_request', 'workflow_dispatch'}
    assert workflow['on']['pull_request']['types'] == ['synchronize']
    job = workflow['jobs']['smoke']
    for scope in ["github.actor == 'kaionn'", 'number == 250', "head.repo.full_name == 'kaionn/pain-collector'", "head.ref == 'fix/explicit-llm-provider'"]:
        assert scope in job['if']
    steps = job['steps']
    assert steps[0]['with']['persist-credentials'] == 'false'
    assert sum(step.get('run') == 'uv run python -m src.llm_smoke' for step in steps) == 1
    text = Path('.github/workflows/llm-smoke.yml').read_text()
    for forbidden in ['PAT_TOKEN', 'LLM_API_KEY', 'GH_TOKEN', 'src.main', 'git push', 'pull_request_target']:
        assert forbidden not in text
