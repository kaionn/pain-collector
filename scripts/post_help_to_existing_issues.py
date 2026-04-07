"""既存の open Issue 本文末尾にコマンド一覧の折りたたみブロックを一括追加するワンショットスクリプト.

使い方:
    python scripts/post_help_to_existing_issues.py [--dry-run]

仕様:
    - pain-report ラベル付き open Issue を全件取得
    - 既にマーカー付きヘルプブロックがある Issue はスキップ（冪等）
    - --dry-run で更新せず一覧表示のみ
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from src import gh_client


def list_pain_issues() -> list[dict]:
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--label", "pain-report",
            "--state", "open",
            "--limit", "200",
            "--json", "number,title,body",
        ],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0, help="API レート制限避けの待機秒")
    args = parser.parse_args()

    issues = list_pain_issues()
    print(f"対象 Issue: {len(issues)} 件")

    updated = 0
    skipped = 0
    for issue in issues:
        num = issue["number"]
        title = issue["title"][:60]
        body = issue.get("body", "") or ""

        if gh_client.HELP_MARKER in body:
            print(f"  [SKIP] #{num} {title}")
            skipped += 1
            continue

        new_body = gh_client.upsert_help_block(body)

        if args.dry_run:
            print(f"  [DRY] #{num} {title}")
        else:
            if gh_client.update_issue_body(num, new_body):
                print(f"  [UPDATE] #{num} {title}")
                updated += 1
                time.sleep(args.sleep)
            else:
                print(f"  [FAIL] #{num} {title}", file=sys.stderr)

    print(f"\n更新: {updated} / スキップ: {skipped} / 合計: {len(issues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
