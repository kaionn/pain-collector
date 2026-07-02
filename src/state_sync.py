"""pipeline_state.json を GitHub Contents API 経由で取得・更新する.

Branch Protection をバイパスして ``data/pipeline_state.json`` を読み書きするため、
`gh api` で Contents API（SHA 付き PUT）を直接叩く。monitor.yml / approve.yml の
ワークフローから呼び出される（旧 `python3 - <<'PY'` heredoc / bash 直書きの移植先）。
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

DEFAULT_STATE = '{"picked": []}'
GH_TIMEOUT_SEC = 30


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=GH_TIMEOUT_SEC
    )


def fetch(repo: str, remote_path: str, local_path: str) -> None:
    """Contents API から最新の state を取得し local_path に書き込む.

    リモートに存在しない場合（未作成・取得失敗）は DEFAULT_STATE を書き込む。
    """
    dirname = os.path.dirname(local_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    result = _run_gh(["api", f"repos/{repo}/contents/{remote_path}", "--jq", ".content"])
    if result.returncode == 0 and result.stdout.strip():
        content = base64.b64decode(result.stdout.strip()).decode("utf-8")
    else:
        content = DEFAULT_STATE

    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)


def push(
    repo: str,
    remote_path: str,
    local_path: str,
    message: str,
    *,
    create_if_missing: bool = False,
) -> None:
    """local_path の内容を Contents API 経由で repo/remote_path に PUT する（SHA 付き）.

    リモートに既存ファイルが無い場合、``create_if_missing=False``（既定）なら
    何もせず戻る。``create_if_missing=True`` なら SHA なしで新規作成する。
    """
    sha_result = _run_gh(["api", f"repos/{repo}/contents/{remote_path}", "--jq", ".sha"])
    sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""

    if not sha and not create_if_missing:
        logger.info("リモートに %s が存在しないため更新をスキップします", remote_path)
        return

    with open(local_path, "rb") as f:
        encoded_content = base64.b64encode(f.read()).decode("ascii")

    cmd = [
        "api",
        f"repos/{repo}/contents/{remote_path}",
        "-X",
        "PUT",
        "-f",
        f"message={message}",
        "-f",
        f"content={encoded_content}",
    ]
    if sha:
        cmd.extend(["-f", f"sha={sha}"])

    result = _run_gh(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"{remote_path} の更新に失敗しました: {result.stderr.strip()[:300]}")

    if sha:
        logger.info("%s を更新しました", remote_path)
    else:
        logger.info("%s を作成しました", remote_path)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Contents API から state を取得する")
    p_fetch.add_argument("--repo", required=True, help="owner/repo")
    p_fetch.add_argument("--remote-path", default="data/pipeline_state.json")
    p_fetch.add_argument("--local-path", default="data/pipeline_state.json")

    p_push = sub.add_parser("push", help="Contents API へ state を PUT する")
    p_push.add_argument("--repo", required=True, help="owner/repo")
    p_push.add_argument("--remote-path", default="data/pipeline_state.json")
    p_push.add_argument("--local-path", default="data/pipeline_state.json")
    p_push.add_argument("--message", required=True)
    p_push.add_argument(
        "--create-if-missing",
        action="store_true",
        help="リモートに存在しない場合でも新規作成する",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s: %(message)s",
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "fetch":
        fetch(args.repo, args.remote_path, args.local_path)
    elif args.command == "push":
        push(
            args.repo,
            args.remote_path,
            args.local_path,
            args.message,
            create_if_missing=args.create_if_missing,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
