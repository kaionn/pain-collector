"""monitor.yml の stalled 検出後アラート送信ロジック（Issue コメント / Discord）.

`src/monitor_stalled.py` が出力する summary JSON（``--output`` で生成したもの）を
受け取り、stalled Issue へのラベル変更・コメント投稿、および Discord Webhook への
通知を行う（旧 `python3 - <<'PY'` heredoc の移植先）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from datetime import datetime, timezone

from . import discord_notify
from .http_utils import create_retry_session

logger = logging.getLogger(__name__)

GH_TIMEOUT_SEC = 30
DEFAULT_WORKFLOWS = ["collect.yml", "weekly.yml", "monthly.yml", "learn.yml"]


def notify_stalled_issues(summary: dict) -> None:
    """stalled 判定された各 Issue のラベルを更新し、コメントを投稿する."""
    for item in summary.get("stalled", []):
        num = item["issue_number"]
        hours = item["hours_since_last_event"]
        last_at = item["last_event_at"]
        comment = (
            f"⚠️ build が {hours:.1f} 時間進捗していないため stalled に遷移したのだ。\n\n"
            f"- 最終イベント: {last_at}\n"
            f"- mvp-factory 側のログを確認してほしいのだ\n"
            f"- 再開する場合は `/approve` を再実行するのだ"
        )
        subprocess.run(
            [
                "gh", "issue", "edit", str(num),
                "--remove-label", "building",
                "--add-label", "stalled",
            ],
            check=False,
            timeout=GH_TIMEOUT_SEC,
        )
        subprocess.run(
            ["gh", "issue", "comment", str(num), "--body", comment],
            check=False,
            timeout=GH_TIMEOUT_SEC,
        )


def notify_discord_stalled(summary: dict) -> bool:
    """stalled サマリーを Discord Webhook に送信する. 送信したら True."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL 未設定のため Discord 通知をスキップします")
        return False

    lines = ["🚨 **stalled 検出**"]
    for item in summary.get("stalled", []):
        title = item["title"][:80]
        hours = item["hours_since_last_event"]
        lines.append(f"- #{item['issue_number']}: {title} ({hours:.1f}h 停滞)")

    payload = {"content": "\n".join(lines)}
    session = create_retry_session()
    resp = session.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    logger.info("Discord 通知を送信しました")
    return True


def _parse_updated_at(raw: str) -> datetime | None:
    """gh の updatedAt（例: 2026-07-11T23:53:18Z）を UTC datetime にパースする."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_failed_runs(
    repo: str, window_minutes: int = 65, workflows: list[str] | None = None
) -> list[str]:
    """直近 window_minutes 以内に失敗した workflow run を検出する.

    weekly.yml が長期間サイレント失敗していた再発防止のための定期チェック。
    workflow ごとの取得失敗はスキップして続行し、例外は投げない。
    """
    if workflows is None:
        workflows = DEFAULT_WORKFLOWS

    now = datetime.now(timezone.utc)
    problems: list[str] = []

    for wf in workflows:
        result = subprocess.run(
            [
                "gh", "run", "list",
                "--repo", repo,
                "--workflow", wf,
                "--limit", "5",
                "--json", "conclusion,updatedAt,url,displayTitle",
            ],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            logger.warning(f"{wf} の run 一覧取得に失敗しました: {result.stderr}")
            continue

        try:
            runs = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.warning(f"{wf} の run 一覧のパースに失敗しました: {e}")
            continue

        for run in runs:
            if run.get("conclusion") != "failure":
                continue
            updated_at = _parse_updated_at(run.get("updatedAt", ""))
            if updated_at is None:
                continue
            age_minutes = (now - updated_at).total_seconds() / 60
            if age_minutes <= window_minutes:
                problems.append(f"{wf} が失敗: {run['displayTitle']} {run['url']}")

    return problems


def _load_summary(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_issues = sub.add_parser(
        "stalled-issues", help="stalled Issue にラベル変更・コメント投稿を行う"
    )
    p_issues.add_argument(
        "--summary", required=True, help="monitor_stalled --output の JSON パス"
    )

    p_discord = sub.add_parser("discord", help="stalled サマリーを Discord に通知する")
    p_discord.add_argument(
        "--summary", required=True, help="monitor_stalled --output の JSON パス"
    )

    env_repo = os.environ.get("GITHUB_REPOSITORY")
    p_failed = sub.add_parser(
        "failed-runs", help="直近失敗した定期 workflow を検出し Discord に通知する"
    )
    p_failed.add_argument(
        "--repo",
        default=env_repo,
        required=env_repo is None,
        help="対象リポジトリ（owner/repo）。省略時は GITHUB_REPOSITORY 環境変数",
    )
    p_failed.add_argument(
        "--window-minutes",
        type=int,
        default=65,
        help="この分数以内に失敗した run を検知対象にする（既定: 65）",
    )
    p_failed.add_argument(
        "--workflows",
        default=",".join(DEFAULT_WORKFLOWS),
        help="カンマ区切りの対象 workflow ファイル名",
    )

    return parser


def _run_failed_runs_command(args: argparse.Namespace) -> None:
    """failed-runs サブコマンドの実行. 監視自体を落とさないよう例外は握りつぶす."""
    workflows = [w.strip() for w in args.workflows.split(",") if w.strip()]
    try:
        problems = check_failed_runs(args.repo, args.window_minutes, workflows)
        logger.info(
            f"failed-runs チェック: {len(workflows)} workflow を確認, "
            f"{len(problems)} 件検出"
        )
        if problems:
            discord_notify.notify_pipeline_alert(problems)
    except Exception as e:
        logger.warning(f"failed-runs チェックに失敗しました: {e}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s: %(message)s",
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "failed-runs":
        _run_failed_runs_command(args)
        return 0

    summary = _load_summary(args.summary)

    if args.command == "stalled-issues":
        notify_stalled_issues(summary)
    elif args.command == "discord":
        notify_discord_stalled(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
