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

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        if token:
            from openai import OpenAI
            client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=token,
            )
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            content = response.choices[0].message.content or "[]"
        else:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr[:200])
            content = result.stdout.strip()

        from src.extract_pains import _parse_json_response
        return _parse_json_response(content)
    except Exception as e:
        print(f"[learn_rules] LLM パターン汎化に失敗、フォールバック: {e}")
        return titles


def learn_rules() -> dict:
    """フィードバックから学習ルールを抽出して feedback_rules.json に保存する."""
    fb = collect_feedback()

    # 既存のシードデータを読み込む
    rules_path = os.path.join(BASE_DIR, "feedback_rules.json")
    existing_exclude: list[str] = []
    existing_priority: list[str] = []
    if os.path.exists(rules_path):
        try:
            with open(rules_path, encoding="utf-8") as f:
                existing = json.load(f)
            existing_exclude = existing.get("exclude_patterns", [])
            existing_priority = existing.get("priority_patterns", [])
        except Exception:
            pass

    # bad issues のタイトルを収集
    bad_titles = [issue.get("title", "") for issue in fb["bad"] if issue.get("title")]
    # good issues のタイトルを収集
    good_titles = [issue.get("title", "") for issue in fb["good"] if issue.get("title")]

    # LLM で汎用パターンに変換
    new_exclude = _generalize_patterns_with_llm(bad_titles, "exclude") if bad_titles else []
    new_priority = _generalize_patterns_with_llm(good_titles, "priority") if good_titles else []

    # 既存パターンとマージ（重複排除）
    exclude_patterns = list(dict.fromkeys(existing_exclude + new_exclude))
    priority_patterns = list(dict.fromkeys(existing_priority + new_priority))

    jst = timezone(timedelta(hours=9))
    rules = {
        "exclude_patterns": exclude_patterns,
        "priority_patterns": priority_patterns,
        "updated_at": datetime.now(jst).isoformat(),
    }

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
