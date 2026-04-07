"""Issue コメントから操作するコマンド群.

GitHub Actions の issue_comment トリガーから呼び出され、
スコアラベルや日次パイプラインに依存せず単体で Issue を pick → spec → approve まで進められる。

サブコマンド:
- pick     : pipeline_state.json の picked[] にこの Issue を追加
- spec     : Issue 本文から Spec を生成し、picked[] の spec を更新（--force で再生成）
- status   : この Issue の picked / spec / deep_dive 状態を返却
- reject   : picked[] からこの Issue を削除
- help     : コマンド一覧を返す（既存 Issue で覚えがない時用）

設計メモ:
- パスは常にリポジトリ相対で保存する（CI 環境でも一意に解決させる）
- 状態変化は events[] に時系列で記録する（/status で表示）
- pipeline_state.json への書き込み有無は STATE_DIRTY ファイルでワークフローに通知
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
from datetime import datetime, timezone, timedelta

from . import generate_spec
from . import gh_client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_STATE_PATH = os.path.join(BASE_DIR, "data", "pipeline_state.json")
STATE_DIRTY_FLAG = os.path.join(BASE_DIR, "data", ".state_dirty")
JST = timezone(timedelta(hours=9))

LABEL_PICKED = "📌picked"
LABEL_SPEC_READY = "📐spec-ready"
LABEL_BUILDING = "building"

HELP_TEXT = """## 🎮 Issue コマンド一覧

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

💡 `/spec` は LLM 呼び出しで 30〜90 秒かかるのだ。完了コメントを待つのだ。
"""


# ---------------------------------------------------------------------------
# 状態管理
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if not os.path.exists(PIPELINE_STATE_PATH):
        return {"picked": []}
    with open(PIPELINE_STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(PIPELINE_STATE_PATH), exist_ok=True)
    with open(PIPELINE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    # ワークフローに「state を書き換えた」と通知
    with open(STATE_DIRTY_FLAG, "w") as f:
        f.write("1")


def _find_entry(state: dict, issue_number: int) -> dict | None:
    for item in state.get("picked", []):
        if item.get("issue_number") == issue_number:
            return item
    return None


def _now() -> str:
    return datetime.now(JST).isoformat()


def _append_event(entry: dict, action: str, payload: dict | None = None) -> None:
    """entry の events[] にアクション履歴を追加する."""
    events = entry.setdefault("events", [])
    event = {"action": action, "at": _now()}
    if payload:
        event["payload"] = payload
    events.append(event)


def _normalize_path(path: str | None) -> str | None:
    """絶対パスならリポジトリ相対に変換する."""
    if not path:
        return None
    if os.path.isabs(path):
        try:
            return os.path.relpath(path, BASE_DIR)
        except ValueError:
            return path
    return path


def _resolve_path(rel_path: str | None) -> str | None:
    """リポジトリ相対パスを絶対パスに復元する."""
    if not rel_path:
        return None
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(BASE_DIR, rel_path)


def _notify_discord(message: str) -> None:
    """Discord 通知（失敗しても無視）."""
    try:
        from . import discord_notify
        if hasattr(discord_notify, "notify"):
            discord_notify.notify(message)
        elif hasattr(discord_notify, "send"):
            discord_notify.send(message)
    except Exception as e:
        logger.debug(f"Discord 通知スキップ: {e}")


# ---------------------------------------------------------------------------
# サブコマンド実装
# ---------------------------------------------------------------------------

def cmd_pick(issue_number: int, args: list[str] | None = None) -> int:
    """Issue を picked に追加する."""
    state = _load_state()
    state.setdefault("picked", [])

    existing = _find_entry(state, issue_number)
    if existing:
        gh_client.post_comment(
            issue_number,
            "ℹ️ この Issue はすでに picked 済みなのだ。`/status` で状態確認できるのだ。",
        )
        return 0

    issue = gh_client.fetch_issue(issue_number)
    entry = {
        "issue_number": issue_number,
        "title": issue.get("title", ""),
        "picked_at": _now(),
        "spec": None,
        "deep_dive": None,
        "status": "picked",
        "source": "issue-command",
        "events": [],
    }
    _append_event(entry, "pick", {"by": "issue-command"})
    state["picked"].append(entry)
    _save_state(state)

    gh_client.add_labels(issue_number, [LABEL_PICKED])
    gh_client.post_comment(
        issue_number,
        "✅ MVP 候補として pick されたのだ。\n\n"
        "次のステップ:\n"
        "- `/spec` で Spec を生成\n"
        "- Spec 生成後に `/approve` で自動実装トリガー\n"
        "- 取り消すには `/reject`",
    )
    _notify_discord(f"📌 picked: #{issue_number} {entry['title'][:60]}")
    return 0


def cmd_spec(issue_number: int, args: list[str] | None = None) -> int:
    """Issue から Spec を生成して picked[].spec を更新する."""
    force = bool(args and "--force" in args)

    state = _load_state()
    entry = _find_entry(state, issue_number)
    if entry is None:
        # 未 pick の場合は自動で pick も行う
        cmd_pick(issue_number)
        state = _load_state()
        entry = _find_entry(state, issue_number)
        if entry is None:
            gh_client.post_comment(issue_number, "❌ pick に失敗したのだ。")
            return 1

    existing_spec = _resolve_path(entry.get("spec"))
    if existing_spec and os.path.exists(existing_spec) and not force:
        gh_client.post_comment(
            issue_number,
            f"ℹ️ Spec はすでに存在するのだ: `{entry['spec']}`\n\n"
            f"再生成したい場合は `/spec --force` を使うのだ。",
        )
        return 0

    # 進捗コメント（先に投げて連打抑止）#3
    gh_client.post_comment(
        issue_number,
        "⏳ Spec を生成中なのだ… LLM 呼び出しで 30〜90 秒かかるのだ。完了したらコメントするのだ。",
    )

    issue = gh_client.fetch_issue(issue_number)
    title = issue.get("title", "")
    body = issue.get("body", "")

    # Deep Dive があればそれ経由、無ければ Issue 本文から直接生成
    deep_dive_abs = _resolve_path(entry.get("deep_dive"))
    if deep_dive_abs and os.path.exists(deep_dive_abs):
        spec_path = generate_spec.generate_spec_from_deep_dive(deep_dive_abs)
    else:
        spec_path = generate_spec.generate_spec_from_issue(issue_number, title, body)

    if not spec_path:
        gh_client.post_comment(
            issue_number,
            "❌ Spec 生成に失敗したのだ。\n"
            "- LLM レート制限の可能性: しばらく待ってから `/spec` 再実行\n"
            "- ログ確認: Actions タブの `Issue Commands` ワークフロー",
        )
        return 1

    rel_path = _normalize_path(spec_path)
    entry["spec"] = rel_path
    entry["status"] = "spec-ready"
    _append_event(entry, "spec", {"path": rel_path, "force": force})
    _save_state(state)

    gh_client.add_labels(issue_number, [LABEL_SPEC_READY])
    gh_client.post_comment(
        issue_number,
        f"✅ Spec を生成したのだ: `{rel_path}`\n\n"
        f"次は `/approve` コメントで自動実装が走るのだ。",
    )
    _notify_discord(f"📐 spec-ready: #{issue_number} → {rel_path}")
    return 0


def cmd_status(issue_number: int, args: list[str] | None = None) -> int:
    """Issue の現状を返却する."""
    state = _load_state()
    entry = _find_entry(state, issue_number)
    if entry is None:
        gh_client.post_comment(
            issue_number,
            "📭 この Issue はまだ picked されてないのだ。`/pick` で追加するのだ。\n\n"
            f"{HELP_TEXT}",
        )
        return 0

    spec = entry.get("spec") or "未生成"
    dd = entry.get("deep_dive") or "未生成"
    status = entry.get("status", "unknown")
    picked_at = entry.get("picked_at", "")

    lines = [
        "## 📊 ステータス",
        "",
        "| 項目 | 値 |",
        "|------|-----|",
        f"| status | `{status}` |",
        f"| picked_at | {picked_at} |",
        f"| deep_dive | `{dd}` |",
        f"| spec | `{spec}` |",
        "",
    ]

    events = entry.get("events", [])
    if events:
        lines.append("### 🕒 履歴")
        for ev in events[-10:]:
            lines.append(f"- `{ev.get('at', '')}` **{ev.get('action', '')}**")
        lines.append("")

    gh_client.post_comment(issue_number, "\n".join(lines))
    return 0


def cmd_reject(issue_number: int, args: list[str] | None = None) -> int:
    """Issue を picked から削除する."""
    state = _load_state()
    before = len(state.get("picked", []))
    state["picked"] = [
        i for i in state.get("picked", [])
        if i.get("issue_number") != issue_number
    ]
    if len(state["picked"]) == before:
        gh_client.post_comment(issue_number, "ℹ️ picked に存在しなかったのだ。")
        return 0

    _save_state(state)
    gh_client.remove_labels(issue_number, [LABEL_PICKED, LABEL_SPEC_READY])
    gh_client.post_comment(issue_number, "🗑️ picked から削除したのだ。")
    _notify_discord(f"🗑️ rejected: #{issue_number}")
    return 0


def cmd_help(issue_number: int, args: list[str] | None = None) -> int:
    """コマンド一覧を返す."""
    gh_client.post_comment(issue_number, HELP_TEXT)
    return 0


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------

COMMANDS = {
    "pick": cmd_pick,
    "spec": cmd_spec,
    "status": cmd_status,
    "reject": cmd_reject,
    "help": cmd_help,
}


def parse_command(comment_body: str) -> tuple[str | None, list[str]]:
    """コメント本文からコマンドと引数を抽出する.

    例:
        '/spec --force' → ('spec', ['--force'])
        '/pick お願い'  → ('pick', ['お願い'])
        'こんにちは'    → (None, [])
    """
    body = (comment_body or "").strip()
    if not body.startswith("/"):
        return None, []

    # 1 行目だけを解釈
    first_line = body.split("\n", 1)[0].strip()
    try:
        parts = shlex.split(first_line)
    except ValueError:
        parts = first_line.split()
    if not parts:
        return None, []

    cmd = parts[0].lstrip("/")
    return cmd, parts[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue コマンド処理")
    parser.add_argument("--action", required=False)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--body", required=False, help="コメント本文（--action 未指定時にパース）")
    parser.add_argument("--args", nargs="*", default=[])
    parsed = parser.parse_args()

    action = parsed.action
    args_list: list[str] = parsed.args or []

    if not action and parsed.body:
        action, args_list = parse_command(parsed.body)

    if not action or action not in COMMANDS:
        logger.error(f"未対応のコマンド: {action}")
        return 2

    handler = COMMANDS[action]
    try:
        return handler(parsed.issue, args_list)
    except Exception as e:
        logger.exception("コマンド実行失敗")
        gh_client.post_comment(parsed.issue, f"❌ コマンド失敗: `{e}`")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
