"""GitHub CLI / API の薄いラッパー.

issue_commands.py / pick_idea.py / notify.py から共通で使う想定。
- subprocess + gh CLI を 1 か所に集約
- リトライや軽いエラーハンドリングをここに寄せる
"""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)


HELP_MARKER = "<!-- issue-commands-help-v1 -->"
HELP_BLOCK = f"""{HELP_MARKER}
<details>
<summary>🎮 コマンド一覧（クリックで展開）</summary>

オーナー専用。コメント本文の先頭に投稿:

| コマンド | 動作 |
|---------|------|
| `/pick` | MVP 候補として picked に追加（📌picked ラベル付与） |
| `/spec` | Issue 本文から Spec を生成（未 pick なら自動 pick） |
| `/spec --force` | 既存 Spec を上書き再生成 |
| `/status` | picked / spec / deep_dive の現状と履歴を返答 |
| `/approve` | Spec 生成後、mvp-factory で自動実装を開始 |
| `/reject` | picked から削除 |
| `/help` | このヘルプを Issue 本文に追加・更新 |

💡 `/spec` は LLM 呼び出しで 30〜90 秒かかるのだ。
</details>"""


def upsert_help_block(body: str) -> str:
    """Issue 本文末尾にヘルプブロックを冪等に追加・更新する.

    マーカーが既にあれば該当ブロックを置換、無ければ末尾に追加する。
    """
    if HELP_MARKER in body:
        # マーカー以降を末尾まで全削除して差し替え（v1 限定の単純戦略）
        idx = body.index(HELP_MARKER)
        before = body[:idx].rstrip()
        return f"{before}\n\n{HELP_BLOCK}\n"
    sep = "\n\n" if body.strip() else ""
    return f"{body}{sep}{HELP_BLOCK}\n"


def update_issue_body(issue_number: int, body: str) -> bool:
    """Issue 本文を上書きする."""
    try:
        subprocess.run(
            ["gh", "issue", "edit", str(issue_number), "--body", body],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return True
    except Exception as e:
        logger.warning(f"Issue 本文更新失敗 #{issue_number}: {e}")
        return False


def fetch_issue(issue_number: int) -> dict:
    """Issue の JSON を取得する."""
    result = subprocess.run(
        [
            "gh", "issue", "view", str(issue_number),
            "--json", "number,title,body,labels,url,state",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Issue #{issue_number} 取得失敗: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def post_comment(issue_number: int, body: str) -> bool:
    """Issue にコメントを投稿する. 成功なら True."""
    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"コメント投稿失敗 #{issue_number}: {e.stderr[:200] if e.stderr else e}")
        return False
    except Exception as e:
        logger.warning(f"コメント投稿失敗 #{issue_number}: {e}")
        return False


def add_labels(issue_number: int, labels: list[str]) -> bool:
    """Issue にラベルを追加する."""
    if not labels:
        return True
    try:
        cmd = ["gh", "issue", "edit", str(issue_number)]
        for label in labels:
            cmd.extend(["--add-label", label])
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        return True
    except Exception as e:
        logger.warning(f"ラベル追加失敗 #{issue_number}: {e}")
        return False


def remove_labels(issue_number: int, labels: list[str]) -> bool:
    """Issue からラベルを削除する."""
    if not labels:
        return True
    try:
        cmd = ["gh", "issue", "edit", str(issue_number)]
        for label in labels:
            cmd.extend(["--remove-label", label])
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        return True
    except Exception as e:
        logger.warning(f"ラベル削除失敗 #{issue_number}: {e}")
        return False


def list_issues(label: str, state: str = "open", limit: int = 100) -> list[dict]:
    """ラベルで Issue を一覧取得する."""
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--label", label,
            "--state", state,
            "--limit", str(limit),
            "--json", "number,title,labels",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return []
    return json.loads(result.stdout)
