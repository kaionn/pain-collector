"""自動仮説検証: スコア上位アイデアに対して市場データを自動収集し Issue コメントに追加する."""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

VALIDATE_PROMPT = """\
以下のアイデアについて、市場での実現可能性を検証してください。

以下の観点で分析し、Markdown 形式でレポートを作成してください:

1. **検索トレンド**: このペインに関連するキーワードの検索需要は増えているか？
2. **類似プロダクト**: Product Hunt や GitHub で類似のプロダクトは存在するか？
3. **市場規模の推定**: ターゲットユーザーの規模感は？
4. **参入障壁**: 技術的・法的な参入障壁はあるか？
5. **検証スコア**: 1-10 で総合的な実現可能性を評価

簡潔に（各項目 1-2 文で）まとめてください。
"""


def _fetch_top_ideas(top_n: int = 3) -> list[dict]:
    """スコア上位の Issue を取得する."""
    score_labels = ["🏆score-S", "🥇score-A"]
    all_issues = []

    for label in score_labels:
        try:
            result = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--label", label,
                    "--state", "open",
                    "--json", "number,title,body,labels",
                    "--limit", "10",
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

    # 既に検証済み（"validated" ラベル付き）を除外
    unvalidated = []
    for issue in all_issues:
        labels = {l["name"] for l in issue.get("labels", [])}
        if "validated" not in labels:
            unvalidated.append(issue)

    return unvalidated[:top_n]


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


def validate_issue(issue: dict) -> None:
    """1 件の Issue に対して仮説検証を実行し、結果をコメントする."""
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")[:500]

    prompt = (
        f"{VALIDATE_PROMPT}\n\n"
        f"## アイデア\n\n"
        f"タイトル: {title}\n\n"
        f"{body}\n"
    )

    logger.info(f"#{number} を検証中...")

    try:
        content = _call_llm(prompt)
    except Exception as e:
        logger.error(f"#{number} LLM 呼び出し失敗: {e}")
        return

    today = datetime.now(JST).date().isoformat()
    comment = f"## 🔬 自動仮説検証 ({today})\n\n{content}"

    try:
        subprocess.run(
            ["gh", "issue", "comment", str(number), "--body", comment],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # validated ラベルを追加
        subprocess.run(
            ["gh", "issue", "edit", str(number), "--add-label", "validated"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(f"#{number} に検証結果を追加")
    except Exception as e:
        logger.warning(f"#{number} コメント失敗: {e}")


def run(top_n: int = 3) -> None:
    """スコア上位アイデアの自動仮説検証を実行する."""
    ideas = _fetch_top_ideas(top_n)

    if not ideas:
        logger.info("検証対象のアイデアがありません")
        return

    logger.info(f"{len(ideas)} 件のアイデアを検証...")

    for idea in ideas:
        validate_issue(idea)

    logger.info("仮説検証完了")
