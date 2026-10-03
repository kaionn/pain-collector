"""LLM tests: all provider calls mocked."""
from unittest.mock import MagicMock, patch
import pytest
from src.llm_client import LLMError, _RetriableLLMError, chat, embed, parse_json_object, parse_json_response

@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "fake-ai-key")
    monkeypatch.setenv("LLM_MODEL", "chosen-model")
    monkeypatch.setenv("LLM_EMBED_MODEL", "chosen-embedding")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-repo-token")


def test_repo_token_does_not_select_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-repo-token")
    with patch("openai.OpenAI") as client, pytest.raises(LLMError, match="LLM_PROVIDER"):
        chat("synthetic")
    client.assert_not_called()

@pytest.mark.parametrize("missing", ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"])
def test_missing_config(configured, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with patch("openai.OpenAI") as client, pytest.raises(LLMError):
        chat("synthetic")
    client.assert_not_called()

@pytest.mark.parametrize("url", ["https://models.github.ai/inference", "http://provider.example", "https://user:secret@provider.example"])
def test_invalid_endpoint(configured, monkeypatch, url):
    monkeypatch.setenv("LLM_BASE_URL", url)
    with pytest.raises(LLMError):
        chat("synthetic")


def test_explicit_api_config(configured):
    with patch("openai.OpenAI") as factory:
        factory.return_value.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="[]"))])
        assert chat("synthetic") == "[]"
        factory.assert_called_once_with(base_url="https://provider.example/v1", api_key="fake-ai-key", max_retries=0, timeout=180)
        assert factory.return_value.chat.completions.create.call_args.kwargs["model"] == "chosen-model"

@pytest.mark.parametrize("response", ["retired", MagicMock(choices=[]), MagicMock(choices=[MagicMock(message=MagicMock(content=None))])])
def test_invalid_response_fails_once(configured, response):
    with patch("openai.OpenAI") as factory:
        factory.return_value.chat.completions.create.return_value = response
        with pytest.raises(LLMError):
            chat("synthetic")
        assert factory.return_value.chat.completions.create.call_count == 1

@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_auth_and_configuration_fail_once(configured, status):
    import httpx
    from openai import APIStatusError
    error = APIStatusError("synthetic", response=httpx.Response(status, request=httpx.Request("POST", "https://provider.example")), body=None)
    with patch("openai.OpenAI") as factory:
        factory.return_value.chat.completions.create.side_effect = error
        with pytest.raises(LLMError, match=str(status)):
            chat("synthetic")
        assert factory.return_value.chat.completions.create.call_count == 1


def test_transient_retry_bounded(configured):
    with patch("src.llm_client._call_api", side_effect=_RetriableLLMError("temporary")) as call, patch("src.llm_client.time.sleep"):
        with pytest.raises(LLMError):
            chat("synthetic")
        assert call.call_count == 3


def test_cli_explicit_model(configured, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude-cli")
    with patch("src.llm_client._check_claude_subscription"), patch("src.llm_client.subprocess.run", return_value=MagicMock(returncode=0, stdout='{"type":"result","subtype":"success","is_error":false,"result":"[]"}')) as call:
        assert chat("synthetic") == "[]"
        assert "chosen-model" in call.call_args.args[0]
        assert "--tools" in call.call_args.args[0]
        assert call.call_args.kwargs["input"] == "synthetic"
    assert embed(["synthetic"]) is None

@pytest.mark.parametrize("content", ["{}", "null", "[1]", "", "oops"])
def test_wrong_json_shape(content):
    with pytest.raises(LLMError):
        parse_json_response(content)


def test_embeddings_bad_shape(configured):
    with patch("openai.OpenAI") as factory:
        factory.return_value.embeddings.create.return_value = "retired"
        with pytest.raises(LLMError):
            embed(["synthetic"])

class TestParseJsonResponse:
    """parse_json_response のエッジケーステスト."""

    def test_plain_json_array(self):
        assert parse_json_response('[{"a": 1}]') == [{"a": 1}]

    def test_json_in_markdown_code_block(self):
        content = '```json\n[{"a": 1}]\n```'
        assert parse_json_response(content) == [{"a": 1}]

    def test_json_in_plain_code_block(self):
        content = '```\n[{"a": 1}]\n```'
        assert parse_json_response(content) == [{"a": 1}]

    def test_json_with_leading_trailing_text(self):
        content = "はい、以下です:\n" '[{"a": 1}]\n' "以上です。"
        assert parse_json_response(content) == [{"a": 1}]

    def test_empty_array(self):
        assert parse_json_response("[]") == []

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_json_response("これは JSON ではない")

    def test_broken_json_in_code_block_raises(self):
        with pytest.raises(Exception):
            parse_json_response("```\n{invalid json\n```")


class TestParseJsonObject:
    """parse_json_object のエッジケーステスト."""

    def test_plain_json_object(self):
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_json_in_markdown_code_block(self):
        content = '```json\n{"a": 1}\n```'
        assert parse_json_object(content) == {"a": 1}

    def test_json_with_leading_trailing_text(self):
        content = "結果です:\n" '{"a": 1}\n' "以上。"
        assert parse_json_object(content) == {"a": 1}

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_json_object("これは JSON ではない")

    def test_broken_json_raises(self):
        with pytest.raises(Exception):
            parse_json_object("{broken")


@pytest.mark.parametrize("content", ["null", "[]", "[1]", "oops", "```"])
def test_invalid_json_object_is_typed_failure(content):
    with pytest.raises(LLMError):
        parse_json_object(content)

@pytest.fixture
def anthropic_config(configured, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")


def _anthropic_response(content=None, stop="end_turn", status=200):
    return MagicMock(status_code=status, json=MagicMock(return_value={
        "type": "message", "role": "assistant", "stop_reason": stop,
        "content": content if content is not None else [{"type": "text", "text": "[]"}],
    }))


def test_anthropic_direct_request(anthropic_config):
    with patch("requests.Session") as session:
        client = session.return_value.__enter__.return_value
        client.post.return_value = _anthropic_response([{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "[]"}])
        assert chat("synthetic", system="system", temperature=0.3) == "[]"
        args, kwargs = client.post.call_args
        assert args == ("https://api.anthropic.com/v1/messages",)
        assert kwargs["json"] == {"model": "claude-opus-5-5", "max_tokens": 4096, "messages": [{"role": "user", "content": "synthetic"}], "system": "system"}
        assert kwargs["headers"]["x-api-key"] == "fake-ai-key"
        assert kwargs["allow_redirects"] is False
        assert client.trust_env is False
    assert embed(["synthetic"]) is None

@pytest.mark.parametrize("status", [302, 400, 401, 403, 404])
def test_anthropic_fatal_status_once(anthropic_config, status):
    with patch("requests.Session") as session:
        client = session.return_value.__enter__.return_value
        client.post.return_value = _anthropic_response(status=status)
        with pytest.raises(LLMError):
            chat("synthetic")
        assert client.post.call_count == 1

@pytest.mark.parametrize("stop", ["max_tokens", "refusal", "tool_use", None])
def test_anthropic_incomplete_or_refused(anthropic_config, stop):
    with patch("requests.Session") as session:
        session.return_value.__enter__.return_value.post.return_value = _anthropic_response(stop=stop)
        with pytest.raises(LLMError):
            chat("synthetic")

@pytest.mark.parametrize("content", [[], "text", [{"type": "text", "text": None}], [{"type": "thinking"}]])
def test_anthropic_invalid_content(anthropic_config, content):
    with patch("requests.Session") as session:
        session.return_value.__enter__.return_value.post.return_value = _anthropic_response(content=content)
        with pytest.raises(LLMError):
            chat("synthetic")


def test_anthropic_no_output_limit_fails_before_request(anthropic_config, monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS")
    with patch("requests.Session") as session, pytest.raises(LLMError):
        chat("synthetic")
    session.assert_not_called()


def test_anthropic_retries_are_bounded(anthropic_config):
    with patch("requests.Session") as session, patch("src.llm_client.time.sleep"):
        client = session.return_value.__enter__.return_value
        client.post.return_value = _anthropic_response(status=529)
        with pytest.raises(LLMError):
            chat("synthetic")
        assert client.post.call_count == 3


@pytest.mark.parametrize("content", ['{"error": []}', '{"error": "bad", "details": []}'])
def test_error_object_not_mistaken_for_empty_array(content):
    with pytest.raises(LLMError):
        parse_json_response(content)


def test_array_not_mistaken_for_object():
    with pytest.raises(LLMError):
        parse_json_object('[{"a": 1}]')


@pytest.fixture
def clean_cli_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude-cli")
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5-5")
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        monkeypatch.delenv(key, raising=False)


def _cli_auth(**changes):
    import json
    status = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}
    status.update(changes)
    return MagicMock(returncode=0, stdout=json.dumps(status))


def test_subscription_cli_success_zero(clean_cli_env):
    result = MagicMock(returncode=0, stdout='{"type":"result","subtype":"success","is_error":false,"result":"[]"}')
    with patch("src.llm_client.subprocess.run", side_effect=[_cli_auth(), result]) as call:
        assert chat("synthetic") == "[]"
        assert call.call_count == 2
        assert call.call_args_list[0].args[0] == ["claude", "auth", "status", "--json"]
        assert "claude-opus-5-5" in call.call_args_list[1].args[0]

@pytest.mark.parametrize("changes", [{"loggedIn": False}, {"authMethod": "api_key"}, {"authMethod": "third_party"}, {"apiProvider": "thirdParty"}, {"subscriptionType": None}])
def test_cli_unverified_auth_stops_before_inference(clean_cli_env, changes):
    with patch("src.llm_client.subprocess.run", return_value=_cli_auth(**changes)) as call:
        with pytest.raises(LLMError):
            chat("synthetic")
        assert call.call_count == 1

@pytest.mark.parametrize("key,value", [("ANTHROPIC_BASE_URL", "https://gateway.example"), ("ANTHROPIC_API_KEY", "fake"), ("CLAUDE_CODE_USE_VERTEX", "1"), ("CLAUDE_CODE_OAUTH_TOKEN", "fake")])
def test_cli_override_stops_before_any_command(clean_cli_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with patch("src.llm_client.subprocess.run") as call, pytest.raises(LLMError):
        chat("synthetic")
    call.assert_not_called()

@pytest.mark.parametrize("stdout,code", [('not json', 0), ('{"type":"result","subtype":"error_max_turns","is_error":true,"result":"[]"}', 0), ('{"type":"result","subtype":"success","is_error":false,"result":""}', 0), ('{}', 1)])
def test_cli_error_no_retry(clean_cli_env, stdout, code):
    with patch("src.llm_client.subprocess.run", side_effect=[_cli_auth(), MagicMock(returncode=code, stdout=stdout)]) as call, patch("src.llm_client.time.sleep") as sleep:
        with pytest.raises(LLMError):
            chat("synthetic")
        assert call.call_count == 2
        sleep.assert_not_called()



def test_cli_timeout_respects_caller(clean_cli_env):
    import subprocess
    with patch("src.llm_client.subprocess.run", side_effect=[_cli_auth(), subprocess.TimeoutExpired("claude", 30)]) as call:
        with pytest.raises(LLMError, match="タイムアウト"):
            chat("synthetic", timeout=30)
        assert call.call_count == 2
        assert call.call_args.kwargs["timeout"] == 30
