"""GitHub Issues でペインを個別 Issue として作成する."""

import subprocess

# プロダクトタイプ → ラベル名のマッピング
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


def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> None:
    """深刻度が高いペイン TOP N を個別の GitHub Issue として作成する."""
    if not pains:
        return

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    for pain in top:
        _create_issue(pain, date_str)


def _create_issue(pain: dict, date_str: str) -> None:
    """1 件のペインから GitHub Issue を作成する."""
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

    if source_url:
        lines.append(f"## ソース\n")
        lines.append(f"[{source_title}]({source_url})\n")

    lines.append(f"---\n📅 {date_str}")

    body = "\n".join(lines)

    # ラベルを組み立て
    labels = ["pain-report"]

    # ジャンル
    if category:
        labels.append(category)

    # プロダクトタイプ
    pt_label = PRODUCT_TYPE_LABELS.get(product_type)
    if pt_label:
        labels.append(pt_label)

    # 課金意欲
    wtp_label = WTP_LABELS.get(wtp)
    if wtp_label:
        labels.append(wtp_label)

    # 深刻度（3以上）
    if severity >= 3:
        labels.append(f"🔥severity-{severity}")

    # 既存ソリューションなし
    if not existing:
        labels.append("🎯既存なし")

    # gh issue create コマンド組み立て
    cmd = [
        "gh", "issue", "create",
        "--title", f"[{category}] {pain_text[:80]}",
        "--body", body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            print(f"[GitHub] Issue 作成: {issue_url}")
        else:
            print(f"[GitHub] Issue 作成失敗: {result.stderr[:200]}")
    except Exception as e:
        print(f"[GitHub] Issue 作成失敗: {e}")
