import json
import sqlite3

import pytest

from app import db
from app.runtime_router import (
    DatabaseRoutingStore,
    PolicyRevisionError,
    RoutingInput,
    RoutingStateChangedError,
    RuntimeRouter,
)


@pytest.fixture
def routing_db(tmp_path, monkeypatch):
    path = tmp_path / "runtime-routing.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


def _document(revision: int) -> str:
    return json.dumps({"schema_version": 1, "revision": revision, "mode": "manifest_default"})


def _commit(
    decision_id: str,
    *,
    revision: int = 0,
    expected_windows: tuple[str, ...] = (),
    windows: tuple[str, ...] = (),
) -> None:
    db.commit_runtime_routing_decision(
        expected_policy_revision=revision,
        decision_id=decision_id,
        created_at=f"2030-01-01T00:00:0{decision_id[-1]}+00:00",
        process_started_at="2029-12-31T23:00:00+00:00",
        policy_mode="manifest_default" if revision == 0 else "quota",
        task_class="worker_general",
        logical_work_id="work-1",
        request_json='{"task_class":"worker_general"}',
        decision_json='{"state":"selected"}',
        expected_latch_window_ids=expected_windows,
        latch_window_ids=windows,
    )


def test_policy_document_is_narrow_atomic_compare_and_swap(routing_db):
    assert db.routing_policy_document() is None

    first = _document(1)
    db.replace_routing_policy_document(expected_revision=0, document=first)
    assert db.routing_policy_document() == first

    with pytest.raises(db.RoutingPolicyRevisionMismatch, match="expected 0, found 1"):
        db.replace_routing_policy_document(expected_revision=0, document=_document(1))
    assert db.routing_policy_document() == first


def test_database_store_translates_policy_revision_mismatch(routing_db):
    first = _document(1)
    db.replace_routing_policy_document(expected_revision=0, document=first)

    with pytest.raises(PolicyRevisionError, match="expected 0, found 1"):
        DatabaseRoutingStore().replace_policy_document(
            expected_revision=0,
            document=first,
        )

    with pytest.raises(PolicyRevisionError, match="expected 0, found 1"):
        DatabaseRoutingStore().commit_decision(
            expected_policy_revision=0,
            decision_id="decision-1",
            created_at="2030-01-01T00:00:01+00:00",
            process_started_at="2029-12-31T23:00:00+00:00",
            policy_mode="manifest_default",
            task_class="worker_general",
            logical_work_id="work-1",
            request_json="{}",
            decision_json="{}",
            expected_latch_window_ids=(),
            latch_window_ids=(),
        )


@pytest.mark.parametrize(
    "document",
    ["not-json", "[]", '{"revision":true}', '{"revision":-1}', _document(3)],
)
def test_policy_document_rejects_invalid_or_skipped_revision_without_mutation(
    routing_db, document,
):
    with pytest.raises(ValueError):
        db.replace_routing_policy_document(expected_revision=0, document=document)
    assert db.routing_policy_document() is None


def test_decision_and_new_latch_commit_atomically(routing_db):
    _commit("decision-1", windows=("window-1",))

    assert db.routing_latched_window_ids("anthropic") == frozenset({"window-1"})
    assert db.routing_latches() == [{
        "provider": "anthropic",
        "window_id": "window-1",
        "state": "reserve_only",
        "first_decision_id": "decision-1",
        "latched_at": "2030-01-01T00:00:01+00:00",
    }]
    assert db.routing_last_decision()["decision_id"] == "decision-1"


def test_revision_mismatch_persists_neither_decision_nor_latch(routing_db):
    db.replace_routing_policy_document(expected_revision=0, document=_document(1))

    with pytest.raises(db.RoutingPolicyRevisionMismatch, match="expected 0, found 1"):
        _commit("decision-1", windows=("window-1",))

    assert db.routing_last_decision() is None
    assert db.routing_latches() == []


def test_stale_latch_snapshot_cannot_commit_a_decision(routing_db):
    _commit("decision-1", windows=("window-1",))

    with pytest.raises(db.RoutingLatchSnapshotMismatch, match="snapshot changed"):
        _commit("decision-2", expected_windows=())

    assert db.routing_last_decision()["decision_id"] == "decision-1"
    assert db.routing_latched_window_ids("anthropic") == frozenset({"window-1"})


def test_database_store_translates_latch_snapshot_mismatch(routing_db):
    _commit("decision-1", windows=("window-1",))

    with pytest.raises(RoutingStateChangedError, match="snapshot changed"):
        DatabaseRoutingStore().commit_decision(
            expected_policy_revision=0,
            decision_id="decision-2",
            created_at="2030-01-01T00:00:02+00:00",
            process_started_at="2029-12-31T23:00:00+00:00",
            policy_mode="manifest_default",
            task_class="worker_general",
            logical_work_id="work-1",
            request_json="{}",
            decision_json="{}",
            expected_latch_window_ids=(),
            latch_window_ids=(),
        )

    assert db.routing_last_decision()["decision_id"] == "decision-1"


def test_latch_constraint_failure_rolls_back_the_decision(routing_db):
    with pytest.raises(sqlite3.IntegrityError):
        _commit("decision-1", windows=("",))

    assert db.routing_last_decision() is None
    assert db.routing_latches() == []


def test_duplicate_decision_fails_loud_without_adding_another_latch(routing_db):
    _commit("decision-1", windows=("window-1",))

    with pytest.raises(sqlite3.IntegrityError):
        _commit(
            "decision-1",
            expected_windows=("window-1",),
            windows=("window-2",),
        )

    assert db.routing_latched_window_ids("anthropic") == frozenset({"window-1"})


def test_second_decision_keeps_first_latching_decision(routing_db):
    _commit("decision-1", windows=("window-1",))
    _commit(
        "decision-2",
        expected_windows=("window-1",),
        windows=("window-1",),
    )

    latch = db.routing_latches()[0]
    assert latch["first_decision_id"] == "decision-1"
    assert latch["latched_at"] == "2030-01-01T00:00:01+00:00"
    assert db.routing_last_decision()["decision_id"] == "decision-2"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE runtime_routing_latches SET state = 'normal'",
        "UPDATE runtime_routing_latches SET window_id = 'window-moved'",
        "DELETE FROM runtime_routing_latches",
    ],
)
def test_direct_sql_cannot_roll_back_or_move_latch(routing_db, statement):
    _commit("decision-1", windows=("window-1",))

    connection = sqlite3.connect(str(routing_db))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(statement)
    connection.close()

    assert db.routing_latched_window_ids("anthropic") == frozenset({"window-1"})


def test_insert_or_replace_cannot_change_first_latching_decision(routing_db):
    _commit("decision-1", windows=("window-1",))
    _commit("decision-2", expected_windows=("window-1",))

    connection = sqlite3.connect(str(routing_db))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        connection.execute(
            "INSERT OR REPLACE INTO runtime_routing_latches "
            "(provider, window_id, state, first_decision_id, latched_at) "
            "VALUES ('anthropic', 'window-1', 'reserve_only', 'decision-2', "
            "'2030-01-01T00:00:02+00:00')"
        )
    connection.close()

    assert db.routing_latches()[0]["first_decision_id"] == "decision-1"


@pytest.mark.asyncio
async def test_runtime_router_uses_the_persisted_policy_and_audit_store(routing_db):
    async def must_not_load(**_kwargs):
        raise AssertionError("manifest mode must not load quota telemetry")

    router = RuntimeRouter(
        store=DatabaseRoutingStore(),
        observation_loader=must_not_load,
        baseline_loader=lambda _reset: None,
        process_started_at="process-1",
    )
    policy = await router.replace_policy({
        "schema_version": 1,
        "revision": 1,
        "mode": "manifest_default",
        "codex_access": "all",
    })

    async with router.admission(
        RoutingInput(task_class="worker_general", manifest_model="gpt-5.6-sol")
    ) as admission:
        assert admission.decision.selected_model == "gpt-5.6-sol"

    status = await router.status()
    assert policy.revision == 1
    assert status["policy"]["revision"] == 1
    assert status["last_decision"]["decision_id"] == admission.decision_id
    assert status["last_decision"]["process_started_at"] == "process-1"
