"""Issue コメントから操作するコマンド群.

GitHub Actions の issue_comment トリガーから呼び出され、
スコアラベルや日次パイプラインに依存せず単体で Issue を pick → spec → probe まで進められる。

サブコマンド:
- pick     : pipeline_state.json の picked[] にこの Issue を追加
- spec     : Issue 本文から Spec を生成し、picked[] の spec を更新（--force で再生成）
- status   : この Issue の picked / spec / deep_dive 状態を返却
- probe    : Signal Lab（kaionn/signal-lab）へ検証用 LP 生成を dispatch する
- reject   : picked[] からこの Issue を削除
- help     : コマンド一覧を返す（既存 Issue で覚えがない時用）

設計メモ:
- パスは常にリポジトリ相対で保存する（CI 環境でも一意に解決させる）
- 状態変化は events[] に時系列で記録する（/status で表示）
- pipeline_state.json への書き込み有無は STATE_DIRTY ファイルでワークフローに通知
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import shlex
from datetime import datetime, timezone, timedelta

from . import generate_product_name
from . import generate_spec
from . import gh_client
from . import notify

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_STATE_PATH = os.path.join(BASE_DIR, "data", "pipeline_state.json")
STATE_DIRTY_FLAG = os.path.join(BASE_DIR, "data", ".state_dirty")
JST = timezone(timedelta(hours=9))

LABEL_PICKED = "📌picked"
LABEL_SPEC_READY = "📐spec-ready"
LABEL_BUILDING = "building"
LABEL_PROBING = "🧪probing"

SIGNAL_LAB_REPO = "kaionn/signal-lab"
SIGNAL_LAB_WORKFLOW = "probe-request.yml"

HELP_TEXT = gh_client.HELP_BLOCK


# ---------------------------------------------------------------------------
# 状態管理
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """pipeline_state.json をロードする.

    ファイルが存在しない、または JSON パース失敗時は空 state にフォールバックする。
    """
    if not os.path.exists(PIPELINE_STATE_PATH):
        return {"picked": []}
    try:
        with open(PIPELINE_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        logger = logging.getLogger(__name__)
        logger.error(
            "pipeline_state.json のパースに失敗（空 state にフォールバック）: %s", exc
        )
        return {"picked": []}


def _save_state(state: dict) -> None:
    """pipeline_state.json を atomic に書き込む.

    write-to-tmp + os.replace で、書き込み中のクラッシュや並行 read による
    部分書き込みファイル参照を防ぐ。同一プロセスの並行書き込みでも tmp ファイル名が
    衝突しないよう ``tempfile.mkstemp`` で unique 名を生成する。
    """
    import tempfile

    state_dir = os.path.dirname(PIPELINE_STATE_PATH)
    os.makedirs(state_dir, exist_ok=True)
    base_name = os.path.basename(PIPELINE_STATE_PATH)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=state_dir,
        prefix=f"{base_name}.tmp.",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, PIPELINE_STATE_PATH)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
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
        "product_name": None,
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
        "- `/probe` で Signal Lab に検証用 LP を生成依頼\n"
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
        spec_path = generate_spec.generate_spec_from_deep_dive(
            deep_dive_abs,
            issue_number=issue_number,
            title=title,
        )
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
        f"次は `/probe` コメントで Signal Lab に検証用 LP 生成を依頼できるのだ。",
    )
    _notify_discord(f"📐 spec-ready: #{issue_number} → {rel_path}")
    return 0


_SOURCE_SECTION_RE = re.compile(r"## ソース\n+\[(.*?)\]\((https?://[^\s)]+)\)")
_MARKET_SECTION_RE = re.compile(r"## 市場シグナル\n(.*?)(?:\n##|\Z)", re.DOTALL)
_MARKET_APP_RE = re.compile(
    r"- \[(?P<name>.*?)\]\((?P<url>https?://[^\s)]+)\) "
    r"⭐(?P<rating>[^\s(]+) \((?P<reviews>\d+)件\) (?P<price>.+)"
)


def _first_sentence(text: str) -> str:
    """先頭の一文（句点区切り）を取り出す。無ければ先頭行を短縮して返す."""
    stripped = text.strip()
    if not stripped:
        return ""
    first_line = stripped.split("\n", 1)[0].strip()
    if "。" in first_line:
        return first_line.split("。", 1)[0] + "。"
    return first_line[:120]


def _extract_source(body: str) -> tuple[str | None, str | None]:
    """Issue 本文の `## ソース` セクションから (source_url, source_title) を抽出する."""
    m = _SOURCE_SECTION_RE.search(body)
    if not m:
        return None, None
    title, url = m.group(1), m.group(2)
    return url, title


def _extract_market_apps(body: str) -> list[dict]:
    """Issue 本文の `## 市場シグナル` セクションから競合アプリ一覧を抽出する."""
    section_match = _MARKET_SECTION_RE.search(body)
    if not section_match:
        return []

    apps = []
    for m in _MARKET_APP_RE.finditer(section_match.group(1)):
        apps.append({
            "name": m.group("name"),
            "url": m.group("url"),
            "rating": m.group("rating"),
            "reviews": int(m.group("reviews")),
            "price": m.group("price").strip(),
        })
    return apps


def _build_probe_payload(issue_number: int, title: str, body: str, product_name: str) -> dict:
    """signal-lab の probe-request.yml へ渡すペイロードを構築する.

    構造化データは notify.extract_pain_data_from_body（Issue 本文に埋め込まれた
    pain-data メタデータ）を再利用し、そこに含まれない source_url / market_apps のみ
    Issue 本文の該当セクションから抽出する。
    """
    pain_data = notify.extract_pain_data_from_body(body) or {
        "pain": title,
        "app_idea": "",
        "existing_solutions": None,
        "severity": 3,
        "willingness_to_pay": "medium",
    }

    pain_text = pain_data.get("pain") or title
    existing = pain_data.get("existing_solutions")
    pain_full = f"{pain_text}\n\n既存ソリューション: {existing}" if existing else pain_text

    idea = pain_data.get("app_idea") or ""
    tagline = _first_sentence(idea) if idea else title

    source_url, source_title = _extract_source(body)
    market_apps = _extract_market_apps(body)

    return {
        "slug": product_name,
        "title": product_name,
        "tagline": tagline,
        "pain": pain_full,
        "idea": idea,
        "source_url": source_url,
        "source_title": source_title,
        "market_apps": market_apps,
        "severity": pain_data.get("severity", 3),
        "monetization": pain_data.get("willingness_to_pay", "medium"),
    }


def cmd_probe(issue_number: int, args: list[str] | None = None) -> int:
    """Signal Lab（kaionn/signal-lab）へ検証用 LP 生成を dispatch する."""
    state = _load_state()
    entry = _find_entry(state, issue_number)
    if entry is None:
        # 未 pick の場合は自動で pick も行う（/spec と同じ流儀）
        cmd_pick(issue_number)
        state = _load_state()
        entry = _find_entry(state, issue_number)
        if entry is None:
            gh_client.post_comment(issue_number, "❌ pick に失敗したのだ。")
            return 1

    issue = gh_client.fetch_issue(issue_number)
    title = issue.get("title", "")
    body = issue.get("body", "") or ""

    # 既存 product_name があれば再利用（冪等化。/approve と同じ方針）
    product_name = entry.get("product_name") or generate_product_name.generate(title, issue_number)

    payload = _build_probe_payload(issue_number, title, body, product_name)
    encoded_payload = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    dispatched = gh_client.trigger_workflow(
        SIGNAL_LAB_REPO,
        SIGNAL_LAB_WORKFLOW,
        {
            "issue_number": str(issue_number),
            "source_repo": "kaionn/pain-collector",
            "payload": encoded_payload,
        },
        token=os.environ.get("PAT_TOKEN"),
    )

    if not dispatched:
        gh_client.post_comment(
            issue_number,
            "❌ Signal Lab への dispatch に失敗したのだ。Actions ログを確認するのだ。",
        )
        return 1

    entry["product_name"] = product_name
    entry["status"] = "probing"
    _append_event(entry, "probe", {"product_name": product_name})
    _save_state(state)

    gh_client.add_labels(issue_number, [LABEL_PROBING])
    gh_client.post_comment(
        issue_number,
        "🧪 Probe 生成を Signal Lab に依頼したのだ。PR ができたら通知が届くのだ。\n\n"
        f"プロダクト名: `{product_name}`",
    )
    _notify_discord(f"🧪 probing: #{issue_number} {product_name}")
    return 0


def cmd_status(issue_number: int, args: list[str] | None = None) -> int:
    """Issue の現状を返却する."""
    state = _load_state()
    entry = _find_entry(state, issue_number)
    if entry is None:
        gh_client.post_comment(
            issue_number,
            "📭 この Issue はまだ picked されてないのだ。\n\n"
            "- `/pick` で追加\n"
            "- `/help` で本文にコマンド一覧を埋め込み",
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
    """Issue 本文にコマンド一覧の折りたたみブロックを追加・更新する."""
    issue = gh_client.fetch_issue(issue_number)
    body = issue.get("body", "") or ""
    new_body = gh_client.upsert_help_block(body)

    if new_body == body:
        gh_client.post_comment(issue_number, "ℹ️ ヘルプブロックは最新だったのだ。")
        return 0

    if not gh_client.update_issue_body(issue_number, new_body):
        gh_client.post_comment(issue_number, "❌ Issue 本文の更新に失敗したのだ。")
        return 1

    gh_client.post_comment(
        issue_number,
        "✅ Issue 本文にコマンド一覧を追加したのだ。これからは本文末尾の折りたたみで確認できるのだ。",
    )
    return 0


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------

COMMANDS = {
    "pick": cmd_pick,
    "spec": cmd_spec,
    "status": cmd_status,
    "probe": cmd_probe,
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
