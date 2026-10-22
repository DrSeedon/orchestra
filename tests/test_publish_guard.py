"""V-1014: forbidden-string publish guard and the shared `.orchestra/private/` folder."""
from __future__ import annotations

import subprocess
from pathlib import Path

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
