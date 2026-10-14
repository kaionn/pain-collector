"""Issue タイトルからプロダクト名を生成する。

共有 LLM クライアントの明示設定を使用し、接続障害は伝播する。
名前の検証に失敗した場合は mvp-{issue_number} を使用する。
"""

import argparse
import logging
import os
import re
import sys

from src import llm_client

logger = logging.getLogger(__name__)

MAX_LENGTH = 30
MIN_LENGTH = 3
LLM_TIMEOUT_SEC = 30

# プロダクト名として意味のない単独語（フォールバック判定に使う）
_BANNED_NAMES = frozenset({
    "mvp",
    "app",
    "application",
    "product",
    "service",
    "tool",
    "test",
    "temp",
    "tmp",
    "demo",
    "example",
    "project",
    "name",
    "unknown",
})

_SYSTEM_PROMPT = (
    "You convert Japanese product idea titles into concise English kebab-case "
    "repository names. Output ONLY the name — no quotes, no explanation, no "
    "code fence. Max 30 characters. Only lowercase letters, digits, and hyphens. "
    "2-4 words, describing the product concretely (avoid generic words like "
    "app/mvp/tool). Prefer domain nouns over verbs."
)


def _extract_kebab_token(raw: str) -> str:
    """LLM の出力から最もそれらしいケバブケース文字列を抽出する."""
    text = raw.strip().lower()
    text = text.strip("`\"'")

    candidates: list[str] = []
    for line in text.splitlines():
        for token in re.findall(r"[a-z0-9][a-z0-9-]*[a-z0-9]", line):
            candidates.append(token)

    if not candidates:
        return ""

    hyphenated = [c for c in candidates if "-" in c]
    pool = hyphenated or candidates
    return max(pool, key=len)


def _sanitize(name: str) -> str:
    """ケバブケース token として正規化する."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name[:MAX_LENGTH].rstrip("-")


def _is_valid(name: str) -> bool:
    """生成されたプロダクト名が採用可能かどうか."""
    if len(name) < MIN_LENGTH:
        return False
    if name in _BANNED_NAMES:
        return False
    if re.fullmatch(r"[0-9-]+", name):
        return False
    return True


def _call_llm(title: str, *, timeout: int = LLM_TIMEOUT_SEC) -> str | None:
    """共有クライアントの明示 provider 設定を使用する。障害は伝播する。"""
    return llm_client.chat(f"Title: {title}", system=_SYSTEM_PROMPT, temperature=0.3, timeout=timeout).strip()


def generate(title: str, issue_number: int, *, timeout: int = LLM_TIMEOUT_SEC) -> str:
    """タイトルからプロダクト名を生成する。失敗時は ``mvp-{issue_number}``."""
    raw = _call_llm(title, timeout=timeout)
    if raw is not None:
        token = _extract_kebab_token(raw)
        name = _sanitize(token)
        if _is_valid(name):
            logger.info("プロダクト名を生成: %s", name)
            return name
        logger.warning(
            "LLM 出力が無効のためフォールバック (raw=%r, sanitized=%r)",
            raw[:200],
            name,
        )

    fallback = f"mvp-{issue_number}"
    logger.warning("フォールバック名を使用: %s", fallback)
    return fallback


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Issue タイトル")
    parser.add_argument(
        "--issue-number",
        required=True,
        type=int,
        help="フォールバック用の Issue 番号",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=LLM_TIMEOUT_SEC,
        help=f"LLM 呼び出しのタイムアウト秒数（デフォルト {LLM_TIMEOUT_SEC}）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。stdout に生成されたプロダクト名を出力する."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    name = generate(args.title, args.issue_number, timeout=args.timeout)
    print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
