"""LINE Notify で通知を送信する."""

import os

import requests

LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"


def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> None:
    """深刻度が高いペイン TOP N を LINE Notify で通知する."""
    token = os.environ.get("LINE_NOTIFY_TOKEN", "")
    if not token:
        print("[LINE] LINE_NOTIFY_TOKEN が未設定、通知スキップ")
        return

    if not pains:
        return

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    lines = [f"\n🔥 Pain Report: {date_str} TOP{top_n}\n"]

    for i, pain in enumerate(top, 1):
        severity = pain.get("severity", 0)
        stars = "★" * severity + "☆" * (5 - severity)
        category = pain.get("category", "")
        pain_text = pain.get("pain", "")
        product_type = pain.get("product_type", "")
        wtp = pain.get("willingness_to_pay", "")
        existing = pain.get("existing_solutions")
        idea = pain.get("app_idea", "")

        lines.append(f"{i}. {stars} [{category}]")
        lines.append(f"   {pain_text}")
        lines.append(f"   → {product_type} | 課金: {wtp}")
        lines.append(f"   💡 {idea}")

        if not existing:
            lines.append("   🎯 既存ソリューションなし！")

        lines.append("")

    message = "\n".join(lines)

    # LINE Notify は 1000 文字制限
    if len(message) > 1000:
        message = message[:997] + "..."

    try:
        resp = requests.post(
            LINE_NOTIFY_URL,
            headers={"Authorization": f"Bearer {token}"},
            data={"message": message},
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"[LINE] TOP{top_n} ペインを通知しました")
        else:
            print(f"[LINE] 通知失敗: {resp.status_code} {resp.text[:100]}")
    except requests.RequestException as e:
        print(f"[LINE] 通知失敗: {e}")
