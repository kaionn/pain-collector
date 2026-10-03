"""Workflow provider variables remain aligned; credential routes remain separate."""
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("name", ["collect", "weekly", "monthly", "issue-commands"])
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
            assert env["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert matched > 0
    if name != "issue-commands":
        assert any(step.get("with", {}).get("token") == "${{ secrets.PAT_TOKEN }}" for job in workflow["jobs"].values() for step in job["steps"])
