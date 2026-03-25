"""Issue 作成時に LLM でスコアリングし、Project V2 カスタムフィールドに保存する."""

import json
import logging
import math
import os
import subprocess

logger = logging.getLogger(__name__)

# スコアリング基準（60 点満点）
# 技術的シンプルさ x3 + スコープ x3 + 差別化 x2 + コミュニティ検証 x2 + ペイン強度 x1 + 収益可能性 x1
SCORING_PROMPT = """\
以下のペイン（課題）を個人開発の MVP 候補として評価してください。

各項目を 1〜5 で採点し、JSON で返してください:

{
  "technical_simplicity": 1-5（技術的にシンプルか。5=1人で2週間で作れる）,
  "scope": 1-5（スコープが明確で小さいか。5=機能を絞りやすい）,
  "differentiation": 1-5（差別化できるか。5=競合が少なく独自性がある）,
  "pain_intensity": 1-5（ペインが強いか。5=深刻で頻繁に発生する）,
  "revenue_potential": 1-5（収益化できるか。5=課金意欲が高い）,
  "reasoning": "スコアの根拠を1-2文で"
}

JSON のみ出力してください。
"""

# 加重: 技術的シンプルさ x3 + スコープ x3 + 差別化 x2 + コミュニティ検証 x2 + ペイン強度 x1 + 収益可能性 x1
WEIGHTS = {
    "technical_simplicity": 3,
    "scope": 3,
    "differentiation": 2,
    "community_validation": 2,
    "pain_intensity": 1,
    "revenue_potential": 1,
}


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
        return response.choices[0].message.content or "{}"

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])
    return result.stdout.strip()


def _parse_score_response(content: str) -> dict:
    """LLM レスポンスからスコア JSON をパースする."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    return json.loads(content)


def normalize_engagement(engagement: dict) -> int:
    """エンゲージメント情報を 1-5 のスコアに正規化する.

    閾値ベースで変換:
    - エンゲージメントなし → 3（中立）
    - 0 → 1, 1-9 → 2, 10-49 → 3, 50-499 → 4, 500+ → 5
    """
    if not engagement:
        return 3  # エンゲージメント情報なし → 中立

    values = [v for v in engagement.values() if isinstance(v, (int, float)) and v >= 0]
    if not values:
        return 3

    max_val = max(values)
    if max_val >= 500:
        return 5
    elif max_val >= 50:
        return 4
    elif max_val >= 10:
        return 3
    elif max_val >= 1:
        return 2
    else:
        return 1


def calculate_total_score(scores: dict) -> int:
    """加重合計スコアを計算する（60 点満点）."""
    total = 0
    for key, weight in WEIGHTS.items():
        total += scores.get(key, 0) * weight
    return total


def score_pain(pain: dict) -> dict | None:
    """1 件のペインをスコアリングする."""
    pain_text = pain.get("pain", "")
    category = pain.get("category", "")
    severity = pain.get("severity", 0)
    wtp = pain.get("willingness_to_pay", "")
    idea = pain.get("app_idea", "")
    existing = pain.get("existing_solutions") or "なし"

    user_prompt = (
        f"{SCORING_PROMPT}\n\n"
        f"ペイン: {pain_text}\n"
        f"カテゴリ: {category}\n"
        f"深刻度: {severity}/5\n"
        f"課金意欲: {wtp}\n"
        f"アイデア: {idea}\n"
        f"既存ソリューション: {existing}\n"
    )

    try:
        content = _call_llm(user_prompt)
        scores = _parse_score_response(content)
        # エンゲージメント情報からコミュニティ検証スコアを算出
        engagement = pain.get("source_engagement", {})
        scores["community_validation"] = normalize_engagement(engagement)
        scores["total_score"] = calculate_total_score(scores)
        return scores
    except Exception as e:
        logger.warning(f"スコアリング失敗: {e}")
        return None


def score_and_update_issue(pain: dict, issue_number: int) -> None:
    """ペインをスコアリングし、Issue にコメントとして追加する."""
    scores = score_pain(pain)
    if not scores:
        return

    total = scores["total_score"]
    reasoning = scores.get("reasoning", "")

    comment = (
        f"## 🎯 MVP スコア: {total}/60\n\n"
        f"| 項目 | スコア | 加重 |\n"
        f"|------|--------|------|\n"
        f"| 技術的シンプルさ | {scores.get('technical_simplicity', 0)}/5 | x3 |\n"
        f"| スコープ | {scores.get('scope', 0)}/5 | x3 |\n"
        f"| 差別化 | {scores.get('differentiation', 0)}/5 | x2 |\n"
        f"| コミュニティ検証 | {scores.get('community_validation', 0)}/5 | x2 |\n"
        f"| ペイン強度 | {scores.get('pain_intensity', 0)}/5 | x1 |\n"
        f"| 収益可能性 | {scores.get('revenue_potential', 0)}/5 | x1 |\n\n"
        f"根拠: {reasoning}"
    )

    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", comment],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(f"#{issue_number} にスコア {total}/60 を追加")
    except Exception as e:
        logger.warning(f"#{issue_number} コメント失敗: {e}")

    # スコアラベルを追加
    if total >= 48:
        label = "🏆score-S"
    elif total >= 36:
        label = "🥇score-A"
    elif total >= 24:
        label = "🥈score-B"
    else:
        label = "🥉score-C"

    try:
        subprocess.run(
            ["gh", "issue", "edit", str(issue_number), "--add-label", label],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass


def score_open_issues() -> None:
    """未スコアの open Issue をまとめてスコアリングする."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "open",
                "--json", "number,title,body,labels",
                "--limit", "50",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Issue 取得失敗")
            return
        issues = json.loads(result.stdout)
    except Exception as e:
        logger.warning(f"Issue 取得失敗: {e}")
        return

    score_labels = {"🏆score-S", "🥇score-A", "🥈score-B", "🥉score-C"}

    for issue in issues:
        labels = {l["name"] for l in issue.get("labels", [])}
        if labels & score_labels:
            continue  # 既にスコア済み

        # Issue body からペイン情報を簡易的に再構成
        pain = {
            "pain": issue["title"],
            "app_idea": "",
            "existing_solutions": None,
            "severity": 3,
            "willingness_to_pay": "medium",
            "category": "",
        }
        score_and_update_issue(pain, issue["number"])

    logger.info("スコアリング完了")
