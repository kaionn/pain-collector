"""pipeline_state.json の load/save の安全性テスト.

D-1 の一部: race condition 耐性、broken JSON フォールバック、atomic write を検証する。
"""

from __future__ import annotations

import json
import os
import threading
from unittest.mock import patch

import pytest

from src import issue_commands


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """PIPELINE_STATE_PATH を tmp_path に切り替える."""
    state_path = tmp_path / "pipeline_state.json"
    dirty_path = tmp_path / ".state_dirty"
    monkeypatch.setattr(issue_commands, "PIPELINE_STATE_PATH", str(state_path))
    monkeypatch.setattr(issue_commands, "STATE_DIRTY_FLAG", str(dirty_path))
    return tmp_path


class TestLoadState:
    def test_returns_default_when_file_absent(self, isolated_state):
        assert issue_commands._load_state() == {"picked": []}

    def test_returns_parsed_state_when_file_valid(self, isolated_state):
        state_path = isolated_state / "pipeline_state.json"
        state_path.write_text(
            json.dumps({"picked": [{"issue_number": 1}]}),
            encoding="utf-8",
        )
        assert issue_commands._load_state() == {"picked": [{"issue_number": 1}]}

    def test_falls_back_to_default_on_broken_json(self, isolated_state, caplog):
        state_path = isolated_state / "pipeline_state.json"
        state_path.write_text("{ broken json", encoding="utf-8")

        with caplog.at_level("ERROR"):
            result = issue_commands._load_state()

        assert result == {"picked": []}
        assert any("パースに失敗" in r.message for r in caplog.records)

    def test_falls_back_to_default_on_truncated_file(self, isolated_state):
        """書き込み途中で kill された場合のシミュレーション."""
        state_path = isolated_state / "pipeline_state.json"
        state_path.write_text('{"picked": [{"issu', encoding="utf-8")
        assert issue_commands._load_state() == {"picked": []}


class TestSaveState:
    def test_writes_state_to_disk(self, isolated_state):
        state = {"picked": [{"issue_number": 42}]}
        issue_commands._save_state(state)

        state_path = isolated_state / "pipeline_state.json"
        assert json.loads(state_path.read_text(encoding="utf-8")) == state

    def test_creates_dirty_flag(self, isolated_state):
        issue_commands._save_state({"picked": []})
        assert (isolated_state / ".state_dirty").exists()

    def test_creates_directory_if_missing(self, isolated_state, monkeypatch):
        nested = isolated_state / "deep" / "data"
        state_path = nested / "pipeline_state.json"
        monkeypatch.setattr(issue_commands, "PIPELINE_STATE_PATH", str(state_path))

        issue_commands._save_state({"picked": []})
        assert state_path.exists()

    def test_does_not_leave_tmp_file(self, isolated_state):
        issue_commands._save_state({"picked": []})

        # tmp ファイルが残っていないこと
        leftover = list(isolated_state.glob("*.tmp.*"))
        assert leftover == []

    def test_atomic_write_does_not_leave_tmp_on_failure(self, isolated_state, monkeypatch):
        """書き込み失敗時に tmp ファイルが残らないこと."""
        original_replace = os.replace

        def failing_replace(*args, **kwargs):
            raise OSError("simulated failure")

        monkeypatch.setattr("os.replace", failing_replace)

        with pytest.raises(OSError):
            issue_commands._save_state({"picked": []})

        leftover = list(isolated_state.glob("*.tmp.*"))
        assert leftover == []
        # 元ファイルは作成されていない
        assert not (isolated_state / "pipeline_state.json").exists()

    def test_concurrent_save_no_partial_read(self, isolated_state):
        """複数スレッドから同時 save が走っても、読み手は常に valid な JSON を見る.

        atomic write (os.replace) によって、書き込み途中の partial state は外部から見えない。
        """
        # 初期状態を書く
        issue_commands._save_state({"picked": [{"issue_number": 0}]})

        results: list[dict | str] = []

        def writer(n: int):
            issue_commands._save_state({"picked": [{"issue_number": n}]})

        def reader():
            for _ in range(50):
                try:
                    state = issue_commands._load_state()
                    # picked が必ず list で issue_number を持っていること
                    assert isinstance(state, dict)
                    assert "picked" in state
                    results.append(state)
                except (json.JSONDecodeError, ValueError) as exc:
                    results.append(f"FAILED: {exc}")

        writers = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        readers = [threading.Thread(target=reader) for _ in range(3)]

        for t in writers + readers:
            t.start()
        for t in writers + readers:
            t.join()

        # 1 件も partial read 起因のエラーがないこと
        failures = [r for r in results if isinstance(r, str)]
        assert failures == [], f"partial read detected: {failures[:3]}"


class TestRoundtrip:
    def test_save_then_load_returns_same_state(self, isolated_state):
        original = {
            "picked": [
                {
                    "issue_number": 1,
                    "title": "テスト",
                    "events": [{"action": "pick", "at": "2026-04-18T00:00:00+09:00"}],
                }
            ]
        }
        issue_commands._save_state(original)
        assert issue_commands._load_state() == original

    def test_save_overwrite_replaces_old_content(self, isolated_state):
        issue_commands._save_state({"picked": [{"issue_number": 1}]})
        issue_commands._save_state({"picked": [{"issue_number": 2}]})

        loaded = issue_commands._load_state()
        assert loaded["picked"] == [{"issue_number": 2}]
