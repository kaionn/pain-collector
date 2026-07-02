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

from .http_utils import create_retry_session

logger = logging.getLogger(__name__)

GH_TIMEOUT_SEC = 30


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

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s: %(message)s",
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    summary = _load_summary(args.summary)

    if args.command == "stalled-issues":
        notify_stalled_issues(summary)
    elif args.command == "discord":
        notify_discord_stalled(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
