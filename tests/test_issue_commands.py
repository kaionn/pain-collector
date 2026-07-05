"""issue_commands.py の /probe ハンドラのユニットテスト.

gh CLI 呼び出し（gh_client 経由）と pipeline_state.json への書き込みはモックし、
signal-lab へ渡す payload の構築ロジックのみを検証する。
"""

from __future__ import annotations

import base64
import json
import os
import re

import pytest

from src import issue_commands


ISSUE_BODY = """\
## ペイン

家計簿を毎日つけるのが面倒くさい。

## 詳細

| 項目 | 値 |
|---|---|
| 深刻度 | ★★★☆☆ (3/5) |

## アイデア

レシート撮影だけで自動仕訳する家計簿アプリ。手入力を一切なくす。

## 既存ソリューション

Zaim や MoneyForward はあるが手動修正が多い。

## 市場シグナル

🟡 市場あり・満足度低い（チャンス）

- [Zaim](https://apps.apple.com/jp/app/id123456) ⭐3.8 (1200件) 無料
- [MoneyForward](https://apps.apple.com/jp/app/id654321) ⭐3.5 (900件) ¥480/月

## ソース

[家計簿アプリの不満まとめ](https://example.com/thread/1)

---
📅 2026-07-05
<!-- pain-data:{"pain":"家計簿を毎日つけるのが面倒くさい。","app_idea":"レシート撮影だけで自動仕訳する家計簿アプリ。手入力を一切なくす。","existing_solutions":"Zaim や MoneyForward はあるが手動修正が多い。","severity":3,"willingness_to_pay":"medium","category":"生活"} -->
"""


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    state_path = tmp_path / "pipeline_state.json"
    dirty_path = tmp_path / ".state_dirty"
    monkeypatch.setattr(issue_commands, "PIPELINE_STATE_PATH", str(state_path))
    monkeypatch.setattr(issue_commands, "STATE_DIRTY_FLAG", str(dirty_path))
    return tmp_path


@pytest.fixture
def stub_gh(monkeypatch):
    """gh_client の外部呼び出しを記録するだけのスタブに差し替える."""
    calls = {"comments": [], "labels": [], "workflow": None}

    monkeypatch.setattr(
        issue_commands.gh_client,
        "fetch_issue",
        lambda issue_number: {
            "number": issue_number,
            "title": "[生活] 家計簿を毎日つけるのが面倒くさい",
            "body": ISSUE_BODY,
        },
    )
    monkeypatch.setattr(
        issue_commands.gh_client,
        "post_comment",
        lambda issue_number, body: calls["comments"].append((issue_number, body)) or True,
    )
    monkeypatch.setattr(
        issue_commands.gh_client,
        "add_labels",
        lambda issue_number, labels: calls["labels"].append((issue_number, labels)) or True,
    )

    def _fake_trigger_workflow(repo, workflow, inputs, *, token=None):
        calls["workflow"] = {
            "repo": repo,
            "workflow": workflow,
            "inputs": inputs,
            "token": token,
        }
        return True

    monkeypatch.setattr(issue_commands.gh_client, "trigger_workflow", _fake_trigger_workflow)
    monkeypatch.setattr(
        issue_commands, "generate_product_name",
        type("_M", (), {"generate": staticmethod(lambda title, issue_number: "kakeibo-auto")}),
    )
    monkeypatch.setattr(issue_commands, "_notify_discord", lambda message: None)
    return calls


class TestBuildProbePayload:
    def test_includes_all_receiver_contract_fields(self):
        payload = issue_commands._build_probe_payload(
            42, "[生活] 家計簿を毎日つけるのが面倒くさい", ISSUE_BODY, "kakeibo-auto",
        )

        expected_keys = {
            "slug", "title", "tagline", "pain", "idea",
            "source_url", "source_title", "market_apps",
            "severity", "monetization",
        }
        assert expected_keys.issubset(payload.keys())

    def test_slug_is_kebab_case_ascii(self):
        payload = issue_commands._build_probe_payload(
            42, "タイトル", ISSUE_BODY, "kakeibo-auto",
        )
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", payload["slug"])

    def test_extracts_source_url_and_title(self):
        payload = issue_commands._build_probe_payload(
            42, "タイトル", ISSUE_BODY, "kakeibo-auto",
        )
        assert payload["source_url"] == "https://example.com/thread/1"
        assert payload["source_title"] == "家計簿アプリの不満まとめ"

    def test_source_url_is_null_when_no_source_section(self):
        body_without_source = ISSUE_BODY.split("## ソース")[0]
        payload = issue_commands._build_probe_payload(
            42, "タイトル", body_without_source, "kakeibo-auto",
        )
        assert payload["source_url"] is None
        assert payload["source_title"] is None

    def test_extracts_market_apps(self):
        payload = issue_commands._build_probe_payload(
            42, "タイトル", ISSUE_BODY, "kakeibo-auto",
        )
        assert payload["market_apps"] == [
            {
                "name": "Zaim",
                "url": "https://apps.apple.com/jp/app/id123456",
                "rating": "3.8",
                "reviews": 1200,
                "price": "無料",
            },
            {
                "name": "MoneyForward",
                "url": "https://apps.apple.com/jp/app/id654321",
                "rating": "3.5",
                "reviews": 900,
                "price": "¥480/月",
            },
        ]

    def test_market_apps_empty_when_no_section(self):
        body_without_market = (
            "## ペイン\n\n家計簿が面倒\n\n"
            "## ソース\n\n[出典](https://example.com/thread/2)\n"
        )
        payload = issue_commands._build_probe_payload(
            42, "タイトル", body_without_market, "kakeibo-auto",
        )
        assert payload["market_apps"] == []

    def test_severity_and_monetization_from_pain_data(self):
        payload = issue_commands._build_probe_payload(
            42, "タイトル", ISSUE_BODY, "kakeibo-auto",
        )
        assert payload["severity"] == 3
        assert payload["monetization"] == "medium"

    def test_falls_back_when_pain_data_missing(self):
        """pain-data メタデータが無い古い Issue でも例外にならずフォールバックする."""
        legacy_body = "## ペイン\n\n古いペイン\n"
        payload = issue_commands._build_probe_payload(
            1, "古いタイトル", legacy_body, "legacy-app",
        )
        assert payload["pain"] == "古いタイトル"
        assert payload["severity"] == 3
        assert payload["monetization"] == "medium"
        assert payload["source_url"] is None
        assert payload["market_apps"] == []


class TestPayloadBase64Roundtrip:
    def test_decoded_payload_matches_original_json(self):
        payload = issue_commands._build_probe_payload(
            42, "タイトル", ISSUE_BODY, "kakeibo-auto",
        )
        encoded = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")

        decoded = json.loads(base64.b64decode(encoded).decode("utf-8"))
        assert decoded == payload


class TestCmdProbe:
    def test_dispatches_to_signal_lab_with_expected_inputs(self, isolated_state, stub_gh):
        rc = issue_commands.cmd_probe(42)

        assert rc == 0
        workflow_call = stub_gh["workflow"]
        assert workflow_call["repo"] == "kaionn/signal-lab"
        assert workflow_call["workflow"] == "probe-request.yml"
        assert workflow_call["inputs"]["issue_number"] == "42"
        assert workflow_call["inputs"]["source_repo"] == "kaionn/pain-collector"

        decoded = json.loads(base64.b64decode(workflow_call["inputs"]["payload"]).decode("utf-8"))
        assert decoded["slug"] == "kakeibo-auto"

    def test_auto_picks_when_not_picked(self, isolated_state, stub_gh):
        issue_commands.cmd_probe(42)

        state = issue_commands._load_state()
        entry = issue_commands._find_entry(state, 42)
        assert entry is not None
        assert entry["status"] == "probing"
        assert entry["product_name"] == "kakeibo-auto"

    def test_reuses_existing_product_name(self, isolated_state, stub_gh):
        issue_commands._save_state({
            "picked": [{
                "issue_number": 42,
                "product_name": "already-named",
                "status": "spec-ready",
                "events": [],
            }],
        })

        issue_commands.cmd_probe(42)

        workflow_call = stub_gh["workflow"]
        decoded = json.loads(base64.b64decode(workflow_call["inputs"]["payload"]).decode("utf-8"))
        assert decoded["slug"] == "already-named"

    def test_uses_pat_token_for_dispatch(self, isolated_state, stub_gh, monkeypatch):
        monkeypatch.setenv("PAT_TOKEN", "fake-pat-token")

        issue_commands.cmd_probe(42)

        assert stub_gh["workflow"]["token"] == "fake-pat-token"

    def test_posts_failure_comment_when_dispatch_fails(self, isolated_state, monkeypatch, stub_gh):
        monkeypatch.setattr(
            issue_commands.gh_client, "trigger_workflow",
            lambda *args, **kwargs: False,
        )

        rc = issue_commands.cmd_probe(42)

        assert rc == 1
        assert any("失敗" in body for _, body in stub_gh["comments"])
        state = issue_commands._load_state()
        assert issue_commands._find_entry(state, 42) is None or \
            issue_commands._find_entry(state, 42).get("status") != "probing"
