"""既存の open Issue にコマンド一覧をコメントとして一括投稿するワンショットスクリプト.

使い方:
    python scripts/post_help_to_existing_issues.py [--dry-run]

仕様:
    - pain-report ラベル付き open Issue を全件取得
    - 既に Issue Commands ヘルプを投稿済みの Issue はスキップ（マーカー文字列で判定）
    - --dry-run で投稿せず一覧表示のみ
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

MARKER = "<!-- issue-commands-help-v1 -->"
HELP_BODY = f"""{MARKER}
## 🎮 Issue コマンド一覧

オーナー専用。コメント本文の先頭に投稿:

| コマンド | 動作 |
|---------|------|
| `/pick` | MVP 候補として picked に追加（📌picked ラベル付与） |
| `/spec` | Issue 本文から Spec を生成（未 pick なら自動 pick） |
| `/spec --force` | 既存 Spec を上書き再生成 |
| `/status` | picked / spec / deep_dive の現状を返答 |
| `/approve` | Spec 生成後、mvp-factory で自動実装を開始 |
| `/reject` | picked から削除 |
| `/help` | このヘルプを表示 |

💡 `/spec` は LLM 呼び出しで 30〜90 秒かかるのだ。
"""


def list_pain_issues() -> list[dict]:
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--label", "pain-report",
            "--state", "open",
            "--limit", "200",
            "--json", "number,title",
        ],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(result.stdout)


def has_help_already(issue_number: int) -> bool:
    result = subprocess.run(
        [
            "gh", "issue", "view", str(issue_number),
            "--json", "comments",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return False
    data = json.loads(result.stdout)
    for c in data.get("comments", []):
        if MARKER in (c.get("body") or ""):
            return True
    return False


def post_help(issue_number: int) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--body", HELP_BODY],
        check=True, timeout=30,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0, help="API レート制限避けの待機秒")
    args = parser.parse_args()

    issues = list_pain_issues()
    print(f"対象 Issue: {len(issues)} 件")

    posted = 0
    skipped = 0
    for issue in issues:
        num = issue["number"]
        title = issue["title"][:60]
        if has_help_already(num):
            print(f"  [SKIP] #{num} {title}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [DRY] #{num} {title}")
        else:
            try:
                post_help(num)
                print(f"  [POST] #{num} {title}")
                posted += 1
                time.sleep(args.sleep)
            except Exception as e:
                print(f"  [FAIL] #{num} {e}", file=sys.stderr)

    print(f"\n投稿: {posted} / スキップ: {skipped} / 合計: {len(issues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
