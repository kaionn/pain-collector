"""GitHub Issues でペインを個別 Issue として作成する（重複チェック付き）."""

import json
import subprocess

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

DUPLICATE_THRESHOLD = 0.5


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


def _find_duplicate(pain_text: str, existing_issues: list[dict]) -> dict | None:
    """既存 Issue の中から重複を検出する. 類似度が閾値以上なら既存 Issue を返す."""
    if not existing_issues:
        return None

    titles = [issue["title"] for issue in existing_issues]
    corpus = titles + [pain_text]

    try:
        tfidf = TfidfVectorizer().fit_transform(corpus)
        sims = cosine_similarity(tfidf[-1:], tfidf[:-1]).flatten()

        max_idx = sims.argmax()
        if sims[max_idx] >= DUPLICATE_THRESHOLD:
            return existing_issues[max_idx]
    except ValueError:
        pass

    return None


def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> None:
    """深刻度が高いペイン TOP N を個別の GitHub Issue として作成する."""
    if not pains:
        return

    existing_issues = _fetch_open_issues()
    print(f"[GitHub] 既存 open Issue: {len(existing_issues)} 件")

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    for pain in top:
        pain_text = pain.get("pain", "")
        duplicate = _find_duplicate(pain_text, existing_issues)

        if duplicate:
            print(f"[GitHub] 重複検出 → #{duplicate['number']} {duplicate['title'][:50]}")
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
        print(f"[GitHub] #{issue_number} にコメント追加")
    except Exception as e:
        print(f"[GitHub] コメント追加失敗: {e}")


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
            print(f"[GitHub] Issue 作成: {issue_url}")

            # Issue 番号を抽出
            issue_number = int(issue_url.rstrip("/").split("/")[-1])

            # Project に自動追加
            subprocess.run(
                ["gh", "project", "item-add", "1", "--owner", "kaionn", "--url", issue_url],
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {"number": issue_number, "title": title}
        else:
            print(f"[GitHub] Issue 作成失敗: {result.stderr[:200]}")
    except Exception as e:
        print(f"[GitHub] Issue 作成失敗: {e}")

    return None
