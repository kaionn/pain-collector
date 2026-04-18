"""monitor_stalled.py のテスト."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.monitor_stalled import (
    StalledItem,
    detect_stalled,
    mark_stalled,
)


NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


def _state(items: list[dict]) -> dict:
    return {"picked": items}


def test_detect_stalled_returns_building_over_threshold():
    state = _state([
        {
            "issue_number": 97,
            "title": "old",
            "status": "building",
            "events": [{"action": "spec", "at": "2026-04-09T07:37:00+00:00"}],
        }
    ])
    result = detect_stalled(state, now=NOW, threshold_hours=24)
    assert len(result) == 1
    assert result[0].issue_number == 97
    assert result[0].hours_since_last_event > 200  # 9 日経過


def test_detect_stalled_skips_recent_building():
    recent = (NOW - timedelta(hours=12)).isoformat()
    state = _state([
        {
            "issue_number": 1,
            "title": "recent",
            "status": "building",
            "events": [{"action": "spec", "at": recent}],
        }
    ])
    assert detect_stalled(state, now=NOW, threshold_hours=24) == []


def test_detect_stalled_skips_non_building():
    old = (NOW - timedelta(hours=48)).isoformat()
    state = _state([
        {
            "issue_number": 1,
            "title": "spec-ready",
            "status": "spec-ready",
            "events": [{"action": "spec", "at": old}],
        },
        {
            "issue_number": 2,
            "title": "picked",
            "status": "picked",
            "events": [{"action": "pick", "at": old}],
        },
    ])
    assert detect_stalled(state, now=NOW, threshold_hours=24) == []


def test_detect_stalled_falls_back_to_picked_at():
    """events が空の場合は picked_at を使う."""
    old = (NOW - timedelta(hours=48)).isoformat()
    state = _state([
        {
            "issue_number": 1,
            "title": "no events",
            "status": "building",
            "picked_at": old,
            "events": [],
        }
    ])
    result = detect_stalled(state, now=NOW, threshold_hours=24)
    assert len(result) == 1


def test_detect_stalled_uses_latest_event_only():
    """events の最後のイベント時刻が閾値内なら stalled ではない."""
    old = (NOW - timedelta(hours=48)).isoformat()
    recent = (NOW - timedelta(hours=1)).isoformat()
    state = _state([
        {
            "issue_number": 1,
            "title": "active",
            "status": "building",
            "events": [
                {"action": "pick", "at": old},
                {"action": "build_progress", "at": recent},
            ],
        }
    ])
    assert detect_stalled(state, now=NOW, threshold_hours=24) == []


def test_detect_stalled_handles_invalid_timestamp_gracefully():
    state = _state([
        {
            "issue_number": 1,
            "title": "bad ts",
            "status": "building",
            "events": [{"action": "spec", "at": "not-a-date"}],
        }
    ])
    assert detect_stalled(state, now=NOW, threshold_hours=24) == []


def test_detect_stalled_handles_zulu_timestamp():
    state = _state([
        {
            "issue_number": 1,
            "title": "zulu",
            "status": "building",
            "events": [{"action": "spec", "at": "2026-04-09T07:37:00Z"}],
        }
    ])
    result = detect_stalled(state, now=NOW, threshold_hours=24)
    assert len(result) == 1


def test_mark_stalled_updates_status_and_appends_event():
    state = _state([
        {
            "issue_number": 97,
            "status": "building",
            "events": [{"action": "spec", "at": "2026-04-09T07:37:00+00:00"}],
        },
        {
            "issue_number": 104,
            "status": "spec-ready",
            "events": [],
        },
    ])
    new_state = mark_stalled(state, {97}, now=NOW)

    target = next(i for i in new_state["picked"] if i["issue_number"] == 97)
    other = next(i for i in new_state["picked"] if i["issue_number"] == 104)

    assert target["status"] == "stalled"
    assert target["events"][-1]["action"] == "stalled"
    assert target["events"][-1]["at"] == NOW.isoformat()
    # 対象外は変更されない
    assert other["status"] == "spec-ready"
    assert other["events"] == []


def test_mark_stalled_does_not_mutate_input():
    state = _state([
        {
            "issue_number": 97,
            "status": "building",
            "events": [{"action": "spec", "at": "2026-04-09T07:37:00+00:00"}],
        }
    ])
    original = dict(state["picked"][0])
    mark_stalled(state, {97}, now=NOW)
    assert state["picked"][0] == original


def test_mark_stalled_skips_already_non_building():
    """status が building 以外なら無視（race condition 対策）."""
    state = _state([
        {
            "issue_number": 97,
            "status": "spec-ready",
            "events": [{"action": "spec", "at": "2026-04-09T07:37:00+00:00"}],
        }
    ])
    new_state = mark_stalled(state, {97}, now=NOW)
    assert new_state["picked"][0]["status"] == "spec-ready"
    assert len(new_state["picked"][0]["events"]) == 1


def test_mark_stalled_with_empty_set_returns_unchanged():
    state = _state([{"issue_number": 1, "status": "building", "events": []}])
    assert mark_stalled(state, set(), now=NOW) is state
