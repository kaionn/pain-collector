"""週次トレンド分析.

過去 7 日分の日次レポート（daily/*.md の元データ）を横断分析し、
繰り返し出現するペインテーマを特定する。
"""

import glob
import json
import os
import subprocess
from collections import Counter
from datetime import date, timedelta

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from .tokenizer import create_tfidf_vectorizer

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

            # raw には reddit/hatena/zenn/hackernews/note の生データが入っている
            posts = (
                data.get("reddit", []) + data.get("hatena", [])
                + data.get("zenn", []) + data.get("hackernews", [])
                + data.get("note", [])
            )
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
    tfidf = create_tfidf_vectorizer().fit_transform(corpus)
    similarities = cosine_similarity(tfidf[-1:], tfidf[:-1])
    return 1.0 - float(similarities.max())


def cluster_pains(pains: list[dict], threshold: float = 0.3) -> list[dict]:
    """類似ペインをクラスタリングして代表ペインとグループサイズを返す.

    TF-IDF + cosine similarity で類似度 threshold 以上のペインをグループ化する。
    グリーディに最も類似度が高いペア同士を同一クラスタにマージしていく。

    Returns:
        [{"representative": "代表ペイン", "count": グループサイズ, "members": [...]}]
    """
    if len(pains) < 2:
        return [{"representative": p["pain"], "count": 1, "members": [p["pain"]]} for p in pains]

    texts = [p["pain"] for p in pains]

    try:
        tfidf = TfidfVectorizer().fit_transform(texts)
        sim_matrix = cosine_similarity(tfidf)
    except ValueError:
        return [{"representative": t, "count": 1, "members": [t]} for t in texts]

    # Union-Find でクラスタリング
    n = len(texts)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i][j] >= threshold:
                union(i, j)

    # クラスタごとに集約
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    result = []
    for members in clusters.values():
        member_texts = [texts[i] for i in members]
        # 最も他のメンバーとの類似度合計が高いものを代表にする
        if len(members) == 1:
            rep = member_texts[0]
        else:
            sims = [sum(sim_matrix[i][j] for j in members) for i in members]
            rep_idx = members[np.argmax(sims)]
            rep = texts[rep_idx]
        result.append({
            "representative": rep,
            "count": len(members),
            "members": member_texts,
        })

    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def _render_bar(value: int, max_value: int, width: int = 20) -> str:
    """テキストベースのバーチャートを描画する."""
    if max_value == 0:
        return ""
    filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def _render_sparkline(daily_counts: list[int]) -> str:
    """日次出現数をスパークラインで描画する."""
    if not daily_counts:
        return ""
    blocks = " ▁▂▃▄▅▆▇█"
    max_val = max(daily_counts) if max(daily_counts) > 0 else 1
    return "".join(blocks[min(round(v / max_val * 8), 8)] for v in daily_counts)


def generate_cluster_section(clusters: list[dict]) -> str:
    """クラスタリング結果のレポートセクションを生成する."""
    if not clusters:
        return ""

    max_count = max(c["count"] for c in clusters)

    lines = [
        "\n## Pain Clusters\n",
        "類似ペインをグルーピングした結果（TF-IDF + cosine similarity）:\n",
        "| クラスタ | 件数 | 分布 |",
        "|----------|------|------|",
    ]
    for c in clusters[:15]:
        bar = _render_bar(c["count"], max_count, 15)
        lines.append(f"| {c['representative'][:40]} | {c['count']} | {bar} |")
    lines.append("")

    # 件数2以上のクラスタの詳細
    multi = [c for c in clusters if c["count"] >= 2]
    if multi:
        lines.append("### 重複ペイン詳細\n")
        for c in multi[:10]:
            lines.append(f"**{c['representative']}** ({c['count']} 件)")
            for m in c["members"]:
                if m != c["representative"]:
                    lines.append(f"  - {m}")
            lines.append("")

    return "\n".join(lines)


def generate_trend_visualization(pains: list[dict], trends: list[dict], target_date: date) -> str:
    """日次出現数のスパークラインとカテゴリ分布チャートを生成する."""
    lines = []

    # カテゴリ分布
    cat_counter: Counter = Counter()
    for p in pains:
        cat_counter[p.get("pain", "").split("（")[0][:10]] += 1

    # 日次ペイン数のスパークライン
    daily_counts = []
    for i in range(6, -1, -1):
        d = target_date - timedelta(days=i)
        count = sum(1 for p in pains if p.get("date") == d.isoformat())
        daily_counts.append(count)

    if any(c > 0 for c in daily_counts):
        lines.append("\n## Daily Pain Volume\n")
        sparkline = _render_sparkline(daily_counts)
        days_label = " ".join(
            (target_date - timedelta(days=6 - i)).strftime("%m/%d") for i in range(7)
        )
        lines.append(f"```")
        lines.append(f"{sparkline}  ({sum(daily_counts)} 件/7日間)")
        lines.append(f"{days_label}")
        lines.append(f"```\n")

    # トレンドスコアの横棒グラフ
    if trends:
        lines.append("\n## Opportunity Score Chart\n")
        lines.append("```")
        for t in trends[:10]:
            score = t.get("market_opportunity_score", 0)
            bar = "█" * score + "░" * (10 - score)
            theme = t.get("trend_theme", "")[:20]
            lines.append(f"{theme:<20} {bar} {score}/10")
        lines.append("```\n")

    return "\n".join(lines)


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


def generate_weekly_report(trends: list[dict], pains: list[dict], target_date: date, cross_lang_results: list[dict] | None = None) -> str:
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

    # Trend Visualization（スパークライン + スコアチャート）
    viz = generate_trend_visualization(pains, trends, target_date)
    if viz:
        lines.append(viz)

    if not trends:
        lines.append("トレンドが見つかりませんでした。\n")
    else:
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

    # Pain Clustering セクション
    if pains:
        clusters = cluster_pains(pains)
        cluster_section = generate_cluster_section(clusters)
        if cluster_section:
            lines.append(cluster_section)

    # 言語横断分析セクション
    if cross_lang_results:
        cross_section = generate_cross_language_section(cross_lang_results)
        if cross_section:
            lines.append(cross_section)

    return "\n".join(lines)


CROSS_LANG_PROMPT = """\
以下は日本語と英語の両方で収集されたペインリストです。
各ペインの言語タグ [ja] / [en] に注目して分析してください。

タスク:
1. 日本語ペインをそれぞれ英語に1文で要約する
2. 英語ペインと日本語ペイン（英語要約）を比較し、同じ課題を指しているペアを特定する
3. 以下のカテゴリに分類する:
   - "global_trend": 日英両方で出現しているペイン（グローバルトレンド）
   - "localize_chance": 英語圏で出現 → 日本語圏で未出現（ローカライズチャンス）
   - "japan_only": 日本語圏のみで出現

JSON 配列で出力してください（コードブロック不要）:
[
  {
    "type": "global_trend | localize_chance | japan_only",
    "theme": "テーマ名（日本語）",
    "en_pains": ["英語圏の関連ペイン"],
    "ja_pains": ["日本語圏の関連ペイン"],
    "opportunity_note": "なぜこれがチャンスなのか（1文）"
  }
]

ルール:
- global_trend と localize_chance を優先して出力する
- japan_only は特に注目に値するもののみ
- 最大 10 件まで
"""


def analyze_cross_language(pains: list[dict]) -> list[dict]:
    """日英ペインの言語横断分析を実行する."""
    en_pains = [p for p in pains if p.get("language") == "en"]
    ja_pains = [p for p in pains if p.get("language", "ja") == "ja"]

    if not en_pains or not ja_pains:
        print(f"[横断分析] 英語 {len(en_pains)} 件 / 日本語 {len(ja_pains)} 件 → スキップ")
        return []

    pain_lines = []
    for p in en_pains[:30]:
        pain_lines.append(f"[en] {p['pain']}")
    for p in ja_pains[:30]:
        pain_lines.append(f"[ja] {p['pain']}")

    prompt_text = f"{CROSS_LANG_PROMPT}\n\n--- ペインリスト ---\n" + "\n".join(pain_lines)

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        call_fn = extract_pains._call_github_models(token)
        label = "GitHub Models"
    else:
        call_fn = extract_pains._call_claude
        label = "Claude Code"

    try:
        content = call_fn(prompt_text)
        results = extract_pains._parse_json_response(content)
        print(f"[横断分析] {label} で {len(results)} 件の横断テーマを抽出")
        return results
    except Exception as e:
        print(f"[横断分析] 分析に失敗: {e}")
        return []


def generate_cross_language_section(cross_results: list[dict]) -> str:
    """言語横断分析のレポートセクションを生成する."""
    if not cross_results:
        return ""

    lines = ["\n## 🌍 言語横断分析\n"]

    global_trends = [r for r in cross_results if r.get("type") == "global_trend"]
    localize_chances = [r for r in cross_results if r.get("type") == "localize_chance"]
    japan_only = [r for r in cross_results if r.get("type") == "japan_only"]

    if global_trends:
        lines.append("### グローバルトレンド（日英両方で出現）\n")
        for r in global_trends:
            lines.append(f"- {r.get('theme', '')}")
            lines.append(f"  - {r.get('opportunity_note', '')}")
        lines.append("")

    if localize_chances:
        lines.append("### 🎯 ローカライズチャンス（英語圏のみ → 日本未参入）\n")
        for r in localize_chances:
            lines.append(f"- {r.get('theme', '')}")
            en = r.get("en_pains", [])
            if en:
                lines.append(f"  - 英語圏: {en[0]}")
            lines.append(f"  - {r.get('opportunity_note', '')}")
        lines.append("")

    if japan_only:
        lines.append("### 🇯🇵 日本語圏のみ\n")
        for r in japan_only:
            lines.append(f"- {r.get('theme', '')}")
        lines.append("")

    return "\n".join(lines)


def run(target_date: date) -> None:
    """週次トレンド分析を実行し、レポートを保存する."""
    print(f"=== Weekly Trend Analysis: {target_date.isoformat()} ===\n")

    pains = load_extracted_pains(target_date, days=7)
    print(f"過去7日分のペイン: {len(pains)} 件\n")

    trends = analyze_trends(target_date)

    # 言語横断分析（ペインに言語情報を付与）
    for p in pains:
        p.setdefault("language", "ja")  # デフォルト
    # daily/*.md からは言語情報が取れないため、ソースに基づいて推定
    # ペインテキストが ASCII 主体なら en と推定
    for p in pains:
        text = p.get("pain", "")
        ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(len(text), 1)
        if ascii_ratio > 0.8:
            p["language"] = "en"

    cross_lang_results = analyze_cross_language(pains)

    report = generate_weekly_report(trends, pains, target_date, cross_lang_results)

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
