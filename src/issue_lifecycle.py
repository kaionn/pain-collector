"""Issue ライフサイクル管理: stale ラベル付与と自動クローズ."""

import json
import logging
import subprocess
from datetime import datetime, timezone, timedelta

from src import notify, pain_gate

logger = logging.getLogger(__name__)


STALE_DAYS = 30
CLOSE_DAYS = 60
KEEP_LABELS = {"👍good", "💡interesting"}

PICKED_LABEL = "📌picked"
SCOPE_OUT_LABEL = "🚫scope-out"


def _fetch_open_issues() -> list[dict]:
    """open 状態の pain-report Issue を取得する."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "open",
                "--json", "number,title,body,labels,createdAt",
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


def _comment_issue(issue_number: int, body: str) -> None:
    """Issue にコメントを投稿する."""
    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(f"#{issue_number} にコメント投稿")
    except Exception as e:
        logger.warning(f"#{issue_number} コメント投稿失敗: {e}")


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


def _restore_pain_data(issue: dict) -> dict:
    """Issue から pain データを復元する.

    本文の pain-data メタデータを優先し、無ければタイトルから簡易復元する。
    """
    pain = notify.extract_pain_data_from_body(issue.get("body"))
    if pain is not None:
        return pain
    return {
        "pain": issue.get("title", ""),
        "category": "",
        "product_type": "",
        "target_user": "",
        "app_idea": "",
    }


def _reject_issue(issue_number: int, reason: str) -> None:
    """reject 判定の Issue に理由コメント・scope-out ラベル付与・クローズを行う."""
    _comment_issue(issue_number, f"🚫 actionability 再評価により close: {reason}")
    _add_label(issue_number, SCOPE_OUT_LABEL)
    _close_issue(issue_number, reason)


def _log_regate_summary(checked: int, rejected: list[dict], audience_labeled: int) -> None:
    """regate の結果サマリーをログ出力する."""
    logger.info(f"regate 完了: checked={checked}, rejected={len(rejected)}, audience_labeled={audience_labeled}")
    for item in rejected:
        title_trunc = item["title"][:50]
        logger.info(f"#{item['number']} {title_trunc} → {item['reason']}")


def regate(apply: bool = False) -> dict:
    """open の pain-report Issue を pain_gate で再評価する.

    既存 Issue プールは actionability ゲート導入前のものが混在するため、
    一括で再判定し reject 対象を close・audience ラベル未付与分を補完する。

    Args:
        apply: True なら実際に GitHub へ書き込む（コメント・ラベル・クローズ）。
               False（既定）は判定のみ行い書き込みは一切しない（dry-run）。

    Returns:
        {"checked": int, "rejected": [{"number": int, "title": str, "reason": str}],
         "audience_labeled": int}
    """
    issues = _fetch_open_issues()
    checked = 0
    rejected: list[dict] = []
    audience_labeled = 0

    for issue in issues:
        labels = _get_label_names(issue)
        if PICKED_LABEL in labels or SCOPE_OUT_LABEL in labels:
            continue

        number = issue["number"]
        title = issue.get("title", "")
        checked += 1

        pain = _restore_pain_data(issue)
        verdict = pain_gate.classify(pain)

        if not verdict["actionable"]:
            reason = verdict.get("reject_reason") or "理由不明"
            rejected.append({"number": number, "title": title, "reason": reason})
            if apply:
                _reject_issue(number, reason)
            continue

        audience_label = notify.AUDIENCE_LABELS.get(verdict.get("audience"))
        if audience_label and audience_label not in labels and apply:
            _add_label(number, audience_label)
            audience_labeled += 1

    _log_regate_summary(checked, rejected, audience_labeled)
    return {"checked": checked, "rejected": rejected, "audience_labeled": audience_labeled}
