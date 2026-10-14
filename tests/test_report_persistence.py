"""Synthetic local Git remotes only: no collection, models, or delivery."""
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from src import report_persistence as rp


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def configure(repo):
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.hooksPath", "/dev/null")


def commit(repo, path, text):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git(repo, "add", "--", path)
    git(repo, "commit", "-m", "synthetic fixture")


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)],
                   check=True, capture_output=True)
    writer = tmp_path / "writer"
    subprocess.run(["git", "clone", str(remote), str(writer)], check=True, capture_output=True)
    configure(writer)
    commit(writer, "daily/existing.md", "base\n")
    commit(writer, "README.md", "baseline\n")
    git(writer, "push", "origin", "main")
    checkout = tmp_path / "collector"
    subprocess.run(["git", "clone", "--depth=1", remote.as_uri(), str(checkout)],
                   check=True, capture_output=True)
    configure(checkout)
    return remote, writer, checkout, tmp_path / "backup"


def generated(checkout):
    (checkout / "daily/generated.md").write_text("generated daily\n")
    (checkout / "deep_dive").mkdir()
    (checkout / "deep_dive/generated.md").write_text("generated deep dive\n")


def race(monkeypatch, writer, count, path="README.md"):
    original = rp.git
    pushes = []

    def racing(repo, *args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            if len(pushes) <= count:
                commit(writer, path, f"remote advance {len(pushes)}\n")
                git(writer, "push", "origin", "main")
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(rp, "git", racing)
    return pushes


@pytest.mark.parametrize("races", [1, 2])
def test_shallow_concurrent_main_advances_preserve_reports(repos, monkeypatch, races):
    remote, writer, checkout, backup = repos
    generated(checkout)
    assert git(checkout, "rev-parse", "--is-shallow-repository") == "true"
    rp.snapshot(checkout, backup)
    advances = race(monkeypatch, writer, races)
    rp.persist(checkout, backup, "synthetic report")
    assert len(advances) == races + 1
    assert git(remote, "show", "main:daily/generated.md") == "generated daily"
    assert git(remote, "show", "main:deep_dive/generated.md") == "generated deep dive"
    assert git(remote, "show", "main:README.md") == f"remote advance {races}"
    assert git(checkout, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")
    assert git(checkout, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() == [
        "daily/generated.md", "deep_dive/generated.md"]
    assert not any("--force" in arg or arg.startswith("+") for args in advances for arg in args)


def test_report_conflict_aborts_and_keeps_original_backup(repos, monkeypatch):
    remote, writer, checkout, backup = repos
    (checkout / "daily/existing.md").write_text("generated replacement\n")
    rp.snapshot(checkout, backup)
    advances = race(monkeypatch, writer, 1, "daily/existing.md")
    with pytest.raises(RuntimeError, match="conflicted"):
        rp.persist(checkout, backup, "synthetic report")
    assert len(advances) == 1
    assert (backup / "reports/daily/existing.md").read_text() == "generated replacement\n"
    assert git(remote, "show", "main:daily/existing.md") == "remote advance 1"
    assert git(checkout, "show", "HEAD:daily/existing.md") == "generated replacement"
    assert git(checkout, "status", "--porcelain") == ""
    assert not Path(git(checkout, "rev-parse", "--absolute-git-dir"), "rebase-merge").exists()


def test_final_race_failure_retains_exact_backup(repos, monkeypatch):
    remote, writer, checkout, backup = repos
    generated(checkout)
    rp.snapshot(checkout, backup)
    advances = race(monkeypatch, writer, 3)
    with pytest.raises(RuntimeError, match="exhausted"):
        rp.persist(checkout, backup, "synthetic report")
    assert len(advances) == 3
    assert (backup / "reports/daily/generated.md").read_text() == "generated daily\n"
    assert (backup / "reports/deep_dive/generated.md").read_text() == "generated deep dive\n"
    assert subprocess.run(["git", "-C", str(remote), "cat-file", "-e", "main:daily/generated.md"],
                          capture_output=True).returncode != 0


def test_no_changes_does_not_commit_fetch_or_push(repos, monkeypatch):
    remote, _, checkout, backup = repos
    rp.snapshot(checkout, backup)
    base = git(remote, "rev-parse", "main")
    original = rp.git

    def guard(repo, *args, **kwargs):
        assert args[0] not in ("commit", "fetch", "push", "add", "rebase")
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(rp, "git", guard)
    rp.persist(checkout, backup, "synthetic report")
    assert json.loads((backup / "manifest.json").read_text())["reports"] == {}
    assert git(remote, "rev-parse", "main") == base


def test_snapshot_allowlist_excludes_sensitive_and_nested_files(repos):
    _, _, checkout, backup = repos
    generated(checkout)
    for path in ("daily/raw.json", "daily/nested/report.md", "daily/.hidden.md",
                 "deep_dive/data.json", "raw/posts.json", "logs/run.log", "data/state.json",
                 ".env", ".notification-state/receipts.json", ".notification-outbox/outbox.json"):
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("sensitive fixture")
    rp.snapshot(checkout, backup)
    assert sorted(str(p.relative_to(backup / "reports")) for p in (backup / "reports").rglob("*")
                  if p.is_file()) == ["daily/generated.md", "deep_dive/generated.md"]


@pytest.mark.parametrize("parent_link", [False, True])
def test_symlink_cannot_expose_external_file(repos, tmp_path, parent_link):
    _, _, checkout, backup = repos
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret fixture")
    if parent_link:
        (checkout / "deep_dive").symlink_to(outside, target_is_directory=True)
    else:
        (checkout / "daily/secret.md").symlink_to(outside / "secret.md")
    with pytest.raises(ValueError, match="regular Markdown"):
        rp.snapshot(checkout, backup)
    assert not (backup / "manifest.json").exists()


@pytest.mark.parametrize("staged", [False, True])
def test_unrelated_changes_fail_after_backup_without_commit(repos, staged):
    remote, _, checkout, backup = repos
    generated(checkout)
    (checkout / "README.md").write_text("unrelated work\n")
    if staged:
        git(checkout, "add", "README.md")
    rp.snapshot(checkout, backup)
    base = git(checkout, "rev-parse", "HEAD")
    with pytest.raises(ValueError):
        rp.persist(checkout, backup, "synthetic report")
    assert git(checkout, "rev-parse", "HEAD") == base == git(remote, "rev-parse", "main")
    assert (checkout / "README.md").read_text() == "unrelated work\n"
    assert (backup / "reports/daily/generated.md").read_text() == "generated daily\n"


def test_report_change_after_backup_fails_closed(repos):
    _, _, checkout, backup = repos
    generated(checkout)
    rp.snapshot(checkout, backup)
    (checkout / "daily/generated.md").write_text("changed after snapshot")
    with pytest.raises(ValueError, match="contents changed"):
        rp.persist(checkout, backup, "synthetic report")


def test_non_race_push_failure_stops_without_force(repos, monkeypatch):
    _, _, checkout, backup = repos
    generated(checkout)
    rp.snapshot(checkout, backup)
    original = rp.git
    pushes = []

    def reject(repo, *args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            return subprocess.CompletedProcess(args, 1, b"", b"private diagnostic")
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(rp, "git", reject)
    with pytest.raises(RuntimeError, match="safe main advance"):
        rp.persist(checkout, backup, "synthetic report")
    assert len(pushes) == 1
    assert (backup / "reports/daily/generated.md").exists()


def test_workflow_uploads_only_markdown_before_persistence_and_keeps_notification_policy():
    repo = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((repo / ".github/workflows/collect.yml").read_text())
    steps = workflow["jobs"]["collect"]["steps"]
    snapshot_step = next(i for i, s in enumerate(steps) if "report_persistence snapshot" in s.get("run", ""))
    report_step = next(i for i, s in enumerate(steps) if s.get("name") == "Preserve generated report Markdown")
    persist_step = next(i for i, s in enumerate(steps) if "report_persistence persist" in s.get("run", ""))
    assert snapshot_step < report_step < persist_step
    artifact = steps[report_step]
    assert artifact["uses"] == "actions/upload-artifact@v4"
    assert artifact["with"]["path"].splitlines() == [
        "${{ runner.temp }}/collected-reports/reports/daily/*.md",
        "${{ runner.temp }}/collected-reports/reports/deep_dive/*.md"]
    assert artifact["with"]["retention-days"] == 7
    assert artifact["with"]["if-no-files-found"] == "ignore"
    assert "if" not in steps[persist_step] and "continue-on-error" not in artifact
    assert steps[persist_step]["run"].splitlines()[0] == 'test "$GITHUB_REF" = "refs/heads/main"'
    notifications = next(s for s in steps if s.get("with", {}).get("name", "").startswith("slack-delivery-"))
    assert notifications["with"]["retention-days"] == 90
    assert notifications["with"]["include-hidden-files"] is True
    assert notifications["with"]["path"].splitlines() == [".notification-state/*.json", ".notification-outbox/**"]
    assert "always()" in notifications["if"]
    assert sum("python -m src.main" in s.get("run", "") for s in steps) == 1
