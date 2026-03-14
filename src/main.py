"""pain-collector メインスクリプト.

SNS からペインを収集 → LLM で構造化 → Markdown で保存する.
"""

import os
from datetime import datetime, timezone, timedelta

from . import collect_reddit, collect_hatena, extract_pains

JST = timezone(timedelta(hours=9))


def generate_report(pains: list[dict], date_str: str) -> str:
    """日次レポートの Markdown を生成する."""
    lines = [
        f"# Pain Report: {date_str}\n",
        f"抽出件数: {len(pains)} 件\n",
    ]

    # カテゴリ別に集計
    by_category: dict[str, list[dict]] = {}
    for pain in pains:
        cat = pain.get("category", "その他")
        by_category.setdefault(cat, []).append(pain)

    # 深刻度の高い順にソート
    for cat in sorted(by_category.keys()):
        items = sorted(by_category[cat], key=lambda x: x.get("severity", 0), reverse=True)
        lines.append(f"\n## {cat}\n")

        for item in items:
            severity = item.get("severity", 0)
            stars = "★" * severity + "☆" * (5 - severity)
            pain_text = item.get("pain", "")
            idea = item.get("app_idea", "")
            existing = item.get("existing_solutions")
            source_title = item.get("source_title", "")
            source_url = item.get("source_url", "")

            lines.append(f"### {pain_text}\n")
            lines.append(f"- 深刻度: {stars} ({severity}/5)")
            lines.append(f"- アプリアイデア: {idea}")

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
