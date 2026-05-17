"""Discord でパイプラインイベントを通知する.

Issue 作成通知は Webhook、MVP 選定通知は Bot API（Interactive Approve ボタン付き）で送信する。
Bot 関連の環境変数が未設定の場合は Webhook にフォールバックする。
"""

import logging
import os

from .http_utils import create_retry_session

logger = logging.getLogger(__name__)

_MENTION = "<@276013234962825217>"

# 深刻度 → embed カラー
_SEVERITY_COLORS = {
    1: 0x95A5A6,  # grey
    2: 0x95A5A6,
    3: 0xF1C40F,  # yellow
    4: 0xE67E22,  # orange
    5: 0xE74C3C,  # red
}

_MARKET_SIGNAL_LABELS = {
    "whitespace": "🟢 ホワイトスペース",
    "underserved": "🟡 満足度低い",
    "emerging": "🟡 新興市場",
    "competitive": "🔴 競合が強い",
}


def _severity_color(severity: int) -> int:
    """深刻度から embed カラーを返す."""
    return _SEVERITY_COLORS.get(severity, 0x95A5A6)


def _post_webhook(payload: dict) -> None:
    """Discord Webhook にペイロードを POST する."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return

    session = create_retry_session()
    resp = session.post(url, json=payload, timeout=10)
    resp.raise_for_status()


def _post_bot_message(payload: dict) -> None:
    """Discord Bot API でチャンネルにメッセージを送信する."""
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")
    if not token or not channel_id:
        return

    session = create_retry_session()
    resp = session.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        json=payload,
        headers={"Authorization": f"Bot {token}"},
        timeout=10,
    )
    resp.raise_for_status()


def notify_issue_created(
    pain: dict, issue_number: int, issue_url: str
) -> None:
    """Issue 作成時に Discord へ通知する（Webhook）."""
    severity = pain.get("severity", 0)
    category = pain.get("category", "")
    pain_text = pain.get("pain", "")
    idea = pain.get("app_idea", "")
    market_signal = pain.get("market_signal")

    title = f"[{category}] {pain_text[:80]}"
    stars = "★" * severity + "☆" * (5 - severity)

    description = pain_text[:200]
    if idea:
        description += f"\n\n💡 {idea[:100]}"

    fields = [
        {"name": "深刻度", "value": f"{stars} ({severity}/5)", "inline": True},
        {
            "name": "対象ユーザー",
            "value": pain.get("target_user", "-"),
            "inline": True,
        },
        {
            "name": "課金意欲",
            "value": pain.get("willingness_to_pay", "-"),
            "inline": True,
        },
    ]

    if market_signal:
        label = _MARKET_SIGNAL_LABELS.get(market_signal, market_signal)
        fields.append({"name": "市場シグナル", "value": label, "inline": True})

    payload = {
        "content": f"{_MENTION} 新しいペイン Issue が作成されました",
        "embeds": [
            {
                "title": title,
                "url": issue_url,
                "description": description,
                "color": _severity_color(severity),
                "fields": fields,
                "footer": {"text": f"#{issue_number} | pain-collector"},
            }
        ]
    }

    try:
        _post_webhook(payload)
        logger.info(f"Discord 通知送信: #{issue_number}")
    except Exception as e:
        logger.warning(f"Discord 通知失敗: {e}")


def notify_daily_digest(created: list[dict], date_str: str) -> None:
    """1 日に新規作成した Issue を 1 つの digest メッセージにまとめて Discord に通知する.

    created の各要素は notify._create_issue の戻り値 + {"pain": pain_dict}:
        {"number": int, "title": str, "url": str, "body": str, "pain": dict}

    個別の Issue 作成通知（notify_issue_created）はノイズが多いため、
    日次集約版に置き換える。0 件なら何もしない。
    """
    if not created:
        return

    # 重複したプロダクトが連発した日でも 1 通にまとまるため、
    # メッセージ内で severity 順にソートして可読性を上げる。
    sorted_items = sorted(
        created,
        key=lambda x: x.get("pain", {}).get("severity", 0),
        reverse=True,
    )

    embeds = []
    max_color = 0x95A5A6
    for item in sorted_items[:10]:  # Discord embed は 1 メッセージ 10 個まで
        pain = item.get("pain", {})
        severity = pain.get("severity", 0)
        category = pain.get("category", "")
        pain_text = pain.get("pain", "")
        wtp = pain.get("willingness_to_pay", "-")
        target = pain.get("target_user", "-")
        market_signal = pain.get("market_signal")

        title = f"[{category}] {pain_text[:60]}"
        stars = "★" * severity + "☆" * (5 - severity)

        field_value_parts = [f"{stars} ({severity}/5)"]
        if wtp and wtp != "-":
            field_value_parts.append(f"💰{wtp}")
        if market_signal:
            field_value_parts.append(_MARKET_SIGNAL_LABELS.get(market_signal, market_signal))
        meta_line = " / ".join(field_value_parts)

        description = f"{meta_line}\n対象: {target}"

        embeds.append(
            {
                "title": f"#{item['number']} {title}",
                "url": item.get("url", ""),
                "description": description,
                "color": _severity_color(severity),
            }
        )
        max_color = max(max_color, _severity_color(severity))

    total = len(created)
    omitted = total - len(embeds)
    headline = f"📋 本日のペイン Issue: {total} 件"
    if omitted > 0:
        headline += f"（うち {len(embeds)} 件を抜粋表示、残り {omitted} 件は GitHub で確認）"

    payload = {
        "content": f"{_MENTION} {headline}",
        "embeds": embeds,
    }

    try:
        _post_webhook(payload)
        logger.info(f"Discord daily digest 通知送信: {total} 件")
    except Exception as e:
        logger.warning(f"Discord daily digest 通知失敗: {e}")


def notify_mvp_picked(
    picked: list[dict], today: str, repo_url: str
) -> None:
    """MVP 候補選定時に Discord へ通知する（Bot API: Interactive Approve ボタン付き）.

    Bot API が利用不可の場合は Webhook にフォールバックする。
    """
    if not picked:
        return

    bot_available = bool(
        os.environ.get("DISCORD_BOT_TOKEN") and os.environ.get("DISCORD_CHANNEL_ID")
    )

    rank_emoji = ["🥇", "🥈", "🥉"]

    if bot_available:
        try:
            for i, item in enumerate(picked[:3]):
                _send_mvp_bot_message(item, i, rank_emoji, today, repo_url)
            logger.info(f"Discord MVP 選定通知送信（Bot API）: {len(picked)} 件")
            return
        except Exception as e:
            logger.warning(f"Discord Bot API 失敗、Webhook にフォールバック: {e}")

    # Webhook フォールバック
    embeds = []
    for i, item in enumerate(picked[:3]):
        embeds.append(_build_mvp_embed(item, i, rank_emoji, today, repo_url))

    payload = {
        "content": f"{_MENTION} 🏆 MVP 候補が選定されました！承認するには Issue で `/approve` とコメントしてください。",
        "embeds": embeds,
    }

    try:
        _post_webhook(payload)
        logger.info(f"Discord MVP 選定通知送信（Webhook）: {len(picked)} 件")
    except Exception as e:
        logger.warning(f"Discord MVP 選定通知失敗: {e}")


def _build_mvp_embed(
    item: dict, index: int, rank_emoji: list[str], today: str, repo_url: str
) -> dict:
    """MVP 候補の embed を構築する."""
    number = item["number"]
    title = item.get("title", "")
    emoji = rank_emoji[index] if index < len(rank_emoji) else f"#{index + 1}"

    spec = item.get("spec")
    spec_status = "✅ Ready" if spec else "⚠️ 未生成"

    fields = [
        {"name": "スコア", "value": item.get("score_label", "-"), "inline": True},
        {"name": "Spec", "value": spec_status, "inline": True},
        {"name": "開発期間", "value": item.get("dev_period", "-"), "inline": True},
    ]

    reason = item.get("reason", "")
    if reason:
        fields.append({"name": "選定理由", "value": reason, "inline": False})

    footer_text = (
        "Spec Ready → Approve ボタンで自動実装を開始"
        if spec
        else "Spec 未生成 → Deep Dive 完了後に再選定"
    )

    return {
        "title": f"{emoji} #{number} {title[:60]}",
        "url": f"{repo_url}/issues/{number}",
        "color": 0xFFD700,
        "fields": fields,
        "footer": {"text": f"{today} | {footer_text}"},
    }


def _send_mvp_bot_message(
    item: dict, index: int, rank_emoji: list[str], today: str, repo_url: str
) -> None:
    """Bot API で 1 件の MVP 候補メッセージを送信する."""
    number = item["number"]
    spec = item.get("spec")
    embed = _build_mvp_embed(item, index, rank_emoji, today, repo_url)

    buttons = []
    if spec:
        buttons.append(
            {
                "type": 2,  # BUTTON
                "style": 3,  # SUCCESS (green)
                "label": "Approve",
                "custom_id": f"approve:{number}",
                "emoji": {"name": "🚀"},
            }
        )
    buttons.append(
        {
            "type": 2,  # BUTTON
            "style": 4,  # DANGER (red)
            "label": "Reject",
            "custom_id": f"reject:{number}",
            "emoji": {"name": "❌"},
        }
    )
    buttons.append(
        {
            "type": 2,
            "style": 5,  # LINK
            "label": "View Issue",
            "url": f"{repo_url}/issues/{number}",
        }
    )

    payload = {
        "content": f"{_MENTION} 🏆 MVP 候補が選定されました！",
        "embeds": [embed],
        "components": [{"type": 1, "components": buttons}],
    }

    _post_bot_message(payload)
