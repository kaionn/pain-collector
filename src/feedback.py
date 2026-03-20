"""フィードバック集計: GitHub Issues のラベルからペイン評価を集計する.

ユーザーが Issues に 👍good / 👎bad / 💡interesting ラベルを付けることで
フィードバックループを回す。集計結果はプロンプト改善のヒントになる。
"""

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

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
            print(f"[Feedback] {rating} の取得に失敗: {e}")

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
    print(report)


def learn_rules() -> dict:
    """フィードバックから学習ルールを抽出して feedback_rules.json に保存する."""
    fb = collect_feedback()

    exclude_patterns: list[str] = []
    priority_patterns: list[str] = []

    # bad issues からノイズパターンを抽出
    for issue in fb["bad"]:
        title = issue.get("title", "")
        # "[カテゴリ] ペインテキスト" 形式からカテゴリを抽出
        if title.startswith("[") and "]" in title:
            bracket_end = title.index("]")
            category = title[1:bracket_end].strip()
            pain_text = title[bracket_end + 1:].strip()
            pattern = f"{category}: {pain_text}" if pain_text else category
        else:
            pattern = title

        if pattern and pattern not in exclude_patterns:
            exclude_patterns.append(pattern)

    # good issues から優先パターンを抽出
    category_count: dict[str, int] = {}
    for issue in fb["good"]:
        title = issue.get("title", "")
        if title.startswith("[") and "]" in title:
            bracket_end = title.index("]")
            category = title[1:bracket_end].strip()
            category_count[category] = category_count.get(category, 0) + 1

        pain_text_part = title[title.index("]") + 1:].strip() if "]" in title else title
        if pain_text_part and pain_text_part not in priority_patterns:
            priority_patterns.append(pain_text_part)

    jst = timezone(timedelta(hours=9))
    rules = {
        "exclude_patterns": exclude_patterns,
        "priority_patterns": priority_patterns,
        "updated_at": datetime.now(jst).isoformat(),
    }

    rules_path = os.path.join(BASE_DIR, "feedback_rules.json")
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)

    print(f"[learn_rules] 除外パターン: {len(exclude_patterns)} 件")
    print(f"[learn_rules] 優先パターン: {len(priority_patterns)} 件")
    print(f"[learn_rules] 保存先: {rules_path}")

    return rules


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
        lines.append(f"- {p}")
    lines.append("")

    lines.append(f"## 優先パターン ({len(priority)} 件)\n")
    for p in priority:
        lines.append(f"- {p}")
    lines.append("")

    return "\n".join(lines)
