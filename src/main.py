"""pain-collector メインスクリプト.

SNS からペインを収集 → LLM で構造化 → Markdown で保存する.
"""

import json
import os
from datetime import datetime, timezone, timedelta

from . import collect_reddit, collect_hatena, extract_pains

JST = timezone(timedelta(hours=9))


PRODUCT_TYPE_EMOJI = {
    "モバイルアプリ": "📱",
    "Webサービス": "🌐",
    "ブラウザ拡張": "🧩",
    "CLI・開発ツール": "⌨️",
    "ハードウェア・IoT": "🔧",
    "API・SaaS": "☁️",
    "その他": "📦",
}


def generate_report(pains: list[dict], date_str: str) -> str:
    """日次レポートの Markdown を生成する."""
    # プロダクトタイプ別に集計
    by_product: dict[str, list[dict]] = {}
    for pain in pains:
        pt = pain.get("product_type", "その他")
        by_product.setdefault(pt, []).append(pain)

    # サマリーテーブル
    lines = [
        f"# Pain Report: {date_str}\n",
        f"抽出件数: {len(pains)} 件\n",
        "| プロダクトタイプ | 件数 |",
        "|---|---|",
    ]
    for pt in sorted(by_product.keys()):
        emoji = PRODUCT_TYPE_EMOJI.get(pt, "📦")
        lines.append(f"| {emoji} {pt} | {len(by_product[pt])} |")
    lines.append("")

    # プロダクトタイプ別セクション
    for pt in sorted(by_product.keys()):
        emoji = PRODUCT_TYPE_EMOJI.get(pt, "📦")
        items = sorted(by_product[pt], key=lambda x: x.get("severity", 0), reverse=True)
        lines.append(f"\n## {emoji} {pt}\n")

        for item in items:
            severity = item.get("severity", 0)
            stars = "★" * severity + "☆" * (5 - severity)
            pain_text = item.get("pain", "")
            category = item.get("category", "")
            idea = item.get("app_idea", "")
            existing = item.get("existing_solutions")
            source_title = item.get("source_title", "")
            source_url = item.get("source_url", "")

            lines.append(f"### {pain_text}\n")
            lines.append(f"- 深刻度: {stars} ({severity}/5)")
            lines.append(f"- カテゴリ: {category}")
            lines.append(f"- プロダクトアイデア: {idea}")

            if existing:
                lines.append(f"- 既存ソリューション: {existing}")
            else:
                lines.append("- 既存ソリューション: なし（チャンス！）")

            if source_url:
                lines.append(f"- ソース: [{source_title}]({source_url})")

            lines.append("")

    return "\n".join(lines)


def main() -> None:
    """メイン処理."""
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    print(f"=== Pain Collector: {date_str} ===\n")

    # 1. データ収集
    print("--- Reddit 収集 ---")
    reddit_posts = collect_reddit.collect()

    print("\n--- はてブ 収集 ---")
    hatena_posts = collect_hatena.collect()

    all_posts = reddit_posts + hatena_posts
    print(f"\n合計投稿数: {len(all_posts)} 件\n")

    # 生データを JSON で保存
    raw_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{date_str}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(
            {"date": date_str, "reddit": reddit_posts, "hatena": hatena_posts},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"生データを保存: {raw_path}")

    if not all_posts:
        print("投稿が0件のため終了")
        return

    # 2. LLM でペイン抽出
    print("--- ペイン抽出 ---")
    pains = extract_pains.extract(all_posts)

    if not pains:
        print("ペインが0件のため終了")
        return

    # 3. レポート生成・保存
    report = generate_report(pains, date_str)
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "daily")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{date_str}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nレポートを保存: {output_path}")
    print(f"ペイン件数: {len(pains)} 件")


if __name__ == "__main__":
    main()
