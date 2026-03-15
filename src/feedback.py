"""フィードバック集計: GitHub Issues のラベルからペイン評価を集計する.

ユーザーが Issues に 👍good / 👎bad / 💡interesting ラベルを付けることで
フィードバックループを回す。集計結果はプロンプト改善のヒントになる。
"""

import json
import subprocess


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
