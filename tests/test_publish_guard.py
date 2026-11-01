"""V-1014: forbidden-string publish guard and the shared `.orchestra/private/` folder."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import forbidden_strings, private_folder

SECRET = "hub-user-7f3a91"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.invalid")
    (repo / "a.txt").write_text("base\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "base")
    return repo


def _branch(repo: Path, name: str, filename: str, content: str, message: str = "work") -> str:
    _git(repo, "checkout", "-q", "-b", name, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-qm", message)
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    return head


def _rules(tmp_path: Path):
    lst = tmp_path / "forbidden.txt"
    lst.write_text(f"# comment\n\n{SECRET}\n")
    return forbidden_strings.load_rules(lst)


def test_blocks_added_line_and_names_rule_without_value(tmp_path):
    repo = _repo(tmp_path)
    head = _branch(repo, "w", "b.txt", f"login = {SECRET}\n")
    found = forbidden_strings.scan_range(repo, "main", head, _rules(tmp_path))
    assert found and "line 3 of forbidden.txt" in found[0]
    assert SECRET not in forbidden_strings.block_message(found)


def test_blocks_commit_message_and_path(tmp_path):
    repo = _repo(tmp_path)
    in_msg = _branch(repo, "m", "c.txt", "clean\n", message=f"fix {SECRET}")
    in_path = _branch(repo, "p", f"{SECRET}.txt", "clean\n")
    rules = _rules(tmp_path)
    assert forbidden_strings.scan_range(repo, "main", in_msg, rules)
    assert forbidden_strings.scan_range(repo, "main", in_path, rules)


def test_allows_clean_change_and_removal_of_a_leak(tmp_path):
    repo = _repo(tmp_path)
    clean = _branch(repo, "ok", "b.txt", "nothing special\n")
    rules = _rules(tmp_path)
    assert forbidden_strings.scan_range(repo, "main", clean, rules) == []
    (repo / "leak.txt").write_text(f"{SECRET}\n")
    _git(repo, "add", "leak.txt")
    _git(repo, "commit", "-qm", "old leak")
    _git(repo, "checkout", "-q", "-b", "fix", "main")
    _git(repo, "rm", "-q", "leak.txt")
    _git(repo, "commit", "-qm", "remove leak")
    assert forbidden_strings.scan_range(repo, "main", "fix", rules) == []


def test_missing_list_allows_everything(tmp_path):
    assert forbidden_strings.load_rules(tmp_path / "absent.txt") == []


def test_default_list_is_isolated_from_live_checkout(tmp_path):
    repo = _repo(tmp_path)
    path = forbidden_strings.list_path(repo)
    assert path == tmp_path / "forbidden-strings.txt"
    assert forbidden_strings.load_rules(path) == forbidden_strings.publication_secrets.literal_rules(repo)


@pytest.mark.parametrize("location", ["content", "shared_content", "path", "message", "clean"])
def test_orphan_branch_is_scanned_without_a_merge_base(tmp_path, location):
    repo = _repo(tmp_path)
    if location == "shared_content":
        (repo / "a.txt").write_text(f"login = {SECRET}\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-qm", "existing content")
    target_head = _git(repo, "rev-parse", "main")
    _git(repo, "checkout", "-q", "--orphan", "orphan-worker")
    _git(repo, "rm", "-rf", ".")
    filename = f"{SECRET}.txt" if location == "path" else "orphan.txt"
    if location == "shared_content":
        filename = "a.txt"
    content = f"login = {SECRET}\n" if location in {"content", "shared_content"} else "clean\n"
    message = f"work {SECRET}" if location == "message" else "orphan work"
    (repo / filename).write_text(content)
    _git(repo, "add", filename)
    _git(repo, "commit", "-qm", message)
    worker_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    found = forbidden_strings.scan_range(repo, "main", worker_head, _rules(tmp_path))

    if location == "clean":
        assert found == []
    else:
        assert found and "line 3 of forbidden.txt" in found[0]
        if location != "path":
            assert SECRET not in forbidden_strings.block_message(found)
    assert _git(repo, "rev-parse", "main") == target_head
    assert _git(repo, "rev-parse", "orphan-worker") == worker_head
    assert _git(repo, "status", "--porcelain") == ""


def test_merge_base_failure_is_not_treated_as_unrelated_history(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    head = _branch(repo, "w", "b.txt", "clean\n")
    run = forbidden_strings.subprocess.run

    def fail_merge_base(args, **kwargs):
        if args[3] == "merge-base":
            return subprocess.CompletedProcess(args, 128, b"", b"cannot read object")
        return run(args, **kwargs)

    monkeypatch.setattr(forbidden_strings.subprocess, "run", fail_merge_base)
    with pytest.raises(RuntimeError, match="git merge-base failed"):
        forbidden_strings.scan_range(repo, "main", head, _rules(tmp_path))


def test_pre_push_hook_blocks_listed_string(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    head = _branch(repo, "w", "b.txt", f"{SECRET}\n")
    lst = tmp_path / "forbidden.txt"
    lst.write_text(f"{SECRET}\n")
    monkeypatch.setenv(forbidden_strings.ENV_VAR, str(lst))
    scan = Path(__file__).resolve().parents[1] / "scripts" / "secret_scan.py"
    feed = f"refs/heads/w {head} refs/heads/w {'0' * 40}\n"
    run = subprocess.run(
        ["python3", str(scan), "--pre-push"], cwd=repo, input=feed, text=True, capture_output=True,
    )
    assert run.returncode == 1 and "forbidden-string line 1" in run.stderr
    assert SECRET not in run.stderr
    clean = _branch(repo, "c", "d.txt", "fine\n")
    ok = subprocess.run(
        ["python3", str(scan), "--pre-push"], cwd=repo, text=True, capture_output=True,
        input=f"refs/heads/c {clean} refs/heads/c {'0' * 40}\n",
    )
    assert ok.returncode == 0


def test_worktree_private_dir_is_the_main_checkouts_folder(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".orchestra").mkdir()
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "w", str(wt))
    shared = private_folder.ensure_private(wt)
    assert shared == repo / ".orchestra" / "private"
    (wt / ".orchestra" / "private" / "report.md").write_text("x")
    assert (repo / ".orchestra" / "private" / "report.md").read_text() == "x"
    assert private_folder.shared_private_dir(wt) == shared


def test_private_folder_is_ignored_once_excluded(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".orchestra").mkdir()
    (repo / ".git" / "info" / "exclude").write_text(private_folder.EXCLUDE_PATTERN + "\n")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "w", str(wt))
    private_folder.ensure_private(wt)
    (wt / ".orchestra" / "private" / "s.txt").write_text("x")
    assert _git(wt, "status", "--porcelain") == ""


def test_tracked_private_path_is_left_to_the_repo(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".orchestra" / "private").mkdir(parents=True)
    (repo / ".orchestra" / "private" / "k.txt").write_text("tracked")
    _git(repo, "add", "-f", ".orchestra/private/k.txt")
    _git(repo, "commit", "-qm", "tracked")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "w", str(wt))
    assert private_folder.ensure_private(wt) is None
    assert not (wt / ".orchestra" / "private").is_symlink()


def _merge_setup(tmp_path, monkeypatch, content):
    from app.workspace import create_worktree

    repo = _repo(tmp_path)
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
    lst = tmp_path / "forbidden.txt"
    lst.write_text(f"{SECRET}\n")
    monkeypatch.setenv(forbidden_strings.ENV_VAR, str(lst))
    wt = create_worktree(str(repo), "w", base_branch="main")
    (Path(wt.path) / "note.txt").write_text(content)
    _git(Path(wt.path), "add", "note.txt")
    _git(Path(wt.path), "commit", "-qm", "work")
    return repo, wt


def test_merge_gate_refuses_listed_string_and_names_rule(tmp_path, monkeypatch):
    from app.workspace import merge_worktree_to_main

    repo, wt = _merge_setup(tmp_path, monkeypatch, f"user {SECRET}\n")
    res = merge_worktree_to_main(wt.path, str(repo))
    assert res["ok"] is False and res["code"] == "FORBIDDEN_STRING"
    assert "forbidden-string line 1" in res["error"] and SECRET not in res["error"]
    assert not (repo / "note.txt").exists()


def test_merge_gate_allows_leak_removed_before_squash(tmp_path, monkeypatch):
    from app.workspace import merge_worktree_to_main

    # V-1051: squash publishes only the final tree; an intermediate leak never lands.
    repo, wt = _merge_setup(tmp_path, monkeypatch, f"user {SECRET}\n")
    (Path(wt.path) / "note.txt").write_text("clean\n")
    _git(Path(wt.path), "commit", "-qam", "remove leak")
    res = merge_worktree_to_main(wt.path, str(repo))
    assert res["ok"] is True, res
    assert (repo / "note.txt").read_text() == "clean\n"


def test_merge_gate_refuses_orphan_branch_with_listed_string(tmp_path, monkeypatch):
    from app.workspace import merge_worktree_to_main

    repo, wt = _merge_setup(tmp_path, monkeypatch, "clean\n")
    worker = Path(wt.path)
    _git(worker, "checkout", "-q", "--orphan", "orphan-worker")
    _git(worker, "rm", "-rf", ".")
    (worker / "orphan.txt").write_text(f"login = {SECRET}\n")
    _git(worker, "add", "orphan.txt")
    _git(worker, "commit", "-qm", "orphan work")
    target_head = _git(repo, "rev-parse", "main")
    worker_head = _git(worker, "rev-parse", "HEAD")

    result = merge_worktree_to_main(wt.path, str(repo))

    assert result["ok"] is False
    assert result.get("code") == "FORBIDDEN_STRING", result
    assert "forbidden-string line 1" in result["error"]
    assert SECRET not in result["error"]
    assert _git(repo, "rev-parse", "main") == target_head
    assert _git(worker, "rev-parse", "HEAD") == worker_head
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(worker, "status", "--porcelain") == ""


def test_merge_gate_lets_clean_change_land(tmp_path, monkeypatch):
    from app.workspace import merge_worktree_to_main

    repo, wt = _merge_setup(tmp_path, monkeypatch, "harmless\n")
    res = merge_worktree_to_main(wt.path, str(repo))
    assert res.get("ok") is True, res


def test_project_without_orchestra_dir_is_left_untouched(tmp_path):
    repo = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "w", str(wt))
    assert private_folder.ensure_private(wt) is None
    assert not (repo / ".orchestra").exists()


def _two_commit_branch(repo: Path, content_ok: str = "clean\n"):
    _git(repo, "checkout", "-q", "-b", "two", "main")
    (repo / "t.txt").write_text(f"login = {SECRET}\n")
    _git(repo, "add", "t.txt")
    _git(repo, "commit", "-qm", "add")
    (repo / "t.txt").write_text(content_ok)
    _git(repo, "add", "t.txt")
    _git(repo, "commit", "-qm", "remove")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    return head


def test_squash_guard_ignores_leak_removed_in_later_commit(tmp_path):
    repo = _repo(tmp_path)
    head = _two_commit_branch(repo)
    rules = _rules(tmp_path)
    assert forbidden_strings.scan_tree(repo, "main", head, rules) == []
    # pre-push stays per-commit
    assert forbidden_strings.scan_range(repo, "main", head, rules)


def test_squash_guard_refuses_leak_in_final_tree_with_file_and_line(tmp_path):
    repo = _repo(tmp_path)
    head = _two_commit_branch(repo, content_ok=f"ok\nkey = {SECRET}\n")
    found = forbidden_strings.scan_tree(repo, "main", head, _rules(tmp_path))
    assert found and any("t.txt:2" in f for f in found)
    assert SECRET not in forbidden_strings.block_message(found)


def test_squash_guard_refuses_leak_in_squash_message_and_path(tmp_path):
    repo = _repo(tmp_path)
    head = _branch(repo, "q", f"{SECRET}.txt", "clean\n")
    rules = _rules(tmp_path)
    assert forbidden_strings.scan_tree(repo, "main", head, rules)
    clean = _branch(repo, "r", "r.txt", "clean\n")
    assert forbidden_strings.scan_tree(repo, "main", clean, rules, f"note {SECRET}")


def test_squash_guard_refuses_leak_inside_archive_in_final_tree(tmp_path):
    import io
    import tarfile
    repo = _repo(tmp_path)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = f"x = {SECRET}\n".encode()
        info = tarfile.TarInfo("inner.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    _git(repo, "checkout", "-q", "-b", "arc", "main")
    (repo / "a.tgz").write_bytes(buf.getvalue())
    _git(repo, "add", "a.tgz")
    _git(repo, "commit", "-qm", "archive")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    found = forbidden_strings.scan_tree(repo, "main", head, _rules(tmp_path))
    assert found and any("a.tgz" in f for f in found)
