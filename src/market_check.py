"""競合チェック: App Store で既存ソリューションを検索する."""

import json
import os
import subprocess

import requests

from src.http_utils import create_retry_session

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINES_PATH = os.path.join(BASE_DIR, "data", "market_baselines.json")

# フォールバック閾値（蓄積データ不足時）
DEFAULT_RATING_THRESHOLD = 3.5
DEFAULT_REVIEWS_THRESHOLD = 1000
MIN_SAMPLES_FOR_BASELINE = 10

_session = create_retry_session()


def _load_baselines() -> dict:
    """カテゴリ別の市場ベースラインデータを読み込む."""
    if not os.path.exists(BASELINES_PATH):
        return {}
    try:
        with open(BASELINES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_baselines(baselines: dict) -> None:
    """カテゴリ別の市場ベースラインデータを保存する."""
    os.makedirs(os.path.dirname(BASELINES_PATH), exist_ok=True)
    with open(BASELINES_PATH, "w", encoding="utf-8") as f:
        json.dump(baselines, f, ensure_ascii=False, indent=2)


def _update_baseline(category: str, apps: list[dict]) -> None:
    """検索結果からカテゴリ別ベースラインを更新する."""
    if not category or not apps:
        return

    baselines = _load_baselines()
    entry = baselines.get(category, {"ratings": [], "review_counts": []})

    for app in apps:
        if app.get("rating", 0) > 0:
            entry["ratings"].append(app["rating"])
        if app.get("reviews", 0) > 0:
            entry["review_counts"].append(app["reviews"])

    # 最新 100 件まで保持
    entry["ratings"] = entry["ratings"][-100:]
    entry["review_counts"] = entry["review_counts"][-100:]

    baselines[category] = entry
    _save_baselines(baselines)


def _get_category_thresholds(category: str) -> tuple[float, int]:
    """カテゴリ別の閾値を返す。データ不足時はデフォルト値にフォールバック."""
    baselines = _load_baselines()
    entry = baselines.get(category, {})
    ratings = entry.get("ratings", [])
    review_counts = entry.get("review_counts", [])

    if len(ratings) < MIN_SAMPLES_FOR_BASELINE:
        return DEFAULT_RATING_THRESHOLD, DEFAULT_REVIEWS_THRESHOLD

    avg_rating = sum(ratings) / len(ratings)
    avg_reviews = sum(review_counts) / len(review_counts) if review_counts else DEFAULT_REVIEWS_THRESHOLD

    # カテゴリ平均 - 0.5 を underserved 閾値とする
    rating_threshold = avg_rating - 0.5
    reviews_threshold = int(avg_reviews * 0.5)

    return rating_threshold, reviews_threshold


def _extract_search_keywords(app_idea: str, category: str = "") -> list[str]:
    """app_idea から App Store 検索に適した英語キーワードを 3 セット抽出する."""
    token = os.environ.get("GITHUB_TOKEN", "")
    prompt = (
        "以下のアプリアイデアから、App Store で検索するための英語キーワードセットを3つ生成してください。\n"
        "各キーワードセットは2-3語で、異なる言い回し・同義語を使ってください。\n"
        "1行に1キーワードセット、計3行のみを出力してください（説明不要）。\n\n"
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
                max_tokens=60,
            )
            content = (response.choices[0].message.content or "").strip()
        else:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                content = result.stdout.strip()
            else:
                return [app_idea[:50]]

        keywords = [line.strip() for line in content.splitlines() if line.strip()]
        return keywords[:3] if keywords else [app_idea[:50]]
    except Exception as e:
        print(f"[AppStore] キーワード抽出失敗、フォールバック: {e}")

    return [app_idea[:50]]


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
    keywords = _extract_search_keywords(idea, category)
    print(f"[AppStore] 検索キーワード: {keywords}")

    # 全キーワードで US + JP 両方を検索してマージ
    seen_names: set[str] = set()
    apps: list[dict] = []
    for kw in keywords:
        for country in ("us", "jp"):
            for app in check_app_store(kw, country=country, limit=3):
                if app["name"] not in seen_names:
                    seen_names.add(app["name"])
                    apps.append(app)
    apps = apps[:5]

    if not apps:
        pain["market_apps"] = []
        pain["market_signal"] = "whitespace"
        return pain

    # ベースラインを更新
    _update_baseline(category, apps)

    avg_rating = sum(a["rating"] for a in apps) / len(apps)
    total_reviews = sum(a["reviews"] for a in apps)

    # カテゴリ別閾値で判定
    rating_threshold, reviews_threshold = _get_category_thresholds(category)

    if total_reviews == 0:
        signal = "whitespace"
    elif avg_rating < rating_threshold:
        signal = "underserved"  # カテゴリ平均以下 → 満足度が低い
    elif total_reviews < reviews_threshold:
        signal = "emerging"  # レビュー数がカテゴリ平均の半分以下 → 新興市場
    else:
        signal = "competitive"  # 競合が強い

    pain["market_apps"] = apps
    pain["market_signal"] = signal

    # 競合アプリの低評価レビューからペインを逆抽出
    if apps and signal in ("underserved", "competitive"):
        competitor_pains = extract_competitor_pains(apps)
        if competitor_pains:
            pain["competitor_pains"] = competitor_pains

    return pain


COMPETITOR_REVIEW_PROMPT = """\
以下は App Store で見つかった競合アプリの低評価レビュー（★1-2）です。
これらのレビューから「このアプリに足りないもの・改善点」をペインとして抽出してください。

以下の JSON 配列形式で出力してください（コードブロック不要）:
[
  {
    "pain": "不満・改善点の要約（1文）",
    "competitor_name": "対象アプリ名",
    "opportunity": "この不満を解決するプロダクトアイデア（1文）"
  }
]

ルール:
- 具体的で actionable な不満を優先する
- 「使いにくい」のような曖昧な不満はスキップ
- 最大 5 件まで
"""


def extract_competitor_pains(apps: list[dict]) -> list[dict]:
    """競合アプリの低評価レビューからペインを逆抽出する."""
    from src.collect_appstore import _fetch_reviews

    all_review_texts = []
    for app in apps[:3]:
        app_url = app.get("url", "")
        # App Store URL から app_id を抽出
        app_id = ""
        if "/id" in app_url:
            app_id = app_url.split("/id")[-1].split("?")[0]
        if not app_id:
            continue

        entries = _fetch_reviews(app_id, country="jp")
        for entry in entries:
            try:
                rating = int(entry.get("im:rating", {}).get("label", "5"))
            except (ValueError, TypeError, AttributeError):
                continue
            if rating > 2:
                continue
            body = entry.get("content", {}).get("label", "")[:500]
            if body:
                all_review_texts.append(f"[{app['name']}] ★{rating}: {body}")

    if not all_review_texts:
        return []

    review_text = "\n---\n".join(all_review_texts[:15])
    prompt = f"{COMPETITOR_REVIEW_PROMPT}\n\n--- レビュー ---\n{review_text}"

    token = os.environ.get("GITHUB_TOKEN", "")
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
                temperature=0.3,
            )
            content = response.choices[0].message.content or "[]"
        else:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return []
            content = result.stdout.strip()

        from src.extract_pains import _parse_json_response
        pains = _parse_json_response(content)
        print(f"[AppStore] 競合レビューから {len(pains)} 件のペインを逆抽出")
        return pains
    except Exception as e:
        print(f"[AppStore] 競合レビュー分析失敗: {e}")
        return []


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
