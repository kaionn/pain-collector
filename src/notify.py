"""GitHub Issues でペインを個別 Issue として作成する（重複チェック付き）."""

import json
import logging
import subprocess

from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

from src.tokenizer import create_tfidf_vectorizer

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


def _fetch_open_issues() -> list[dict]:
    """open 状態の Issue タイトル一覧を取得する."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", "pain-report",
                "--state", "open",
                "--json", "number,title",
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


def _llm_judge_duplicate(pain_text: str, existing_title: str) -> bool:
    """LLM でグレーゾーンの重複を二次判定する."""
    import os

    prompt = (
        "以下の2つのペインが実質的に同じ課題を指しているか判定してください。\n"
        "同じ課題なら YES、異なる課題なら NO とだけ答えてください。\n\n"
        f"ペイン A: {pain_text}\n"
        f"ペイン B: {existing_title}\n"
    )

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=token,
            )
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10,
            )
            answer = (response.choices[0].message.content or "").strip().upper()
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
    """深刻度が高いペイン TOP N を個別の GitHub Issue として作成する."""
    if not pains:
        return

    existing_issues = _fetch_open_issues()
    logger.info(f"既存 open Issue: {len(existing_issues)} 件")

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    for pain in top:
        pain_text = pain.get("pain", "")
        duplicate = _find_duplicate(pain_text, existing_issues)

        if duplicate:
            logger.info(f"重複検出 → #{duplicate['number']} {duplicate['title'][:50]}")
            _comment_duplicate(duplicate["number"], pain, date_str)
        else:
            issue = _create_issue(pain, date_str)
            if issue:
                existing_issues.append(issue)


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


def _create_issue(pain: dict, date_str: str) -> dict | None:
    """1 件のペインから GitHub Issue を作成する. 成功時は {number, title} を返す."""
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

    lines.append(f"---\n📅 {date_str}")

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

            # Discord 通知
            try:
                from . import discord_notify
                discord_notify.notify_issue_created(pain, issue_number, issue_url)
            except Exception as e:
                logger.warning(f"Discord 通知失敗（続行）: {e}")

            return {"number": issue_number, "title": title}
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
