"""pain-collector メインスクリプト.

SNS からペインを収集 → LLM で構造化 → Markdown で保存する.
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta

from . import collect_reddit, collect_hatena, collect_zenn, collect_hn, collect_note, extract_pains, feedback, market_check, notify, weekly_trends, deep_dive, issue_lifecycle

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

            # 市場データ（あれば）
            market_signal = item.get("market_signal")
            market_apps = item.get("market_apps", [])
            if market_signal:
                signal_label = {
                    "whitespace": "🟢 ホワイトスペース（競合なし）",
                    "underserved": "🟡 市場あり・満足度低い（チャンス）",
                    "emerging": "🟡 新興市場（レビュー少）",
                    "competitive": "🔴 競合が強い",
                }.get(market_signal, market_signal)
                lines.append(f"- 市場シグナル: {signal_label}")

                if market_apps:
                    for app in market_apps[:3]:
                        lines.append(
                            f"  - [{app['name']}]({app['url']}) "
                            f"⭐{app['rating']} ({app['reviews']}件) {app['price']}"
                        )

            lines.append("")

    return "\n".join(lines)


def process_day(
    date_str: str,
    reddit_posts: list[dict],
    hatena_posts: list[dict],
    zenn_posts: list[dict],
    hn_posts: list[dict] | None = None,
    note_posts: list[dict] | None = None,
) -> None:
    """1日分の抽出・保存を行う（収集済みデータを受け取る）."""
    print(f"=== Pain Collector: {date_str} ===\n")

    hn_posts = hn_posts or []
    note_posts = note_posts or []
    all_posts = reddit_posts + hatena_posts + zenn_posts + hn_posts + note_posts
    print(
        f"投稿数: Reddit {len(reddit_posts)} 件 + はてブ {len(hatena_posts)} 件"
        f" + Zenn {len(zenn_posts)} 件 + HN {len(hn_posts)} 件"
        f" + note {len(note_posts)} 件 = {len(all_posts)} 件\n"
    )

    # 生データを JSON で保存
    raw_dir = os.path.join(BASE_DIR, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{date_str}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "date": date_str,
                "reddit": reddit_posts,
                "hatena": hatena_posts,
                "zenn": zenn_posts,
                "hackernews": hn_posts,
                "note": note_posts,
            },
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

    # App Store で競合チェック（上位5件のみ）
    print("--- 競合チェック ---")
    pains = market_check.enrich_pains(pains, top_n=5)

    # レポート生成・保存
    report = generate_report(pains, date_str)
    output_dir = os.path.join(BASE_DIR, "daily")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{date_str}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nレポートを保存: {output_path}")
    print(f"ペイン件数: {len(pains)} 件")

    # LINE Notify で TOP3 を通知
    notify.send_top_pains(pains, date_str)

    # 高ポテンシャルなペインのディープダイブレポートを自動生成
    print("--- ディープダイブ ---")
    deep_dive.run(pains, date_str)


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
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="週次トレンド分析を実行する",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="フィードバック集計レポートを表示する",
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="フィードバックから学習ルールを抽出する",
    )
    parser.add_argument(
        "--deep-dive",
        action="store_true",
        help="高ポテンシャルなペインのディープダイブレポートを生成する",
    )
    parser.add_argument(
        "--deep-dive-weekly",
        action="store_true",
        help="週次ディープダイブ（上位5件）を生成する",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="stale Issue の整理と自動クローズを実行する",
    )
    parser.add_argument(
        "--score-issues",
        action="store_true",
        help="未スコアの Issue にスコアを付与する",
    )
    parser.add_argument(
        "--pick-idea",
        action="store_true",
        help="スコア上位の Issue から MVP 候補を選定する",
    )
    parser.add_argument(
        "--monthly",
        action="store_true",
        help="月次レポートを生成する",
    )
    parser.add_argument(
        "--cross-analysis",
        action="store_true",
        help="カテゴリ横断分析を実行する",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="GitHub Pages ダッシュボードを生成する",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="ポートフォリオスナップショットを生成する",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="スコア上位アイデアの自動仮説検証を実行する",
    )
    args = parser.parse_args()

    today = datetime.now(JST).date()

    if args.feedback:
        feedback.run()
        return

    if args.learn:
        feedback.learn_rules()
        return

    if args.weekly:
        weekly_trends.run(today)
        return

    if args.cleanup:
        issue_lifecycle.cleanup()
        return

    if args.score_issues:
        from . import scoring
        scoring.score_open_issues()
        return

    if args.pick_idea:
        from . import pick_idea
        pick_idea.run()
        return

    if args.monthly:
        from . import monthly_report
        monthly_report.run(today)
        return

    if args.cross_analysis:
        from . import cross_analysis
        cross_analysis.run(today)
        return

    if args.dashboard:
        from . import generate_dashboard
        generate_dashboard.run()
        return

    if args.portfolio:
        from . import portfolio
        portfolio.run()
        return

    if args.validate:
        from . import validate_idea
        validate_idea.run()
        return

    if args.deep_dive_weekly:
        # 週次ディープダイブ: 上位5件
        raw_path = os.path.join(BASE_DIR, "raw", f"{today.isoformat()}.json")
        if not os.path.exists(raw_path):
            print("本日の raw データがありません。先に日次収集を実行してください。")
            return
        with open(raw_path, encoding="utf-8") as f:
            raw_data = json.load(f)
        all_posts = (
            raw_data.get("reddit", []) + raw_data.get("hatena", [])
            + raw_data.get("zenn", []) + raw_data.get("hackernews", [])
            + raw_data.get("note", [])
        )
        pains = extract_pains.extract(all_posts)
        pains = market_check.enrich_pains(pains, top_n=5)
        deep_dive.run(pains, today.isoformat(), top_n=5)
        return

    if args.deep_dive:
        # 直近の日次レポートの raw データからディープダイブ対象を探す
        raw_path = os.path.join(BASE_DIR, "raw", f"{today.isoformat()}.json")
        if not os.path.exists(raw_path):
            print("本日の raw データがありません。先に日次収集を実行してください。")
            return
        with open(raw_path, encoding="utf-8") as f:
            raw_data = json.load(f)
        all_posts = (
            raw_data.get("reddit", []) + raw_data.get("hatena", [])
            + raw_data.get("zenn", []) + raw_data.get("hackernews", [])
            + raw_data.get("note", [])
        )
        pains = extract_pains.extract(all_posts)
        pains = market_check.enrich_pains(pains, top_n=5)
        deep_dive.run(pains, today.isoformat())
        return

    if args.backfill > 0:
        # バックフィル: データを 1 回だけ収集し、日付ごとにレポート生成
        print("--- Reddit 収集（バックフィル） ---")
        reddit_posts = collect_reddit.collect(backfill=True)

        print("\n--- はてブ 収集 ---")
        hatena_posts = collect_hatena.collect()

        print("\n--- Zenn 収集 ---")
        zenn_posts = collect_zenn.collect()

        print("\n--- Hacker News 収集 ---")
        hn_posts = collect_hn.collect()

        print("\n--- note 収集 ---")
        note_posts = collect_note.collect()

        for i in range(args.backfill, 0, -1):
            target = today - timedelta(days=i)
            process_day(target.isoformat(), reddit_posts, hatena_posts, zenn_posts, hn_posts, note_posts)
            print("\n" + "=" * 60 + "\n")
    else:
        # 通常: 収集 → 抽出 → 保存
        print("--- Reddit 収集 ---")
        reddit_posts = collect_reddit.collect()

        print("\n--- はてブ 収集 ---")
        hatena_posts = collect_hatena.collect()

        print("\n--- Zenn 収集 ---")
        zenn_posts = collect_zenn.collect()

        print("\n--- Hacker News 収集 ---")
        hn_posts = collect_hn.collect()

        print("\n--- note 収集 ---")
        note_posts = collect_note.collect()

        process_day(today.isoformat(), reddit_posts, hatena_posts, zenn_posts, hn_posts, note_posts)


if __name__ == "__main__":
    main()
