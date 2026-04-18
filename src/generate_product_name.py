"""Issue タイトルから MVP リポジトリ用のプロダクト名（英語ケバブケース）を生成する.

GitHub Models Inference API（OpenAI SDK 経由）で変換し、失敗時は
``mvp-{issue_number}`` にフォールバックする。``GITHUB_TOKEN`` が無い環境では
ローカル claude CLI にフォールバックする（``generate_spec.py`` と同じ方針）。
"""

import argparse
import logging
import os
import re
import subprocess
import sys

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
    """LLM を呼び出してプロダクト名候補の生文字列を返す。失敗時は None.

    - GITHUB_TOKEN がある場合: GitHub Models Inference API（OpenAI SDK）
    - 無い場合: ローカル claude CLI にフォールバック
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    user_prompt = f"Title: {title}"

    if token:
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=token,
            )
            response = client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                timeout=timeout,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                logger.error("GitHub Models の応答が空でした")
                return None
            logger.info("LLM 応答（生）: %r", content[:200])
            return content
        except Exception as e:
            logger.error("GitHub Models 呼び出し失敗: %s", str(e)[:300])
            return None

    # ローカルフォールバック: claude CLI
    combined = f"{_SYSTEM_PROMPT}\n\n{user_prompt}"
    try:
        result = subprocess.run(
            ["claude", "-p", combined, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("claude CLI が見つかりません")
        return None
    except subprocess.TimeoutExpired:
        logger.error("claude CLI がタイムアウトしました (title=%r)", title)
        return None

    if result.returncode != 0:
        logger.error(
            "claude CLI 失敗 (rc=%s, stderr=%s)",
            result.returncode,
            (result.stderr or "").strip()[:500],
        )
        return None

    stdout = (result.stdout or "").strip()
    if not stdout:
        logger.error("claude CLI の stdout が空でした")
        return None

    logger.info("LLM 応答（生）: %r", stdout[:200])
    return stdout


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
