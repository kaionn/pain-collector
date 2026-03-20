"""Issue ライフサイクル管理: stale ラベル付与と自動クローズ."""

import json
import subprocess
from datetime import datetime, timezone, timedelta


STALE_DAYS = 30
CLOSE_DAYS = 60
KEEP_LABELS = {"👍good", "💡interesting"}


def _fetch_open_issues() -> list[dict]:
    """open 状態の pain-report Issue を取得する."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "open",
                "--json", "number,title,labels,createdAt",
                "--limit", "200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return []


def _get_label_names(issue: dict) -> set[str]:
    """Issue のラベル名の集合を返す."""
    return {label["name"] for label in issue.get("labels", [])}


def _add_label(issue_number: int, label: str) -> None:
    """Issue にラベルを追加する."""
    try:
        subprocess.run(
            ["gh", "issue", "edit", str(issue_number), "--add-label", label],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"[Lifecycle] #{issue_number} に '{label}' ラベルを追加")
    except Exception as e:
        print(f"[Lifecycle] #{issue_number} ラベル追加失敗: {e}")


def _close_issue(issue_number: int, reason: str) -> None:
    """Issue をクローズする."""
    try:
        subprocess.run(
            [
                "gh", "issue", "close", str(issue_number),
                "--comment", f"🤖 自動クローズ: {reason}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"[Lifecycle] #{issue_number} をクローズ ({reason})")
    except Exception as e:
        print(f"[Lifecycle] #{issue_number} クローズ失敗: {e}")


def cleanup() -> None:
    """Issue のライフサイクル管理を実行する.

    ルール:
    - 👎bad ラベル → 即クローズ
    - 30 日 open + good/interesting ラベルなし → stale ラベル付与
    - 60 日 open + stale → 自動クローズ
    """
    issues = _fetch_open_issues()
    if not issues:
        print("[Lifecycle] 対象 Issue なし")
        return

    now = datetime.now(timezone.utc)
    stale_count = 0
    close_count = 0
    bad_count = 0

    for issue in issues:
        number = issue["number"]
        labels = _get_label_names(issue)

        # 👎bad → 即クローズ
        if "👎bad" in labels:
            _close_issue(number, "👎bad ラベルのため")
            bad_count += 1
            continue

        # good/interesting ラベルがあれば保護
        if labels & KEEP_LABELS:
            continue

        created = datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))
        age_days = (now - created).days

        if "stale" in labels and age_days >= CLOSE_DAYS:
            _close_issue(number, f"{age_days} 日経過 + stale")
            close_count += 1
        elif age_days >= STALE_DAYS and "stale" not in labels:
            _add_label(number, "stale")
            stale_count += 1

    print(f"[Lifecycle] 完了: stale={stale_count}, close={close_count}, bad={bad_count}")
