"""One synthetic-only CLI request; emit fixed, nonsecret verification metadata."""

import json
import os
import subprocess
import tempfile
from unittest.mock import patch

from . import llm_client

MODEL = "claude-opus-5-5"


def run_smoke() -> tuple[dict, int]:
    report = {
        "success": False,
        "requested_model": MODEL,
        "response_model": None,
        "auth_verified": False,
        "inference_count": 0,
    }
    if (os.environ.get("LLM_PROVIDER") != "claude-cli"
            or os.environ.get("LLM_MODEL") != MODEL
            or os.environ.get("LLM_CLAUDE_AUTH_MODE") != "ci-oauth"):
        report["failure"] = "configuration"
        return report, 1

    real_run = subprocess.run
    model_verified = False

    def observe(command, *args, **kwargs):
        nonlocal model_verified
        inference = "-p" in command
        if inference:
            report["inference_count"] += 1
            if report["inference_count"] > 1:
                raise llm_client.LLMError("Only one synthetic inference is permitted")
        result = real_run(command, *args, **kwargs)
        # Never log raw stdout/stderr, identities, arbitrary model names or credentials.
        try:
            data = json.loads(result.stdout)
        except (ValueError, TypeError):
            return result
        if isinstance(data, dict) and result.returncode == 0:
            if command == ["claude", "auth", "status", "--json"]:
                report["auth_verified"] = (
                    data.get("loggedIn") is True
                    and data.get("authMethod") == "oauth_token"
                    and data.get("apiProvider") == "firstParty"
                )
            elif inference:
                usage = data.get("modelUsage")
                model_verified = isinstance(usage, dict) and set(usage) == {MODEL}
                if model_verified:
                    report["response_model"] = MODEL
        return result

    previous_cwd = os.getcwd()
    try:
        # CLI runs outside the checkout and receives only the fixed fixture below.
        with tempfile.TemporaryDirectory(prefix="pain-collector-smoke-") as cwd:
            os.chdir(cwd)
            with patch("src.llm_client.subprocess.run", side_effect=observe):
                response = llm_client.chat(
                    "Synthetic fixture: no posts and no pains.",
                    system="Return exactly the JSON array []. Do not use any tools.",
                    timeout=180,
                )
            parsed = llm_client.parse_json_response(response)
            if parsed != []:
                report["failure"] = "unexpected_json"
                return report, 1
            if not model_verified:
                report["failure"] = "response_model_unverified"
                return report, 1
            if not report["auth_verified"]:
                report["failure"] = "authentication"
                return report, 1
            report.update(success=True, parsed_json=[])
            return report, 0
    except (llm_client.LLMError, ValueError, OSError):
        report["failure"] = "authentication_or_cli_or_response"
        return report, 1
    finally:
        os.chdir(previous_cwd)


def main() -> int:
    report, code = run_smoke()
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
