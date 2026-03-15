"""Discord Webhook で通知を送信する."""

import json
import os

import requests

def send_top_pains(pains: list[dict], date_str: str, top_n: int = 3) -> None:
    """深刻度が高いペイン TOP N を Discord Webhook で通知する."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("[Discord] DISCORD_WEBHOOK_URL が未設定、通知スキップ")
        return

    if not pains:
        return

    sorted_pains = sorted(pains, key=lambda x: x.get("severity", 0), reverse=True)
    top = sorted_pains[:top_n]

    embeds = []
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
        source_url = pain.get("source_url", "")

        # 深刻度で色を変える
        color = {5: 0xFF0000, 4: 0xFF6B00, 3: 0xFFAA00, 2: 0x00AA00, 1: 0x888888}.get(severity, 0x888888)

        fields = [
            {"name": "深刻度", "value": f"{stars} ({severity}/5)", "inline": True},
            {"name": "カテゴリ", "value": category, "inline": True},
            {"name": "プロダクト", "value": product_type, "inline": True},
            {"name": "対象ユーザー", "value": target_user, "inline": False},
            {"name": "頻度 / 課金意欲", "value": f"{frequency} / {wtp}", "inline": True},
            {"name": "アイデア", "value": idea, "inline": False},
        ]

        if existing:
            fields.append({"name": "既存ソリューション", "value": existing, "inline": False})
        else:
            fields.append({"name": "既存ソリューション", "value": "なし（チャンス！）", "inline": False})

        embed = {
            "title": f"{i}. {pain_text}",
            "color": color,
            "fields": fields,
        }

        if source_url:
            embed["url"] = source_url

        embeds.append(embed)

    payload = {
        "content": f"🔥 **Pain Report: {date_str}** TOP{top_n}",
        "embeds": embeds,
    }

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 204):
            print(f"[Discord] TOP{top_n} ペインを通知しました")
        else:
            print(f"[Discord] 通知失敗: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as e:
        print(f"[Discord] 通知失敗: {e}")
