"""generate_product_name.py の純粋ロジックのユニットテスト.

LLM 呼び出し（``_call_llm``）は monkeypatch でモックし、抽出・サニタイズ・
妥当性検査・fallback の振る舞いを検証する。
"""

from __future__ import annotations

import pytest

from src import generate_product_name as gpn


class TestExtractKebabToken:
    def test_returns_hyphenated_token_when_mixed_with_explanation(self):
        raw = "Here's the name:\nsubscription-cancel-tracker\nHope it helps!"
        assert gpn._extract_kebab_token(raw) == "subscription-cancel-tracker"

    def test_strips_code_fence(self):
        raw = "```\nfood-delivery-refund\n```"
        assert gpn._extract_kebab_token(raw) == "food-delivery-refund"

    def test_picks_longest_hyphenated_when_multiple_candidates(self):
        raw = "app or subscription-cancel-tracker"
        assert gpn._extract_kebab_token(raw) == "subscription-cancel-tracker"

    def test_falls_back_to_single_word_when_no_hyphenated(self):
        raw = "tracker"
        assert gpn._extract_kebab_token(raw) == "tracker"

    def test_empty_input_returns_empty_string(self):
        assert gpn._extract_kebab_token("") == ""

    def test_japanese_only_returns_empty_string(self):
        assert gpn._extract_kebab_token("お金の管理アプリ") == ""


class TestSanitize:
    def test_lowercases_and_trims(self):
        assert gpn._sanitize("Subscription-Cancel-Tracker") == "subscription-cancel-tracker"

    def test_replaces_invalid_chars_with_hyphen(self):
        assert gpn._sanitize("foo_bar baz") == "foo-bar-baz"

    def test_collapses_consecutive_hyphens(self):
        assert gpn._sanitize("foo--bar---baz") == "foo-bar-baz"

    def test_strips_leading_trailing_hyphens(self):
        assert gpn._sanitize("---foo-bar---") == "foo-bar"

    def test_truncates_to_max_length(self):
        long = "a" * 50
        assert len(gpn._sanitize(long)) == gpn.MAX_LENGTH

    def test_trailing_hyphen_after_truncation_is_stripped(self):
        name = "abcdefghijklmnopqrstuvwxyz12-xyz"
        result = gpn._sanitize(name)
        assert not result.endswith("-")
        assert len(result) <= gpn.MAX_LENGTH


class TestIsValid:
    def test_valid_kebab_case(self):
        assert gpn._is_valid("subscription-cancel-tracker")

    def test_too_short_rejected(self):
        assert not gpn._is_valid("ab")

    def test_banned_name_rejected(self):
        assert not gpn._is_valid("mvp")
        assert not gpn._is_valid("app")
        assert not gpn._is_valid("test")

    def test_numeric_only_rejected(self):
        assert not gpn._is_valid("104")
        assert not gpn._is_valid("12-34")


class TestGenerate:
    def test_uses_llm_output_when_valid(self, monkeypatch):
        monkeypatch.setattr(gpn, "_call_llm", lambda title, timeout=30: "subscription-cancel-tracker")
        assert gpn.generate("解約管理", issue_number=42) == "subscription-cancel-tracker"

    def test_fallback_when_llm_returns_none(self, monkeypatch):
        monkeypatch.setattr(gpn, "_call_llm", lambda title, timeout=30: None)
        assert gpn.generate("anything", issue_number=104) == "mvp-104"

    def test_fallback_when_llm_returns_banned_word(self, monkeypatch):
        monkeypatch.setattr(gpn, "_call_llm", lambda title, timeout=30: "app")
        assert gpn.generate("anything", issue_number=97) == "mvp-97"

    def test_fallback_when_llm_returns_only_japanese(self, monkeypatch):
        monkeypatch.setattr(gpn, "_call_llm", lambda title, timeout=30: "アプリ")
        assert gpn.generate("anything", issue_number=50) == "mvp-50"

    def test_extracts_from_llm_explanation(self, monkeypatch):
        monkeypatch.setattr(
            gpn,
            "_call_llm",
            lambda title, timeout=30: "Sure, here's a good name:\nfood-delivery-refund",
        )
        assert gpn.generate("Uber Eats 返金", issue_number=104) == "food-delivery-refund"


class TestCallLlmFallbackCli:
    """GITHUB_TOKEN が無い環境で claude CLI にフォールバックする経路のテスト."""

    @pytest.fixture(autouse=True)
    def clear_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def test_returncode_non_zero_returns_none(self, monkeypatch):
        class FakeResult:
            returncode = 1
            stdout = ""
            stderr = "auth error"

        monkeypatch.setattr(gpn.subprocess, "run", lambda *a, **kw: FakeResult())
        assert gpn._call_llm("title") is None

    def test_empty_stdout_returns_none(self, monkeypatch):
        class FakeResult:
            returncode = 0
            stdout = "   \n"
            stderr = ""

        monkeypatch.setattr(gpn.subprocess, "run", lambda *a, **kw: FakeResult())
        assert gpn._call_llm("title") is None

    def test_timeout_returns_none(self, monkeypatch):
        def raise_timeout(*args, **kwargs):
            raise gpn.subprocess.TimeoutExpired(cmd="claude", timeout=30)

        monkeypatch.setattr(gpn.subprocess, "run", raise_timeout)
        assert gpn._call_llm("title") is None

    def test_cli_not_found_returns_none(self, monkeypatch):
        def raise_fnf(*args, **kwargs):
            raise FileNotFoundError("claude")

        monkeypatch.setattr(gpn.subprocess, "run", raise_fnf)
        assert gpn._call_llm("title") is None

    def test_success_returns_stdout_stripped(self, monkeypatch):
        class FakeResult:
            returncode = 0
            stdout = "  food-delivery-refund  \n"
            stderr = ""

        monkeypatch.setattr(gpn.subprocess, "run", lambda *a, **kw: FakeResult())
        assert gpn._call_llm("title") == "food-delivery-refund"


class TestCallLlmGitHubModels:
    """GITHUB_TOKEN がある環境で GitHub Models Inference API を使う経路のテスト."""

    @pytest.fixture(autouse=True)
    def set_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    def test_success_returns_content(self, monkeypatch):
        class FakeMessage:
            content = "  subscription-cancel-tracker  "

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        class FakeCompletions:
            def create(self, **kwargs):
                return FakeResponse()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            def __init__(self, **kwargs):
                self.chat = FakeChat()

        import sys
        import types

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeClient
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        assert gpn._call_llm("解約管理") == "subscription-cancel-tracker"

    def test_empty_content_returns_none(self, monkeypatch):
        class FakeMessage:
            content = ""

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        class FakeCompletions:
            def create(self, **kwargs):
                return FakeResponse()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            def __init__(self, **kwargs):
                self.chat = FakeChat()

        import sys
        import types

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeClient
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        assert gpn._call_llm("title") is None

    def test_api_error_returns_none(self, monkeypatch):
        class FakeCompletions:
            def create(self, **kwargs):
                raise RuntimeError("API down")

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            def __init__(self, **kwargs):
                self.chat = FakeChat()

        import sys
        import types

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeClient
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        assert gpn._call_llm("title") is None


class TestCli:
    def test_main_prints_generated_name(self, monkeypatch, capsys):
        monkeypatch.setattr(gpn, "_call_llm", lambda title, timeout=30: "subscription-cancel-tracker")
        rc = gpn.main(["--title", "Uber Eats 解約", "--issue-number", "104"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "subscription-cancel-tracker"

    def test_main_prints_fallback_on_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(gpn, "_call_llm", lambda title, timeout=30: None)
        rc = gpn.main(["--title", "something", "--issue-number", "104"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "mvp-104"
