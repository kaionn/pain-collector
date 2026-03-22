"""Google Play Store の低評価レビューからペインを収集する."""

from google_play_scraper import Sort, reviews

# 人気アプリの パッケージ名
TARGET_APPS = [
    # 生産性
    {"package": "com.slack", "name": "Slack"},
    {"package": "notion.id", "name": "Notion"},
    {"package": "com.todoist", "name": "Todoist"},
    # ライフスタイル
    {"package": "com.ubercab.eats", "name": "Uber Eats"},
    {"package": "com.kouzoh.mercari", "name": "Mercari"},
    # ヘルス
    {"package": "com.myfitnesspal.android", "name": "MyFitnessPal"},
]

MAX_REVIEWS_PER_APP = 30


def collect() -> list[dict]:
    """Google Play Store の低評価レビューを収集する."""
    all_reviews: list[dict] = []

    for app_info in TARGET_APPS:
        try:
            result, _ = reviews(
                app_info["package"],
                lang="ja",
                country="jp",
                sort=Sort.NEWEST,
                count=MAX_REVIEWS_PER_APP,
                filter_score_with=1,
            )

            for review in result:
                body = review.get("content", "")[:1000]
                if not body:
                    continue

                all_reviews.append({
                    "source": "googleplay",
                    "title": f"{app_info['name']}: {review.get('userName', '')}",
                    "url": f"https://play.google.com/store/apps/details?id={app_info['package']}",
                    "body": body,
                    "score": review.get("score", 1),
                })

            # 星 2 のレビューも取得
            result2, _ = reviews(
                app_info["package"],
                lang="ja",
                country="jp",
                sort=Sort.NEWEST,
                count=MAX_REVIEWS_PER_APP,
                filter_score_with=2,
            )

            for review in result2:
                body = review.get("content", "")[:1000]
                if not body:
                    continue

                all_reviews.append({
                    "source": "googleplay",
                    "title": f"{app_info['name']}: {review.get('userName', '')}",
                    "url": f"https://play.google.com/store/apps/details?id={app_info['package']}",
                    "body": body,
                    "score": review.get("score", 2),
                })

        except Exception as e:
            print(f"[GooglePlay] {app_info['name']} の取得に失敗: {e}")

    print(f"[GooglePlay] {len(all_reviews)} 件の低評価レビューを取得")
    return all_reviews
