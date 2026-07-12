"""pain_gate.py の actionability ゲートのユニットテスト."""

import json

from src import pain_gate


class TestRuleBasedAudience:
    """rule_based_audience のテスト."""

    def test_cli_dev_tool_is_developer(self):
        pain = {"product_type": "CLI・開発ツール"}
        assert pain_gate.rule_based_audience(pain) == "developer"

    def test_api_saas_is_developer(self):
        pain = {"product_type": "API・SaaS"}
        assert pain_gate.rule_based_audience(pain) == "developer"

    def test_mobile_app_is_consumer(self):
        pain = {"product_type": "モバイルアプリ"}
        assert pain_gate.rule_based_audience(pain) == "consumer"

    def test_missing_product_type_is_consumer(self):
        assert pain_gate.rule_based_audience({}) == "consumer"


class TestClassify:
    """classify のテスト（llm_client.chat をモック）."""

    def test_reject_verdict_propagates_reason(self, monkeypatch):
        response = json.dumps(
            {
                "actionable": False,
                "reject_reason": "特定アプリの不具合クレームのため対象外",
                "audience": "consumer",
            },
            ensure_ascii=False,
        )
        monkeypatch.setattr(pain_gate.llm_client, "chat", lambda *a, **k: response)

        pain = {"pain": "PayPayがログインできない", "product_type": "モバイルアプリ"}
        verdict = pain_gate.classify(pain)

        assert verdict["actionable"] is False
        assert verdict["reject_reason"] == "特定アプリの不具合クレームのため対象外"
        assert verdict["audience"] == "consumer"

    def test_pass_verdict_propagates_audience(self, monkeypatch):
        response = json.dumps(
            {"actionable": True, "reject_reason": None, "audience": "developer"},
            ensure_ascii=False,
        )
        monkeypatch.setattr(pain_gate.llm_client, "chat", lambda *a, **k: response)

        pain = {"pain": "毎回のリリースノート作成が面倒", "product_type": "CLI・開発ツール"}
        verdict = pain_gate.classify(pain)

        assert verdict["actionable"] is True
        assert verdict["reject_reason"] is None
        assert verdict["audience"] == "developer"

    def test_chat_exception_fails_open(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise RuntimeError("LLM 呼び出し失敗")

        monkeypatch.setattr(pain_gate.llm_client, "chat", _raise)

        pain = {"pain": "テスト", "product_type": "API・SaaS"}
        verdict = pain_gate.classify(pain)

        assert verdict["actionable"] is True
        assert verdict["reject_reason"] is None
        assert verdict["audience"] == pain_gate.rule_based_audience(pain)

    def test_malformed_json_fails_open(self, monkeypatch):
        monkeypatch.setattr(pain_gate.llm_client, "chat", lambda *a, **k: "not json")

        pain = {"pain": "テスト", "product_type": "モバイルアプリ"}
        verdict = pain_gate.classify(pain)

        assert verdict["actionable"] is True
        assert verdict["audience"] == "consumer"

    def test_invalid_audience_falls_back_to_rule_based(self, monkeypatch):
        """LLM が想定外の audience 値を返した場合は rule_based_audience にフォールバック."""
        response = json.dumps({"actionable": True, "audience": "unknown"}, ensure_ascii=False)
        monkeypatch.setattr(pain_gate.llm_client, "chat", lambda *a, **k: response)

        pain = {"pain": "テスト", "product_type": "CLI・開発ツール"}
        verdict = pain_gate.classify(pain)

        assert verdict["audience"] == "developer"
