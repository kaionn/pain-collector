"""Issue コメントから操作するコマンド群.

GitHub Actions の issue_comment トリガーから呼び出され、
スコアラベルや日次パイプラインに依存せず単体で Issue を pick → spec → approve まで進められる。

サブコマンド:
- pick     : pipeline_state.json の picked[] にこの Issue を追加
- spec     : Issue 本文から Spec を生成し、picked[] の spec を更新
- status   : この Issue の picked / spec / deep_dive 状態を返却
- reject   : picked[] からこの Issue を削除
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta

from . import generate_spec

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_STATE_PATH = os.path.join(BASE_DIR, "data", "pipeline_state.json")
JST = timezone(timedelta(hours=9))


def _load_state() -> dict:
    if not os.path.exists(PIPELINE_STATE_PATH):
        return {"picked": []}
    with open(PIPELINE_STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(PIPELINE_STATE_PATH), exist_ok=True)
    with open(PIPELINE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _find_entry(state: dict, issue_number: int) -> dict | None:
    for item in state.get("picked", []):
        if item.get("issue_number") == issue_number:
            return item
    return None


def _fetch_issue(issue_number: int) -> dict:
    """gh CLI で Issue の title/body/labels を取得する."""
    result = subprocess.run(
        [
            "gh", "issue", "view", str(issue_number),
            "--json", "number,title,body,labels",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Issue #{issue_number} 取得失敗: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def _post_comment(issue_number: int, body: str) -> None:
    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except Exception as e:
        logger.warning(f"コメント投稿失敗: {e}")


# ---------------------------------------------------------------------------
# サブコマンド実装
# ---------------------------------------------------------------------------

def cmd_pick(issue_number: int) -> int:
    """Issue を picked に追加する."""
    state = _load_state()
    state.setdefault("picked", [])

    if _find_entry(state, issue_number):
        _post_comment(issue_number, "ℹ️ この Issue はすでに picked 済みなのだ。")
        logger.info(f"#{issue_number} は既に picked 済み")
        return 0

    issue = _fetch_issue(issue_number)
    state["picked"].append({
        "issue_number": issue_number,
        "title": issue.get("title", ""),
        "picked_at": datetime.now(JST).isoformat(),
        "spec": None,
        "deep_dive": None,
        "status": "picked",
        "source": "issue-command",
    })
    _save_state(state)

    _post_comment(
        issue_number,
        "✅ MVP 候補として pick されたのだ。\n\n"
        "次のステップ:\n"
        "- `/spec` で Spec を生成\n"
        "- Spec 生成後に `/approve` で自動実装トリガー\n"
        "- 取り消すには `/reject`",
    )
    logger.info(f"#{issue_number} を picked に追加")
    return 0


def cmd_spec(issue_number: int) -> int:
    """Issue から Spec を生成して picked[].spec を更新する."""
    state = _load_state()
    entry = _find_entry(state, issue_number)
    if entry is None:
        # 未 pick の場合は自動で pick も行う
        cmd_pick(issue_number)
        state = _load_state()
        entry = _find_entry(state, issue_number)
        if entry is None:
            return 1

    if entry.get("spec") and os.path.exists(os.path.join(BASE_DIR, entry["spec"])):
        _post_comment(issue_number, f"ℹ️ Spec はすでに存在するのだ: `{entry['spec']}`")
        return 0

    issue = _fetch_issue(issue_number)
    title = issue.get("title", "")
    body = issue.get("body", "")

    # Deep Dive があればそれ経由、無ければ Issue 本文から直接生成
    spec_path: str | None
    if entry.get("deep_dive"):
        spec_path = generate_spec.generate_spec_from_deep_dive(entry["deep_dive"])
    else:
        spec_path = generate_spec.generate_spec_from_issue(issue_number, title, body)

    if not spec_path:
        _post_comment(issue_number, "❌ Spec 生成に失敗したのだ。ログを確認するのだ。")
        return 1

    # リポジトリ相対パスで保存
    rel_path = os.path.relpath(spec_path, BASE_DIR)
    entry["spec"] = rel_path
    entry["status"] = "spec-ready"
    _save_state(state)

    _post_comment(
        issue_number,
        f"✅ Spec を生成したのだ: `{rel_path}`\n\n"
        f"`/approve` コメントで自動実装が走るのだ。",
    )
    logger.info(f"#{issue_number} の Spec 生成完了: {rel_path}")
    return 0


def cmd_status(issue_number: int) -> int:
    """Issue の現状を返却する."""
    state = _load_state()
    entry = _find_entry(state, issue_number)
    if entry is None:
        _post_comment(issue_number, "📭 この Issue はまだ picked されてないのだ。`/pick` で追加するのだ。")
        return 0

    spec = entry.get("spec") or "未生成"
    dd = entry.get("deep_dive") or "未生成"
    status = entry.get("status", "unknown")
    picked_at = entry.get("picked_at", "")

    body = (
        f"## 📊 ステータス\n\n"
        f"| 項目 | 値 |\n|------|-----|\n"
        f"| status | `{status}` |\n"
        f"| picked_at | {picked_at} |\n"
        f"| deep_dive | `{dd}` |\n"
        f"| spec | `{spec}` |\n"
    )
    _post_comment(issue_number, body)
    return 0


def cmd_reject(issue_number: int) -> int:
    """Issue を picked から削除する."""
    state = _load_state()
    before = len(state.get("picked", []))
    state["picked"] = [
        i for i in state.get("picked", [])
        if i.get("issue_number") != issue_number
    ]
    if len(state["picked"]) == before:
        _post_comment(issue_number, "ℹ️ picked に存在しなかったのだ。")
        return 0

    _save_state(state)
    _post_comment(issue_number, "🗑️ picked から削除したのだ。")
    return 0


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------

COMMANDS = {
    "pick": cmd_pick,
    "spec": cmd_spec,
    "status": cmd_status,
    "reject": cmd_reject,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue コマンド処理")
    parser.add_argument("--action", required=True, choices=COMMANDS.keys())
    parser.add_argument("--issue", required=True, type=int)
    args = parser.parse_args()

    handler = COMMANDS[args.action]
    try:
        return handler(args.issue)
    except Exception as e:
        logger.exception("コマンド実行失敗")
        _post_comment(args.issue, f"❌ コマンド失敗: `{e}`")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
