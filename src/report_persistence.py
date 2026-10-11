"""Back up generated report Markdown before committing and retrying Git races.

This module never invokes collection, models, or notification delivery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

GIT_TIMEOUT = 60
MAX_PUSH_ATTEMPTS = 3


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, timeout=GIT_TIMEOUT
    )
    if check and result.returncode:
        # Git diagnostics can contain credential-bearing remote URLs.
        raise RuntimeError(f"Git {args[0]} failed; saved report backup retained")
    return result


def allowed(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return (
        len(parts) == 2 and parts[0] in ("daily", "deep_dive")
        and parts[1].endswith(".md") and not parts[1].startswith(".")
    )


def regular_report(repo: Path, path: str) -> Path:
    source = repo / path
    if not allowed(path) or source.parent.is_symlink() or source.is_symlink() or not source.is_file():
        raise ValueError("Report must be a direct regular Markdown file")
    return source


def changed_reports(repo: Path) -> list[str]:
    if any((repo / directory).is_symlink() for directory in ("daily", "deep_dive")):
        raise ValueError("Report directory must contain direct regular Markdown files")
    tracked = git(repo, "diff", "--name-only", "-z", "HEAD").stdout
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    paths = {p.decode("utf-8") for p in (tracked + untracked).split(b"\0") if p}
    # Deletions are not generated reports. Symlinks fail closed instead of being copied.
    return sorted(p for p in paths if allowed(p) and (repo / p).exists())


def snapshot(repo: Path, destination: Path) -> None:
    repo = repo.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(repo):
        raise ValueError("Backup directory must be outside the checkout")
    destination.mkdir(parents=True, exist_ok=False)
    entries = {}
    for path in changed_reports(repo):
        raw = regular_report(repo, path).read_bytes()
        target = destination / "reports" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        entries[path] = hashlib.sha256(raw).hexdigest()
    # Metadata is outside reports/ and never part of the uploaded artifact.
    (destination / "manifest.json").write_text(json.dumps({
        "base": git(repo, "rev-parse", "HEAD").stdout.decode().strip(),
        "reports": entries,
    }), encoding="utf-8")
    print(f"Saved {len(entries)} changed Markdown reports")


def persist(repo: Path, backup: Path, message: str) -> None:
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    base = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    if manifest["base"] != base:
        raise ValueError("Checkout changed since report backup")
    paths = sorted(manifest["reports"])
    if paths != changed_reports(repo):
        raise ValueError("Report list changed since backup")
    for path in paths:
        raw = regular_report(repo, path).read_bytes()
        saved = regular_report(backup / "reports", path).read_bytes()
        if raw != saved or hashlib.sha256(raw).hexdigest() != manifest["reports"][path]:
            raise ValueError("Report contents changed since backup")
    if not paths:
        print("No new reports to commit")
        return
    if git(repo, "diff", "--cached", "--quiet", check=False).returncode:
        raise ValueError("Refusing pre-existing staged changes")
    # Rebase requires clean tracked files. Do not stash or discard other work.
    dirty = git(repo, "diff", "--name-only", "-z").stdout.split(b"\0")
    if any(p and p.decode("utf-8") not in paths for p in dirty):
        raise ValueError("Unrelated tracked changes; report backup retained")
    git(repo, "add", "--", *paths)
    git(repo, "commit", "-m", message)
    for attempt in range(MAX_PUSH_ATTEMPTS):
        if git(repo, "push", "origin", "HEAD:refs/heads/main", check=False).returncode == 0:
            print("Reports persisted to main")
            return
        if attempt == MAX_PUSH_ATTEMPTS - 1:
            break
        fetch_args = ["fetch", "--no-tags"]
        if git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == b"true":
            fetch_args.append("--unshallow")
        git(repo, *fetch_args, "origin", "refs/heads/main")
        latest = git(repo, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
        head = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        if latest == head:  # A push may have succeeded despite a transport error.
            return
        if latest == base or git(repo, "merge-base", "--is-ancestor", base, latest, check=False).returncode:
            raise RuntimeError("Push failed without a safe main advance; backup retained")
        result = git(repo, "rebase", "--onto", latest, base, check=False)
        if result.returncode:
            git(repo, "rebase", "--abort")
            raise RuntimeError("Report rebase conflicted; stopped with backup retained")
        base = latest
    raise RuntimeError("Report push attempts exhausted; backup retained")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "persist"))
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--message", default="生成済みペインレポートを保存")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            snapshot(Path.cwd(), args.backup)
        else:
            persist(Path.cwd(), args.backup, args.message)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        # Avoid raw subprocess diagnostics, file contents, and environment values.
        print(f"Report persistence stopped ({type(exc).__name__}); inspect saved reports", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
