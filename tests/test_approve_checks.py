"""approve_checks.py のユニットテスト.

各関数は approve.yml の $(...) キャプチャで使われるため、
stdout 形式（picked_check / resolve_product_name / deep_dive_path の戻り値）を
特に厳密に検証する。
"""

from __future__ import annotations

import json
import os

from src import approve_checks


def _write_state(path: str, picked: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"picked": picked}, f)


class TestPickedCheck:
    def test_returns_no_state_when_file_missing(self, tmp_path):
        path = os.path.join(tmp_path, "missing.json")
        assert approve_checks.picked_check(path, 1) == "NO_STATE"

    def test_returns_not_picked_when_issue_absent(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 99, "spec": "specs/99.md"}])
        assert approve_checks.picked_check(path, 1) == "NOT_PICKED"

    def test_returns_no_spec_when_spec_missing(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1}])
        assert approve_checks.picked_check(path, 1) == "NO_SPEC"

    def test_returns_spec_path_when_present(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1, "spec": "specs/1.md"}])
        assert approve_checks.picked_check(path, 1) == "specs/1.md"


class TestResolveProductName:
    def test_returns_empty_when_no_state(self, tmp_path):
        path = os.path.join(tmp_path, "missing.json")
        assert approve_checks.resolve_product_name(path, 1) == ""

    def test_returns_empty_when_not_picked(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 99, "product_name": "foo"}])
        assert approve_checks.resolve_product_name(path, 1) == ""

    def test_returns_existing_product_name(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1, "product_name": "cool-app"}])
        assert approve_checks.resolve_product_name(path, 1) == "cool-app"


class TestUpdateState:
    def test_updates_status_and_product_name(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1, "status": "picked"}])

        approve_checks.update_state(path, 1, "building", "cool-app")

        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        item = state["picked"][0]
        assert item["status"] == "building"
        assert item["product_name"] == "cool-app"

    def test_noop_when_state_file_missing(self, tmp_path):
        path = os.path.join(tmp_path, "missing.json")
        approve_checks.update_state(path, 1, "building", "cool-app")
        assert not os.path.exists(path)

    def test_leaves_other_items_untouched(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [
            {"issue_number": 1, "status": "picked"},
            {"issue_number": 2, "status": "building", "product_name": "other"},
        ])

        approve_checks.update_state(path, 1, "building", "cool-app")

        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        assert state["picked"][1] == {"issue_number": 2, "status": "building", "product_name": "other"}


class TestDeepDivePath:
    def test_returns_empty_when_no_state(self, tmp_path):
        path = os.path.join(tmp_path, "missing.json")
        assert approve_checks.deep_dive_path(path, 1) == ""

    def test_returns_empty_when_not_picked(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 99, "deep_dive": "deep_dive/99.md"}])
        assert approve_checks.deep_dive_path(path, 1) == ""

    def test_returns_deep_dive_path_when_present(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1, "deep_dive": "deep_dive/1.md"}])
        assert approve_checks.deep_dive_path(path, 1) == "deep_dive/1.md"


class TestCli:
    def test_picked_check_command_prints_result(self, tmp_path, capsys):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1, "spec": "specs/1.md"}])

        approve_checks.main([
            "picked-check", "--state", path, "--issue-number", "1",
        ])

        assert capsys.readouterr().out.strip() == "specs/1.md"

    def test_update_state_command_writes_file(self, tmp_path):
        path = os.path.join(tmp_path, "state.json")
        _write_state(path, [{"issue_number": 1, "status": "picked"}])

        approve_checks.main([
            "update-state", "--state", path, "--issue-number", "1",
            "--status", "building", "--product-name", "cool-app",
        ])

        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        assert state["picked"][0]["status"] == "building"
