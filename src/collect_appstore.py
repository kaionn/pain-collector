"""App Store の RSS フィードから低評価レビューを収集する."""

import json
import logging

from src.http_utils import create_retry_session

logger = logging.getLogger(__name__)

# Apple の公開 RSS JSON エンドポイント
# https://rss.applemarketingtools.com/ 経由でレビューを取得
TARGET_APPS = [
    # 生産性
    {"app_id": "1232780281", "name": "Notion"},
    {"app_id": "585829637", "name": "Todoist"},
    {"app_id": "618783545", "name": "Slack"},
    # ライフスタイル
    {"app_id": "1058959277", "name": "Uber Eats"},
    {"app_id": "896130944", "name": "Mercari"},
    # ヘルス
    {"app_id": "341232718", "name": "MyFitnessPal"},
    # 料理
    {"app_id": "1059498728", "name": "クラシル"},
    {"app_id": "340368403", "name": "クックパッド"},
    # 健康・ダイエット
    {"app_id": "986692880", "name": "あすけん"},
    # 家計
    {"app_id": "594145971", "name": "マネーフォワード ME"},
    {"app_id": "581689724", "name": "Zaim"},
    # 子育て
    {"app_id": "1124977949", "name": "ママリ"},
    {"app_id": "935560915", "name": "みてね"},
    # 予約・決済
    {"app_id": "261654104", "name": "ホットペッパーグルメ"},
    {"app_id": "1435783608", "name": "PayPay"},
    # 移動・通勤
    {"app_id": "291676451", "name": "Yahoo!乗換案内"},
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
        logger.warning(f"app_id={app_id} の取得に失敗: {e}")
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

    logger.info(f"{len(all_reviews)} 件の低評価レビューを取得")
    return all_reviews
