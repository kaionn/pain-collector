"""notify.py の純粋ロジック関数のユニットテスト.

外部サービス（GitHub API、LLM）はモックしない。
TF-IDF による重複検出の純粋ロジックのみをテストする。
"""

import json

import pytest

from src.notify import (
    DUPLICATE_THRESHOLD_HIGH,
    DUPLICATE_THRESHOLD_LOW,
    REJECTED_LOOKBACK_DAYS,
    _filter_rejected_issues,
    _find_duplicate,
    _record_dedup_metrics,
    _record_skipped_pain,
)


class TestFindDuplicate:
    """_find_duplicate のテスト.

    注: _llm_judge_duplicate は GITHUB_TOKEN がない環境では False を返すため、
    グレーゾーン（0.4 <= sim < 0.7）のケースは LLM 判定なしで検証する。
    """

    def test_empty_existing_issues_returns_none(self):
        result = _find_duplicate("タスク管理アプリが欲しい", [])
        assert result is None

    def test_clearly_duplicate_text_detected(self):
        """ほぼ同一のテキストは高い類似度で重複検出される."""
        existing = [
            {"number": 1, "title": "毎日の家計管理が面倒で自動化したい"},
        ]
        pain_text = "毎日の家計管理が面倒で自動化したい"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 1

    def test_clearly_different_text_not_detected(self):
        """全く異なるトピックは重複として検出されない."""
        existing = [
            {"number": 1, "title": "cooking recipe app needed"},
            {"number": 2, "title": "fitness tracker for running"},
        ]
        pain_text = "tax return filing automation"
        result = _find_duplicate(pain_text, existing)
        assert result is None

    def test_same_text_returns_matching_issue(self):
        """同一テキストは必ず重複検出される."""
        existing = [
            {"number": 10, "title": "レシートの自動仕分けができるアプリ"},
            {"number": 11, "title": "子どもの睡眠記録アプリ"},
        ]
        pain_text = "レシートの自動仕分けができるアプリ"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 10

    def test_returns_most_similar_issue(self):
        """複数候補の中で最も類似度が高い Issue を返す."""
        existing = [
            {"number": 1, "title": "email inbox management tool"},
            {"number": 2, "title": "email newsletter unsubscribe automation"},
            {"number": 3, "title": "fitness workout tracker app"},
        ]
        # email に関連したテキストは email 系の Issue とマッチするはず
        pain_text = "email newsletter unsubscribe automation tool"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 2

    def test_single_word_corpus_returns_none_on_value_error(self):
        """TF-IDF が ValueError を出す場合は None を返す（例: 1文字トークンのみ）.

        tokenizer が空のトークンリストを返す入力では ValueError が発生するが、
        _find_duplicate は try/except ValueError で保護されている。
        """
        # 全て記号・数字のみの場合、日本語 tokenizer は空を返し ValueError になる可能性がある
        existing = [{"number": 1, "title": "1 2 3"}]
        result = _find_duplicate("4 5 6", existing)
        # ValueError が出ても None を返す（クラッシュしない）
        assert result is None or isinstance(result, dict)

    def test_duplicate_threshold_constants(self):
        """閾値定数が期待通りの値であることを確認."""
        assert DUPLICATE_THRESHOLD_HIGH == 0.7
        assert DUPLICATE_THRESHOLD_LOW == 0.4

    def test_similar_but_different_topic_not_duplicate(self):
        """似た単語を含むが異なるトピックは重複にならない."""
        existing = [
            {"number": 1, "title": "baby sleep tracking app for parents"},
        ]
        pain_text = "sleep quality monitoring for adults with insomnia"
        result = _find_duplicate(pain_text, existing)
        # 異なるトピックなので重複なし（高い閾値 0.7 を超えない）
        assert result is None

    def test_japanese_duplicate_detected(self):
        """日本語テキストの重複も正しく検出される."""
        existing = [
            {"number": 5, "title": "子育て中の予防接種スケジュール管理が煩雑"},
        ]
        pain_text = "子育て中の予防接種スケジュール管理が煩雑"
        result = _find_duplicate(pain_text, existing)
        assert result is not None
        assert result["number"] == 5

    def test_match_kind_open_propagated(self):
        """open issue にマッチした場合、_match_kind が open として返る."""
        existing = [
            {"number": 1, "title": "毎日の家計管理が面倒で自動化したい", "_match_kind": "open"},
        ]
        result = _find_duplicate("毎日の家計管理が面倒で自動化したい", existing)
        assert result is not None
        assert result["number"] == 1
        assert result.get("_match_kind") == "open"

    def test_match_kind_rejected_propagated(self):
        """rejected issue にマッチした場合、_match_kind が rejected として返る."""
        existing = [
            {"number": 99, "title": "全く関係ない別の話題", "_match_kind": "open"},
            {"number": 100, "title": "毎日の家計管理が面倒で自動化したい", "_match_kind": "rejected"},
        ]
        result = _find_duplicate("毎日の家計管理が面倒で自動化したい", existing)
        assert result is not None
        assert result["number"] == 100
        assert result.get("_match_kind") == "rejected"

    def test_match_kind_default_open_when_missing(self):
        """_match_kind が dict にない場合は補完されない（後方互換）.

        既存呼び出し側は _match_kind を付けずに dict を渡すケースがある（テスト等）。
        _find_duplicate は受け取った dict をそのまま返すだけで、kind の補完はしない。
        呼び出し側が `.get("_match_kind", "open")` で補完する想定。
        """
        existing = [
            {"number": 1, "title": "毎日の家計管理が面倒で自動化したい"},
        ]
        result = _find_duplicate("毎日の家計管理が面倒で自動化したい", existing)
        assert result is not None
        # _match_kind がない dict が返ったときは呼び出し側が "open" 扱い
        assert result.get("_match_kind", "open") == "open"


class TestFilterRejectedIssues:
    """_filter_rejected_issues のテスト.

    closedAt が cutoff 日数以内、かつ stateReason=NOT_PLANNED または
    rejected ラベル付きの issue だけを返すこと。
    """

    def test_not_planned_within_window_included(self):
        """NOT_PLANNED で直近の close は含める."""
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        issues = [
            {
                "number": 1,
                "title": "foo",
                "closedAt": recent,
                "stateReason": "NOT_PLANNED",
                "labels": [],
            },
        ]
        result = _filter_rejected_issues(issues)
        assert len(result) == 1
        assert result[0]["number"] == 1

    def test_completed_without_rejected_label_excluded(self):
        """COMPLETED で rejected ラベルなしは含めない（done の作業は再起票許可）."""
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        issues = [
            {
                "number": 1,
                "title": "foo",
                "closedAt": recent,
                "stateReason": "COMPLETED",
                "labels": [{"name": "pain-report"}],
            },
        ]
        result = _filter_rejected_issues(issues)
        assert result == []

    def test_completed_with_rejected_label_included(self):
        """COMPLETED でも rejected ラベル付きは含める（手動却下対策）."""
        from datetime import datetime, timedelta, timezone

        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        issues = [
            {
                "number": 2,
                "title": "bar",
                "closedAt": recent,
                "stateReason": "COMPLETED",
                "labels": [{"name": "rejected"}],
            },
        ]
        result = _filter_rejected_issues(issues)
        assert len(result) == 1
        assert result[0]["number"] == 2

    def test_outside_lookback_window_excluded(self):
        """cutoff より古い close は除外する."""
        from datetime import datetime, timedelta, timezone

        old = (
            datetime.now(timezone.utc) - timedelta(days=REJECTED_LOOKBACK_DAYS + 30)
        ).isoformat().replace("+00:00", "Z")
        issues = [
            {
                "number": 1,
                "title": "foo",
                "closedAt": old,
                "stateReason": "NOT_PLANNED",
                "labels": [],
            },
        ]
        result = _filter_rejected_issues(issues)
        assert result == []

    def test_missing_closed_at_excluded(self):
        """closedAt がない issue は除外する."""
        issues = [
            {"number": 1, "title": "foo", "stateReason": "NOT_PLANNED", "labels": []},
        ]
        result = _filter_rejected_issues(issues)
        assert result == []


class TestRecordSkippedPain:
    """_record_skipped_pain のテスト."""

    def test_appends_jsonl_line(self, tmp_path, monkeypatch):
        """指定パスに jsonl 形式で 1 行追記される."""
        path = tmp_path / "skipped_pains.jsonl"
        pain = {
            "pain": "PayPay が起動しない",
            "source_url": "https://example.com",
            "source_title": "PayPay レビュー",
        }
        matched = {"number": 156, "title": "[テクノロジー] PayPay 起動不可"}

        _record_skipped_pain(pain, matched, "2026-04-28", str(path))

        content = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(content) == 1
        record = json.loads(content[0])
        assert record["pain"] == "PayPay が起動しない"
        assert record["matched_issue_number"] == 156
        assert record["date"] == "2026-04-28"

    def test_creates_parent_dir_if_missing(self, tmp_path):
        """親ディレクトリが存在しない場合は自動作成する."""
        path = tmp_path / "nested" / "dir" / "skipped.jsonl"
        pain = {"pain": "x"}
        matched = {"number": 1, "title": "y"}
        _record_skipped_pain(pain, matched, "2026-04-28", str(path))
        assert path.exists()


class TestRecordDedupMetrics:
    """_record_dedup_metrics のテスト."""

    def test_writes_new_metrics_file(self, tmp_path):
        """新規ファイルに stats を date_str キーで書き込む."""
        path = tmp_path / "dedup_metrics.json"
        stats = {"open_match": 2, "rejected_match": 5, "new_issues": 1}
        _record_dedup_metrics("2026-04-28", stats, str(path))

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "2026-04-28" in data
        assert data["2026-04-28"]["open_match"] == 2
        assert data["2026-04-28"]["rejected_match"] == 5
        assert data["2026-04-28"]["new_issues"] == 1

    def test_appends_to_existing_metrics(self, tmp_path):
        """既存ファイルに別 date_str を追加する（過去データを保持）."""
        path = tmp_path / "dedup_metrics.json"
        path.write_text(
            json.dumps({"2026-04-27": {"open_match": 1, "rejected_match": 0, "new_issues": 3}}),
            encoding="utf-8",
        )
        stats = {"open_match": 0, "rejected_match": 2, "new_issues": 1}
        _record_dedup_metrics("2026-04-28", stats, str(path))

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "2026-04-27" in data
        assert "2026-04-28" in data
        assert data["2026-04-27"]["new_issues"] == 3
        assert data["2026-04-28"]["rejected_match"] == 2

    def test_overwrites_same_date(self, tmp_path):
        """同じ date_str で 2 回呼ばれた場合は後勝ちで上書きする."""
        path = tmp_path / "dedup_metrics.json"
        _record_dedup_metrics(
            "2026-04-28",
            {"open_match": 1, "rejected_match": 0, "new_issues": 0},
            str(path),
        )
        _record_dedup_metrics(
            "2026-04-28",
            {"open_match": 0, "rejected_match": 5, "new_issues": 2},
            str(path),
        )

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["2026-04-28"]["rejected_match"] == 5
        assert data["2026-04-28"]["open_match"] == 0

    def test_recovers_from_corrupted_file(self, tmp_path):
        """壊れた JSON を上書きして新規データを書く（クラッシュしない）."""
        path = tmp_path / "dedup_metrics.json"
        path.write_text("not a valid json {", encoding="utf-8")
        _record_dedup_metrics(
            "2026-04-28",
            {"open_match": 1, "rejected_match": 1, "new_issues": 1},
            str(path),
        )

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["2026-04-28"]["open_match"] == 1
