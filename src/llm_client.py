"""LLM 呼び出しの共有クライアント.

バックエンド選択:
- `GITHUB_TOKEN` あり: GitHub Models (openai SDK)
- `GITHUB_TOKEN` なし: Claude Code CLI (ローカル実行)

モデル名のハードコードはこのファイルの `DEFAULT_MODEL` の 1 箇所のみに集約する。
"""

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
DEFAULT_EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "openai/text-embedding-3-small")
GITHUB_MODELS_BASE_URL = "https://models.github.ai/inference"

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2.0
CLAUDE_CLI_TIMEOUT_SECONDS = 180


class _RetriableLLMError(Exception):
    """LLM 呼び出しの一時的な失敗（リトライ対象）."""


def _call_github_models(
    token: str,
    user_content: str,
    *,
    system: str | None,
    temperature: float,
    max_tokens: int | None,
    model: str | None,
) -> str:
    """GitHub Models API (openai SDK) を呼び出す."""
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    client = OpenAI(
        base_url=GITHUB_MODELS_BASE_URL,
        api_key=token,
    )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    kwargs: dict = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        response = client.chat.completions.create(**kwargs)
    except RateLimitError as e:
        raise _RetriableLLMError(str(e)) from e
    except APIConnectionError as e:
        raise _RetriableLLMError(str(e)) from e
    except APIStatusError as e:
        if e.status_code >= 500:
            raise _RetriableLLMError(str(e)) from e
        raise

    return response.choices[0].message.content or ""


def _call_github_embeddings(
    token: str,
    texts: list[str],
    *,
    model: str | None,
) -> list[list[float]]:
    """GitHub Models の embeddings API (openai SDK) を呼び出す."""
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    client = OpenAI(
        base_url=GITHUB_MODELS_BASE_URL,
        api_key=token,
    )

    try:
        response = client.embeddings.create(
            model=model or DEFAULT_EMBED_MODEL,
            input=texts,
        )
    except RateLimitError as e:
        raise _RetriableLLMError(str(e)) from e
    except APIConnectionError as e:
        raise _RetriableLLMError(str(e)) from e
    except APIStatusError as e:
        if e.status_code >= 500:
            raise _RetriableLLMError(str(e)) from e
        raise

    return [item.embedding for item in response.data]


def _call_claude_cli(user_content: str, *, system: str | None) -> str:
    """Claude Code CLI を呼び出す（ローカル実行用フォールバック）."""
    prompt = f"{system}\n\n{user_content}" if system else user_content

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=CLAUDE_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise _RetriableLLMError(str(e)) from e

    if result.returncode != 0:
        raise _RetriableLLMError(result.stderr[:200])

    return result.stdout.strip()


def chat(
    user_content: str,
    *,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """LLM 呼び出しの単一入口.

    `GITHUB_TOKEN` があれば GitHub Models、なければ Claude Code CLI を使う。
    一時的な失敗（レート制限・接続エラー・5xx・subprocess 失敗）は
    指数バックオフで最大 `MAX_RETRIES` 回リトライする。
    """
    token = os.environ.get("GITHUB_TOKEN", "")

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if token:
                return _call_github_models(
                    token,
                    user_content,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model,
                )
            return _call_claude_cli(user_content, system=system)
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

    GitHub Models の embeddings API のみに対応する。`GITHUB_TOKEN` が無い
    （Claude CLI バックエンド）場合、または API 呼び出しが最終的に失敗した場合は
    None を返す。呼び出し側は TF-IDF 等へのフォールバックを行うこと。
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.info("GITHUB_TOKEN 未設定のため embeddings をスキップ")
        return None

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _call_github_embeddings(token, texts, model=model)
        except _RetriableLLMError as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"embeddings 呼び出し失敗 ({attempt}/{MAX_RETRIES}): {e}. "
                    f"{wait}秒後にリトライ"
                )
                time.sleep(wait)
        except Exception as e:
            logger.warning(f"embeddings 呼び出し失敗（リトライ対象外）: {e}")
            return None

    logger.error(f"embeddings 呼び出しが{MAX_RETRIES}回失敗: {last_exc}")
    return None


def _strip_code_fence(content: str) -> str:
    """LLM レスポンスの Markdown コードフェンスを除去する."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return content


def parse_json_response(content: str) -> list[dict]:
    """LLM レスポンスから JSON 配列をパースする."""
    content = _strip_code_fence(content)
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    return json.loads(content)


def parse_json_object(content: str) -> dict:
    """LLM レスポンスから JSON オブジェクトをパースする."""
    content = _strip_code_fence(content)
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    return json.loads(content)
