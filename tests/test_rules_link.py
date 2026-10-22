"""V-902 — AGENTS.md/CLAUDE.md: симлинк, лечение копий, тревога при расхождении.

Настоящие временные git-репозитории; подменено только хранилище kv и список сессий.
"""
import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from app import rules_link


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def make_repo(tmp_path, files, symlinks=True):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@example.com")
    if not symlinks:
        git(root, "config", "core.symlinks", "false")
    for name, content in files.items():
        if isinstance(content, tuple):
            os.symlink(content[0], root / name)
        else:
            (root / name).write_text(content)
    (root / "x.txt").write_text("x")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def head(root):
    return git(root, "rev-parse", "HEAD").strip()


def clean(root):
    return git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("files", [
    {"AGENTS.md": "rules", "CLAUDE.md": ("AGENTS.md",)},
    {"CLAUDE.md": "rules", "AGENTS.md": ("CLAUDE.md",)},
    {"AGENTS.md": "rules", "CLAUDE.md": "@AGENTS.md\n"},
])
def test_already_linked_is_left_alone(tmp_path, files):
    root = make_repo(tmp_path, files)
    before = head(root)
    assert rules_link.reconcile(root).state == "linked"
    assert head(root) == before and clean(root)


def test_identical_copies_become_symlink_and_commit(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": "rules", "CLAUDE.md": "rules"})
    before = head(root)
    assert rules_link.reconcile(root).state == "converted"
    assert (root / "CLAUDE.md").is_symlink() and not (root / "AGENTS.md").is_symlink()
    assert (root / "CLAUDE.md").read_text() == "rules"
    assert head(root) != before and clean(root)
    assert rules_link.reconcile(root).state == "linked"


def test_single_file_gets_symlink_to_it(tmp_path):
    root = make_repo(tmp_path, {"CLAUDE.md": "only"})
    assert rules_link.reconcile(root).state == "converted"
    assert (root / "AGENTS.md").is_symlink() and not (root / "CLAUDE.md").is_symlink()
    assert (root / "AGENTS.md").read_text() == "only"
    assert clean(root)


def test_diverged_copies_are_never_overwritten(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": "old rules", "CLAUDE.md": "newer, longer rules"})
    before = head(root)
    outcome = rules_link.reconcile(root)
    assert outcome.state == "diverged" and outcome.needs_attention
    assert outcome.sizes == {"AGENTS.md": 9, "CLAUDE.md": 19}
    assert (root / "AGENTS.md").read_text() == "old rules"
    assert (root / "CLAUDE.md").read_text() == "newer, longer rules"
    assert head(root) == before and clean(root)


def test_without_symlink_support_an_exact_copy_is_kept(tmp_path):
    root = make_repo(tmp_path, {"CLAUDE.md": "only"}, symlinks=False)
    assert rules_link.reconcile(root).state == "copied"
    assert not (root / "AGENTS.md").is_symlink()
    assert (root / "AGENTS.md").read_bytes() == (root / "CLAUDE.md").read_bytes()
    assert clean(root)


def test_without_symlink_support_identical_copies_stay_copies(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": "rules", "CLAUDE.md": "rules"}, symlinks=False)
    before = head(root)
    assert rules_link.reconcile(root).state == "linked_copy"
    assert not (root / "CLAUDE.md").is_symlink() and head(root) == before


def test_without_symlink_support_divergence_still_alarms(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": "a", "CLAUDE.md": "bb"}, symlinks=False)
    assert rules_link.reconcile(root).state == "diverged"


def test_dirty_rules_file_blocks_the_change(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": "rules", "CLAUDE.md": "stale"})
    (root / "CLAUDE.md").write_text("rules")
    outcome = rules_link.reconcile(root)
    assert outcome.state == "blocked" and "uncommitted" in outcome.detail
    assert not (root / "CLAUDE.md").is_symlink()


def test_off_mainline_branch_blocks_the_change(tmp_path):
    root = make_repo(tmp_path, {"CLAUDE.md": "only"})
    git(root, "checkout", "-q", "-b", "feature")
    assert rules_link.reconcile(root).state == "blocked"
    assert not (root / "AGENTS.md").exists()


def test_failed_commit_rolls_back_to_the_original_bytes(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": "rules", "CLAUDE.md": "rules"})
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    before = head(root)
    outcome = rules_link.reconcile(root)
    assert outcome.state == "blocked" and "rolled back" in outcome.detail
    assert not (root / "CLAUDE.md").is_symlink() and (root / "CLAUDE.md").read_text() == "rules"
    assert head(root) == before and clean(root)


def test_plain_directory_without_git_is_converted_in_place(tmp_path):
    root = tmp_path / "nogit"
    root.mkdir()
    (root / "CLAUDE.md").write_text("only")
    assert rules_link.reconcile(root).state == "converted"
    assert (root / "AGENTS.md").is_symlink()


def test_dangling_symlink_is_reported(tmp_path):
    root = make_repo(tmp_path, {"AGENTS.md": ("gone.md",)})
    assert rules_link.reconcile(root).state == "broken"


def test_no_rules_files_is_not_a_problem(tmp_path):
    root = make_repo(tmp_path, {})
    assert rules_link.reconcile(root).state == "absent"


@pytest.fixture
def kv(tmp_path, monkeypatch):
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()


def test_alert_repeats_daily_not_every_sweep(kv):
    bad = rules_link.Outcome("diverged")
    t0 = 1_000_000.0
    assert rules_link.due_for_alert("/p", bad, t0)
    assert not rules_link.due_for_alert("/p", bad, t0 + 6 * 3600)
    assert rules_link.due_for_alert("/p", bad, t0 + rules_link.REALERT_SECONDS + 1)


def test_alert_fires_at_once_when_problem_kind_changes_and_resets_when_fixed(kv):
    t0 = 1_000_000.0
    assert rules_link.due_for_alert("/p", rules_link.Outcome("diverged"), t0)
    assert rules_link.due_for_alert("/p", rules_link.Outcome("blocked"), t0 + 60)
    assert not rules_link.due_for_alert("/p", rules_link.Outcome("linked"), t0 + 120)
    assert rules_link.due_for_alert("/p", rules_link.Outcome("blocked"), t0 + 180)


class FakeManager:
    def __init__(self):
        self.sent = []

    async def send(self, session_id, text, provenance=None):
        self.sent.append((session_id, text, provenance.subtype))


def test_sweep_alerts_project_orchestrator_once(kv, tmp_path, monkeypatch):
    import app.db as dbmod
    root = make_repo(tmp_path, {"AGENTS.md": "old", "CLAUDE.md": "newer rules"})
    rows = [{"id": "o1", "name": "proj-orch", "scope": str(root), "is_orchestrator": 1,
             "role": "orchestrator", "status": "idle"}]
    monkeypatch.setattr(dbmod, "get_all_sessions", lambda *a, **k: rows)
    manager = FakeManager()
    assert asyncio.run(rules_link.sweep(manager)) == {str(root): "diverged"}
    assert asyncio.run(rules_link.sweep(manager)) == {str(root): "diverged"}
    assert len(manager.sent) == 1
    sid, text, subtype = manager.sent[0]
    assert sid == "o1" and subtype == "rules_link" and "3 B" in text and "11 B" in text


def test_sweep_heals_silently_without_alert(kv, tmp_path, monkeypatch):
    import app.db as dbmod
    root = make_repo(tmp_path, {"CLAUDE.md": "only"})
    rows = [{"id": "w1", "name": "w", "scope": str(root), "is_orchestrator": 0, "status": "idle"}]
    monkeypatch.setattr(dbmod, "get_all_sessions", lambda *a, **k: rows)
    manager = FakeManager()
    assert asyncio.run(rules_link.sweep(manager)) == {str(root): "converted"}
    assert manager.sent == [] and (root / "AGENTS.md").is_symlink()


def test_blocked_alerts_once_per_detail_not_daily(kv):
    t0 = 1_000_000.0
    stuck = rules_link.Outcome("blocked", "checked-out branch is dev, not mainline main")
    assert rules_link.due_for_alert("/p", stuck, t0)
    assert not rules_link.due_for_alert("/p", stuck, t0 + rules_link.REALERT_SECONDS * 3)
    other = rules_link.Outcome("blocked", "HEAD is detached")
    assert rules_link.due_for_alert("/p", other, t0 + rules_link.REALERT_SECONDS * 3 + 1)


def test_diverged_still_realerts_after_a_day(kv):
    t0 = 1_000_000.0
    bad = rules_link.Outcome("diverged", "x")
    assert rules_link.due_for_alert("/p", bad, t0)
    assert not rules_link.due_for_alert("/p", bad, t0 + 3600)
    assert rules_link.due_for_alert("/p", bad, t0 + rules_link.REALERT_SECONDS + 1)
