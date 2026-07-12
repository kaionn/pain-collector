"""issue_lifecycle.py の regate（既存 Issue の actionability 再評価）のユニットテスト."""

import json

from src import issue_lifecycle
from src.notify import _build_pain_data_comment


class _FakeResult:
    """gh コマンド実行結果のフェイク."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_run_factory(issues: list[dict], calls: list[list[str]]):
    """gh issue list には issues を返し、それ以外の呼び出しは記録するだけの fake subprocess.run."""

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return _FakeResult(stdout=json.dumps(issues))
        return _FakeResult()

    return fake_run


def _issue_with_pain_data(number: int, title: str, pain: dict, labels: list[str] | None = None) -> dict:
    """pain-data メタデータ入りの Issue 辞書を生成する."""
    body = f"## ペイン\n{pain['pain']}\n{_build_pain_data_comment(pain)}"
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": label} for label in (labels or [])],
    }


class TestRegateReject:
    """actionable=False 判定の Issue の扱い."""

    def test_dry_run_collects_rejected_without_writes(self, monkeypatch):
        pain = {
            "pain": "PayPayがログインできない",
            "category": "その他",
            "product_type": "モバイルアプリ",
            "target_user": "",
            "app_idea": "",
        }
        issues = [_issue_with_pain_data(1, "PayPayがログインできない", pain)]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: {
                "actionable": False,
                "reject_reason": "特定アプリの不具合クレームのため対象外",
                "audience": "consumer",
            },
        )

        result = issue_lifecycle.regate(apply=False)

        assert result["checked"] == 1
        assert result["rejected"] == [
            {
                "number": 1,
                "title": "PayPayがログインできない",
                "reason": "特定アプリの不具合クレームのため対象外",
            }
        ]
        assert result["audience_labeled"] == 0

        write_calls = [c for c in calls if c[:3] != ["gh", "issue", "list"]]
        assert write_calls == []

    def test_apply_true_comments_labels_and_closes(self, monkeypatch):
        pain = {
            "pain": "地方公務員の採用難",
            "category": "仕事・キャリア",
            "product_type": "その他",
            "target_user": "",
            "app_idea": "",
        }
        issues = [_issue_with_pain_data(2, "地方公務員の採用難", pain)]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: {
                "actionable": False,
                "reject_reason": "社会問題・政策レベルの課題のため対象外",
                "audience": "consumer",
            },
        )

        result = issue_lifecycle.regate(apply=True)

        assert result["rejected"][0]["number"] == 2

        comment_calls = [c for c in calls if c[:3] == ["gh", "issue", "comment"]]
        label_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
        close_calls = [c for c in calls if c[:3] == ["gh", "issue", "close"]]

        assert len(comment_calls) == 1
        assert any("🚫 actionability 再評価により close" in part for part in comment_calls[0])
        assert len(label_calls) == 1
        assert "🚫scope-out" in label_calls[0]
        assert len(close_calls) == 1


class TestRegateSkip:
    """スキップ対象ラベルの扱い."""

    def test_picked_label_skips_issue(self, monkeypatch):
        issues = [
            {
                "number": 3,
                "title": "選定済みの Issue",
                "body": "",
                "labels": [{"name": "📌picked"}],
            }
        ]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        classified: list[dict] = []
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: classified.append(p) or {"actionable": True, "reject_reason": None, "audience": "consumer"},
        )

        result = issue_lifecycle.regate(apply=False)

        assert result["checked"] == 0
        assert result["rejected"] == []
        assert classified == []

    def test_scope_out_label_skips_issue(self, monkeypatch):
        issues = [
            {
                "number": 4,
                "title": "既に scope-out 済みの Issue",
                "body": "",
                "labels": [{"name": "🚫scope-out"}],
            }
        ]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        classified: list[dict] = []
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: classified.append(p) or {"actionable": True, "reject_reason": None, "audience": "consumer"},
        )

        result = issue_lifecycle.regate(apply=False)

        assert result["checked"] == 0
        assert classified == []


class TestRegatePainDataRestoration:
    """pain-data メタデータの有無による復元経路のテスト."""

    def test_missing_pain_data_falls_back_to_title(self, monkeypatch):
        issues = [
            {
                "number": 5,
                "title": "古い形式の Issue タイトル",
                "body": "## ペイン\n本文のみ（メタデータなし）",
                "labels": [],
            }
        ]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))

        captured: dict = {}

        def fake_classify(pain):
            captured["pain"] = pain
            return {"actionable": True, "reject_reason": None, "audience": "consumer"}

        monkeypatch.setattr(issue_lifecycle.pain_gate, "classify", fake_classify)

        issue_lifecycle.regate(apply=False)

        assert captured["pain"]["pain"] == "古い形式の Issue タイトル"
        assert captured["pain"]["category"] == ""


class TestRegateAudienceLabeling:
    """actionable=True 時の audience ラベル補完."""

    def test_apply_true_adds_missing_audience_label(self, monkeypatch):
        pain = {
            "pain": "毎回のリリースノート作成が面倒",
            "category": "テクノロジー",
            "product_type": "CLI・開発ツール",
            "target_user": "",
            "app_idea": "",
        }
        issues = [_issue_with_pain_data(6, "毎回のリリースノート作成が面倒", pain)]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: {"actionable": True, "reject_reason": None, "audience": "developer"},
        )

        result = issue_lifecycle.regate(apply=True)

        assert result["audience_labeled"] == 1
        label_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
        assert len(label_calls) == 1
        assert "👨‍💻dev" in label_calls[0]

    def test_dry_run_does_not_add_or_count_audience_label(self, monkeypatch):
        pain = {
            "pain": "毎回のリリースノート作成が面倒",
            "category": "テクノロジー",
            "product_type": "CLI・開発ツール",
            "target_user": "",
            "app_idea": "",
        }
        issues = [_issue_with_pain_data(7, "毎回のリリースノート作成が面倒", pain)]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: {"actionable": True, "reject_reason": None, "audience": "developer"},
        )

        result = issue_lifecycle.regate(apply=False)

        assert result["audience_labeled"] == 0
        write_calls = [c for c in calls if c[:3] != ["gh", "issue", "list"]]
        assert write_calls == []

    def test_existing_audience_label_is_not_duplicated(self, monkeypatch):
        pain = {
            "pain": "毎回のリリースノート作成が面倒",
            "category": "テクノロジー",
            "product_type": "CLI・開発ツール",
            "target_user": "",
            "app_idea": "",
        }
        issues = [
            _issue_with_pain_data(8, "毎回のリリースノート作成が面倒", pain, labels=["👨‍💻dev"])
        ]
        calls: list[list[str]] = []
        monkeypatch.setattr(issue_lifecycle.subprocess, "run", _fake_run_factory(issues, calls))
        monkeypatch.setattr(
            issue_lifecycle.pain_gate,
            "classify",
            lambda p: {"actionable": True, "reject_reason": None, "audience": "developer"},
        )

        result = issue_lifecycle.regate(apply=True)

        assert result["audience_labeled"] == 0
        write_calls = [c for c in calls if c[:3] != ["gh", "issue", "list"]]
        assert write_calls == []
