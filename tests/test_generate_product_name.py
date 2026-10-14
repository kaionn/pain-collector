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


class TestCallLlmExplicitProvider:
    def test_uses_shared_client(self, monkeypatch):
        from unittest.mock import Mock
        call = Mock(return_value="  subscription-cancel-tracker  ")
        monkeypatch.setattr(gpn.llm_client, "chat", call)
        assert gpn._call_llm("synthetic", timeout=15) == "subscription-cancel-tracker"
        call.assert_called_once()
        assert call.call_args.kwargs["timeout"] == 15

    def test_provider_failure_propagates(self, monkeypatch):
        from unittest.mock import Mock
        from src.llm_client import LLMError
        monkeypatch.setattr(gpn.llm_client, "chat", Mock(side_effect=LLMError("configuration")))
        with pytest.raises(LLMError):
            gpn._call_llm("synthetic")


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
