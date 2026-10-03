"""明示設定した LLM provider を使用する共有クライアント。"""

import json
import logging
import os
import subprocess
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """構成・認証・応答など、抽出を成功扱いしてはいけない障害。"""


def _config(model=None, *, embedding=False):
    provider = os.environ.get("LLM_PROVIDER", "")
    if provider not in {"openai-compatible", "claude-cli", "anthropic"}:
        raise LLMError("LLM_PROVIDER を anthropic、openai-compatible または claude-cli に明示設定してください")
    selected_model = model or os.environ.get("LLM_EMBED_MODEL" if embedding else "LLM_MODEL", "")
    if provider == "claude-cli":
        if not embedding and not selected_model:
            raise LLMError("LLM_MODEL を設定してください")
        return provider, "", "", selected_model
    if provider == "anthropic":
        base_url = os.environ.get("LLM_BASE_URL", "")
        token = os.environ.get("LLM_API_KEY", "")
        if base_url != "https://api.anthropic.com":
            raise LLMError("anthropic は LLM_BASE_URL=https://api.anthropic.com を使用してください")
        if not token or not selected_model:
            raise LLMError("LLM_API_KEY と LLM_MODEL を設定してください")
        return provider, base_url, token, selected_model
    base_url = os.environ.get("LLM_BASE_URL", "")
    token = os.environ.get("LLM_API_KEY", "")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LLMError("LLM_BASE_URL に credential を含まない HTTPS endpoint を設定してください")
    if parsed.hostname in {"models.github.ai", "models.inference.ai.azure.com"}:
        raise LLMError("廃止された GitHub Models endpoint は使用できません")
    if not token or not selected_model:
        raise LLMError("LLM_API_KEY と LLM_MODEL（embeddings は LLM_EMBED_MODEL）を設定してください")
    return provider, base_url, token, selected_model

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2.0
CLAUDE_CLI_TIMEOUT_SECONDS = 180


class _RetriableLLMError(LLMError):
    """LLM 呼び出しの一時的な失敗（リトライ対象）."""


def _call_api(
    token: str,
    user_content: str,
    *,
    system: str | None,
    temperature: float,
    max_tokens: int | None,
    model: str | None,
    timeout: float,
) -> str:
    """明示設定された OpenAI-compatible API (openai SDK) を呼び出す."""
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    client = OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=token,
        max_retries=0,
        timeout=timeout,
    )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        response = client.chat.completions.create(**kwargs)
    except RateLimitError as e:
        raise _RetriableLLMError("LLM の一時的な接続/API 障害") from e
    except APIConnectionError as e:
        raise _RetriableLLMError("LLM の一時的な接続/API 障害") from e
    except APIStatusError as e:
        if e.status_code >= 500:
            raise _RetriableLLMError("LLM の一時的な接続/API 障害") from e
        raise LLMError(f"LLM API 障害 (HTTP {e.status_code})") from e

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as e:
        raise LLMError("LLM 応答形式が不正: choices/message/content が必要です") from e
    if not isinstance(content, str) or not content.strip():
        raise LLMError("LLM 応答が空、またはテキストではありません")
    return content


def _call_embeddings(
    token: str,
    texts: list[str],
    *,
    model: str | None,
) -> list[list[float]]:
    """明示設定された embeddings API (openai SDK) を呼び出す."""
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    client = OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=token,
        max_retries=0,
    )

    try:
        response = client.embeddings.create(
            model=model,
            input=texts,
        )
    except RateLimitError as e:
        raise _RetriableLLMError("LLM の一時的な接続/API 障害") from e
    except APIConnectionError as e:
        raise _RetriableLLMError("LLM の一時的な接続/API 障害") from e
    except APIStatusError as e:
        if e.status_code >= 500:
            raise _RetriableLLMError("LLM の一時的な接続/API 障害") from e
        raise LLMError(f"LLM API 障害 (HTTP {e.status_code})") from e

    try:
        vectors = [item.embedding for item in response.data]
        if len(vectors) != len(texts) or any(not v or any(type(x) not in (int, float) for x in v) for v in vectors):
            raise ValueError
        return vectors
    except (AttributeError, TypeError, ValueError) as e:
        raise LLMError("embeddings 応答形式が不正です") from e


def _call_anthropic(token, user_content, *, system, model, max_tokens, timeout):
    """Anthropic 直 API。credential/body はエラーログへ出さない。"""
    import requests

    try:
        limit = max_tokens if max_tokens is not None else int(os.environ.get("LLM_MAX_TOKENS", ""))
    except ValueError:
        raise LLMError("anthropic では LLM_MAX_TOKENS に正の整数を設定してください") from None
    if type(limit) is not int or limit <= 0:
        raise LLMError("max_tokens は正の整数である必要があります")
    payload = {
        "model": model,
        "max_tokens": limit,
        "messages": [{"role": "user", "content": user_content}],
    }
    if system:
        payload["system"] = system
    # Opus 5.5: sampling parameters unsupported; thinking stays enabled.
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": token, "anthropic-version": "2023-06-01"},
                json=payload,
                timeout=(min(10, timeout), timeout),
                allow_redirects=False,
            )
        except (requests.ConnectionError, requests.Timeout):
            raise _RetriableLLMError("Anthropic の一時的な接続障害") from None
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetriableLLMError(f"Anthropic API 一時障害 (HTTP {response.status_code})")
        if response.status_code != 200:
            raise LLMError(f"Anthropic API 障害 (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError:
            raise LLMError("Anthropic 応答が JSON ではありません") from None
    if not isinstance(data, dict) or data.get("type") != "message" or data.get("role") != "assistant" or data.get("stop_reason") != "end_turn":
        raise LLMError("Anthropic 応答が不正、拒否、または生成未完了です")
    blocks = data.get("content")
    if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
        raise LLMError("Anthropic content 形式が不正です")
    texts = []
    for block in blocks:
        if block.get("type") == "text":
            if not isinstance(block.get("text"), str):
                raise LLMError("Anthropic text 形式が不正です")
            texts.append(block["text"])
        elif block.get("type") not in {"thinking", "redacted_thinking"}:
            raise LLMError("Anthropic 応答に予期しない content block があります")
    content = "".join(texts)
    if not content.strip():
        raise LLMError("Anthropic のテキスト応答が空です")
    return content


def _claude_auth_mode() -> str:
    """公式 CLI の認証経路を明示し、別 provider の上書きを拒否する。"""
    endpoint = os.environ.get("ANTHROPIC_BASE_URL", "")
    if endpoint and endpoint.rstrip("/") != "https://api.anthropic.com":
        raise LLMError("Claude CLI の接続先が公式 Anthropic ではありません。本人が CLI 設定を確認してください")
    overrides = (
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    )
    if any(os.environ.get(name) for name in overrides):
        raise LLMError("Claude CLI に認証/provider の上書きがあります。サブスク利用は本人による確認が必要です")
    mode = os.environ.get("LLM_CLAUDE_AUTH_MODE", "local-subscription")
    if mode == "local-subscription":
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            raise LLMError("ローカルサブスク認証では OAuth token の環境上書きは使用できません")
    elif mode == "ci-oauth":
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise LLMError("ci-oauth は GitHub Actions 専用です")
        if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            raise LLMError("Actions Secret CLAUDE_CODE_OAUTH_TOKEN を本人が設定してください")
    else:
        raise LLMError("LLM_CLAUDE_AUTH_MODE が不正です")
    return mode


def validate_config(*, check_cli_auth: bool = True) -> None:
    """推論やデータ収集前の構成検証。check_cli_auth=False は CLI インストール前に使う。"""
    provider, _, _, _ = _config()
    if provider == "anthropic":
        try:
            limit = int(os.environ.get("LLM_MAX_TOKENS", ""))
        except ValueError:
            raise LLMError("anthropic では LLM_MAX_TOKENS に正の整数を設定してください") from None
        if limit <= 0:
            raise LLMError("LLM_MAX_TOKENS は正の整数である必要があります")
    if provider == "claude-cli":
        _claude_auth_mode()
        if check_cli_auth:
            _check_claude_subscription()


def _check_claude_subscription() -> None:
    """CLI 自身の状態だけを検証。token の抽出・API key への流用は行わない。"""
    mode = _claude_auth_mode()
    try:
        status = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise LLMError("Claude CLI の認証状態を確認できません") from None
    try:
        auth = json.loads(status.stdout)
    except (ValueError, TypeError):
        raise LLMError("Claude CLI の認証状態応答が不正です") from None
    if (
        status.returncode != 0
        or not isinstance(auth, dict)
        or auth.get("loggedIn") is not True
        or auth.get("authMethod") != ("oauth_token" if mode == "ci-oauth" else "claude.ai")
        or auth.get("apiProvider") != "firstParty"
        or (mode == "local-subscription" and auth.get("subscriptionType") not in {"pro", "max", "team", "enterprise"})
    ):
        if mode == "ci-oauth":
            raise LLMError("Claude CLI の公式 OAuth 認証を確認できません。本人が setup-token と Actions Secret を確認してください")
        raise LLMError("Claude CLI の公式サブスク認証を確認できません。本人が /login と /status を確認してください")


def _call_claude_cli(user_content: str, *, system: str | None, model: str, timeout: float) -> str:
    """確認できた公式サブスク CLI を使用し、API/gateway に切り替えない。"""
    _check_claude_subscription()
    command = [
        "claude", "-p", "--model", model, "--output-format", "json",
        "--tools", "", "--disallowedTools", "mcp__*",
        "--safe-mode", "--no-session-persistence",
    ]
    if system:
        command.extend(["--system-prompt", system])
    try:
        result = subprocess.run(
            command, input=user_content, capture_output=True, text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise LLMError("Claude CLI がインストールされていません") from None
    except subprocess.TimeoutExpired:
        raise LLMError("Claude CLI がタイムアウトしました。自動再送は行いません") from None
    if result.returncode != 0:
        raise LLMError("Claude CLI が失敗しました（認証・設定・利用枠を確認してください）")
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise LLMError("Claude CLI 応答が JSON ではありません") from None
    if (
        not isinstance(response, dict)
        or response.get("type") != "result"
        or response.get("subtype") != "success"
        or response.get("is_error") is not False
        or not isinstance(response.get("result"), str)
        or not response["result"].strip()
    ):
        raise LLMError("Claude CLI 応答が失敗、空、または不正な形式です")
    return response["result"].strip()


def chat(
    user_content: str,
    *,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str | None = None,
    timeout: float = CLAUDE_CLI_TIMEOUT_SECONDS,
) -> str:
    """LLM 呼び出しの単一入口.

    LLM_PROVIDER とモデルを明示設定する。一時的な障害のみ最大3回リトライする。
    """
    if timeout <= 0:
        raise LLMError("timeout は正の値である必要があります")
    provider, base_url, token, model = _config(model)

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if provider == "anthropic":
                return _call_anthropic(token, user_content, system=system, model=model, max_tokens=max_tokens, timeout=timeout)
            if provider == "openai-compatible":
                return _call_api(
                    token,
                    user_content,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model,
                    timeout=timeout,
                )
            return _call_claude_cli(user_content, system=system, model=model, timeout=timeout)
        except _RetriableLLMError as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"LLM 呼び出し失敗 ({attempt}/{MAX_RETRIES}): {e}. "
                    f"{wait}秒後にリトライ"
                )
                time.sleep(wait)

    logger.error(f"LLM 呼び出しが{MAX_RETRIES}回失敗: {last_exc}")
    assert last_exc is not None
    raise last_exc


def embed(
    texts: list[str],
    *,
    model: str | None = None,
) -> list[list[float]] | None:
    """テキスト群を埋め込みベクトル化する（GummySearch / BERTopic 方式の dedup 用）.

    API provider の構成・応答障害は伝播する。Claude CLI は None を返し、
    呼び出し側が TF-IDF にフォールバックする。
    """
    if os.environ.get("LLM_PROVIDER") in {"claude-cli", "anthropic"}:
        return None
    provider, base_url, token, model = _config(model, embedding=True)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _call_embeddings(token, texts, model=model)
        except _RetriableLLMError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)))


def _strip_code_fence(content: str) -> str:
    """LLM レスポンスの Markdown コードフェンスを除去する."""
    if not isinstance(content, str):
        raise LLMError("LLM 応答はテキストである必要があります")
    content = content.strip()
    if content.startswith("```"):
        if "\n" not in content or not content.endswith("```"):
            raise LLMError("LLM 応答のコードフェンスが不正です")
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return content


def parse_json_response(content: str) -> list[dict]:
    """LLM レスポンスから JSON 配列をパースする."""
    content = _strip_code_fence(content)
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end != -1 and (content.find("{") == -1 or start < content.find("{")):
        content = content[start : end + 1]
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        raise LLMError("LLM 応答が有効な JSON ではありません") from e
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise LLMError("LLM 応答には JSON object の配列が必要です")
    return result


def parse_json_object(content: str) -> dict:
    """LLM レスポンスから JSON オブジェクトをパースする."""
    content = _strip_code_fence(content)
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and (content.find("[") == -1 or start < content.find("[")):
        content = content[start : end + 1]
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        raise LLMError("LLM 応答が有効な JSON ではありません") from e
    if not isinstance(result, dict):
        raise LLMError("LLM 応答には JSON object が必要です")
    return result
