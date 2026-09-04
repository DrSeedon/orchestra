"""#473: the layout migration repairs worker ownership, and ownership moves without a branch switch.

Ownership has two owners — the `sessions.owned_dirs` column and the "## Directory ownership"
block inside the stored prompt. Every test here asserts BOTH: fixing one and leaving the other
is the defect this task exists for.
"""

# LEGACY_PATH_FIXTURE: docs/ paths below are the pre-migration state under repair.

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def mgr(db, tmp_path, monkeypatch):
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.manager import SessionManager
    return SessionManager()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True,
    )


def _old_layout_repo(tmp_path: Path, name: str) -> Path:
    """A checkout still on the pre-migration layout, with a task the worker owns."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "task473@example.invalid")
    _git(repo, "config", "user.name", "task473")
    (repo / ".gitignore").write_text("workers/\n", encoding="utf-8")
    for dirname in ("kb", "tasks", "workers", "archive"):
        target = repo / "docs" / dirname
        target.mkdir(parents=True)
        (target / f"{dirname}.md").write_text(f"{dirname}\n", encoding="utf-8")
    (repo / "docs" / "tasks" / "88").mkdir()
    (repo / "docs" / "tasks" / "88" / "plan.md").write_text("plan\n", encoding="utf-8")
    (repo / "oil-paint").mkdir()
    (repo / "oil-paint" / "style.md").write_text("style\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "old layout")
    return repo


def _prompt_for(owned: list[str], *, memory: str = "- remember this") -> tuple[str, str]:
    """(system_prompt, prompt_overlay) exactly as create_session assembles them."""
    from app.manager import SessionManager

    overlay = "\n\nTASK TEXT" + SessionManager._ownership_prompt(owned)
    prompt = "ROLE BASE" + overlay + f"\n\n<worker-memory>\n{memory}\n</worker-memory>"
    return prompt, overlay


def _save_worker(*, name: str, scope: str, owned: list[str], status: str = "idle") -> None:
    from app.db import save_session

    prompt, overlay = _prompt_for(owned)
    save_session({
        "id": f"sid-{name}", "name": name, "scope": scope, "cwd": "/tmp",
        "model": "claude-sonnet-5[1m]", "system_prompt": prompt,
        "prompt_overlay": overlay, "status": status, "session_id": "native",
        "cost_usd": 0.0, "worktree_path": None, "branch": "", "is_orchestrator": False,
        "color": "#fff", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None, "owned_dirs": json.dumps(owned), "role": "worker",
        "pipeline": "default",
    })


def _session_count() -> int:
    from app.db import _conn

    with _conn() as connection:
        return connection.execute("SELECT count(*) FROM sessions").fetchone()[0]


# ── Ч1: the migration that moves the files also moves the ownership ──

def test_layout_migration_repoints_ownership_in_column_and_prompt(db, tmp_path):
    from app.db import get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    _save_worker(name="painter-canvas", scope=str(repo), owned=["docs/tasks/88", "oil-paint"])
    other = tmp_path / "elsewhere"
    other.mkdir()
    _save_worker(name="outsider", scope=str(other), owned=["docs/tasks/88"])

    result = layout.migrate_project_layout(repo, repair=False)

    assert result["status"] == "migrated"
    assert result["ownership"]["changed"] == 1

    row = get_session_by_name("painter-canvas", str(repo))
    assert json.loads(row["owned_dirs"]) == [".orchestra/tasks/88", "oil-paint"]
    for stored in (row["system_prompt"], row["prompt_overlay"]):
        assert "- .orchestra/tasks/88/" in stored
        assert "docs/tasks/88" not in stored
        # Anything that did not move stays verbatim.
        assert "- oil-paint/" in stored
    # The block is rewritten, not the prompt: base, task text and memory survive.
    assert row["system_prompt"].startswith("ROLE BASE\n\nTASK TEXT")
    assert "<worker-memory>\n- remember this\n</worker-memory>" in row["system_prompt"]

    # A worker of another checkout is not touched by this repository's migration.
    untouched = get_session_by_name("outsider", str(other))
    assert json.loads(untouched["owned_dirs"]) == ["docs/tasks/88"]
    assert "- docs/tasks/88/" in untouched["system_prompt"]


def test_migration_leaves_unmigrated_legacy_roots_alone_but_names_them(db, tmp_path):
    """docs/portfolio was deleted, not moved: inventing .orchestra/portfolio is worse."""
    from app.db import get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "orchestra")
    # Give the worker a real, empty worktree: with both trees searchable, "absent" is a
    # fact rather than "unchecked" (#482). The test used to leave this implicit.
    worktree = tmp_path / "wt-portfolio"
    worktree.mkdir()
    _save_worker_with_worktree(
        name="portfolio-orchestra", scope=str(repo), owned=["docs/portfolio"],
        worktree=str(worktree),
    )

    result = layout.migrate_project_layout(repo, repair=False)

    assert result["ownership"]["changed"] == 0
    row = get_session_by_name("portfolio-orchestra", str(repo))
    assert json.loads(row["owned_dirs"]) == ["docs/portfolio"]

    attention = result["ownership"]["attention"]
    assert result["ownership"]["attention_count"] == len(attention) == 1
    assert attention[0]["session"] == "portfolio-orchestra"
    assert attention[0]["path"] == "docs/portfolio"
    assert attention[0]["exists"] is False
    assert "left verbatim" in attention[0]["reason"]


def test_ownership_failure_does_not_stop_the_fleet_or_the_server(db, tmp_path, monkeypatch):
    """A locked DB must not turn a startup ownership repair into a boot failure.

    `migrate_registered_project_layouts` runs in `app/main.py` lifespan for every
    project, and `migrate_registered_projects` only isolates LayoutMigrationError —
    so a raw sqlite error escaping here would stop Orchestra starting at all.
    """
    from app import orchestra_layout as layout

    first = _old_layout_repo(tmp_path, "alpha")
    second = _old_layout_repo(tmp_path, "beta")

    def boom(_repository, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(layout, "migrate_session_ownership", boom)

    fleet = layout.migrate_registered_projects({"alpha": first, "beta": second})

    # Both projects still migrated their files, and neither raised.
    for name, repo in (("alpha", first), ("beta", second)):
        assert fleet[name]["status"] == "migrated"
        assert (repo / ".orchestra" / "tasks" / "88" / "plan.md").is_file()
        for moved in ("kb", "tasks", "workers", "archive"):
            assert not (repo / "docs" / moved).exists()
        ownership = fleet[name]["ownership"]
        assert ownership["status"] == "failed"
        assert "database is locked" in ownership["error"]
        assert ownership["changed"] == 0


def test_ownership_failure_on_an_already_migrated_project_does_not_escape(
    db, tmp_path, monkeypatch,
):
    """The path production actually takes — and the only one that can kill the boot.

    All five affected projects are already migrated, so their repair runs from the
    `already_current` return, which sits OUTSIDE the try/except that converts errors
    into LayoutMigrationError. An escape here is not a failed project: it is a server
    that does not start, for every project, over a repair that retries for free.
    """
    from app import orchestra_layout as layout

    first = _old_layout_repo(tmp_path, "alpha")
    second = _old_layout_repo(tmp_path, "beta")
    clean = layout.migrate_registered_projects({"alpha": first, "beta": second})
    assert [clean[name]["status"] for name in ("alpha", "beta")] == ["migrated", "migrated"]

    def boom(_repository, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(layout, "migrate_session_ownership", boom)

    again = layout.migrate_registered_projects({"alpha": first, "beta": second})

    for name in ("alpha", "beta"):
        assert again[name]["status"] == "already_current"
        assert again[name]["ownership"]["status"] == "failed"
        assert "database is locked" in again[name]["ownership"]["error"]


# ── Ч2: the one-shot repair of rows the migration already left behind ──

def test_ownership_repair_is_idempotent(db, tmp_path):
    from app.db import get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)  # files move, no sessions yet
    _save_worker(name="painter-canvas", scope=str(repo), owned=["docs/tasks/88", "oil-paint"])
    _save_worker(name="portfolio-orchestra", scope=str(repo), owned=["docs/portfolio"])
    _save_worker(name="dead-one", scope=str(repo), owned=["docs/tasks/88"], status="archived")
    rows_before = _session_count()

    first = layout.repair_registered_ownership({"comfy": repo})

    assert first["changed"] == 1
    assert first["projects"]["comfy"]["plan"][0]["before"] == ["docs/tasks/88", "oil-paint"]
    assert first["projects"]["comfy"]["plan"][0]["after"] == [".orchestra/tasks/88", "oil-paint"]
    assert first["projects"]["comfy"]["plan"][0]["prompt_changed"] is True
    assert first["projects"]["comfy"]["plan"][0]["overlay_changed"] is True
    unmapped = [item for item in first["projects"]["comfy"]["attention"]
                if item["path"] == "docs/portfolio"]
    assert len(unmapped) == 1 and unmapped[0]["session"] == "portfolio-orchestra"

    second = layout.repair_registered_ownership({"comfy": repo})

    assert second["changed"] == 0
    assert second["projects"]["comfy"]["plan"] == []
    # The unrepairable row is still reported on every run — silence would read as "fine".
    assert second["attention_count"] == first["attention_count"]
    assert _session_count() == rows_before

    assert json.loads(get_session_by_name("painter-canvas", str(repo))["owned_dirs"]) == [
        ".orchestra/tasks/88", "oil-paint",
    ]
    # An archived worker is not live ownership and stays untouched.
    with sqlite3.connect(str(db)) as connection:
        dead = connection.execute(
            "SELECT owned_dirs FROM sessions WHERE name='dead-one'"
        ).fetchone()[0]
    assert json.loads(dead) == ["docs/tasks/88"]


def test_repair_ownership_cli_prints_the_plan_and_repeats_to_zero(db, tmp_path):
    repo = _old_layout_repo(tmp_path, "comfy")
    from app import orchestra_layout as layout
    layout.migrate_project_layout(repo, repair=False)
    _save_worker(name="painter-canvas", scope=str(repo), owned=["docs/tasks/88", "oil-paint"])
    rows_before = _session_count()

    script = ROOT / "scripts" / "migrate_orchestra_layout.py"
    env = {**os.environ, "ORCHESTRA_DB_PATH": str(db)}

    # Positive control: the child really resolves the isolated database. Without this the
    # subprocess below could be writing to the production DB and still look green.
    resolved = subprocess.run(
        [sys.executable, "-c", "import app.db; print(app.db.DB_PATH)"],
        cwd=str(ROOT), env=env, text=True, capture_output=True, check=True,
    )
    assert resolved.stdout.strip() == str(db)

    def run(*args: str) -> dict:
        done = subprocess.run(
            [sys.executable, str(script), "--repair-ownership", *args],
            cwd=str(ROOT), env=env, text=True, capture_output=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)

    dry = run("--dry-run", str(repo))
    assert dry["applied"] is False and dry["changed"] == 1
    assert dry["deferred_count"] == 0, "an idle fixture worker is not treated as resident"
    assert dry["plan"][0]["after"] == [".orchestra/tasks/88", "oil-paint"]
    with sqlite3.connect(str(db)) as connection:
        still_legacy = connection.execute(
            "SELECT owned_dirs FROM sessions WHERE name='painter-canvas'"
        ).fetchone()[0]
    assert json.loads(still_legacy) == ["docs/tasks/88", "oil-paint"]

    applied = run(str(repo))
    assert applied["applied"] is True and applied["changed"] == 1

    again = run(str(repo))
    assert again["changed"] == 0 and again["plan"] == []
    assert _session_count() == rows_before


# ── Sol round 1 findings: each accepted blocker pinned by its own test ──

def test_migration_refuses_a_rewrite_that_would_overlap_another_worker(db, tmp_path):
    """F1: mapping row-by-row cannot see that the target is already owned."""
    from app.db import get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    _save_worker(name="legacy-owner", scope=str(repo), owned=["docs/tasks/88"])
    _save_worker(name="current-owner", scope=str(repo), owned=[".orchestra/tasks/88"])

    result = layout.migrate_session_ownership(repo)

    assert result["changed"] == 0
    assert json.loads(
        get_session_by_name("legacy-owner", str(repo))["owned_dirs"]
    ) == ["docs/tasks/88"]
    overlap = [item for item in result["attention"] if "overlap" in item["reason"]]
    assert len(overlap) == 1
    assert overlap[0]["session"] == "legacy-owner"
    assert ".orchestra/tasks/88" in overlap[0]["path"]


def test_quoted_ownership_heading_does_not_divert_the_rewrite(db, tmp_path):
    """F5: task text may quote the heading; the generated block must still be the one moved."""
    from app.db import save_session, get_session_by_name
    from app.manager import ownership_block
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    owned = ["docs/tasks/88"]
    # An operator overlay that quotes the heading and a bullet BEFORE the real suffix.
    quoted = ("\n\nTASK: the block below is what a worker sees:"
              "\n\n## Directory ownership\n- docs/tasks/999/\nEnd of quotation.")
    overlay = quoted + ownership_block(owned)
    prompt = "ROLE BASE" + overlay
    save_session({
        "id": "sid-quoted", "name": "quoted", "scope": str(repo), "cwd": "/tmp",
        "model": "claude-sonnet-5[1m]", "system_prompt": prompt, "prompt_overlay": overlay,
        "status": "idle", "session_id": "native", "cost_usd": 0.0, "worktree_path": None,
        "branch": "", "is_orchestrator": False, "color": "#fff",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "owned_dirs": json.dumps(owned), "role": "worker", "pipeline": "default",
    })

    assert layout.migrate_session_ownership(repo)["changed"] == 1

    row = get_session_by_name("quoted", str(repo))
    assert json.loads(row["owned_dirs"]) == [".orchestra/tasks/88"]
    for stored in (row["system_prompt"], row["prompt_overlay"]):
        # The real generated block moved...
        assert ownership_block([".orchestra/tasks/88"]) in stored
        # ...and the quotation was left exactly as the operator wrote it.
        assert "- docs/tasks/999/\nEnd of quotation." in stored


def test_prompt_without_a_generated_block_is_reported_not_half_migrated(db, tmp_path):
    """F5 corollary: a column-only rewrite would look fixed and change nothing for the agent."""
    from app.db import save_session, get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    save_session({
        "id": "sid-drift", "name": "drifted", "scope": str(repo), "cwd": "/tmp",
        "model": "claude-sonnet-5[1m]", "system_prompt": "FREEFORM OPERATOR PROMPT",
        "prompt_overlay": None, "status": "idle", "session_id": "native", "cost_usd": 0.0,
        "worktree_path": None, "branch": "", "is_orchestrator": False, "color": "#fff",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "owned_dirs": json.dumps(["docs/tasks/88"]), "role": "worker", "pipeline": "default",
    })

    result = layout.migrate_session_ownership(repo)

    assert result["changed"] == 0
    assert json.loads(
        get_session_by_name("drifted", str(repo))["owned_dirs"]
    ) == ["docs/tasks/88"]
    drift = [item for item in result["attention"] if "no generated ownership block" in item["reason"]]
    assert len(drift) == 1 and drift[0]["session"] == "drifted"


def test_authoritative_overlay_must_carry_the_repair(db, tmp_path):
    """R2-3: assemble_prompt reads a non-NULL overlay and ignores owned_dirs entirely."""
    from app.db import save_session, get_session_by_name
    from app.manager import ownership_block
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    owned = ["docs/tasks/88"]
    save_session({
        "id": "sid-split", "name": "split-owner", "scope": str(repo), "cwd": "/tmp",
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "ROLE BASE" + ownership_block(owned),
        # The authoritative owner has NO generated block: repairing system_prompt alone
        # would leave the worker with no ownership at all.
        "prompt_overlay": "\n\nTASK TEXT WITHOUT A BLOCK",
        "status": "idle", "session_id": "native", "cost_usd": 0.0, "worktree_path": None,
        "branch": "", "is_orchestrator": False, "color": "#fff",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "owned_dirs": json.dumps(owned), "role": "worker", "pipeline": "default",
    })

    result = layout.migrate_session_ownership(repo)

    assert result["changed"] == 0
    row = get_session_by_name("split-owner", str(repo))
    assert json.loads(row["owned_dirs"]) == ["docs/tasks/88"]
    assert row["prompt_overlay"] == "\n\nTASK TEXT WITHOUT A BLOCK"
    named = [i for i in result["attention"] if i["session"] == "split-owner"]
    assert len(named) == 1 and "no generated ownership block" in named[0]["reason"]


def test_worker_memory_quoting_a_block_does_not_absorb_the_rewrite(db):
    """R2-4: memory is appended after the suffix and can quote a whole old block."""
    from app.manager import ownership_block, replace_ownership_block

    before, after = ["docs/tasks/88"], [".orchestra/tasks/88"]
    real = ownership_block(before)
    prompt = ("ROLE BASE" + real
              + "\n\n<worker-memory>\nI once owned:" + real + "\n</worker-memory>")

    rewritten, found = replace_ownership_block(prompt, before, after)

    assert found is True
    # The real block moved...
    assert rewritten.startswith("ROLE BASE" + ownership_block(after))
    # ...and the memory copy is untouched, still quoting the old path.
    memory = rewritten.split("<worker-memory>", 1)[1]
    assert "- docs/tasks/88/" in memory
    assert ".orchestra/tasks/88" not in memory


def test_dry_run_alone_cannot_commit_a_layout_migration(db, tmp_path):
    """F6: the flag was consumed only on the ownership path, so it silently migrated."""
    repo = _old_layout_repo(tmp_path, "comfy")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_orchestra_layout.py"),
         "--dry-run", str(repo)],
        cwd=str(ROOT), env={**os.environ, "ORCHESTRA_DB_PATH": str(db)},
        text=True, capture_output=True,
    )

    assert done.returncode == 2, done.stdout + done.stderr
    assert "--dry-run is only supported together with --repair-ownership" in done.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert (repo / "docs" / "tasks" / "88" / "plan.md").is_file()
    assert not (repo / ".orchestra" / "tasks").exists()


# ── #482: existence is asked of the tree where ownership actually acts ──

def _save_worker_with_worktree(*, name: str, scope: str, owned: list[str], worktree: str):
    from app.db import _conn

    _save_worker(name=name, scope=scope, owned=owned)
    with _conn() as connection:
        connection.execute(
            "UPDATE sessions SET worktree_path=? WHERE id=?", (worktree, f"sid-{name}")
        )


def _attention_for(result, session: str) -> list[dict]:
    return [item for item in result["attention"] if item["session"] == session]


def test_path_present_only_in_the_worker_worktree_is_not_flagged(db, tmp_path):
    """The reported bug: a worker writes into its OWN tree; main sees it only after merge."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    worktree = tmp_path / "wt-painter"
    # Task 999 is the worker's own, still unmerged, work: present in ITS tree only.
    (worktree / ".orchestra" / "tasks" / "999").mkdir(parents=True)
    (worktree / "oil-paint").mkdir()
    assert not (repo / ".orchestra" / "tasks" / "999").exists(), "precondition: absent from checkout"

    _save_worker_with_worktree(
        name="painter-canvas", scope=str(repo),
        owned=["docs/tasks/999", "oil-paint"], worktree=str(worktree),
    )
    result = layout.migrate_session_ownership(repo)

    assert result["changed"] == 1
    assert _attention_for(result, "painter-canvas") == []


def test_path_present_only_in_the_checkout_is_not_flagged_either(db, tmp_path):
    """The mirrored false alarm: a worker branched before the directory existed."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "sensar")
    layout.migrate_project_layout(repo, repair=False)
    worktree = tmp_path / "wt-strategy"
    worktree.mkdir()
    assert (repo / ".orchestra" / "tasks" / "88").exists(), "precondition: present in checkout"

    _save_worker_with_worktree(
        name="mobile-os-strategy", scope=str(repo),
        owned=["docs/tasks/88"], worktree=str(worktree),
    )
    result = layout.migrate_session_ownership(repo)

    assert result["changed"] == 1
    assert _attention_for(result, "mobile-os-strategy") == []


def test_path_absent_from_both_trees_is_still_flagged(db, tmp_path):
    """The true signal must survive the fix, or it degenerates into always staying quiet."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    worktree = tmp_path / "wt-ghost"
    worktree.mkdir()

    _save_worker_with_worktree(
        name="ghost", scope=str(repo), owned=["docs/tasks/404"], worktree=str(worktree),
    )
    result = layout.migrate_session_ownership(repo)

    flagged = _attention_for(result, "ghost")
    assert len(flagged) == 1
    assert flagged[0]["path"] == ".orchestra/tasks/404"
    assert flagged[0]["exists"] is False
    assert flagged[0]["reason"] == (
        "path was rewritten but exists in neither the worker's worktree nor the checkout"
    )


@pytest.mark.parametrize(
    "worktree_value, expected_note",
    [("", "worker has no worktree"), ("__missing__", "worker worktree is missing")],
)
def test_unsearchable_worktree_is_named_not_reported_as_absent(
    db, tmp_path, worktree_value, expected_note,
):
    """'I could not look' and 'it is not there' are different claims."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    worktree = worktree_value
    if worktree_value == "__missing__":
        worktree = str(tmp_path / "wt-deleted")
        assert not Path(worktree).exists()

    _save_worker_with_worktree(
        name="stranded", scope=str(repo), owned=["docs/tasks/404"], worktree=worktree,
    )
    result = layout.migrate_session_ownership(repo)

    flagged = _attention_for(result, "stranded")
    assert len(flagged) == 1
    assert flagged[0]["exists"] is None, "unchecked must not be reported as False"
    assert expected_note in flagged[0]["reason"]
    assert "worktree unchecked" in flagged[0]["reason"]


def test_legacy_path_with_unchecked_worktree_states_both_facts(db, tmp_path):
    """Neither fact may swallow the other: legacy leftover AND worktree never searched."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "orchestra")
    layout.migrate_project_layout(repo, repair=False)
    _save_worker_with_worktree(
        name="portfolio-orchestra", scope=str(repo), owned=["docs/portfolio"], worktree="",
    )

    result = layout.migrate_session_ownership(repo)

    flagged = _attention_for(result, "portfolio-orchestra")
    assert len(flagged) == 1
    assert flagged[0]["exists"] is None
    assert "left verbatim" in flagged[0]["reason"]
    assert "worktree unchecked" in flagged[0]["reason"]


def test_relative_worktree_path_is_unchecked_not_searched_from_cwd(db, tmp_path):
    """A relative value would resolve against the service CWD and suppress a real alarm."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    _save_worker_with_worktree(
        name="relative", scope=str(repo), owned=["docs/tasks/404"], worktree="some/relative/dir",
    )

    result = layout.migrate_session_ownership(repo)

    flagged = _attention_for(result, "relative")
    assert len(flagged) == 1
    assert flagged[0]["exists"] is None
    assert "not absolute" in flagged[0]["reason"]


def test_unsearchable_worktree_still_trusts_the_checkout(db, tmp_path):
    """A path the checkout does have is not an alarm just because the worktree is gone."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)

    _save_worker_with_worktree(
        name="stranded-but-real", scope=str(repo), owned=["docs/tasks/88"], worktree="",
    )
    result = layout.migrate_session_ownership(repo)

    assert result["changed"] == 1
    assert _attention_for(result, "stranded-but-real") == []


# ── #482: a repair a live session will revert is not a repair ──

def test_live_session_is_not_reported_as_changed(db, tmp_path):
    """The report must not claim work that the worker's next save undoes."""
    from app.db import get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    _save_worker(name="painter-canvas", scope=str(repo), owned=["docs/tasks/88"])

    result = layout.migrate_session_ownership(
        repo, live_session_ids=frozenset({"sid-painter-canvas"}),
    )

    assert result["changed"] == 0, "a reverted write must never be counted as changed"
    assert result["plan"] == []
    assert result["deferred_count"] == 1
    deferred = result["deferred"][0]
    assert deferred["session"] == "painter-canvas"
    assert deferred["after"] == [".orchestra/tasks/88"]
    assert "reverted by its next save" in deferred["reason"]
    assert "next restart" in deferred["reason"]
    # And nothing was written, so the report and the database agree.
    assert json.loads(
        get_session_by_name("painter-canvas", str(repo))["owned_dirs"]
    ) == ["docs/tasks/88"]


def test_dormant_session_is_still_repaired(db, tmp_path):
    """Deferral must not degenerate into repairing nothing."""
    from app.db import get_session_by_name
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    _save_worker(name="dormant", scope=str(repo), owned=["docs/tasks/88"])

    result = layout.migrate_session_ownership(repo, live_session_ids=frozenset())

    assert result["changed"] == 1
    assert result["deferred_count"] == 0
    assert json.loads(
        get_session_by_name("dormant", str(repo))["owned_dirs"]
    ) == [".orchestra/tasks/88"]


@pytest.mark.parametrize("status, expected_changed", [("waiting", 0), ("running", 0), ("idle", 1)])
def test_unknown_residency_defers_the_statuses_that_are_certainly_live(
    db, tmp_path, status, expected_changed,
):
    """The CLI is a separate process and cannot see memory → infer from status."""
    from app import orchestra_layout as layout

    repo = _old_layout_repo(tmp_path, "comfy")
    layout.migrate_project_layout(repo, repair=False)
    _save_worker(name="worker", scope=str(repo), owned=["docs/tasks/88"], status=status)

    result = layout.migrate_session_ownership(repo)  # live_session_ids omitted = unknown

    assert result["changed"] == expected_changed
    assert result["deferred_count"] == 1 - expected_changed


def test_startup_migration_declares_that_nothing_is_loaded_yet(db, tmp_path, monkeypatch):
    """The layout hook runs before auto_resume_all, so its repairs are durable."""
    from app import orchestra_layout as layout

    seen = {}

    def capture(project_roots, *, preserve_dirty=False, live_session_ids=None):
        seen["live_session_ids"] = live_session_ids
        return {}

    monkeypatch.setattr(layout, "migrate_registered_projects", capture)
    monkeypatch.setattr(layout, "_registered_project_roots", lambda: {})

    layout.migrate_registered_project_layouts()

    assert seen["live_session_ids"] == frozenset(), (
        "startup must state that no session is resident, otherwise the one reliable "
        "repair path defers every row"
    )


# ── Ч3: ownership changes without a branch switch ──

@pytest.fixture
def worker(mgr):
    from tests.conftest import make_backend_mock

    async def _make(name: str, owned: list[str], scope: str = "/s"):
        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
            with patch(
                "app.session.AgentSession._make_backend", return_value=make_backend_mock()
            ):
                return await mgr.create_session(
                    name=name, scope=scope, cwd="/tmp", model="claude-sonnet-5[1m]",
                    role="worker", owned_dirs=owned,
                )
    return _make


@pytest.mark.asyncio
async def test_apply_owned_dirs_moves_column_and_prompt_together(mgr, worker):
    from app.db import get_session_by_name

    session = await worker("painter-canvas", ["docs/tasks/88"])

    applied = await mgr.apply_owned_dirs(session, ["app/api", "tests"])

    assert applied == ["app/api", "tests"]
    assert session.owned_dirs == ["app/api", "tests"]
    for live in (session.system_prompt, session.prompt_overlay):
        assert "- app/api/" in live and "- tests/" in live
        assert "docs/tasks/88" not in live
    row = get_session_by_name("painter-canvas", "/s")
    assert json.loads(row["owned_dirs"]) == ["app/api", "tests"]
    assert "- app/api/" in row["system_prompt"]
    assert "docs/tasks/88" not in row["system_prompt"]
    assert "- app/api/" in row["prompt_overlay"]
    assert "docs/tasks/88" not in row["prompt_overlay"]
    # The new block has to reach the agent, so the next turn must re-inject the prompt.
    assert session._prompt_injected is False


@pytest.mark.asyncio
async def test_empty_owned_dirs_clears_ownership(mgr, worker):
    from app.db import get_session_by_name
    from app.manager import OWNERSHIP_MARKER

    session = await worker("painter-canvas", ["docs/tasks/88"])

    assert await mgr.apply_owned_dirs(session, []) == []

    assert session.owned_dirs == []
    assert OWNERSHIP_MARKER not in session.system_prompt
    row = get_session_by_name("painter-canvas", "/s")
    assert row["owned_dirs"] == ""
    assert OWNERSHIP_MARKER not in row["system_prompt"]


@pytest.mark.asyncio
async def test_overlap_with_a_live_worker_blocks_the_change(mgr, worker):
    from app.db import get_session_by_name

    session = await worker("painter-canvas", ["oil-paint"])
    await worker("sculptor", ["app/api"])

    with pytest.raises(ValueError, match="overlap with 'sculptor'"):
        await mgr.apply_owned_dirs(session, ["app/api/v1"])

    assert session.owned_dirs == ["oil-paint"]
    row = get_session_by_name("painter-canvas", "/s")
    assert json.loads(row["owned_dirs"]) == ["oil-paint"]
    assert "- oil-paint/" in row["system_prompt"]

    # A worker keeping or extending its OWN directories must not collide with its own row.
    assert await mgr.apply_owned_dirs(session, ["oil-paint", "oil-paint/brushes"]) == [
        "oil-paint", "oil-paint/brushes",
    ]


@pytest.mark.asyncio
async def test_detached_update_touches_only_ownership_columns(mgr, db):
    """F3: `_hydrate_row` never fills color/template_hash, so a full snapshot blanks them."""
    from app.db import get_session_by_name

    _save_worker(name="detached", scope="/s", owned=["oil-paint"])
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "UPDATE sessions SET color='#818cf8', template_hash='02715933' WHERE id=?",
            ("sid-detached",),
        )
    before = get_session_by_name("detached", "/s")
    assert (before["color"], before["template_hash"]) == ("#818cf8", "02715933")

    session = mgr.get_by_name("detached", "/s")
    assert session.loaded is False
    await mgr.apply_owned_dirs(session, ["app/api"])

    after = get_session_by_name("detached", "/s")
    assert json.loads(after["owned_dirs"]) == ["app/api"]
    assert "- app/api/" in after["system_prompt"]
    # Fields nobody asked to change must survive untouched.
    assert (after["color"], after["template_hash"]) == ("#818cf8", "02715933")


@pytest.mark.asyncio
async def test_concurrent_changes_cannot_hand_one_dir_to_two_workers(mgr, worker):
    """F2: per-session locks let two different workers both validate against old state."""
    from app.db import get_session_by_name

    first = await worker("alpha", ["alpha-only"])
    second = await worker("beta", ["beta-only"])

    results = await asyncio.gather(
        mgr.apply_owned_dirs(first, ["shared"]),
        mgr.apply_owned_dirs(second, ["shared"]),
        return_exceptions=True,
    )

    ok = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, ValueError)]
    assert len(ok) == 1 and len(refused) == 1, results
    assert "overlap" in str(refused[0])
    owners = [
        name for name in ("alpha", "beta")
        if "shared" in json.loads(get_session_by_name(name, "/s")["owned_dirs"] or "[]")
    ]
    assert len(owners) == 1, f"both workers own it: {owners}"


@pytest.mark.asyncio
async def test_loader_rereads_the_row_under_the_lock(mgr, db):
    """R2-2: `ensure_loaded` captures the row BEFORE the lock; hydrating it publishes stale."""
    from app.db import get_session_by_name
    from unittest.mock import AsyncMock

    _save_worker(name="racer", scope="/s", owned=["old-dir"])
    stale_row = get_session_by_name("racer", "/s")

    detached = mgr.get_by_name("racer", "/s")
    await mgr.apply_owned_dirs(detached, ["new-dir"])
    assert json.loads(get_session_by_name("racer", "/s")["owned_dirs"]) == ["new-dir"]

    # The loader now proceeds with the row it captured before the write.
    with patch("app.session.AgentSession.start", AsyncMock()):
        loaded = await mgr._ensure_loaded_row(stale_row)

    assert loaded.owned_dirs == ["new-dir"], (
        "loader published the pre-write row: the live worker would run under a boundary "
        "the database says it no longer has"
    )


@pytest.mark.asyncio
async def test_cancelling_the_request_cannot_split_write_from_publication(mgr, worker):
    """R2-5: a disconnect between the DB write and in-memory publish diverges the two."""
    from app.db import get_session_by_name

    session = await worker("painter-canvas", ["oil-paint"])
    task = asyncio.create_task(mgr.apply_owned_dirs(session, ["app/api"]))
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Whatever the cancellation did, SQLite and the live session must agree.
    stored = json.loads(get_session_by_name("painter-canvas", "/s")["owned_dirs"] or "[]")
    assert stored == session.owned_dirs, f"DB {stored} vs live {session.owned_dirs}"
    if stored == ["app/api"]:
        assert "- app/api/" in session.system_prompt


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_split_write_from_publication(
    mgr, worker, monkeypatch,
):
    """R3-2: a second cancel penetrates an unshielded `await commit` mid-write."""
    import threading
    from app import manager as manager_module
    from app.db import get_session_by_name, save_session as real_save

    inside_write = threading.Event()
    may_finish = threading.Event()

    def blocking_save(snapshot):
        # Deterministic window: the SQLite thread is provably in flight while the test
        # cancels, instead of hoping a sleep lands in the right place.
        inside_write.set()
        may_finish.wait(5)
        return real_save(snapshot)

    session = await worker("painter-canvas", ["oil-paint"])
    monkeypatch.setattr(manager_module, "save_session", blocking_save)

    task = asyncio.create_task(mgr.apply_owned_dirs(session, ["app/api"]))
    while not inside_write.is_set():
        await asyncio.sleep(0.005)

    task.cancel()          # first: caught by the shield
    await asyncio.sleep(0.01)
    task.cancel()          # second: lands while `to_thread` is still running
    await asyncio.sleep(0.01)
    may_finish.set()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # The worker thread keeps running after its future is cancelled — give it the
    # chance to commit behind our back, which is exactly the failure being tested.
    await asyncio.sleep(0.2)

    stored = json.loads(get_session_by_name("painter-canvas", "/s")["owned_dirs"] or "[]")
    assert stored == session.owned_dirs, (
        f"repeated cancellation split the write from the publication: "
        f"DB {stored} vs live {session.owned_dirs}"
    )
    if stored == ["app/api"]:
        assert "- app/api/" in session.system_prompt


def test_route_refuses_a_running_worker_and_changes_nothing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.conftest import make_backend_mock

    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.db import get_session_by_name, init_db
    init_db()

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import app, manager
        from app.session import AgentStatus
        manager.sessions.clear()
        with TestClient(app) as client:
            created = client.post("/api/sessions", json={
                "name": "painter-canvas", "scope": "/s", "cwd": "/tmp",
                "model": "claude-sonnet-5[1m]", "role": "worker",
                "owned_dirs": ["oil-paint"],
            })
            assert created.status_code == 201, created.text
            session = manager.get_by_name("painter-canvas", "/s")
            before_prompt = session.system_prompt

            session.status = AgentStatus.RUNNING
            busy = client.post("/api/sessions/painter-canvas/owned-dirs",
                               json={"scope": "/s", "owned_dirs": ["app/api"]})

            assert busy.status_code == 409
            assert "running" in busy.json()["error"]
            assert session.owned_dirs == ["oil-paint"]
            assert session.system_prompt == before_prompt
            assert json.loads(
                get_session_by_name("painter-canvas", "/s")["owned_dirs"]
            ) == ["oil-paint"]

            session.status = AgentStatus.IDLE
            ok = client.post("/api/sessions/painter-canvas/owned-dirs",
                             json={"scope": "/s", "owned_dirs": ["app/api"]})

            assert ok.status_code == 200
            assert ok.json()["owned_dirs"] == ["app/api"]
            assert "- app/api/" in manager.get_by_name(
                "painter-canvas", "/s"
            ).system_prompt
        manager.sessions.clear()
