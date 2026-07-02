"""日次実行の健全性チェック（healthchecks.io 的な fail-loud アラート）.

コレクタ・LLM の失敗は従来 logger.warning で沈黙していた。
異常を検出して人間向けメッセージを返し、呼び出し側で通知に使う。
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE_HEALTH_PATH = os.path.join(BASE_DIR, "data", "source_health.json")

EMPTY_SOURCE_THRESHOLD = 3
CONSECUTIVE_FAILURE_THRESHOLD = 3


def _load_source_health(path: str) -> dict:
    """ソースの健全性データを読み込む（欠損・破損時は空 dict）."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"source_health.json の読み込みに失敗: {e}")
        return {}


def check_daily_run(
    sources: dict[str, list[dict]],
    pains_count: int,
    source_health_path: str = DEFAULT_SOURCE_HEALTH_PATH,
) -> list[str]:
    """日次実行の異常を検出し、人間向け日本語メッセージのリストを返す.

    検出条件:
        a. 収集 0 件のソースが 3 つ以上
        b. 全ソース合計の投稿数 > 0 なのに抽出ペイン数が 0
        c. source_health.json の consecutive_failures >= 3 のソースがある
    """
    problems: list[str] = []

    empty_sources = sorted(name for name, posts in sources.items() if not posts)
    if len(empty_sources) >= EMPTY_SOURCE_THRESHOLD:
        problems.append(
            f"収集 0 件のソースが {len(empty_sources)} 件あります: {', '.join(empty_sources)}"
        )

    total_posts = sum(len(posts) for posts in sources.values())
    if total_posts > 0 and pains_count == 0:
        problems.append(
            f"投稿は {total_posts} 件収集されましたが、抽出されたペインが 0 件でした"
        )

    health = _load_source_health(source_health_path)
    failing = sorted(
        (name, entry.get("consecutive_failures", 0))
        for name, entry in health.items()
        if entry.get("consecutive_failures", 0) >= CONSECUTIVE_FAILURE_THRESHOLD
    )
    if failing:
        failing_desc = ", ".join(f"{name} ({count} 回)" for name, count in failing)
        problems.append(
            f"連続失敗が {CONSECUTIVE_FAILURE_THRESHOLD} 回以上のソースがあります: {failing_desc}"
        )

    return problems
