"""GitHub Issues で通知を送信する."""

import subprocess


def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> None:
    """深刻度が高いペイン TOP N を GitHub Issue として作成する."""
    if not pains:
        return

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    lines = []
    for i, pain in enumerate(top, 1):
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

        lines.append(f"## {i}. {pain_text}\n")
        lines.append(f"- {stars} ({severity}/5)")
        lines.append(f"- カテゴリ: {category}")
        lines.append(f"- 対象: {target_user}")
        lines.append(f"- 頻度: {frequency} / 課金意欲: {wtp}")
        lines.append(f"- プロダクト: {product_type}")
        lines.append(f"- アイデア: {idea}")

        if existing:
            lines.append(f"- 既存ソリューション: {existing}")
        else:
            lines.append("- 既存ソリューション: なし（チャンス！）")

        if source_url:
            lines.append(f"- ソース: [{source_title}]({source_url})")

        lines.append("")

    body = "\n".join(lines)
    title = f"🔥 Pain Report: {date_str} TOP{top_n}"

    try:
        result = subprocess.run(
            [
                "gh", "issue", "create",
                "--title", title,
                "--body", body,
                "--label", "pain-report",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            print(f"[GitHub] Issue を作成しました: {issue_url}")
        else:
            print(f"[GitHub] Issue 作成失敗: {result.stderr[:200]}")
    except Exception as e:
        print(f"[GitHub] Issue 作成失敗: {e}")
