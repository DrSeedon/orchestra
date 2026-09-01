"""Regression coverage for the canonical/legacy task write ordering (audit 01.09)."""

from contextlib import contextmanager

import pytest


def _init_project():
    from app.db import init_db

    init_db()
    from app import tm

    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")


def _init_task():
    from app import tm

    _init_project()
    with tm._conn() as connection:
        return tm.create_task(connection, "project", "Drifted task", par_number=42)


def _save_worker(name: str):
    from app.db import save_session

    save_session({
        "id": name,
        "name": name,
        "scope": "/scope",
        "cwd": "/worktree",
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": "main",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "",
        "is_orchestrator": False,
        "parent_name": "orchestrator",
        "color": "",
        "created_at": "2026-09-01T00:00:00+00:00",
        "finished_at": None,
    })


@contextmanager
def _canonical_store(tmp_path, *, mode: str = "canonical"):
    from app import tm

    with tm.ia_task_store_mode(
        mode=mode,
        canonical_root=tmp_path / "canonical",
        projection_path=tmp_path / "task.db",
        cutoff="2026-09-01T00:00:00+00:00",
        source_head="source-0901",
    ) as store:
        yield store


class _RejectingStore:
    """Canonical store that refuses the prevalidated update, as the real one does."""

    canonical_head = "store-head"
    projection_head = "store-head"

    def __init__(self):
        self.rejections = 0

    def task_get(self, ref, project=""):
        return {
            "project": "project",
            "par": "42",
            "stable_id": "canonical-42",
            "canonical_head": "store-head",
            "sync_revision": 7,
        }

    def task_update_if_current(self, identity, **_kwargs):
        self.rejections += 1
        return {"ok": False, "error": "prevalidated task stable identity changed"}


def test_assignment_survives_legacy_only_revision_drift(tmp_path):
    """Binding bumps only the legacy counter; the canonical CAS must still admit it."""
    from app import tm

    task = _init_task()
    _save_worker("worker-0901")
    with _canonical_store(tmp_path) as store:
        tm.bind_task_to_session("/scope", "worker-0901", "42")
        identity = tm.resolve_scoped_task_identity("/scope", "42")
        result = tm.api_update_task_if_current(
            identity, status="in_progress", worker_session_id="worker-0901",
        )
        canonical = store.task_get("42", project="project")

    assert identity["sync_revision"] == 1
    assert result["ok"] is True
    assert canonical["status"] == "in_progress"
    with tm._conn() as connection:
        assert tm.get_task_by_id(connection, task["id"])["status"] == "in_progress"


def test_canonical_rejection_is_returned_without_touching_legacy():
    from app import tm

    task = _init_task()
    identity = {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
    }
    store = _RejectingStore()
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        result = tm.api_update_task_if_current(identity, status="in_progress")

    assert store.rejections == 1
    assert result["ok"] is False
    assert "stable identity changed" in result["error"]
    with tm._conn() as connection:
        legacy = tm.get_task_by_id(connection, task["id"])
    assert legacy["status"] == "new"
    assert legacy["sync_revision"] == 0


def test_shadow_rejection_reports_debt_instead_of_crashing():
    from app import tm

    task = _init_task()
    identity = {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
    }
    store = _RejectingStore()
    with tm.ia_process_task_store_mode(store=store, mode="shadow"):
        result = tm.api_update_task_if_current(identity, status="in_progress")

    assert store.rejections == 1
    assert result["shadow_match"] is False
    assert result["projection_debt"]["reason"] == "candidate_update_rejected"
    assert "stable identity changed" in result["projection_debt"]["message"]
    with tm._conn() as connection:
        assert tm.get_task_by_id(connection, task["id"])["status"] == "in_progress"


def test_discarded_spawn_allocation_keeps_display_counters_aligned(tmp_path):
    from app import tm

    _init_project()
    with _canonical_store(tmp_path) as store:
        allocated = tm.create_task_for_scope("/scope", "spawn that never published")
        assert tm.discard_unbound_task(allocated["id"]) is True
        again = tm.create_task_for_scope("/scope", "next spawn")
        canonical_next = store.task_list(project="project")["next_display_number"]

    assert allocated["par_number"] == 1
    assert again["par_number"] == 2
    assert canonical_next == 3


def test_rejected_create_leaves_display_counters_aligned(tmp_path):
    from app import tm

    _init_project()
    with _canonical_store(tmp_path) as store:
        with pytest.raises(ValueError, match="required acceptance oracle has no command"):
            tm.api_create_task("project", "unacceptable task", acceptance_required=True)
        created = tm.api_create_task("project", "healthy task")
        canonical_next = store.task_list(project="project")["next_display_number"]

    assert created["par"] == "1"
    assert canonical_next == 2


class _AcceptingStore:
    """Canonical store that admits the update, as the real one does once its own CAS matches."""

    canonical_head = "store-head"
    projection_head = "store-head"

    def __init__(self):
        self.updates = 0

    def task_get(self, ref, project=""):
        return {
            "project": "project",
            "par": "42",
            "stable_id": "canonical-42",
            "canonical_head": "store-head",
            "sync_revision": 0,
        }

    def task_update_if_current(self, identity, **_kwargs):
        self.updates += 1
        return {
            "ok": True,
            "task_id": "canonical-42",
            "par": "42",
            "updated": ["status"],
            "new_status": "in_progress",
            "sync_revision": 1,
            "stable_id": "canonical-42",
            "display_ref": "#42",
            "canonical_head": "store-head",
            "projection_head": "store-head",
            "evidence_refs": [],
        }


class _LinkingStore:
    """Canonical store that links commits happily, whatever legacy thinks of the ref."""

    canonical_head = "store-head"
    projection_head = "store-head"

    def __init__(self):
        self.links = 0

    def link_commits_to_task(self, task_ref, commits, project_id, expected_head=None):
        self.links += 1
        return {
            "ok": True,
            "added": len(commits),
            "stable_id": "canonical-42",
            "display_ref": "#42",
            "canonical_head": "store-head",
            "projection_head": "store-head",
            "evidence_refs": [],
        }


class _StoreFailingAfterCanonicalWrite:
    """Real store whose create materialises the task and only then fails.

    Так падает перестройка проекции: событие и state.json уже записаны, исключение летит
    после них — и задача в canonical есть, хотя вызов «не удался».
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def task_create(self, **kwargs):
        self._inner.task_create(**kwargs)
        raise RuntimeError("projection rebuild failed after canonical state was written")


def _build_canonical_store(tmp_path):
    """Build the real store, then hand it back for a process-mode swap."""
    with _canonical_store(tmp_path) as store:
        return store


def test_legacy_rejection_after_canonical_write_is_reported_as_failure():
    """Устаревшая ревизия ловится ТОЛЬКО legacy-CAS, поэтому его отказ обязан быть отказом."""
    from app import tm

    task = _init_task()
    identity = {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
    }
    # Любой legacy-only писатель между резолвом личности и обновлением двигает ревизию.
    tm.link_commits_to_task("42", [{"hash": "c0ffee"}], "project")
    store = _AcceptingStore()
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        result = tm.api_update_task_if_current(
            identity, status="in_progress", worker_session_id="worker-0901",
        )

    assert store.updates == 1
    assert result["ok"] is False
    assert "revision changed" in result["error"]
    assert result["projection_debt"]["reason"] == "legacy_update_rejected"
    with tm._conn() as connection:
        legacy = tm.get_task_by_id(connection, task["id"])
    assert legacy["status"] == "new"
    assert legacy["worker_session_id"] is None


def test_rejected_update_leaves_canonical_untouched(tmp_path):
    """Приёмочный оракул проверяет только legacy — canonical нельзя писать до этой проверки."""
    from app import tm

    _init_project()
    with _canonical_store(tmp_path) as store:
        created = tm.api_create_task("project", "healthy task")
        head = store.canonical_head
        with pytest.raises(ValueError, match="required acceptance oracle has no command"):
            tm.api_update_task(created["par"], project="project", acceptance_required=True)
        detail = store.task_get(created["par"], project="project")

    assert store.canonical_head == head
    assert detail["acceptance"]["required"] is False


def test_link_commits_stops_when_legacy_has_no_such_task():
    """Canonical нашёл задачу, legacy — нет: успехом это объявлять нельзя."""
    from app import tm

    _init_project()
    store = _LinkingStore()
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        result = tm.link_commits_to_task("42", [{"hash": "c0ffee"}], "project")

    assert store.links == 0
    assert result["ok"] is False
    assert result["reason"] == "TASK_NOT_FOUND"


def test_create_failure_after_canonical_write_keeps_legacy_row(tmp_path):
    """Компенсация сносит legacy-строку, только доказав, что в canonical задачи нет."""
    from app import tm

    _init_project()
    store = _build_canonical_store(tmp_path)
    with tm.ia_process_task_store_mode(
        store=_StoreFailingAfterCanonicalWrite(store), mode="canonical",
    ):
        with pytest.raises(RuntimeError, match="projection rebuild failed"):
            tm.api_create_task("project", "half-written task")

    assert store.task_get("1", project="project")["title"] == "half-written task"
    with tm._conn() as connection:
        rows = connection.execute("SELECT par_number FROM tm_tasks").fetchall()
    assert [row["par_number"] for row in rows] == [1]
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        assert tm.api_create_task("project", "next task")["par"] == "2"


class _StoreBumpingLegacyRevisionMidWrite(_AcceptingStore):
    """Canonical store that accepts while a legacy-only writer moves the row underneath."""

    def task_update_if_current(self, identity, **kwargs):
        from app import tm

        with tm._conn() as connection:
            connection.execute(
                "UPDATE tm_tasks SET sync_revision=sync_revision+1 WHERE id=?",
                (identity["id"],),
            )
            connection.commit()
        return super().task_update_if_current(identity, **kwargs)


def test_finalization_fails_loudly_when_legacy_rejects():
    """Финализация мержа обязана падать, а не закрывать задачу только в canonical."""
    from app import tm

    task = _init_task()
    payload = {}
    store = _StoreBumpingLegacyRevisionMidWrite()
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        with pytest.raises(RuntimeError, match="canonical task finalization failed"):
            tm._apply_finalization_task_update(payload, task["id"], status="done")

    assert payload["task_status"]["ok"] is False
    with tm._conn() as connection:
        assert tm.get_task_by_id(connection, task["id"])["status"] == "new"
