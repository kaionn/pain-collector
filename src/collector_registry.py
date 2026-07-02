"""コレクタの登録レジストリ（Scrapy 的なデコレータ登録）.

各 collect_*.py の collect 関数に @register_collector を付けることで、
main.py の手動並行リスト（collectors / raw_keys）を廃止し、登録駆動にする。
"""

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

CollectFn = Callable[..., list[dict]]


@dataclass(frozen=True)
class CollectorEntry:
    key: str
    display_name: str
    fn: CollectFn
    supports_backfill: bool = False


_REGISTRY: list[CollectorEntry] = []


def register_collector(
    key: str, display_name: str, supports_backfill: bool = False
) -> Callable[[CollectFn], CollectFn]:
    """モジュールレベルの collect 関数をレジストリに登録するデコレータ."""

    def decorator(fn: CollectFn) -> CollectFn:
        _REGISTRY.append(
            CollectorEntry(
                key=key, display_name=display_name, fn=fn, supports_backfill=supports_backfill
            )
        )
        return fn

    return decorator


def all_collectors() -> list[CollectorEntry]:
    """登録済みの全コレクタを登録順で返す."""
    return list(_REGISTRY)


def validate_post(post: dict, key: str) -> dict | None:
    """収集した投稿の境界バリデーションを行う.

    title または body/summary のいずれかが非空文字列であることを要求する。
    source が無ければ key で補完する。不正な場合は None を返し、呼び出し側で drop する。
    """
    title = post.get("title")
    body = post.get("body") or post.get("summary")
    has_title = isinstance(title, str) and title.strip() != ""
    has_body = isinstance(body, str) and body.strip() != ""

    if not has_title and not has_body:
        logger.warning(f"{key}: title/body が空の post を drop しました: {post}")
        return None

    if not post.get("source"):
        return {**post, "source": key}

    return post
