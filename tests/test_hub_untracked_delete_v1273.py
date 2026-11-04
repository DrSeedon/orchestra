"""V-1273: two real imports after a scanner refusal, in synthetic Git only."""
import subprocess
from pathlib import Path

import pytest

from app import hub_workspace as hw
from tests.test_hub_workspace import repo, _offline_hub_pool, _backend, _turn, _git


@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_deleted_never_committed_output_is_noop(repo, indexed, mixed):
    before = _git(repo, "rev-parse", "HEAD")
    gone = "deleted output.txt"
    (repo / gone).write_text("temporary output\n")
    if indexed:
        _git(repo, "add", "--", gone)
    (repo / gone).unlink()
    changed = []
    if mixed:
        (repo / "calc.py").write_text("# imported\n")
        changed = ["calc.py"]
    sha, failed = hw.commit_sync(repo, changed, [gone], "hub return")
    assert failed == []
    assert _git(repo, "ls-files", "--", gone) == ""
    if mixed:
        assert sha
        assert _git(repo, "show", "HEAD:calc.py") == "# imported\n"
        assert _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() == changed
    else:
        assert sha == ""
        assert _git(repo, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("staged_deletion", [False, True])
def test_mixed_deletions_preserve_wip_and_visible_refusals(repo, staged_deletion):
    # Include a real deletion, vanished staged addition, unknown deletion,
    # ignored output and missing changed path in one import's candidate set.
    (repo / "native.txt").write_text("original\n")
    (repo / ".gitignore").write_text("/ignored.txt\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    (repo / "native.txt").write_text("staged native\n")
    (repo / "native-add.txt").write_text("staged addition\n")
    _git(repo, "add", "native.txt", "native-add.txt")
    (repo / "native.txt").write_text("unstaged native\n")
    (repo / "native-add.txt").write_text("unstaged addition\n")
    (repo / "native-untracked.txt").write_text("untracked native\n")
    index = _git(repo, "diff", "--cached", "--binary")
    worktree = _git(repo, "diff", "--binary")
    (repo / "vanished.txt").write_text("new\n")
    _git(repo, "add", "vanished.txt")
    (repo / "vanished.txt").unlink()
    (repo / "src/keep.txt").unlink()
    if staged_deletion:
        _git(repo, "add", "-A", "--", "src/keep.txt")
    (repo / "calc.py").write_text("# imported\n")
    (repo / "ignored.txt").write_text("ignored WIP\n")
    sha, failed = hw.commit_sync(
        repo, ["calc.py", "ignored.txt", "missing-changed.txt"],
        ["src/keep.txt", "vanished.txt", "missing-deleted.txt"], "mixed import")
    assert sha
    assert {p for p, why in failed if why} == {"ignored.txt", "missing-changed.txt"}
    assert set(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == {
        "calc.py", "src/keep.txt"}
    assert _git(repo, "diff", "--cached", "--binary") == index
    assert _git(repo, "diff", "--binary") == worktree
    assert (repo / "native-untracked.txt").read_text() == "untracked native\n"
    assert (repo / "ignored.txt").read_text() == "ignored WIP\n"


@pytest.mark.parametrize("inspection", ["ls-files", "diff"])
def test_deletion_inspection_failure_refuses_commit_visibly(repo, monkeypatch, inspection):
    before = _git(repo, "rev-parse", "HEAD")
    (repo / "calc.py").write_text("# imported\n")
    real_run = subprocess.run

    def refuse(command, **kwargs):
        if command[3] == inspection and (inspection == "ls-files" or "--no-renames" in command):
            return subprocess.CompletedProcess(command, 128, "", "synthetic inspection refused")
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", refuse)
    with pytest.raises(hw.HubWorkspaceError, match="cannot inspect hub deletion paths: synthetic inspection refused"):
        hw.commit_sync(repo, ["calc.py"], ["missing-deleted.txt"], "refused inspection")
    assert _git(repo, "rev-parse", "HEAD") == before
    assert (repo / "calc.py").read_text() == "# imported\n"
    assert _git(repo, "diff", "--cached", "--name-only").splitlines() == ["calc.py"]


@pytest.mark.asyncio
async def test_two_imports_after_scanner_guard_commit_survivors(repo, tmp_path, monkeypatch):
    source = Path(hw.__file__).resolve().parents[1]
    support = ["scripts/secret_scan.py", "app/forbidden_strings.py", "app/publication_secrets.py"]
    for rel in support:
        dst = repo / rel
        dst.parent.mkdir(exist_ok=True)
        dst.write_bytes((source / rel).read_bytes())
    (repo / "app/__init__.py").write_text("")
    # The real scanner imports these fixture modules and may write bytecode.
    # Exclude only that generated cache, keeping source/WIP status checks strict.
    with (repo / ".git/info/exclude").open("a") as exclude:
        exclude.write("\n/app/__pycache__/\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "scanner baseline")
    hook = repo / ".git/hooks/pre-commit"
    hook.write_bytes((source / "scripts/hooks/pre-commit").read_bytes())
    hook.chmod(0o755)
    scanner = (repo / "scripts/secret_scan.py").read_bytes()
    before = _git(repo, "rev-parse", "HEAD")
    calls = []

    def edit(remote):
        calls.append(True)
        if len(calls) == 1:
            (remote / "duplicate.txt").write_text("temporary duplicate\n")
            (remote / "survivor.txt").write_text("first import\n")
            # The actual production hook must refuse before any commit.
            (repo / "scripts/secret_scan.py").unlink()
        else:
            (remote / "duplicate.txt").unlink()
            (remote / "survivor.txt").write_text("second import\n")
            (remote / "calc.py").write_text("# second import\n")
            (remote / "src/keep.txt").unlink()

    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, edit)
    first = await _turn(backend, "first import")
    assert first[-1].metadata["ok"] is False
    assert "NOT COMMITTED" in first[-2].content
    assert "secret-gate:" in first[-2].content
    assert _git(repo, "rev-parse", "HEAD") == before
    assert set(_git(repo, "diff", "--cached", "--name-only").splitlines()) == {
        "duplicate.txt", "survivor.txt"}
    assert set(backend._state.hub_made) == {"duplicate.txt", "survivor.txt"}
    assert not backend._state.pending_sync  # first outcome saved, no commit receipt

    (repo / "scripts/secret_scan.py").write_bytes(scanner)
    plan = hw.plan_upload(repo, backend._paths, known=[])
    send, drop = hw.local_delta(repo, plan, backend._state.manifest, keep=set(backend._state.hub_made))
    assert "duplicate.txt" not in drop and "survivor.txt" not in drop
    assert "duplicate.txt" not in send and "survivor.txt" not in send
    second = await _turn(backend, "remove duplicate and finish")
    assert second[-1].metadata["ok"] is True, second[-2].content
    assert "NOT COMMITTED" not in second[-2].content
    assert "deleted 2" in second[-2].content
    assert _git(repo, "show", "HEAD:survivor.txt") == "second import\n"
    assert _git(repo, "show", "HEAD:calc.py") == "# second import\n"
    assert set(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == {
        "calc.py", "src/keep.txt", "survivor.txt"}
    assert _git(repo, "rev-list", "--count", f"{before.strip()}..HEAD").strip() == "1"
    assert _git(repo, "status", "--porcelain") == ""
    state = hw.WorkspaceState.load(backend.session_id)
    assert "duplicate.txt" not in state.manifest and "duplicate.txt" not in state.hub_made
    assert not state.pending_sync and not state.path().with_suffix(".sync.tar").exists()
    assert len(calls) == 2
