"""pain-collector メインスクリプト.

SNS からペインを収集 → LLM で構造化 → Markdown で保存する.
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta

from . import collect_reddit, collect_hatena, extract_pains

JST = timezone(timedelta(hours=9))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CATEGORY_EMOJI = {
    "子育て・育児": "👶",
    "食事・料理": "🍽️",
    "お金・家計": "💰",
    "仕事・キャリア": "💼",
    "人間関係": "🤝",
    "健康・体調": "🏥",
    "住まい・暮らし": "🏠",
    "移動・通勤": "🚃",
    "学習・スキル": "📚",
    "テクノロジー": "💻",
    "生き方・価値観": "🌱",
    "趣味・娯楽": "🎮",
    "その他": "📦",
}

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
    # 悩みジャンル別に集計
    by_category: dict[str, list[dict]] = {}
    for pain in pains:
        cat = pain.get("category", "その他")
        by_category.setdefault(cat, []).append(pain)

    sorted_cats = sorted(by_category.keys())

    # サマリーテーブル
    lines = [
        f"# Pain Report: {date_str}\n",
        f"抽出件数: {len(pains)} 件\n",
        "| 悩みのジャンル | 件数 |",
        "|---|---|",
    ]
    for cat in sorted_cats:
        emoji = CATEGORY_EMOJI.get(cat, "📦")
        lines.append(f"| {emoji} {cat} | {len(by_category[cat])} |")
    lines.append("")

    # ジャンル別セクション
    for cat in sorted_cats:
        emoji = CATEGORY_EMOJI.get(cat, "📦")
        items = sorted(by_category[cat], key=lambda x: x.get("severity", 0), reverse=True)
        lines.append(f"\n## {emoji} {cat}\n")

        for item in items:
            severity = item.get("severity", 0)
            stars = "★" * severity + "☆" * (5 - severity)
            pain_text = item.get("pain", "")
            product_type = item.get("product_type", "")
            pt_emoji = PRODUCT_TYPE_EMOJI.get(product_type, "📦")
            idea = item.get("app_idea", "")
            existing = item.get("existing_solutions")
            source_title = item.get("source_title", "")
            source_url = item.get("source_url", "")

            target_user = item.get("target_user", "")
            frequency = item.get("frequency", "")
            wtp = item.get("willingness_to_pay", "")

            lines.append(f"### {pain_text}\n")
            lines.append(f"- 深刻度: {stars} ({severity}/5)")
            lines.append(f"- 対象ユーザー: {target_user}")
            lines.append(f"- 頻度: {frequency} / 課金意欲: {wtp}")
            lines.append(f"- プロダクト: {pt_emoji} {product_type}")
            lines.append(f"- アイデア: {idea}")

            if existing:
                lines.append(f"- 既存ソリューション: {existing}")
            else:
                lines.append("- 既存ソリューション: なし（チャンス！）")

            if source_url:
                lines.append(f"- ソース: [{source_title}]({source_url})")

            lines.append("")

    return "\n".join(lines)


def process_day(
    date_str: str,
    reddit_posts: list[dict],
    hatena_posts: list[dict],
) -> None:
    """1日分の抽出・保存を行う（収集済みデータを受け取る）."""
    print(f"=== Pain Collector: {date_str} ===\n")

    all_posts = reddit_posts + hatena_posts
    print(f"投稿数: Reddit {len(reddit_posts)} 件 + はてブ {len(hatena_posts)} 件 = {len(all_posts)} 件\n")

    # 生データを JSON で保存
    raw_dir = os.path.join(BASE_DIR, "raw")
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

    # LLM でペイン抽出
    print("--- ペイン抽出 ---")
    pains = extract_pains.extract(all_posts)

    if not pains:
        print("ペインが0件のため終了")
        return

    # レポート生成・保存
    report = generate_report(pains, date_str)
    output_dir = os.path.join(BASE_DIR, "daily")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{date_str}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nレポートを保存: {output_path}")
    print(f"ペイン件数: {len(pains)} 件")


def main() -> None:
    """メイン処理."""
    parser = argparse.ArgumentParser(description="Pain Collector")
    parser.add_argument(
        "--backfill",
        type=int,
        default=0,
        metavar="DAYS",
        help="過去 N 日分をバックフィルする（例: --backfill 7）",
    )
    args = parser.parse_args()

    today = datetime.now(JST).date()

    if args.backfill > 0:
        # バックフィル: データを 1 回だけ収集し、日付ごとにレポート生成
        print("--- Reddit 収集（バックフィル） ---")
        reddit_posts = collect_reddit.collect(backfill=True)

        print("\n--- はてブ 収集 ---")
        hatena_posts = collect_hatena.collect()

        for i in range(args.backfill, 0, -1):
            target = today - timedelta(days=i)
            process_day(target.isoformat(), reddit_posts, hatena_posts)
            print("\n" + "=" * 60 + "\n")
    else:
        # 通常: 収集 → 抽出 → 保存
        print("--- Reddit 収集 ---")
        reddit_posts = collect_reddit.collect()

        print("\n--- はてブ 収集 ---")
        hatena_posts = collect_hatena.collect()

        process_day(today.isoformat(), reddit_posts, hatena_posts)


if __name__ == "__main__":
    main()
