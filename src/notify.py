"""GitHub Issues でペインを個別 Issue として作成する（重複チェック付き）."""

import json
import logging
import re
import subprocess

from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

from src import llm_client
from src.tokenizer import create_tfidf_vectorizer

# Issue 本文に埋め込むプロダクトキーのメタデータマーカー
_PRODUCT_KEY_MARKER_RE = re.compile(r"<!--\s*product:([a-z0-9_\-:.]+)\s*-->", re.IGNORECASE)

# Issue 本文に埋め込む元ペインデータのメタデータマーカー（再スコア時の SSOT）
_PAIN_DATA_MARKER_RE = re.compile(r"<!--\s*pain-data:(.+?)\s*-->", re.DOTALL)

# score_open_issues() の再スコアリングに必要なキーのみ埋め込む
_PAIN_DATA_KEYS = (
    "pain",
    "app_idea",
    "existing_solutions",
    "severity",
    "willingness_to_pay",
    "category",
    "source_engagement",
)

PRODUCT_TYPE_LABELS = {
    "モバイルアプリ": "📱モバイルアプリ",
    "Webサービス": "🌐Webサービス",
    "ブラウザ拡張": "🧩ブラウザ拡張",
    "CLI・開発ツール": "⌨️CLI・開発ツール",
    "API・SaaS": "☁️API・SaaS",
}

WTP_LABELS = {
    "high": "💰high",
    "medium": "💰medium",
    "low": "💰low",
    "free": "💰free",
}

DUPLICATE_THRESHOLD_HIGH = 0.7  # 確実に重複
DUPLICATE_THRESHOLD_LOW = 0.4   # グレーゾーン（LLM で二次判定）


def _extract_product_key(source_url: str | None) -> str | None:
    """source_url から「同一プロダクト」を識別するキーを抽出する.

    App Store レビューや特定の Q&A スレッドなど、URL から確実に
    プロダクト/スレッドを特定できるソースに限り key を返す。
    Reddit のサブレディットや Twitter は同一プロダクトを意味しないので除外。

    例:
      https://apps.apple.com/app/id1232780281 -> appstore:1232780281
      https://apps.apple.com/jp/app/notion/id1232780281 -> appstore:1232780281
      https://news.ycombinator.com/item?id=48060054 -> hn:48060054
      https://stackoverflow.com/questions/67855644/... -> so:67855644
      https://togetter.com/li/2695085 -> togetter:2695085
    """
    if not source_url:
        return None

    m = re.search(r"apps\.apple\.com/[^?#]*?/id(\d+)", source_url, re.IGNORECASE)
    if m:
        return f"appstore:{m.group(1)}"

    m = re.search(r"news\.ycombinator\.com/item\?id=(\d+)", source_url, re.IGNORECASE)
    if m:
        return f"hn:{m.group(1)}"

    m = re.search(r"stackoverflow\.com/questions/(\d+)", source_url, re.IGNORECASE)
    if m:
        return f"so:{m.group(1)}"

    m = re.search(r"togetter\.com/li/(\d+)", source_url, re.IGNORECASE)
    if m:
        return f"togetter:{m.group(1)}"

    return None


def _extract_product_key_from_body(body: str | None) -> str | None:
    """Issue 本文から `<!-- product:KEY -->` メタデータを抽出する.

    メタデータが無い古い Issue の場合は、本文中の `## ソース` セクションの
    URL から再抽出を試みる（後方互換）。
    """
    if not body:
        return None

    m = _PRODUCT_KEY_MARKER_RE.search(body)
    if m:
        return m.group(1).lower()

    # 後方互換: 本文中のリンクから URL を拾って _extract_product_key にかける
    for url_match in re.finditer(r"https?://[^\s)\]]+", body):
        key = _extract_product_key(url_match.group(0))
        if key:
            return key

    return None


def _sanitize_for_html_comment(value):
    """HTML コメントに埋め込む値から `-->` を除去する（コメント終端の破壊を防ぐ）."""
    if isinstance(value, str):
        return value.replace("-->", "")
    if isinstance(value, dict):
        return {k: _sanitize_for_html_comment(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_html_comment(v) for v in value]
    return value


def _build_pain_data_comment(pain: dict) -> str:
    """再スコアリングに必要な pain データを不可視 HTML コメントとして埋め込む文字列を作る."""
    data = {key: pain[key] for key in _PAIN_DATA_KEYS if key in pain}
    sanitized = _sanitize_for_html_comment(data)
    compact = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    return f"<!-- pain-data:{compact} -->"


def extract_pain_data_from_body(body: str | None) -> dict | None:
    """Issue 本文から `<!-- pain-data:{json} -->` メタデータを抽出する.

    メタデータが無い（古い Issue）・パース失敗の場合は None を返す。
    呼び出し側はタイトルからの簡易復元にフォールバックすること。
    """
    if not body:
        return None

    m = _PAIN_DATA_MARKER_RE.search(body)
    if not m:
        return None

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    return data


def _fetch_open_issues() -> list[dict]:
    """open 状態の Issue を取得する（番号・タイトル・本文）.

    本文は同一プロダクトの重複検出に使う。
    """
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "open",
                "--json", "number,title,body",
                "--limit", "200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return []


def _find_duplicate_by_product(
    product_key: str | None, existing_issues: list[dict]
) -> dict | None:
    """同一プロダクトキーを持つ既存 open Issue を返す.

    App Store 同一アプリの別バグレポート等、TF-IDF では拾えない
    「同じプロダクトに対する違うペイン」をまとめるための重複検出。
    """
    if not product_key or not existing_issues:
        return None

    for issue in existing_issues:
        existing_key = _extract_product_key_from_body(issue.get("body"))
        if existing_key == product_key:
            return issue
    return None


def _llm_judge_duplicate(pain_text: str, existing_title: str) -> bool:
    """LLM でグレーゾーンの重複を二次判定する（GITHUB_TOKEN がない環境ではスキップ）."""
    import os

    if not os.environ.get("GITHUB_TOKEN"):
        return False

    prompt = (
        "以下の2つのペインが実質的に同じ課題を指しているか判定してください。\n"
        "同じ課題なら YES、異なる課題なら NO とだけ答えてください。\n\n"
        f"ペイン A: {pain_text}\n"
        f"ペイン B: {existing_title}\n"
    )

    try:
        answer = llm_client.chat(prompt, temperature=0, max_tokens=10).strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        logger.warning(f"LLM 二次判定失敗: {e}")
        return False


def _find_duplicate(pain_text: str, existing_issues: list[dict]) -> dict | None:
    """既存 Issue の中から重複を検出する（2 段階判定）.

    1. TF-IDF cosine similarity >= 0.7 → 確実に重複
    2. 0.4 <= similarity < 0.7 → LLM で二次判定
    """
    if not existing_issues:
        return None

    titles = [issue["title"] for issue in existing_issues]
    corpus = titles + [pain_text]

    try:
        tfidf = create_tfidf_vectorizer().fit_transform(corpus)
        sims = cosine_similarity(tfidf[-1:], tfidf[:-1]).flatten()

        max_idx = sims.argmax()
        max_sim = sims[max_idx]

        if max_sim >= DUPLICATE_THRESHOLD_HIGH:
            return existing_issues[max_idx]

        if max_sim >= DUPLICATE_THRESHOLD_LOW:
            logger.info(f"グレーゾーン (sim={max_sim:.2f}) → LLM 二次判定")
            if _llm_judge_duplicate(pain_text, titles[max_idx]):
                return existing_issues[max_idx]
    except ValueError:
        pass

    return None


def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> None:
    """深刻度が高いペイン TOP N を個別の GitHub Issue として作成する.

    重複検出は 2 段階:
      1. 同一プロダクトキー（App Store の app_id 等）で既存 Issue にコメント化
      2. それ以外は pain_text の TF-IDF cosine similarity で判定
    Discord 通知は個別通知をやめ、本関数の最後に当日分の digest をまとめて送信する。
    """
    if not pains:
        return

    existing_issues = _fetch_open_issues()
    logger.info(f"既存 open Issue: {len(existing_issues)} 件")

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    created_for_digest: list[dict] = []

    for pain in top:
        product_key = _extract_product_key(pain.get("source_url"))
        product_duplicate = _find_duplicate_by_product(product_key, existing_issues)

        if product_duplicate:
            logger.info(
                f"プロダクト重複検出 ({product_key}) → "
                f"#{product_duplicate['number']} {product_duplicate['title'][:50]}"
            )
            _comment_duplicate(product_duplicate["number"], pain, date_str)
            continue

        pain_text = pain.get("pain", "")
        duplicate = _find_duplicate(pain_text, existing_issues)

        if duplicate:
            logger.info(f"重複検出 → #{duplicate['number']} {duplicate['title'][:50]}")
            _comment_duplicate(duplicate["number"], pain, date_str)
        else:
            issue = _create_issue(pain, date_str, notify_discord=False)
            if issue:
                existing_issues.append({**issue, "body": issue.get("body", "")})
                created_for_digest.append({**issue, "pain": pain})

    if created_for_digest:
        try:
            from . import discord_notify
            discord_notify.notify_daily_digest(created_for_digest, date_str)
        except Exception as e:
            logger.warning(f"Discord digest 通知失敗（続行）: {e}")


def _comment_duplicate(issue_number: int, pain: dict, date_str: str) -> None:
    """既存 Issue に重複ペインの情報をコメントとして追加する."""
    pain_text = pain.get("pain", "")
    source_title = pain.get("source_title", "")
    source_url = pain.get("source_url", "")

    comment = f"📅 {date_str} に同様のペインを再検出:\n\n> {pain_text}\n"
    if source_url:
        comment += f"\nソース: [{source_title}]({source_url})"

    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", comment],
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(f"#{issue_number} にコメント追加")
    except Exception as e:
        logger.warning(f"コメント追加失敗: {e}")


def _create_issue(pain: dict, date_str: str, notify_discord: bool = True) -> dict | None:
    """1 件のペインから GitHub Issue を作成する. 成功時は {number, title, url, body} を返す.

    notify_discord=False の場合は Discord 個別通知をスキップする
    （send_top_pains のように呼び出し側で digest 通知する場合に使う）。
    """
    severity = pain.get("severity", 0)
    stars = "★" * severity + "☆" * (5 - severity)
    category = pain.get("category", "")
    pain_text = pain.get("pain", "")
    product_type = pain.get("product_type", "")
    target_user = pain.get("target_user", "")
    wtp = pain.get("willingness_to_pay", "")
    frequency = pain.get("frequency", "")
    existing = pain.get("existing_solutions")
    idea = pain.get("app_idea", "")
    source_title = pain.get("source_title", "")
    source_url = pain.get("source_url", "")

    # Issue 本文
    lines = [
        f"## ペイン\n",
        f"{pain_text}\n",
        f"## 詳細\n",
        f"| 項目 | 値 |",
        f"|---|---|",
        f"| 深刻度 | {stars} ({severity}/5) |",
        f"| 対象ユーザー | {target_user} |",
        f"| 頻度 | {frequency} |",
        f"| 課金意欲 | {wtp} |",
        f"| プロダクト | {product_type} |",
        "",
        f"## アイデア\n",
        f"{idea}\n",
        f"## 既存ソリューション\n",
    ]

    if existing:
        lines.append(f"{existing}\n")
    else:
        lines.append("なし（チャンス！）\n")

    # 市場データ
    market_signal = pain.get("market_signal")
    market_apps = pain.get("market_apps", [])
    if market_signal:
        signal_label = {
            "whitespace": "🟢 ホワイトスペース（競合なし）",
            "underserved": "🟡 市場あり・満足度低い（チャンス）",
            "emerging": "🟡 新興市場",
            "competitive": "🔴 競合が強い",
        }.get(market_signal, market_signal)
        lines.append(f"## 市場シグナル\n")
        lines.append(f"{signal_label}\n")
        if market_apps:
            for app in market_apps[:3]:
                lines.append(
                    f"- [{app['name']}]({app['url']}) "
                    f"⭐{app['rating']} ({app['reviews']}件) {app['price']}"
                )
            lines.append("")

    # エンゲージメント情報
    engagement = pain.get("source_engagement", {})
    if engagement:
        engagement_parts = []
        label_map = {
            "score": "👍 スコア",
            "num_comments": "💬 コメント",
            "bookmarks": "🔖 ブックマーク",
            "view_count": "👀 閲覧",
            "answer_count": "✅ 回答",
        }
        for key, label in label_map.items():
            if key in engagement:
                engagement_parts.append(f"{label}: {engagement[key]}")
        if engagement_parts:
            lines.append(f"## エンゲージメント\n")
            lines.append(" / ".join(engagement_parts) + "\n")

    if source_url:
        lines.append(f"## ソース\n")
        lines.append(f"[{source_title}]({source_url})\n")

    lines.append(f"---\n📅 {date_str}\n")
    from . import gh_client
    lines.append(gh_client.HELP_BLOCK)

    # 同一プロダクトの重複検出に使うメタデータ（不可視 HTML コメント）
    product_key = _extract_product_key(source_url)
    if product_key:
        lines.append(f"\n<!-- product:{product_key} -->")

    # 再スコアリング時に元ペインを復元するためのメタデータ（不可視 HTML コメント）
    lines.append(f"\n{_build_pain_data_comment(pain)}")

    body = "\n".join(lines)
    title = f"[{category}] {pain_text[:80]}"

    # ラベルを組み立て
    labels = ["pain-report"]

    if category:
        labels.append(category)

    pt_label = PRODUCT_TYPE_LABELS.get(product_type)
    if pt_label:
        labels.append(pt_label)

    wtp_label = WTP_LABELS.get(wtp)
    if wtp_label:
        labels.append(wtp_label)

    if severity >= 3:
        labels.append(f"🔥severity-{severity}")

    if not existing:
        labels.append("🎯既存なし")

    if market_signal == "whitespace":
        labels.append("🟢whitespace")
    elif market_signal == "underserved":
        labels.append("🟡underserved")

    # gh issue create
    cmd = [
        "gh", "issue", "create",
        "--title", title,
        "--body", body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            logger.info(f"Issue 作成: {issue_url}")

            # Issue 番号を抽出
            issue_number = int(issue_url.rstrip("/").split("/")[-1])

            # Project に自動追加 (GraphQL API)
            _add_to_project(issue_url, issue_number)

            # スコアリング
            try:
                from . import scoring
                scoring.score_and_update_issue(pain, issue_number)
            except Exception as e:
                logger.warning(f"スコアリング失敗（続行）: {e}")

            # Discord 通知（digest 集約の場合は呼び出し側でまとめて通知するためスキップ）
            if notify_discord:
                try:
                    from . import discord_notify
                    discord_notify.notify_issue_created(pain, issue_number, issue_url)
                except Exception as e:
                    logger.warning(f"Discord 通知失敗（続行）: {e}")

            return {
                "number": issue_number,
                "title": title,
                "url": issue_url,
                "body": body,
            }
        else:
            logger.error(f"Issue 作成失敗: {result.stderr[:200]}")
    except Exception as e:
        logger.error(f"Issue 作成失敗: {e}")

    return None


# Project V2 ID (kaionn/projects/1)
_PROJECT_ID = "PVT_kwHOBZbkF84BR2G2"


def _add_to_project(issue_url: str, issue_number: int) -> None:
    """GraphQL API で Issue を Project に追加する。"""
    import json

    # Issue の node ID を取得
    node_result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f'query=query {{ resource(url: "{issue_url}") {{ ... on Issue {{ id }} }} }}',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if node_result.returncode != 0:
        logger.warning(f"Issue node ID 取得失敗: {node_result.stderr[:200]}")
        return

    try:
        node_id = json.loads(node_result.stdout)["data"]["resource"]["id"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Issue node ID パース失敗: {e}")
        return

    # Project に追加
    add_result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f'query=mutation {{ addProjectV2ItemById(input: {{projectId: "{_PROJECT_ID}", contentId: "{node_id}"}}) {{ item {{ id }} }} }}',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if add_result.returncode == 0:
        logger.info(f"Project に追加: #{issue_number}")
    else:
        logger.warning(f"Project 追加失敗: {add_result.stderr[:200]}")
