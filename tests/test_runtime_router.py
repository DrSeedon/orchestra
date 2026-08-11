import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app import runtime_router
from app.quota_runway import RunwayVerdict
from app.runtime_router import (
    PolicyRevisionError,
    RoutingStateChangedError,
    RuntimeRouter,
    RoutingInput,
    RoutingPolicyV1,
    evaluate_routing,
)


NOW = datetime(2030, 1, 8, 12, tzinfo=timezone.utc)


def _policy(*, access="all", revision=1, codex_normal=90, codex_stop=95):
    payload = {
        "schema_version": 1,
        "revision": revision,
        "mode": "quota",
        "codex_access": access,
        "models": {
            "claude": "claude-opus-5[1m]",
            "codex": "gpt-5.6-sol",
        },
        "claude": {
            "alert_deficit_hours": 14,
            "weekly_unavailable_pct": 95,
            "weekly_min_remaining_pp": 0.3,
            "five_hour_unavailable_pct": 95,
        },
        "codex": {
            "normal_below_pct": codex_normal,
            "unavailable_at_pct": codex_stop,
        },
    }
    if access == "off":
        payload["models"].pop("codex")
        payload.pop("codex")
    return RoutingPolicyV1.model_validate(payload)


def _window(minutes, utilization, *, reset_hours=24):
    return {
        "window_minutes": minutes,
        "utilization": utilization,
        "resets_at": (NOW + timedelta(hours=reset_hours)).isoformat(),
    }


def _observation(*, claude_5h=10, claude_7d=10, codex=10, age=1):
    return {
        "providers": {
            "anthropic": {
                "label": "Claude",
                "windows": [
                    _window(300, claude_5h, reset_hours=2),
                    _window(10080, claude_7d, reset_hours=24 * 6),
                ],
            },
            "codex": {
                "label": "Codex",
                "windows": [_window(10080, codex, reset_hours=24 * 6)],
            },
        },
        "observed_at_by_provider": {
            "anthropic": NOW.timestamp() - age,
            "codex": NOW.timestamp() - age,
        },
    }


def _baseline():
    return 0.0, NOW - timedelta(hours=48)


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1, "revision": 1, "mode": "quota"},
        {
            "schema_version": 1,
            "revision": 1,
            "mode": "quota",
            "codex_access": "all",
            "models": {"claude": "claude-opus-5[1m]"},
            "claude": {
                "alert_deficit_hours": 14,
                "weekly_unavailable_pct": 95,
                "weekly_min_remaining_pp": 0.3,
                "five_hour_unavailable_pct": 95,
            },
        },
        {
            "schema_version": 1,
            "revision": 1,
            "mode": "quota",
            "codex_access": "all",
            "models": {
                "claude": "gpt-5.6-sol",
                "codex": "gpt-5.6-sol",
            },
            "claude": {
                "alert_deficit_hours": 14,
                "weekly_unavailable_pct": 95,
                "weekly_min_remaining_pp": 0.3,
                "five_hour_unavailable_pct": 95,
            },
            "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
        },
        {
            "schema_version": 1,
            "revision": 1,
            "mode": "quota",
            "codex_access": "all",
            "models": {
                "claude": "claude-opus-5[1m]",
                "codex": "gpt-5.3-codex-spark",
            },
            "claude": {
                "alert_deficit_hours": 14,
                "weekly_unavailable_pct": 95,
                "weekly_min_remaining_pp": 0.3,
                "five_hour_unavailable_pct": 95,
            },
            "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
        },
    ],
)
def test_quota_policy_rejects_incomplete_or_wrong_runtime_without_defaults(payload):
    with pytest.raises(ValidationError):
        RoutingPolicyV1.model_validate(payload)


@pytest.mark.parametrize("bad_value", [True, "14", float("nan"), float("inf")])
def test_quota_policy_rejects_coerced_or_nonfinite_thresholds(bad_value):
    payload = _policy().model_dump(mode="json")
    payload["claude"]["alert_deficit_hours"] = bad_value

    with pytest.raises(ValidationError):
        RoutingPolicyV1.model_validate(payload)


def test_manifest_default_keeps_server_supplied_model_sources():
    policy = RoutingPolicyV1.manifest_default(revision=7)

    spawn = evaluate_routing(
        policy,
        RoutingInput(task_class="worker_general", manifest_model="gpt-5.6-sol"),
    )
    continuation = evaluate_routing(
        policy,
        RoutingInput(task_class="continuation", current_model="claude-sonnet-4-6"),
    )
    review = evaluate_routing(
        policy,
        RoutingInput(task_class="review", review_default_model="gpt-5.6-sol"),
    )

    assert (spawn.selected_runtime, spawn.selected_model) == ("codex", "gpt-5.6-sol")
    assert continuation.selected_model == "claude-sonnet-4-6"
    assert review.selected_model == "gpt-5.6-sol"
    assert all(item.policy_revision == 7 for item in (spawn, continuation, review))


@pytest.mark.parametrize(
    ("access", "task_class", "expected"),
    [
        ("all", "worker_general", "codex"),
        ("all", "orchestrator_free_text", "codex"),
        ("review_only", "worker_general", "claude"),
        ("review_only", "review", "codex"),
        ("off", "worker_general", "claude"),
        ("off", "review", "claude"),
    ],
)
def test_codex_access_matrix(access, task_class, expected):
    decision = evaluate_routing(
        _policy(access=access),
        RoutingInput(task_class=task_class, implementation_runtimes=frozenset()),
        _observation(),
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert decision.state == "selected"
    assert decision.selected_runtime == expected
    if task_class == "review":
        assert decision.degraded_review_independence == "unknown"


def test_codex_thresholds_are_policy_values_not_evaluator_defaults():
    observation = _observation(codex=89)
    normal = evaluate_routing(
        _policy(codex_normal=90),
        RoutingInput(task_class="worker_general"),
        observation,
        claude_baseline=_baseline(),
        now=NOW,
    )
    reserved = evaluate_routing(
        _policy(codex_normal=80),
        RoutingInput(task_class="worker_general"),
        observation,
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert normal.selected_runtime == "codex"
    assert reserved.selected_runtime == "claude"
    assert next(c for c in reserved.candidates if c.runtime == "codex").state == "reserve_only"


def test_claude_runway_verdict_drives_and_latches_reserve(monkeypatch):
    calls = []

    def runway(**kwargs):
        calls.append(kwargs)
        return RunwayVerdict(
            state="data",
            deficit=15,
            pace=2,
            runway_hours=4,
            work_hours_left=19,
            window_id="2030-01-14T07:00:00+00:00",
            window_end="2030-01-14T07:00:00+00:00",
            reason="measured",
        )

    monkeypatch.setattr(runtime_router, "weekly_runway", runway)
    policy = _policy(access="off")
    first = evaluate_routing(
        policy,
        RoutingInput(task_class="worker_general"),
        _observation(),
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert first.state == "queued"
    assert first.latch_window_ids == ("2030-01-14T07:00:00+00:00",)
    assert calls[0]["window_start_pct"] == 0
    assert calls[0]["window_start_at"] == _baseline()[1]

    def recovered(**_kwargs):
        return RunwayVerdict(
            state="data",
            deficit=1,
            pace=1,
            runway_hours=20,
            work_hours_left=21,
            window_id="2030-01-14T07:00:00+00:00",
            window_end="2030-01-14T07:00:00+00:00",
            reason="recovered",
        )

    monkeypatch.setattr(runtime_router, "weekly_runway", recovered)
    latched = evaluate_routing(
        policy,
        RoutingInput(task_class="worker_general"),
        _observation(),
        claude_baseline=_baseline(),
        latched_window_ids=frozenset(first.latch_window_ids),
        now=NOW,
    )
    assert latched.state == "queued"
    assert next(c for c in latched.candidates if c.runtime == "claude").reason == "claude_weekly_latched"


@pytest.mark.parametrize(
    ("observation", "reason"),
    [
        (_observation(age=300), "quota_observation_stale"),
        (_observation(claude_5h=95), "claude_five_hour_hard_stop"),
        (_observation(claude_7d=95), "claude_weekly_hard_stop"),
    ],
)
def test_claude_unavailable_reasons_are_fail_closed(observation, reason):
    decision = evaluate_routing(
        _policy(access="off"),
        RoutingInput(task_class="worker_general"),
        observation,
        claude_baseline=_baseline(),
        now=NOW,
    )
    candidate = next(c for c in decision.candidates if c.runtime == "claude")

    assert decision.state == "queued"
    assert candidate.reason == reason


def test_missing_five_hour_reset_is_unknown_not_calendar_guess():
    observation = _observation()
    observation["providers"]["anthropic"]["windows"][0]["resets_at"] = None

    decision = evaluate_routing(
        _policy(access="off"),
        RoutingInput(task_class="worker_general"),
        observation,
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert decision.state == "queued"
    assert decision.candidates[-1].reason == "claude_five_hour_reset_missing"


def test_missing_weekly_baseline_is_explicit_no_data():
    decision = evaluate_routing(
        _policy(access="off"),
        RoutingInput(task_class="worker_general"),
        _observation(),
        claude_baseline=None,
        now=NOW,
    )
    candidate = next(c for c in decision.candidates if c.runtime == "claude")

    assert decision.state == "queued"
    assert candidate.reason == "claude_weekly_runway_no_data"
    assert candidate.detail == "данных о квоте нет"


def test_review_prefers_independent_runtime_and_marks_unavoidable_degradation():
    policy = _policy(access="all")
    independent = evaluate_routing(
        policy,
        RoutingInput(task_class="review", implementation_runtimes=frozenset({"codex"})),
        _observation(),
        claude_baseline=_baseline(),
        now=NOW,
    )
    degraded = evaluate_routing(
        _policy(access="off"),
        RoutingInput(task_class="review", implementation_runtimes=frozenset({"claude"})),
        _observation(),
        claude_baseline=_baseline(),
        now=NOW,
    )
    mixed = evaluate_routing(
        policy,
        RoutingInput(
            task_class="review",
            implementation_runtimes=frozenset({"claude", "codex"}),
        ),
        _observation(),
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert independent.selected_runtime == "claude"
    assert independent.degraded_review_independence is None
    assert degraded.selected_runtime == "claude"
    assert degraded.degraded_review_independence == "same_runtime"
    assert mixed.selected_runtime == "codex"
    assert mixed.degraded_review_independence == "mixed"


def test_continuation_can_use_reserve_but_new_work_cannot():
    observation = _observation(codex=92, claude_7d=95)
    general = evaluate_routing(
        _policy(),
        RoutingInput(task_class="worker_general"),
        observation,
        claude_baseline=_baseline(),
        now=NOW,
    )
    continuation = evaluate_routing(
        _policy(),
        RoutingInput(task_class="continuation", current_model="gpt-5.6-sol"),
        observation,
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert general.state == "queued"
    assert continuation.selected_runtime == "codex"


def test_same_policy_and_observation_are_reproducible():
    args = (
        _policy(revision=9),
        RoutingInput(task_class="worker_general", logical_work_id="work-1"),
        _observation(),
    )
    first = evaluate_routing(*args, claude_baseline=_baseline(), now=NOW)
    second = evaluate_routing(*args, claude_baseline=_baseline(), now=NOW)

    assert first == second
    assert first.to_dict() == second.to_dict()


class _Store:
    def __init__(self, policy=None):
        self.raw = policy.model_dump_json() if policy else None
        self.commits = []
        self.replace_calls = []
        self._latches = frozenset()

    def policy_document(self):
        return self.raw

    def replace_policy_document(self, *, expected_revision, document):
        current = RoutingPolicyV1.model_validate_json(self.raw).revision if self.raw else 0
        assert current == expected_revision
        self.replace_calls.append((expected_revision, document))
        self.raw = document

    def latched_window_ids(self, provider):
        assert provider == "anthropic"
        return self._latches

    def commit_decision(self, **kwargs):
        current = RoutingPolicyV1.model_validate_json(self.raw).revision if self.raw else 0
        assert current == kwargs["expected_policy_revision"]
        if frozenset(kwargs["expected_latch_window_ids"]) != self._latches:
            raise RoutingStateChangedError("latch snapshot changed")
        self.commits.append(kwargs)
        self._latches |= frozenset(kwargs["latch_window_ids"])

    def last_decision(self):
        return self.commits[-1] if self.commits else None

    def latches(self):
        return [{"provider": "anthropic", "window_id": value} for value in self._latches]


def _live_observation():
    now = datetime.now(timezone.utc)
    result = _observation()
    result["observed_at_by_provider"] = {
        "anthropic": now.timestamp(),
        "codex": now.timestamp(),
    }
    for provider in result["providers"].values():
        for window in provider["windows"]:
            window["resets_at"] = (now + timedelta(days=6)).isoformat()
    result["providers"]["anthropic"]["windows"][0]["resets_at"] = (
        now + timedelta(hours=2)
    ).isoformat()
    return result


def _next_policy_payload(policy):
    payload = policy.model_dump(mode="json")
    payload["revision"] += 1
    return payload


@pytest.mark.asyncio
async def test_admission_reads_policy_each_time_and_commits_before_yield():
    store = _Store(_policy(access="off"))
    observation = _live_observation()
    calls = []

    async def load_observation(*, required_provider):
        calls.append(required_provider)
        return observation

    router = RuntimeRouter(
        store=store,
        observation_loader=load_observation,
        baseline_loader=lambda _reset: (
            0,
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        ),
        process_started_at="process-1",
    )

    async with router.admission(RoutingInput(task_class="worker_general")) as admission:
        assert len(store.commits) == 1
        assert store.commits[0]["decision_id"] == admission.decision_id
        assert store.commits[0]["process_started_at"] == "process-1"
        assert admission.decision.policy_revision == 1

    assert calls == ["anthropic"]

    updated = _next_policy_payload(_policy(access="off"))
    updated["claude"]["weekly_unavailable_pct"] = 9
    await router.replace_policy(updated)
    async with router.admission(RoutingInput(task_class="worker_general")) as admission:
        assert admission.decision.policy_revision == 2
        assert admission.decision.state == "queued"


@pytest.mark.asyncio
async def test_admission_recomputes_after_cross_process_policy_revision_change():
    initial = _policy(access="off")
    updated = RoutingPolicyV1.model_validate(_next_policy_payload(initial))
    store = _Store(initial)
    original_commit = store.commit_decision
    attempts = 0

    def commit_with_one_revision_race(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            store.raw = updated.model_dump_json()
            raise PolicyRevisionError("policy changed before decision commit")
        original_commit(**kwargs)

    store.commit_decision = commit_with_one_revision_race
    observation_calls = []

    async def load_observation(*, required_provider):
        observation_calls.append(required_provider)
        return _live_observation()

    router = RuntimeRouter(
        store=store,
        observation_loader=load_observation,
        baseline_loader=lambda _reset: (
            0,
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        ),
    )

    async with router.admission(RoutingInput(task_class="worker_general")) as admission:
        assert admission.decision.policy_revision == 2

    assert attempts == 2
    assert observation_calls == ["anthropic", "anthropic"]
    assert len(store.commits) == 1
    assert store.commits[0]["expected_policy_revision"] == 2


@pytest.mark.asyncio
async def test_admission_recomputes_when_latch_snapshot_changes_before_commit(
    monkeypatch,
):
    window_id = "2030-01-14T07:00:00+00:00"

    def runway(**_kwargs):
        return RunwayVerdict(
            state="data",
            deficit=1,
            pace=1,
            runway_hours=20,
            work_hours_left=21,
            window_id=window_id,
            window_end=window_id,
            reason="measured",
        )

    monkeypatch.setattr(runtime_router, "weekly_runway", runway)
    store = _Store(_policy(access="off"))
    original_commit = store.commit_decision
    attempted_states = []

    def commit_with_one_latch_race(**kwargs):
        attempted_states.append(json.loads(kwargs["decision_json"])["state"])
        if len(attempted_states) == 1:
            store._latches = frozenset({window_id})
            raise RoutingStateChangedError("latch snapshot changed")
        original_commit(**kwargs)

    store.commit_decision = commit_with_one_latch_race

    async def load_observation(*, required_provider):
        assert required_provider == "anthropic"
        observation = _live_observation()
        observed_at = datetime.now(timezone.utc).timestamp() - 1
        observation["observed_at_by_provider"] = {
            "anthropic": observed_at,
            "codex": observed_at,
        }
        return observation

    router = RuntimeRouter(
        store=store,
        observation_loader=load_observation,
        baseline_loader=lambda _reset: (
            0,
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        ),
    )

    async with router.admission(RoutingInput(task_class="worker_general")) as admission:
        assert admission.decision.state == "queued"
        assert admission.decision.reason == "no quota-eligible runtime"

    assert attempted_states == ["selected", "queued"]
    assert len(store.commits) == 1
    assert store.commits[0]["expected_latch_window_ids"] == (window_id,)


@pytest.mark.asyncio
async def test_policy_put_waits_until_admission_submit_or_queue_boundary():
    policy = _policy(access="off")
    store = _Store(policy)

    async def load_observation(*, required_provider):
        assert required_provider == "anthropic"
        return _live_observation()

    router = RuntimeRouter(
        store=store,
        observation_loader=load_observation,
        baseline_loader=lambda _reset: (
            0,
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        ),
    )
    put_started = asyncio.Event()

    async def replace():
        put_started.set()
        return await router.replace_policy(_next_policy_payload(policy))

    async with router.admission(RoutingInput(task_class="worker_general")):
        task = asyncio.create_task(replace())
        await put_started.wait()
        await asyncio.sleep(0)
        assert task.done() is False
        assert store.replace_calls == []

    result = await task
    assert result.revision == 2
    assert len(store.replace_calls) == 1


@pytest.mark.asyncio
async def test_simultaneous_local_admissions_are_serialized_through_submit_boundary():
    store = _Store(_policy(access="off"))
    first_inside = asyncio.Event()
    release_first = asyncio.Event()
    entered = []

    async def load_observation(*, required_provider):
        assert required_provider == "anthropic"
        return _live_observation()

    router = RuntimeRouter(
        store=store,
        observation_loader=load_observation,
        baseline_loader=lambda _reset: (
            0,
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        ),
    )

    async def admit(name, *, hold=False):
        async with router.admission(
            RoutingInput(task_class="worker_general", logical_work_id=name)
        ):
            entered.append(name)
            if hold:
                first_inside.set()
                await release_first.wait()

    first = asyncio.create_task(admit("first", hold=True))
    await first_inside.wait()
    second = asyncio.create_task(admit("second"))
    await asyncio.sleep(0)
    assert entered == ["first"]

    release_first.set()
    await asyncio.gather(first, second)
    assert entered == ["first", "second"]
    assert len(store.commits) == 2


@pytest.mark.asyncio
async def test_invalid_put_and_explain_do_not_mutate_store():
    policy = _policy(access="off")
    store = _Store(policy)

    async def must_not_load(**_kwargs):
        raise AssertionError("synthetic explain must not load live telemetry")

    router = RuntimeRouter(
        store=store,
        observation_loader=must_not_load,
        baseline_loader=lambda _reset: None,
    )
    invalid = _next_policy_payload(policy)
    invalid["claude"].pop("alert_deficit_hours")

    with pytest.raises(ValidationError):
        await router.replace_policy(invalid)
    explained = await router.explain(
        RoutingInput(task_class="worker_general"),
        _observation(),
        claude_baseline=_baseline(),
        now=NOW,
    )

    assert explained.state == "selected"
    assert store.replace_calls == []
    assert store.commits == []


@pytest.mark.asyncio
async def test_admission_uses_db_owned_baseline_and_accepts_honest_zero(
    tmp_path, monkeypatch,
):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "router-baseline.db")
    db.init_db()
    observation = _live_observation()
    weekly = observation["providers"]["anthropic"]["windows"][1]
    reset_at = datetime.fromisoformat(weekly["resets_at"])
    baseline_at = datetime.now(timezone.utc) - timedelta(hours=20)
    with sqlite3.connect(str(db.DB_PATH)) as connection:
        connection.execute(
            "INSERT INTO usage_snapshots "
            "(ts, five_hour_pct, seven_day_pct, five_hour_resets_at, "
            "seven_day_resets_at, total_cost_usd, active_agents) "
            "VALUES (?, 0, 0, '', ?, 0, 0)",
            (baseline_at.isoformat(), reset_at.isoformat()),
        )

    store = _Store(_policy(access="off"))

    async def load_observation(*, required_provider):
        assert required_provider == "anthropic"
        return observation

    router = RuntimeRouter(
        store=store,
        observation_loader=load_observation,
        baseline_loader=db.runway_window_start_pct,
    )
    async with router.admission(RoutingInput(task_class="worker_general")) as admission:
        candidate = next(
            item for item in admission.decision.candidates if item.runtime == "claude"
        )

    assert candidate.state == "normal"
    assert candidate.detail
