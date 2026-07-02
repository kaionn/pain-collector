"""フィードバック集計: GitHub Issues のラベルからペイン評価を集計する.

ユーザーが Issues に 👍good / 👎bad / 💡interesting ラベルを付けることで
フィードバックループを回す。集計結果はプロンプト改善のヒントになる。
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta, date

from src import llm_client

logger = logging.getLogger(__name__)

PATTERN_TTL_DAYS = 90

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def collect_feedback() -> dict:
    """GitHub Issues からフィードバックラベル付きの Issue を集計する."""
    feedback = {"good": [], "bad": [], "interesting": []}

    for rating in feedback:
        label = {"good": "👍good", "bad": "👎bad", "interesting": "💡interesting"}[rating]

        try:
            result = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--label", label,
                    "--state", "all",
                    "--json", "title,labels,number",
                    "--limit", "100",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                issues = json.loads(result.stdout)
                for issue in issues:
                    # タイトルからカテゴリとペインテキストを抽出
                    title = issue.get("title", "")
                    labels = [l["name"] for l in issue.get("labels", [])]
                    feedback[rating].append({
                        "title": title,
                        "labels": labels,
                        "number": issue.get("number"),
                    })
        except Exception as e:
            logger.warning(f"{rating} の取得に失敗: {e}")

    return feedback


def generate_feedback_report() -> str:
    """フィードバック集計レポートを生成する."""
    fb = collect_feedback()

    total = sum(len(v) for v in fb.values())
    if total == 0:
        return "フィードバックがまだありません。Issues に 👍good / 👎bad ラベルを付けてください。"

    lines = [
        "# フィードバック集計レポート\n",
        f"合計: {total} 件（👍 {len(fb['good'])} / 👎 {len(fb['bad'])} / 💡 {len(fb['interesting'])}）\n",
    ]

    # bad が多いパターンを分析
    if fb["bad"]:
        lines.append("## 👎 ノイズ・誤抽出パターン\n")
        lines.append("以下のペインは「ノイズ」と評価されました。SYSTEM_PROMPT の除外ルールに反映を検討:\n")
        for issue in fb["bad"]:
            lines.append(f"- #{issue['number']} {issue['title']}")
        lines.append("")

    # good のパターン
    if fb["good"]:
        lines.append("## 👍 良い抽出パターン\n")
        # カテゴリ別に集計
        cat_count: dict[str, int] = {}
        for issue in fb["good"]:
            for label in issue["labels"]:
                if label not in ("pain-report", "👍good") and not label.startswith(("📱", "🌐", "🧩", "⌨️", "☁️", "💰", "🔥", "🎯", "🟢", "🟡")):
                    cat_count[label] = cat_count.get(label, 0) + 1

        for cat, count in sorted(cat_count.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {cat}: {count} 件")
        lines.append("")

    # interesting
    if fb["interesting"]:
        lines.append("## 💡 深掘りしたいペイン\n")
        for issue in fb["interesting"]:
            lines.append(f"- #{issue['number']} {issue['title']}")
        lines.append("")

    return "\n".join(lines)


def run() -> None:
    """フィードバック集計を実行して表示する."""
    report = generate_feedback_report()
    logger.info(report)


def _generalize_patterns_with_llm(titles: list[str], pattern_type: str) -> list[str]:
    """LLM を使って個別タイトルから汎用的なパターンを抽出する."""
    if not titles:
        return []

    titles_text = "\n".join(f"- {t}" for t in titles)

    if pattern_type == "exclude":
        prompt = (
            "以下は「ノイズ」と評価されたペインのタイトル一覧です。\n"
            "これらに共通する汎用的なノイズカテゴリを抽出してください。\n"
            "個別のタイトルではなく、将来のノイズも捕捉できる一般的なパターンにしてください。\n"
            "例: 「国際政治・外交に関するニュース報道」「企業の不祥事・炎上報道」\n\n"
            f"タイトル一覧:\n{titles_text}\n\n"
            "JSON 配列で出力してください（コードブロック不要）:\n"
            '[\"パターン1\", \"パターン2\", ...]'
        )
    else:
        prompt = (
            "以下は「良い抽出」と評価されたペインのタイトル一覧です。\n"
            "これらに共通する汎用的な優先パターンを抽出してください。\n"
            "個別のタイトルではなく、同種のペインも拾えるパターンにしてください。\n"
            "例: 「業務効率化ツールへの具体的な改善要望」「日常の繰り返し作業の自動化ニーズ」\n\n"
            f"タイトル一覧:\n{titles_text}\n\n"
            "JSON 配列で出力してください（コードブロック不要）:\n"
            '[\"パターン1\", \"パターン2\", ...]'
        )

    try:
        content = llm_client.chat(prompt, temperature=0)
        return llm_client.parse_json_response(content or "[]")
    except Exception as e:
        logger.warning(f"LLM パターン汎化に失敗、フォールバック: {e}")
        return titles


def learn_rules() -> dict:
    """フィードバックから学習ルールを抽出して feedback_rules.json に保存する."""
    fb = collect_feedback()

    # 既存のシードデータを読み込む
    rules_path = os.path.join(BASE_DIR, "feedback_rules.json")
    existing_exclude: list[dict] = []
    existing_priority: list[dict] = []
    if os.path.exists(rules_path):
        try:
            with open(rules_path, encoding="utf-8") as f:
                existing = json.load(f)
            existing_exclude = _migrate_patterns(existing.get("exclude_patterns", []))
            existing_priority = _migrate_patterns(existing.get("priority_patterns", []))
        except Exception:
            pass

    # bad issues のタイトルとIssue番号を収集
    bad_titles = [issue.get("title", "") for issue in fb["bad"] if issue.get("title")]
    bad_numbers = [issue.get("number") for issue in fb["bad"] if issue.get("number")]
    # good issues のタイトルとIssue番号を収集
    good_titles = [issue.get("title", "") for issue in fb["good"] if issue.get("title")]
    good_numbers = [issue.get("number") for issue in fb["good"] if issue.get("number")]

    # LLM で汎用パターンに変換
    new_exclude_strs = _generalize_patterns_with_llm(bad_titles, "exclude") if bad_titles else []
    new_priority_strs = _generalize_patterns_with_llm(good_titles, "priority") if good_titles else []

    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).date().isoformat()

    # 新しいパターンにメタデータを付与
    new_exclude = [
        {"pattern": p, "created_at": today_str, "source_issues": bad_numbers}
        for p in new_exclude_strs
    ]
    new_priority = [
        {"pattern": p, "created_at": today_str, "source_issues": good_numbers}
        for p in new_priority_strs
    ]

    # 既存パターンとマージ（重複排除）
    exclude_patterns = _merge_patterns(existing_exclude, new_exclude)
    priority_patterns = _merge_patterns(existing_priority, new_priority)

    rules = {
        "exclude_patterns": exclude_patterns,
        "priority_patterns": priority_patterns,
        "updated_at": datetime.now(jst).isoformat(),
    }

    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)

    # 期限切れパターンの報告
    expired = _find_expired_patterns(exclude_patterns + priority_patterns)
    if expired:
        logger.warning(f"期限切れパターン ({len(expired)} 件):")
        for p in expired:
            logger.warning(f"  - {p['pattern']} (作成: {p['created_at']})")

    logger.info(f"除外パターン: {len(exclude_patterns)} 件")
    logger.info(f"優先パターン: {len(priority_patterns)} 件")
    logger.info(f"保存先: {rules_path}")

    return rules


def _migrate_patterns(patterns: list) -> list[dict]:
    """旧形式（文字列リスト）を新形式（オブジェクトリスト）にマイグレーションする."""
    migrated = []
    for p in patterns:
        if isinstance(p, str):
            migrated.append({"pattern": p, "created_at": "2026-03-01", "source_issues": []})
        elif isinstance(p, dict):
            migrated.append(p)
    return migrated


def _merge_patterns(existing: list[dict], new: list[dict]) -> list[dict]:
    """既存パターンと新パターンをマージする（パターン文字列で重複排除）."""
    seen = set()
    merged = []
    for p in existing + new:
        key = p["pattern"]
        if key not in seen:
            seen.add(key)
            merged.append(p)
    return merged


def _find_expired_patterns(patterns: list[dict]) -> list[dict]:
    """有効期限（90日）を超えたパターンを返す."""
    today = date.today()
    expired = []
    for p in patterns:
        created_str = p.get("created_at", "")
        if not created_str:
            continue
        try:
            created = date.fromisoformat(created_str)
            if (today - created).days > PATTERN_TTL_DAYS:
                expired.append(p)
        except ValueError:
            continue
    return expired


def get_active_patterns(patterns: list) -> list[str]:
    """有効期限内のパターン文字列のみを返す（extract_pains.py から呼ばれる）."""
    today = date.today()
    active = []
    for p in patterns:
        if isinstance(p, str):
            active.append(p)
            continue
        if not isinstance(p, dict):
            continue
        created_str = p.get("created_at", "")
        if not created_str:
            active.append(p["pattern"])
            continue
        try:
            created = date.fromisoformat(created_str)
            if (today - created).days <= PATTERN_TTL_DAYS:
                active.append(p["pattern"])
        except ValueError:
            active.append(p["pattern"])
    return active


def report_learn_results(rules: dict) -> str:
    """learn_rules() の結果をサマリーレポートとして返す."""
    exclude = rules.get("exclude_patterns", [])
    priority = rules.get("priority_patterns", [])
    updated = rules.get("updated_at", "不明")

    lines = [
        "# フィードバック学習レポート\n",
        f"更新日時: {updated}\n",
        f"## 除外パターン ({len(exclude)} 件)\n",
    ]
    for p in exclude:
        pattern = p["pattern"] if isinstance(p, dict) else p
        created = p.get("created_at", "?") if isinstance(p, dict) else "?"
        lines.append(f"- {pattern} (作成: {created})")
    lines.append("")

    lines.append(f"## 優先パターン ({len(priority)} 件)\n")
    for p in priority:
        pattern = p["pattern"] if isinstance(p, dict) else p
        created = p.get("created_at", "?") if isinstance(p, dict) else "?"
        lines.append(f"- {pattern} (作成: {created})")
    lines.append("")

    # 期限切れ警告
    expired = _find_expired_patterns(
        [p for p in exclude + priority if isinstance(p, dict)]
    )
    if expired:
        lines.append(f"## ⚠️ 期限切れパターン ({len(expired)} 件)\n")
        lines.append("以下のパターンは 90 日を超えています。更新または削除を検討してください:\n")
        for p in expired:
            lines.append(f"- {p['pattern']} (作成: {p['created_at']})")
        lines.append("")

    return "\n".join(lines)
