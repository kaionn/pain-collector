"""停滞 (`building` のまま放置されている) Issue を `stalled` に遷移させる.

mvp-factory build が失敗してコールバックが届かない、あるいは
dispatch そのものが失敗したケースで pipeline_state.json が
`building` のまま固まるのを防ぐ。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_HOURS = 24
TARGET_STATUS = "building"
NEW_STATUS = "stalled"


@dataclass(frozen=True)
class StalledItem:
    issue_number: int
    title: str
    last_event_at: str
    hours_since_last_event: float


def _parse_iso8601(value: str) -> datetime:
    """ISO 8601 文字列を tz-aware な datetime に変換する."""
    cleaned = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _last_event_at(item: dict[str, Any]) -> str | None:
    """picked エントリの最新イベント時刻を返す.

    events[] が空または存在しない場合は picked_at にフォールバック。
    """
    events = item.get("events") or []
    for event in reversed(events):
        if isinstance(event, dict) and event.get("at"):
            return event["at"]
    return item.get("picked_at")


def detect_stalled(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    threshold_hours: float = DEFAULT_THRESHOLD_HOURS,
) -> list[StalledItem]:
    """state から stalled 候補を抽出する."""
    current = now or datetime.now(timezone.utc)
    stalled: list[StalledItem] = []

    for item in state.get("picked", []):
        if item.get("status") != TARGET_STATUS:
            continue

        last_at_str = _last_event_at(item)
        if not last_at_str:
            continue

        try:
            last_at = _parse_iso8601(last_at_str)
        except ValueError:
            logger.warning(
                "イベント時刻のパースに失敗: issue=%s value=%s",
                item.get("issue_number"),
                last_at_str,
            )
            continue

        delta_hours = (current - last_at).total_seconds() / 3600
        if delta_hours >= threshold_hours:
            stalled.append(
                StalledItem(
                    issue_number=int(item["issue_number"]),
                    title=item.get("title", ""),
                    last_event_at=last_at_str,
                    hours_since_last_event=delta_hours,
                )
            )

    return stalled


def mark_stalled(
    state: dict[str, Any],
    issue_numbers: set[int],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """対象 Issue の status を stalled に更新し、event を追記する.

    state を破壊的に変更するのではなく、コピーを返す。
    """
    if not issue_numbers:
        return state

    current_iso = (now or datetime.now(timezone.utc)).isoformat()
    new_state = json.loads(json.dumps(state))  # deep copy
    for item in new_state.get("picked", []):
        if int(item.get("issue_number", 0)) not in issue_numbers:
            continue
        if item.get("status") != TARGET_STATUS:
            continue
        item["status"] = NEW_STATUS
        events = item.setdefault("events", [])
        events.append(
            {
                "action": "stalled",
                "at": current_iso,
                "payload": {"reason": "building が閾値時間を超過"},
            }
        )
    return new_state


def _load_state(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_state(path: str, state: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    """CLI エントリポイント.

    使い方:
        python -m src.monitor_stalled \\
            --state data/pipeline_state.json \\
            --threshold-hours 24 \\
            --output stalled.json
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        default="data/pipeline_state.json",
        help="pipeline_state.json のパス",
    )
    parser.add_argument(
        "--threshold-hours",
        type=float,
        default=float(os.environ.get("STALLED_THRESHOLD_HOURS", DEFAULT_THRESHOLD_HOURS)),
        help="停滞と判定する閾値時間 (デフォルト 24)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="検出された stalled 一覧を JSON で出力するパス (省略時は stdout)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="state を更新する (このフラグなしでは検出のみ)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    state = _load_state(args.state)
    stalled_items = detect_stalled(state, threshold_hours=args.threshold_hours)

    summary = {
        "threshold_hours": args.threshold_hours,
        "stalled_count": len(stalled_items),
        "stalled": [
            {
                "issue_number": item.issue_number,
                "title": item.title,
                "last_event_at": item.last_event_at,
                "hours_since_last_event": round(item.hours_since_last_event, 2),
            }
            for item in stalled_items
        ],
    }

    output_text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
            f.write("\n")
    else:
        print(output_text)

    if args.apply and stalled_items:
        new_state = mark_stalled(
            state,
            issue_numbers={item.issue_number for item in stalled_items},
        )
        _save_state(args.state, new_state)
        logger.info("state を更新しました (stalled=%d 件)", len(stalled_items))

    if stalled_items:
        # GitHub Actions 用: stalled が見つかった場合は exit 0 のままだが、stdout JSON で件数を返す
        sys.stderr.write(f"⚠️ {len(stalled_items)} 件の stalled Issue を検出しました\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
