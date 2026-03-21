"""競合チェック: App Store で既存ソリューションを検索する."""

import os
import subprocess

import requests

from src.http_utils import create_retry_session

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


_session = create_retry_session()


def _extract_search_keywords(app_idea: str, category: str = "") -> str:
    """app_idea から App Store 検索に適した英語キーワードを抽出する."""
    token = os.environ.get("GITHUB_TOKEN", "")
    prompt = (
        "以下のアプリアイデアから、App Store で検索するための英語キーワードを2-3語で抽出してください。\n"
        "キーワードのみを出力してください（説明不要）。\n\n"
        f"アイデア: {app_idea}\n"
        f"カテゴリ: {category}\n"
    )

    try:
        if token:
            from openai import OpenAI
            client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=token,
            )
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=20,
            )
            return (response.choices[0].message.content or "").strip()
        else:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception as e:
        print(f"[AppStore] キーワード抽出失敗、フォールバック: {e}")

    return app_idea[:50]


def check_app_store(keyword: str, country: str = "us", limit: int = 5) -> list[dict]:
    """iTunes Search API でアプリを検索する."""
    try:
        resp = _session.get(
            ITUNES_SEARCH_URL,
            params={
                "term": keyword,
                "entity": "software",
                "limit": limit,
                "country": country,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[AppStore] 検索失敗 ({keyword}, {country}): {e}")
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

    category = pain.get("category", "")
    keyword = _extract_search_keywords(idea, category)
    print(f"[AppStore] 検索キーワード: {keyword}")

    # US + JP 両方を検索してマージ
    apps_us = check_app_store(keyword, country="us", limit=3)
    apps_jp = check_app_store(keyword, country="jp", limit=3)

    # 重複排除してマージ（名前ベース）
    seen_names = set()
    apps = []
    for app in apps_us + apps_jp:
        if app["name"] not in seen_names:
            seen_names.add(app["name"])
            apps.append(app)
    apps = apps[:5]

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
