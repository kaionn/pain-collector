"""state_sync.py のユニットテスト.

`gh` 呼び出しは subprocess.run をモックし、ファイル I/O のみ実ファイルシステムで検証する。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from src import state_sync


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestFetch:
    def test_writes_decoded_content_when_remote_exists(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        remote_json = json.dumps({"picked": [{"issue_number": 1}]})
        encoded = base64.b64encode(remote_json.encode("utf-8")).decode("ascii")

        with patch.object(state_sync, "_run_gh", return_value=_completed(0, encoded)) as mock_run:
            state_sync.fetch("owner/repo", "data/pipeline_state.json", local_path)

        with open(local_path, encoding="utf-8") as f:
            assert json.load(f) == {"picked": [{"issue_number": 1}]}
        mock_run.assert_called_once_with(
            ["api", "repos/owner/repo/contents/data/pipeline_state.json", "--jq", ".content"]
        )

    def test_writes_default_state_when_remote_missing(self, tmp_path):
        local_path = os.path.join(tmp_path, "nested", "pipeline_state.json")

        with patch.object(state_sync, "_run_gh", return_value=_completed(1, "", "not found")):
            state_sync.fetch("owner/repo", "data/pipeline_state.json", local_path)

        with open(local_path, encoding="utf-8") as f:
            assert json.load(f) == {"picked": []}

    def test_creates_parent_directory(self, tmp_path):
        local_path = os.path.join(tmp_path, "deep", "nested", "pipeline_state.json")
        with patch.object(state_sync, "_run_gh", return_value=_completed(1)):
            state_sync.fetch("owner/repo", "data/pipeline_state.json", local_path)
        assert os.path.exists(local_path)


class TestPush:
    def test_skips_when_no_sha_and_create_if_missing_false(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write('{"picked": []}')

        with patch.object(state_sync, "_run_gh", return_value=_completed(0, "")) as mock_run:
            state_sync.push("owner/repo", "data/pipeline_state.json", local_path, "msg")

        # SHA 取得の 1 回だけ呼ばれ、PUT は呼ばれない
        mock_run.assert_called_once()

    def test_creates_when_no_sha_and_create_if_missing_true(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write('{"picked": []}')

        with patch.object(state_sync, "_run_gh", return_value=_completed(0, "")) as mock_run:
            state_sync.push(
                "owner/repo", "data/pipeline_state.json", local_path, "msg",
                create_if_missing=True,
            )

        assert mock_run.call_count == 2
        put_call_args = mock_run.call_args_list[1][0][0]
        assert "-X" in put_call_args and "PUT" in put_call_args
        assert not any(arg.startswith("sha=") for arg in put_call_args)

    def test_updates_with_sha_when_remote_exists(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write('{"picked": []}')

        with patch.object(state_sync, "_run_gh", return_value=_completed(0, "abc123")) as mock_run:
            state_sync.push("owner/repo", "data/pipeline_state.json", local_path, "msg")

        assert mock_run.call_count == 2
        put_call_args = mock_run.call_args_list[1][0][0]
        assert "sha=abc123" in put_call_args

    def test_raises_when_put_fails(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write('{"picked": []}')

        responses = [_completed(0, "abc123"), _completed(1, "", "boom")]
        with patch.object(state_sync, "_run_gh", side_effect=responses):
            with pytest.raises(RuntimeError, match="boom"):
                state_sync.push("owner/repo", "data/pipeline_state.json", local_path, "msg")


class TestCli:
    def test_fetch_command_dispatches(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        with patch.object(state_sync, "fetch") as mock_fetch:
            state_sync.main([
                "fetch", "--repo", "owner/repo",
                "--remote-path", "data/pipeline_state.json",
                "--local-path", local_path,
            ])
        mock_fetch.assert_called_once_with("owner/repo", "data/pipeline_state.json", local_path)

    def test_push_command_dispatches_with_create_if_missing(self, tmp_path):
        local_path = os.path.join(tmp_path, "pipeline_state.json")
        with patch.object(state_sync, "push") as mock_push:
            state_sync.main([
                "push", "--repo", "owner/repo",
                "--remote-path", "data/pipeline_state.json",
                "--local-path", local_path,
                "--message", "hello",
                "--create-if-missing",
            ])
        mock_push.assert_called_once_with(
            "owner/repo", "data/pipeline_state.json", local_path, "hello",
            create_if_missing=True,
        )
