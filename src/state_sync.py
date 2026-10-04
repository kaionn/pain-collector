"""pipeline_state.json を GitHub Contents API 経由で取得・更新する.

Branch Protection / ruleset と token 権限が適用される環境で ``data/pipeline_state.json`` を読み書きするため、
`gh api` で Contents API（SHA 付き PUT）を直接叩く。monitor.yml / approve.yml の
ワークフローから呼び出される（旧 `python3 - <<'PY'` heredoc / bash 直書きの移植先）。
"""

from __future__ import annotations

import argparse
import base64
import json
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
    """Fetch content and base SHA together; failed reads never invent empty state."""
    result = _run_gh(["api", f"repos/{repo}/contents/{remote_path}"])
    if result.returncode != 0:
        raise RuntimeError("state fetch failed; local state preserved")
    payload = json.loads(result.stdout)
    sha = payload.get("sha")
    if not isinstance(sha, str) or not sha:
        raise ValueError("state response lacks base SHA")
    content = base64.b64decode(payload["content"]).decode("utf-8")
    json.loads(content)  # Invalid data must not replace a valid local snapshot.
    from .opportunity_pipeline import atomic_write
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    # Sidecar is the fetched revision, not a newly read remote SHA at push time.
    atomic_write(local_path, json.loads(content))
    atomic_write(local_path + ".base.json", {"repo": repo, "path": remote_path, "sha": sha})


def push(repo: str, remote_path: str, local_path: str, message: str, *, create_if_missing: bool = False) -> None:
    """CAS the fetched snapshot; 409 conflicts require refetch + recomputation."""
    sidecar = local_path + ".base.json"
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            base = json.load(f)
        if base.get("repo") != repo or base.get("path") != remote_path or not base.get("sha"):
            raise ValueError("base revision does not match state destination")
        sha = base["sha"]
    elif create_if_missing:
        sha = None  # GitHub rejects creation if a file already exists; never use latest SHA.
    else:
        raise ValueError("fetched base SHA required; fetch before push")
    with open(local_path, "rb") as f:
        raw = f.read()
    json.loads(raw)
    cmd = ["api", f"repos/{repo}/contents/{remote_path}", "-X", "PUT", "-f", f"message={message}",
           "-f", "content=" + base64.b64encode(raw).decode("ascii")]
    if sha:
        cmd.extend(["-f", f"sha={sha}"])
    result = _run_gh(cmd)
    if result.returncode != 0:
        raise RuntimeError("state push failed or conflicted; refetch and recompute before retry")
    # Consume base once: another mutation must start with a new snapshot.
    if os.path.exists(sidecar):
        os.unlink(sidecar)


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
