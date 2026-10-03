"""Workflow provider variables remain aligned; credential routes remain separate."""
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("name", ["collect", "weekly", "monthly", "issue-commands", "learn"])
def test_llm_settings_are_explicit_and_repo_credentials_preserved(name):
    workflow = yaml.safe_load(Path(f".github/workflows/{name}.yml").read_text())
    matched = 0
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            env = step.get("env", {})
            if "LLM_PROVIDER" not in env:
                continue
            matched += 1
            for variable in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_EMBED_MODEL", "LLM_MAX_TOKENS"):
                assert env[variable] == "${{ vars." + variable + " }}"
            assert env["LLM_API_KEY"] == "${{ secrets.LLM_API_KEY }}"
            assert env["LLM_CLAUDE_AUTH_MODE"] == "ci-oauth"
            assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "${{ vars.LLM_PROVIDER == 'claude-cli' && secrets.CLAUDE_CODE_OAUTH_TOKEN || '' }}"
            assert env["DISABLE_AUTOUPDATER"] == "1"
            assert env["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert matched > 0
    if name != "issue-commands":
        assert any(step.get("with", {}).get("token") == "${{ secrets.PAT_TOKEN }}" for job in workflow["jobs"].values() for step in job["steps"])


@pytest.mark.parametrize("name", ["collect", "weekly", "monthly", "issue-commands", "learn"])
def test_setup_precedes_pipeline(name):
    workflow = yaml.safe_load(Path(f".github/workflows/{name}.yml").read_text())
    for job in workflow["jobs"].values():
        steps = job["steps"]
        setup = next(i for i, step in enumerate(steps) if step.get("uses") == "./.github/actions/setup-llm")
        assert setup > next(i for i, step in enumerate(steps) if step.get("run") == "uv sync")
        for i, step in enumerate(steps):
            if "LLM_PROVIDER" in step.get("env", {}) and "run" in step:
                assert setup < i
        if name == "issue-commands":
            assert steps[setup]["if"] == "startsWith(github.event.comment.body, '/spec') || startsWith(github.event.comment.body, '/probe')"


def test_official_installer_is_pinned_and_preflight_first():
    action = yaml.safe_load(Path('.github/actions/setup-llm/action.yml').read_text())
    steps = action['runs']['steps']
    assert 'validate_config(check_cli_auth=False)' in steps[0]['run']
    assert 'https://claude.ai/install.sh' in steps[1]['run']
    assert '-u CLAUDE_CODE_OAUTH_TOKEN -u LLM_API_KEY' in steps[1]['run']
    assert '2.1.288' in steps[1]['run']
    assert 'GITHUB_PATH' in steps[1]['run']
    assert 'validate_config()' in steps[2]['run']
    assert all(step.get('if') == "env.LLM_PROVIDER == 'claude-cli'" for step in steps[1:])
