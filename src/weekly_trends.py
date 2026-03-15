"""週次トレンド分析.

過去 7 日分の日次レポート（daily/*.md の元データ）を横断分析し、
繰り返し出現するペインテーマを特定する。
"""

import glob
import json
import os
from datetime import date, timedelta

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import extract_pains

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WEEKLY_PROMPT = """\
あなたはペイン（日常の不満・困りごと）のトレンドアナリストです。

以下は過去 7 日間で収集されたペインのリストです。
これらを横断分析し、繰り返し出現しているテーマを特定してランキング化してください。

以下の JSON 配列形式で出力してください（Markdown のコードブロックは不要）:

[
  {
    "trend_theme": "繰り返し出現しているテーマ名（簡潔に）",
    "occurrence_count": 7日間での出現回数（推定）,
    "representative_pains": ["代表的なペイン1", "代表的なペイン2"],
    "trend_direction": "rising | stable | declining",
    "category": "子育て・育児 | 食事・料理 | お金・家計 | 仕事・キャリア | 人間関係 | 健康・体調 | 住まい・暮らし | 移動・通勤 | 学習・スキル | テクノロジー | 生き方・価値観 | 趣味・娯楽 | その他",
    "market_opportunity_score": 1-10の整数（出現頻度 × 深刻度 × 課金可能性で総合評価）,
    "reasoning": "なぜこれが重要なトレンドなのか（1-2文）"
  }
]

ルール:
- 1回しか出てこないペインはトレンドではないのでスキップする
- market_opportunity_score が高い順にソートする
- 最大 10 テーマまで
- JSON 配列のみを出力する。説明文やコードブロック記法は不要
"""


def load_daily_pains(target_date: date, days: int = 7) -> list[dict]:
    """過去 N 日分の daily レポートの元データ（raw JSON）からペインを収集する."""
    all_pains = []

    for i in range(days):
        d = target_date - timedelta(days=i)
        raw_path = os.path.join(BASE_DIR, "raw", f"{d.isoformat()}.json")

        if not os.path.exists(raw_path):
            continue

        try:
            with open(raw_path, encoding="utf-8") as f:
                data = json.load(f)

            # raw には reddit/hatena/zenn の生データが入っている
            posts = data.get("reddit", []) + data.get("hatena", []) + data.get("zenn", [])
            all_pains.extend(posts)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[週次] {d.isoformat()} の読み込みに失敗: {e}")

    return all_pains


def load_extracted_pains(target_date: date, days: int = 7) -> list[dict]:
    """過去 N 日分の daily/*.md から抽出済みペインテキストを収集する.

    daily/*.md はマークダウン形式なので、### 以下のペインタイトルを抽出する。
    """
    pains = []

    for i in range(days):
        d = target_date - timedelta(days=i)
        daily_path = os.path.join(BASE_DIR, "daily", f"{d.isoformat()}.md")

        if not os.path.exists(daily_path):
            continue

        try:
            with open(daily_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("### "):
                        pain_text = line[4:].strip()
                        if pain_text:
                            pains.append({"pain": pain_text, "date": d.isoformat()})
        except OSError:
            continue

    return pains


def calculate_novelty(new_pain: str, historical_pains: list[str]) -> float:
    """0.0（完全に既出）〜 1.0（完全に新規）を返す."""
    if not historical_pains:
        return 1.0
    corpus = historical_pains + [new_pain]
    tfidf = TfidfVectorizer().fit_transform(corpus)
    similarities = cosine_similarity(tfidf[-1:], tfidf[:-1])
    return 1.0 - float(similarities.max())


def analyze_trends(target_date: date) -> list[dict]:
    """週次トレンド分析を実行する."""
    pains = load_extracted_pains(target_date, days=7)

    if len(pains) < 3:
        print(f"[週次] ペインが {len(pains)} 件のみ、分析スキップ")
        return []

    # ペインテキストを LLM に投げてトレンド分析
    pain_texts = [f"[{p['date']}] {p['pain']}" for p in pains]
    combined = "\n".join(pain_texts)

    prompt_text = f"{WEEKLY_PROMPT}\n\n--- ペインリスト ({len(pains)} 件) ---\n{combined}"

    # extract_pains の LLM 呼び出し基盤を流用
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        call_fn = extract_pains._call_github_models(token)
        label = "GitHub Models"
    else:
        call_fn = extract_pains._call_claude
        label = "Claude Code"

    try:
        content = call_fn(prompt_text)
        trends = extract_pains._parse_json_response(content)
        print(f"[週次] {label} で {len(trends)} 件のトレンドを抽出")
        return trends
    except Exception as e:
        print(f"[週次] トレンド分析に失敗: {e}")
        return []


def generate_weekly_report(trends: list[dict], pains: list[dict], target_date: date) -> str:
    """週次レポートの Markdown を生成する."""
    week_num = target_date.isocalendar()[1]
    year = target_date.year
    week_label = f"{year}-W{week_num:02d}"

    lines = [
        f"# Weekly Trend Report: {week_label}\n",
        f"分析期間: {(target_date - timedelta(days=6)).isoformat()} 〜 {target_date.isoformat()}",
        f"分析対象ペイン数: {len(pains)} 件",
        f"抽出トレンド数: {len(trends)} 件\n",
    ]

    if not trends:
        lines.append("トレンドが見つかりませんでした。\n")
        return "\n".join(lines)

    # サマリーテーブル
    lines.extend([
        "| # | テーマ | スコア | 出現数 | 方向 | カテゴリ |",
        "|---|--------|--------|--------|------|----------|",
    ])
    for i, t in enumerate(trends, 1):
        score = t.get("market_opportunity_score", 0)
        score_bar = "🟩" * min(score, 10) + "⬜" * max(0, 10 - score)
        lines.append(
            f"| {i} | {t.get('trend_theme', '')} | {score_bar} {score}/10 "
            f"| {t.get('occurrence_count', 0)} 回 | {t.get('trend_direction', '')} "
            f"| {t.get('category', '')} |"
        )
    lines.append("")

    # 詳細セクション
    for i, t in enumerate(trends, 1):
        score = t.get("market_opportunity_score", 0)
        theme = t.get("trend_theme", "")
        direction = t.get("trend_direction", "")
        count = t.get("occurrence_count", 0)
        category = t.get("category", "")
        reasoning = t.get("reasoning", "")
        reps = t.get("representative_pains", [])

        direction_emoji = {"rising": "📈", "stable": "➡️", "declining": "📉"}.get(direction, "")

        lines.append(f"\n## {i}. {theme} ({score}/10) {direction_emoji}\n")
        lines.append(f"- カテゴリ: {category}")
        lines.append(f"- 出現回数: {count} 回 / 方向: {direction}")
        lines.append(f"- 分析: {reasoning}")
        lines.append("")

        if reps:
            lines.append("代表的なペイン:")
            for rep in reps:
                lines.append(f"- {rep}")
            lines.append("")

    return "\n".join(lines)


def run(target_date: date) -> None:
    """週次トレンド分析を実行し、レポートを保存する."""
    print(f"=== Weekly Trend Analysis: {target_date.isoformat()} ===\n")

    pains = load_extracted_pains(target_date, days=7)
    print(f"過去7日分のペイン: {len(pains)} 件\n")

    trends = analyze_trends(target_date)
    report = generate_weekly_report(trends, pains, target_date)

    # 保存
    week_num = target_date.isocalendar()[1]
    year = target_date.year
    output_dir = os.path.join(BASE_DIR, "weekly")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{year}-W{week_num:02d}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n週次レポートを保存: {output_path}")

    if trends:
        print(f"トップトレンド: {trends[0].get('trend_theme', '')} "
              f"(スコア: {trends[0].get('market_opportunity_score', 0)}/10)")
