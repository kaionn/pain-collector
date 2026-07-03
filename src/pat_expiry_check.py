"""PAT_TOKEN の失効を事前検知して Discord に通知する.

GitHub API のレスポンスヘッダ ``github-authentication-token-expiration`` から
fine-grained PAT の失効日時を取得し、失効済み（401）または残り日数が閾値以下の
場合に Discord Webhook へ警告を送る。

monitor.yml から毎時呼ばれる前提のため、``--gate-hour``（UTC）に一致する時間帯
のみ通知してスパムを防ぐ。``--force`` は gate と閾値を無視して現在の状態を必ず
通知する（疎通確認用）。
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone

from .discord_notify import _MENTION, _post_webhook
from .http_utils import create_retry_session

logger = logging.getLogger(__name__)

EXPIRATION_HEADER = "github-authentication-token-expiration"
_API_URL = "https://api.github.com/rate_limit"


def parse_expiration(raw: str) -> datetime | None:
    """失効ヘッダの値を UTC datetime にパースする. 解釈できなければ None."""
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S UTC"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        logger.warning(f"失効ヘッダをパースできませんでした: {raw!r}")
        return None


def fetch_token_status(token: str) -> tuple[str, datetime | None]:
    """PAT の状態を返す.

    戻り値は ("expired" | "valid" | "no-expiry", 失効日時) のタプル。
    401 は失効（または revoke）、失効ヘッダ無しは "no-expiry"（classic PAT の
    無期限設定等）として扱う。
    """
    session = create_retry_session()
    resp = session.get(
        _API_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code == 401:
        return "expired", None
    resp.raise_for_status()
    raw = resp.headers.get(EXPIRATION_HEADER, "")
    if not raw:
        return "no-expiry", None
    expiry = parse_expiration(raw)
    if expiry is None:
        return "no-expiry", None
    return "valid", expiry


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "kaionn/pain-collector")


def build_alert(
    status: str,
    expiry: datetime | None,
    now: datetime,
    warn_days: int,
) -> str | None:
    """通知すべき状態ならメッセージを、正常なら None を返す."""
    if status == "expired":
        return (
            f"{_MENTION} 🔑🚨 **PAT_TOKEN が失効しています**\n"
            "GitHub API が 401 を返しました。Collect Pains を含む全ワークフローが"
            "停止します。\n"
            "PAT を再発行して "
            f"`gh secret set PAT_TOKEN --repo {_repo()}` で更新してください。"
        )
    if status == "valid" and expiry is not None:
        days_left = (expiry - now).days
        if days_left <= warn_days:
            return (
                f"{_MENTION} 🔑⚠️ **PAT_TOKEN が残り {days_left} 日で失効します**"
                f"（{expiry:%Y-%m-%d %H:%M} UTC）\n"
                "失効すると日次収集パイプラインが停止します。早めに再発行して "
                f"`gh secret set PAT_TOKEN --repo {_repo()}` で更新してください。"
            )
    return None


def _build_status_report(status: str, expiry: datetime | None, now: datetime) -> str:
    """--force 用: 現在の PAT 状態の情報メッセージを返す."""
    if status == "valid" and expiry is not None:
        days_left = (expiry - now).days
        return (
            f"🔑 PAT_TOKEN 失効チェック（疎通確認）: 残り {days_left} 日"
            f"（{expiry:%Y-%m-%d %H:%M} UTC に失効）"
        )
    return f"🔑 PAT_TOKEN 失効チェック（疎通確認）: 状態 = {status}（失効日情報なし）"


def run(
    warn_days: int,
    gate_hour: int | None,
    force: bool = False,
    now: datetime | None = None,
) -> int:
    """失効チェックを実行し、必要なら Discord に通知する."""
    token = os.environ.get("PAT_TOKEN", "")
    if not token:
        logger.warning("PAT_TOKEN 未設定のためチェックをスキップします")
        return 0

    if now is None:
        now = datetime.now(timezone.utc)

    status, expiry = fetch_token_status(token)
    message = build_alert(status, expiry, now, warn_days)

    if message is None:
        logger.info(f"PAT は正常です（状態: {status}, 失効: {expiry}）")
        if not force:
            return 0
        message = _build_status_report(status, expiry, now)

    if not force and gate_hour is not None and now.hour != gate_hour:
        logger.info(
            f"gate-hour 外のため通知をスキップします（現在 {now.hour} 時 UTC, "
            f"gate {gate_hour} 時）"
        )
        return 0

    _post_webhook({"content": message})
    logger.info("Discord に PAT 失効チェック結果を送信しました")
    return 0


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--warn-days",
        type=int,
        default=7,
        help="残り日数がこの値以下なら警告する（既定: 7）",
    )
    parser.add_argument(
        "--gate-hour",
        type=int,
        default=None,
        help="通知を許可する UTC 時（毎時実行でのスパム防止。省略時は常に通知）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="gate-hour と閾値を無視して現在の状態を必ず通知する（疎通確認用）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s: %(message)s",
    )
    args = _build_cli_parser().parse_args(argv)
    return run(args.warn_days, args.gate_hour, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
