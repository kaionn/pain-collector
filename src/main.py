"""pain-collector メインスクリプト.

SNS からペインを収集 → LLM で構造化 → Markdown で保存する.
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone, timedelta

# collect_* は @register_collector の副作用で collector_registry に登録するためだけに import する
# （_collect_all は collector_registry.all_collectors() 経由で呼び出す）
from . import collector_registry, collect_reddit, collect_hatena, collect_zenn, collect_hn, collect_note, collect_devto, collect_stackoverflow, collect_bluesky, collect_appstore, collect_googleplay, collect_chiebukuro, collect_girlschannel, collect_producthunt, collect_komachi, collect_mamastar, extract_pains, feedback, market_check, notify, weekly_trends, deep_dive, issue_lifecycle, generate_spec

logger = logging.getLogger(__name__)

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

            # エンゲージメント情報
            engagement = item.get("source_engagement", {})
            if engagement:
                eng_parts = []
                eng_labels = {"score": "👍", "num_comments": "💬", "bookmarks": "🔖", "view_count": "👀", "answer_count": "✅"}
                for key, emoji in eng_labels.items():
                    if key in engagement:
                        eng_parts.append(f"{emoji}{engagement[key]}")
                if eng_parts:
                    lines.append(f"- エンゲージメント: {' '.join(eng_parts)}")

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


# ソースごとの LLM 投入上限（raw 保存は全件、LLM に渡す件数を制限してバランスを取る）
SOURCE_POST_LIMITS: dict[str, int] = {
    "googleplay": 100,
    "appstore": 80,
    "stackoverflow": 30,
    "reddit": 150,
    "hackernews": 50,
}
DEFAULT_POST_LIMIT = 100


def _apply_post_limits(sources: dict[str, list[dict]]) -> list[dict]:
    """ソースごとの上限を適用して LLM に渡す投稿リストを作成する."""
    import random

    all_posts: list[dict] = []
    summary_parts: list[str] = []

    for name, posts in sources.items():
        limit = SOURCE_POST_LIMITS.get(name, DEFAULT_POST_LIMIT)
        if len(posts) > limit:
            selected = random.sample(posts, limit)
            logger.info(f"  {name}: {len(posts)} → {limit} 件にサンプリング")
        else:
            selected = posts
        all_posts.extend(selected)
        summary_parts.append(f"{name} {len(selected)}/{len(posts)}")

    logger.info(f"LLM 投入: {' + '.join(summary_parts)} = {len(all_posts)} 件")
    return all_posts


def process_day(
    date_str: str,
    sources: dict[str, list[dict]],
) -> int:
    """1日分の抽出・保存を行う（収集済みデータを受け取る）. 抽出したペイン件数を返す."""
    logger.info(f"=== Pain Collector: {date_str} ===")

    # 生データを JSON で全件保存
    raw_dir = os.path.join(BASE_DIR, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{date_str}.json")
    raw_data = {"date": date_str}
    raw_data.update(sources)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    logger.info(f"生データを保存: {raw_path}")

    # ソースごとの上限を適用して LLM に渡す投稿を選定
    all_posts = _apply_post_limits(sources)

    if not all_posts:
        logger.info("投稿が0件のため終了")
        return 0

    # LLM でペイン抽出
    logger.info("--- ペイン抽出 ---")
    pains = extract_pains.extract(all_posts)

    if not pains:
        logger.info("ペインが0件のため終了")
        return 0

    # App Store で競合チェック（上位5件のみ）
    logger.info("--- 競合チェック ---")
    pains = market_check.enrich_pains(pains, top_n=5)

    # レポート生成・保存
    report = generate_report(pains, date_str)
    output_dir = os.path.join(BASE_DIR, "daily")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{date_str}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"レポートを保存: {output_path}")
    logger.info(f"ペイン件数: {len(pains)} 件")

    # 深刻度上位のペインを GitHub Issue として作成し、Discord digest で通知
    notify.send_top_pains(pains, date_str)

    # 高ポテンシャルなペインのディープダイブレポートを自動生成
    logger.info("--- ディープダイブ ---")
    deep_dive.run(pains, date_str)

    # Deep Dive から技術 Spec を自動生成
    logger.info("--- Spec 生成 ---")
    generate_spec.run_for_latest(date_str)

    # 日次サマリー生成
    _write_daily_summary(date_str, sources, pains)

    return len(pains)


def _write_daily_summary(date_str: str, sources: dict[str, list[dict]], pains: list[dict]) -> None:
    """日次サマリーを生成し、GitHub Actions Job Summary に出力する."""
    source_lines = ", ".join(f"{name} {len(posts)}件" for name, posts in sources.items())
    total_posts = sum(len(v) for v in sources.values())

    # スコアランク集計
    score_s = sum(1 for p in pains if p.get("total_score", 0) >= 48)
    score_a = sum(1 for p in pains if 36 <= p.get("total_score", 0) < 48)

    # 市場シグナル集計
    whitespace = sum(1 for p in pains if p.get("market_signal") == "whitespace")
    underserved = sum(1 for p in pains if p.get("market_signal") == "underserved")

    summary = (
        f"## 📊 Pain Collector Daily Summary ({date_str})\n\n"
        f"| 項目 | 値 |\n"
        f"|------|----|\n"
        f"| 収集投稿数 | {total_posts} 件 |\n"
        f"| 抽出ペイン数 | {len(pains)} 件 |\n"
        f"| スコア S/A | {score_s}/{score_a} 件 |\n"
        f"| ホワイトスペース | {whitespace} 件 |\n"
        f"| 低満足度市場 | {underserved} 件 |\n\n"
        f"収集内訳: {source_lines}\n"
    )

    logger.info(f"日次サマリー:\n{summary}")

    # GitHub Actions Job Summary に出力
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(summary + "\n")
            logger.info("GitHub Actions Job Summary に出力")
        except Exception as e:
            logger.warning(f"Job Summary 出力失敗: {e}")


SOURCE_HEALTH_PATH = os.path.join(BASE_DIR, "data", "source_health.json")


def _load_source_health() -> dict:
    """ソースの健全性データを読み込む."""
    if not os.path.exists(SOURCE_HEALTH_PATH):
        return {}
    try:
        with open(SOURCE_HEALTH_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _update_source_health(sources: dict[str, list[dict]], today_str: str) -> None:
    """収集結果からソースの健全性データを更新する."""
    health = _load_source_health()

    for source_key, posts in sources.items():
        entry = health.get(source_key, {"last_success": None, "consecutive_failures": 0})

        if posts:
            entry["last_success"] = today_str
            entry["consecutive_failures"] = 0
        else:
            entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1

        health[source_key] = entry

    os.makedirs(os.path.dirname(SOURCE_HEALTH_PATH), exist_ok=True)
    with open(SOURCE_HEALTH_PATH, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)

    # 連続失敗の警告
    for source_key, entry in health.items():
        failures = entry.get("consecutive_failures", 0)
        if failures >= 3:
            logger.warning(f"⚠️ {source_key} が {failures} 日連続で失敗中（最終成功: {entry.get('last_success', '不明')}）")


def _setup_logging() -> None:
    """ロガーの初期化（コンソール + ファイル）."""
    logs_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    date_str = datetime.now(JST).date().isoformat()
    log_path = os.path.join(logs_dir, f"{date_str}.log")

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def main() -> None:
    """メイン処理."""
    _setup_logging()
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
        "--regate",
        action="store_true",
        help="既存 open Issue を actionability ゲートで再評価する（dry-run）",
    )
    parser.add_argument(
        "--regate-apply",
        action="store_true",
        help="既存 open Issue を actionability ゲートで再評価し、reject 分をクローズする",
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

    if args.regate_apply:
        issue_lifecycle.regate(apply=True)
        return

    if args.regate:
        issue_lifecycle.regate(apply=False)
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

    def _load_all_posts_from_raw(date_str: str) -> list[dict] | None:
        """raw JSON から全ソースの投稿を結合して返す."""
        raw_path = os.path.join(BASE_DIR, "raw", f"{date_str}.json")
        if not os.path.exists(raw_path):
            logger.warning("本日の raw データがありません。先に日次収集を実行してください。")
            return None
        with open(raw_path, encoding="utf-8") as f:
            raw_data = json.load(f)
        all_posts: list[dict] = []
        for key, value in raw_data.items():
            if key != "date" and isinstance(value, list):
                all_posts.extend(value)
        return all_posts

    if args.deep_dive_weekly:
        all_posts = _load_all_posts_from_raw(today.isoformat())
        if all_posts is None:
            return
        pains = extract_pains.extract(all_posts)
        pains = market_check.enrich_pains(pains, top_n=5)
        deep_dive.run(pains, today.isoformat(), top_n=5)
        return

    if args.deep_dive:
        all_posts = _load_all_posts_from_raw(today.isoformat())
        if all_posts is None:
            return
        pains = extract_pains.extract(all_posts)
        pains = market_check.enrich_pains(pains, top_n=5)
        deep_dive.run(pains, today.isoformat())
        return

    def _collect_all(backfill: bool = False) -> dict[str, list[dict]]:
        """全ソースからデータを収集し、サマリーを表示する（registry 駆動）."""
        sources: dict[str, list[dict]] = {}
        entries = collector_registry.all_collectors()

        for entry in entries:
            suffix = "（バックフィル）" if backfill and entry.supports_backfill else ""
            logger.info(f"--- {entry.display_name} 収集{suffix} ---")
            try:
                posts = entry.fn(backfill=backfill) if entry.supports_backfill else entry.fn()
            except Exception as e:
                logger.warning(f"{entry.display_name} でエラー: {e}")
                posts = []

            validated = []
            dropped = 0
            for post in posts:
                v = collector_registry.validate_post(post, entry.key)
                if v is None:
                    dropped += 1
                else:
                    validated.append(v)
            if dropped:
                logger.info(f"  {entry.display_name}: 不正な post を {dropped} 件 drop")

            sources[entry.key] = validated

        # 収集サマリー
        total = sum(len(v) for v in sources.values())
        logger.info("--- 収集サマリー ---")
        for entry in entries:
            posts = sources[entry.key]
            status = "OK" if posts else "EMPTY"
            logger.info(f"  [{status}] {entry.display_name}: {len(posts)} 件")
        logger.info(f"  合計: {total} 件")

        # ソースの健全性を更新
        _update_source_health(sources, today.isoformat())

        return sources

    if args.backfill > 0:
        sources = _collect_all(backfill=True)
        pains_count = 0
        for i in range(args.backfill, 0, -1):
            target = today - timedelta(days=i)
            pains_count = process_day(target.isoformat(), sources)
            logger.info("=" * 60)
    else:
        sources = _collect_all()
        pains_count = process_day(today.isoformat(), sources)

    _check_and_alert(sources, pains_count)


def _check_and_alert(sources: dict[str, list[dict]], pains_count: int) -> None:
    """日次実行の健全性をチェックし、異常があれば Discord にアラートする.

    チェック・通知自体の失敗でパイプラインを落とさない。
    """
    try:
        from . import discord_notify, run_health

        problems = run_health.check_daily_run(sources, pains_count)
        if problems:
            discord_notify.notify_pipeline_alert(problems)
    except Exception as e:
        logger.warning(f"健全性チェック失敗: {e}")


if __name__ == "__main__":
    main()
