"""Issue タイトルから MVP リポジトリ用のプロダクト名（英語ケバブケース）を生成する.

LLM（gh models run openai/gpt-4o-mini）で変換し、失敗時は mvp-{issue_number} にフォールバックする。
CLAUDE.md のルールに従い subprocess の returncode を必ずチェックしてエラーログを出す。
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

_PROMPT_TEMPLATE = (
    "Convert the following Japanese product idea title to a concise English "
    "kebab-case repository name.\n"
    "Rules:\n"
    "- Output ONLY the name. No quotes, no explanation, no code fence.\n"
    "- Max {max_length} characters.\n"
    "- Only lowercase letters, digits, and hyphens.\n"
    "- 2-4 words, describing the product concretely (avoid generic words like app/mvp/tool).\n"
    "- Prefer domain nouns over verbs.\n\n"
    "Title: {title}"
)


def _extract_kebab_token(raw: str) -> str:
    """LLM の出力から最もそれらしいケバブケース文字列を抽出する.

    LLM が説明文・コードフェンス・引用符付きで返した場合でも、有効な
    ケバブケース token を拾う。候補が複数あれば最長のものを選ぶ。
    """
    text = raw.strip().lower()
    text = text.strip("`\"'")

    # コードフェンスや quote を剥がした後の行単位で候補を探す
    candidates: list[str] = []
    for line in text.splitlines():
        for token in re.findall(r"[a-z0-9][a-z0-9-]*[a-z0-9]", line):
            candidates.append(token)

    if not candidates:
        return ""

    # ハイフンを含む（＝複数語で構成される）候補を優先
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
    # ハイフンも数字もない単一単語で、かつ禁止語集合に近い形（app1 等）を追加検査したいが
    # まずはハイフン有無のチェックに留める
    if re.fullmatch(r"[0-9-]+", name):
        return False
    return True


def _call_gh_models(title: str, *, timeout: int = 30) -> str | None:
    """gh models run を呼び出して出力を返す。失敗時は None."""
    prompt = _PROMPT_TEMPLATE.format(max_length=MAX_LENGTH, title=title)
    try:
        result = subprocess.run(
            ["gh", "models", "run", "openai/gpt-4o-mini", "--", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("gh コマンドが見つかりません")
        return None
    except subprocess.TimeoutExpired:
        logger.error("gh models run がタイムアウトしました (title=%r)", title)
        return None

    if result.returncode != 0:
        logger.error(
            "gh models run 失敗 (rc=%s, stderr=%s)",
            result.returncode,
            (result.stderr or "").strip()[:500],
        )
        return None

    stdout = (result.stdout or "").strip()
    if not stdout:
        logger.error("gh models run の stdout が空でした")
        return None

    logger.info("LLM 応答（生）: %r", stdout[:200])
    return stdout


def generate(title: str, issue_number: int, *, timeout: int = 30) -> str:
    """タイトルからプロダクト名を生成する.

    Args:
        title: Issue タイトル（日本語想定）。
        issue_number: フォールバック用の Issue 番号。
        timeout: LLM 呼び出しのタイムアウト秒数。

    Returns:
        kebab-case のプロダクト名。LLM が失敗したら ``mvp-{issue_number}``。
    """
    raw = _call_gh_models(title, timeout=timeout)
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
        default=30,
        help="LLM 呼び出しのタイムアウト秒数（デフォルト 30）",
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
