"""App Store の RSS フィードから低評価レビューを収集する."""

import json

from src.http_utils import create_retry_session

# Apple の公開 RSS JSON エンドポイント
# https://rss.applemarketingtools.com/ 経由でレビューを取得
TARGET_APPS = [
    {"app_id": "1232780281", "name": "Notion"},
    {"app_id": "585829637", "name": "Todoist"},
    {"app_id": "618783545", "name": "Slack"},
    {"app_id": "1058959277", "name": "Uber Eats"},
    {"app_id": "896130944", "name": "Mercari"},
    {"app_id": "341232718", "name": "MyFitnessPal"},
]

_session = create_retry_session()


def _fetch_reviews(app_id: str, country: str = "jp") -> list[dict]:
    """Apple の公開 JSON エンドポイントからレビューを取得する."""
    url = f"https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("feed", {}).get("entry", [])
        # 最初のエントリはアプリ情報なのでスキップ
        return entries[1:] if len(entries) > 1 else []
    except Exception as e:
        print(f"[AppStore] app_id={app_id} の取得に失敗: {e}")
        return []


def collect() -> list[dict]:
    """App Store の低評価レビューを収集する."""
    all_reviews: list[dict] = []

    for app_info in TARGET_APPS:
        entries = _fetch_reviews(app_info["app_id"])

        for entry in entries:
            try:
                rating = int(entry.get("im:rating", {}).get("label", "5"))
            except (ValueError, TypeError, AttributeError):
                continue

            if rating > 2:
                continue

            title = entry.get("title", {}).get("label", "")
            body = entry.get("content", {}).get("label", "")[:1000]
            if not body:
                continue

            all_reviews.append({
                "source": "appstore",
                "title": f"{app_info['name']}: {title}",
                "url": f"https://apps.apple.com/app/id{app_info['app_id']}",
                "body": body,
                "score": rating,
            })

    print(f"[AppStore] {len(all_reviews)} 件の低評価レビューを取得")
    return all_reviews
