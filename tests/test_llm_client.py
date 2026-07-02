"""llm_client.py のユニットテスト（ネットワークには一切出ない）."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.llm_client import (
    _RetriableLLMError,
    chat,
    embed,
    parse_json_object,
    parse_json_response,
)


class TestBackendSelection:
    """GITHUB_TOKEN の有無によるバックエンド選択のテスト."""

    def test_uses_github_models_when_token_present(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with (
            patch(
                "src.llm_client._call_github_models", return_value="from github models"
            ) as mock_gh,
            patch("src.llm_client._call_claude_cli") as mock_claude,
        ):
            result = chat("こんにちは")

        assert result == "from github models"
        mock_gh.assert_called_once()
        mock_claude.assert_not_called()

    def test_uses_claude_cli_when_no_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with (
            patch("src.llm_client._call_github_models") as mock_gh,
            patch(
                "src.llm_client._call_claude_cli", return_value="from claude cli"
            ) as mock_claude,
        ):
            result = chat("こんにちは")

        assert result == "from claude cli"
        mock_claude.assert_called_once()
        mock_gh.assert_not_called()

    def test_passes_params_to_github_models(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with patch("src.llm_client._call_github_models", return_value="ok") as mock_gh:
            chat(
                "本文",
                system="システム指示",
                temperature=0.5,
                max_tokens=100,
                model="openai/gpt-4o",
            )

        kwargs = mock_gh.call_args.kwargs
        assert kwargs["system"] == "システム指示"
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 100
        assert kwargs["model"] == "openai/gpt-4o"


class TestRetry:
    """指数バックオフによるリトライ動作のテスト."""

    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        side_effects = [
            _RetriableLLMError("一時的エラー"),
            _RetriableLLMError("一時的エラー"),
            "成功",
        ]

        def fake_call(*args, **kwargs):
            effect = side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect

        with (
            patch("src.llm_client._call_github_models", side_effect=fake_call),
            patch("src.llm_client.time.sleep") as mock_sleep,
        ):
            result = chat("リトライ対象")

        assert result == "成功"
        assert mock_sleep.call_count == 2

    def test_raises_after_max_retries(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with (
            patch(
                "src.llm_client._call_github_models",
                side_effect=_RetriableLLMError("常に失敗"),
            ),
            patch("src.llm_client.time.sleep") as mock_sleep,
        ):
            with pytest.raises(_RetriableLLMError):
                chat("失敗し続ける")

        assert mock_sleep.call_count == 2  # MAX_RETRIES(3) - 1

    def test_non_retriable_exception_propagates_immediately(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with (
            patch(
                "src.llm_client._call_github_models",
                side_effect=ValueError("致命的エラー"),
            ),
            patch("src.llm_client.time.sleep") as mock_sleep,
        ):
            with pytest.raises(ValueError):
                chat("非リトライ対象")

        mock_sleep.assert_not_called()

    def test_claude_cli_nonzero_exit_is_retriable(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        fake_result = MagicMock(returncode=1, stdout="", stderr="claude cli エラー")
        with (
            patch("src.llm_client.subprocess.run", return_value=fake_result),
            patch("src.llm_client.time.sleep") as mock_sleep,
        ):
            with pytest.raises(_RetriableLLMError):
                chat("失敗する CLI 呼び出し")

        assert mock_sleep.call_count == 2

    def test_claude_cli_timeout_is_retriable(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with (
            patch(
                "src.llm_client.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=180),
            ),
            patch("src.llm_client.time.sleep") as mock_sleep,
        ):
            with pytest.raises(_RetriableLLMError):
                chat("タイムアウトする CLI 呼び出し")

        assert mock_sleep.call_count == 2

    def test_claude_cli_success(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        fake_result = MagicMock(returncode=0, stdout="  成功しました  \n", stderr="")
        with patch("src.llm_client.subprocess.run", return_value=fake_result):
            result = chat("CLI 呼び出し", system="システム指示")

        assert result == "成功しました"


class TestEmbed:
    """embed() のテスト（ネットワークには一切出ない）."""

    def test_no_token_returns_none(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("src.llm_client._call_github_embeddings") as mock_embed:
            result = embed(["テキスト"])

        assert result is None
        mock_embed.assert_not_called()

    def test_success_returns_vectors(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with patch(
            "src.llm_client._call_github_embeddings",
            return_value=[[0.1, 0.2], [0.3, 0.4]],
        ) as mock_embed:
            result = embed(["テキスト1", "テキスト2"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_embed.assert_called_once()

    def test_retriable_failure_returns_none_after_max_retries(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with (
            patch(
                "src.llm_client._call_github_embeddings",
                side_effect=_RetriableLLMError("常に失敗"),
            ),
            patch("src.llm_client.time.sleep") as mock_sleep,
        ):
            result = embed(["テキスト"])

        assert result is None
        assert mock_sleep.call_count == 2

    def test_non_retriable_exception_returns_none(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with patch(
            "src.llm_client._call_github_embeddings",
            side_effect=ValueError("致命的エラー"),
        ):
            result = embed(["テキスト"])

        assert result is None

    def test_passes_model_override(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        with patch(
            "src.llm_client._call_github_embeddings", return_value=[[0.1]]
        ) as mock_embed:
            embed(["テキスト"], model="openai/text-embedding-3-large")

        kwargs = mock_embed.call_args.kwargs
        assert kwargs["model"] == "openai/text-embedding-3-large"


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
