"""競合チェック: App Store で既存ソリューションを検索する."""

import requests

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def check_app_store(keyword: str, limit: int = 5) -> list[dict]:
    """iTunes Search API でアプリを検索する."""
    try:
        resp = requests.get(
            ITUNES_SEARCH_URL,
            params={
                "term": keyword,
                "entity": "software",
                "limit": limit,
                "country": "us",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[AppStore] 検索失敗 ({keyword}): {e}")
        return []

    apps = []
    for r in data.get("results", []):
        apps.append({
            "name": r.get("trackName", ""),
            "rating": round(r.get("averageUserRating", 0), 1),
            "reviews": r.get("userRatingCount", 0),
            "price": r.get("formattedPrice", "Free"),
            "url": r.get("trackViewUrl", ""),
        })

    return apps


def enrich_pain_with_market_data(pain: dict) -> dict:
    """ペインに App Store の競合データを付加する."""
    idea = pain.get("app_idea", "")
    if not idea:
        return pain

    # アイデアからキーワードを抽出（LLM を使わず簡易的に）
    # app_idea をそのまま検索ワードに使う
    keyword = idea[:50]  # API の検索は短い方が精度が高い
    apps = check_app_store(keyword, limit=3)

    if not apps:
        pain["market_apps"] = []
        pain["market_signal"] = "whitespace"
        return pain

    avg_rating = sum(a["rating"] for a in apps) / len(apps)
    total_reviews = sum(a["reviews"] for a in apps)

    if total_reviews == 0:
        signal = "whitespace"
    elif avg_rating < 3.5:
        signal = "underserved"  # 市場はあるが満足度が低い
    elif total_reviews < 1000:
        signal = "emerging"  # 新しい市場
    else:
        signal = "competitive"  # 競合が強い

    pain["market_apps"] = apps
    pain["market_signal"] = signal

    return pain


def enrich_pains(pains: list[dict], top_n: int = 5) -> list[dict]:
    """深刻度が高い上位 N 件のペインに市場データを付加する.

    全件に対して API を叩くとレート制限に引っかかるため、
    深刻度 × 課金意欲でスコアリングして上位のみチェックする。
    """
    wtp_score = {"high": 4, "medium": 3, "low": 2, "free": 1}

    scored = []
    for p in pains:
        s = p.get("severity", 0) * wtp_score.get(p.get("willingness_to_pay", "free"), 1)
        scored.append((s, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    enriched_count = 0
    for _, pain in scored:
        if enriched_count >= top_n:
            break
        enrich_pain_with_market_data(pain)
        enriched_count += 1

    return pains
