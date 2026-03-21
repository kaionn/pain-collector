"""スコア上位の Todo Issue から MVP 候補を選定し picks/ に保存する."""

import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = timezone(timedelta(hours=9))

PICK_PROMPT = """\
あなたはプロダクト戦略アドバイザーです。

以下は個人開発の MVP 候補としてスコアが高いペイン（課題）のリストです。
これらを分析し、今すぐ着手すべきトップ 3 を選定してください。

各候補について以下を記述してください:
1. なぜこれを選んだか（1-2文）
2. MVP の最小スコープ（3-5 つの機能）
3. 想定開発期間
4. 最初のユーザー獲得方法

Markdown 形式で出力してください。見出しは ## を使ってください。
"""


def _load_past_picks() -> set[int]:
    """過去の picks/ レポートから選定済みの Issue 番号を抽出する."""
    picks_dir = os.path.join(BASE_DIR, "picks")
    picked = set()
    if not os.path.isdir(picks_dir):
        return picked
    for fname in os.listdir(picks_dir):
        if not fname.endswith(".md"):
            continue
        try:
            with open(os.path.join(picks_dir, fname), encoding="utf-8") as f:
                for line in f:
                    # "### #123" や "#123" 形式の Issue 番号を抽出
                    for match in re.findall(r"#(\d+)", line):
                        picked.add(int(match))
        except OSError:
            continue
    return picked


def _fetch_scored_issues() -> list[dict]:
    """スコアラベル付きの open Issue を取得する."""
    score_labels = ["🏆score-S", "🥇score-A", "🥈score-B"]
    all_issues = []

    for label in score_labels:
        try:
            result = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--label", label,
                    "--state", "open",
                    "--json", "number,title,body,labels",
                    "--limit", "20",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                issues = json.loads(result.stdout)
                for issue in issues:
                    issue["score_label"] = label
                all_issues.extend(issues)
        except Exception:
            continue

    return all_issues


def _call_llm(prompt: str) -> str:
    """LLM を呼び出す."""
    token = os.environ.get("GITHUB_TOKEN", "")

    if token:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://models.github.ai/inference",
            api_key=token,
        )
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])
    return result.stdout.strip()


def run() -> None:
    """MVP 候補を選定してレポートを保存する."""
    issues = _fetch_scored_issues()

    if not issues:
        print("[PickIdea] スコア付き Issue がありません")
        return

    # スコア順にソート（S > A > B）
    score_order = {"🏆score-S": 0, "🥇score-A": 1, "🥈score-B": 2}
    issues.sort(key=lambda x: score_order.get(x.get("score_label", ""), 3))

    # 過去の選定済み Issue を除外
    past_picks = _load_past_picks()
    issues = [i for i in issues if i["number"] not in past_picks]

    if not issues:
        print("[PickIdea] 未選定のスコア付き Issue がありません")
        return

    # 上位10件をLLMに渡す（body 全文を含めて判断精度を向上）
    top = issues[:10]
    issue_texts = []
    for issue in top:
        title = issue["title"]
        body = issue.get("body", "")
        label = issue.get("score_label", "")
        issue_texts.append(f"### #{issue['number']} {title}\nスコア: {label}\n{body}\n")

    combined = "\n".join(issue_texts)
    prompt = f"{PICK_PROMPT}\n\n--- 候補一覧 ---\n\n{combined}"

    print(f"[PickIdea] {len(top)} 件の候補を分析中...")

    try:
        content = _call_llm(prompt)
    except Exception as e:
        print(f"[PickIdea] LLM 呼び出し失敗: {e}")
        return

    today = datetime.now(JST).date().isoformat()

    # ヘッダー付きレポート
    report = f"# MVP 候補選定: {today}\n\n候補数: {len(top)} 件\n\n{content}\n"

    # 保存
    output_dir = os.path.join(BASE_DIR, "picks")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{today}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[PickIdea] レポートを保存: {output_path}")
