"""Issue ライフサイクル管理: stale ラベル付与と自動クローズ."""

import json
import logging
import subprocess
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


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
        logger.info(f"#{issue_number} に '{label}' ラベルを追加")
    except Exception as e:
        logger.warning(f"#{issue_number} ラベル追加失敗: {e}")


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
        logger.info(f"#{issue_number} をクローズ ({reason})")
    except Exception as e:
        logger.warning(f"#{issue_number} クローズ失敗: {e}")


_PIPELINE_LABELS: dict[str, str] = {
    "scored": "📊validated",
    "deep_dived": "🔬analyzed",
    "spec_generated": "📋spec-ready",
    "building": "🚧building",
    "launched": "🚀launched",
}


def update_pipeline_status(issue_number: int, stage: str) -> None:
    """Issue のパイプラインステータスラベルを更新する.

    既存のパイプラインラベルを全て削除して、指定ステージのラベルを追加する。

    Args:
        issue_number: 更新対象の Issue 番号。
        stage: パイプラインステージ名。有効な値:
               "scored", "deep_dived", "spec_generated", "building", "launched"
    """
    new_label = _PIPELINE_LABELS.get(stage)
    if new_label is None:
        logger.warning(f"未知のパイプラインステージ: {stage}")
        return

    # 現在のラベルを取得
    try:
        result = subprocess.run(
            [
                "gh", "issue", "view", str(issue_number),
                "--json", "labels",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"#{issue_number} ラベル取得失敗")
            return
        import json as _json
        current_labels = {label["name"] for label in _json.loads(result.stdout).get("labels", [])}
    except Exception as e:
        logger.warning(f"#{issue_number} ラベル取得エラー: {e}")
        return

    # 古いパイプラインラベルを削除
    old_pipeline_labels = set(_PIPELINE_LABELS.values()) - {new_label}
    labels_to_remove = current_labels & old_pipeline_labels
    for label in labels_to_remove:
        try:
            subprocess.run(
                ["gh", "issue", "edit", str(issue_number), "--remove-label", label],
                capture_output=True,
                text=True,
                timeout=30,
            )
            logger.info(f"#{issue_number} から '{label}' ラベルを削除")
        except Exception as e:
            logger.warning(f"#{issue_number} ラベル削除失敗: {e}")

    # 新しいパイプラインラベルを追加
    _add_label(issue_number, new_label)
    logger.info(f"#{issue_number} パイプラインステータスを '{stage}' ({new_label}) に更新")


def cleanup() -> None:
    """Issue のライフサイクル管理を実行する.

    ルール:
    - 👎bad ラベル → 即クローズ
    - 30 日 open + good/interesting ラベルなし → stale ラベル付与
    - 60 日 open + stale → 自動クローズ
    """
    issues = _fetch_open_issues()
    if not issues:
        logger.info("対象 Issue なし")
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

    logger.info(f"完了: stale={stale_count}, close={close_count}, bad={bad_count}")
