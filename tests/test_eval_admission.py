"""Offline positive and adversarial controls for single-use evaluation admission."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
import sqlite3
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import db, eval_admission as grant, models, quota_gate, temp_rules, tm
from app.events import AgentEvent
from app.usage_contract import AggregateUsage, TurnUsage, current_context
from scripts import wf_adapters, wf_run


@pytest.fixture(autouse=True)
def synthetic_workspaces_stay_in_test_tmp(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(grant, "tempfile", SimpleNamespace(
        gettempdir=lambda: str(tmp_path), mkdtemp=tempfile.mkdtemp))


@pytest.fixture
def manifest():
    return {"fixtures": [{"id": f"fixture-{n}", "prompt": f"Public synthetic arithmetic: {n}+1?"}
                          for n in range(4)],
            "conditions": [{"model": model, "effort": effort}
                           for model, effort in sorted(grant.CONDITIONS)], "repeats": 2}


@pytest.fixture
def actor(monkeypatch):
    db.init_db()
    actor = {"id": "root-eval-test", "name": temp_rules.ORCHESTRA_ORCHESTRATOR,
             "scope": temp_rules.ORCHESTRA_SCOPE, "role": "orchestrator", "is_orchestrator": True}
    monkeypatch.setattr(tm, "resolve_scoped_task_identity", lambda scope, ref: {"stable_id": "task-stable"})
    return actor


def issue(actor, manifest, **overrides):
    args = dict(task_id="V-999", manifest=manifest, expected_hash=grant.manifest_hash(manifest),
                approval_ref="owner synthetic permission receipt", expires_at=time.time() + 5000,
                token_policy=grant.TOKEN_POLICY)
    args.update(overrides)
    return grant.issue(actor, **args)


@pytest.fixture
def bound(actor, manifest):
    issued = issue(actor, manifest)
    return grant.bind(actor, grant_id=issued["grant_id"], task_id=issued["task_id"],
                      manifest_hash=issued["manifest_hash"], run_id="eval-test")


def identity(bound, index=0):
    return {"grant_id": bound["grant_id"], "run_id": "eval-test", "task_id": "V-999",
            "manifest_hash": bound["manifest_hash"], "invocation": index}


def result(model="gpt-6-luna", tokens=10, **changes):
    row = asdict(wf_adapters.AdapterResult("answer", "codex", model, True, "end_turn", 0.001,
        usage=wf_adapters.Usage(100, tokens, 80, 0), reasoning_tokens=min(7, tokens)))
    row.update(changes)
    return row


def test_manifest_exact_unit_and_immutable_digest(manifest):
    tasks = grant.validate_manifest(manifest)
    assert len(tasks) == grant.MAX_CALLS == 56
    assert len({row["task_id"] for row in tasks}) == 56
    assert all(row["billing"] == "subscription" for row in tasks)
    before = grant.manifest_hash(manifest)
    manifest["fixtures"][0]["prompt"] += " changed"
    assert grant.manifest_hash(manifest) != before


@pytest.mark.parametrize("mutation", ["repeat", "fixture_count", "duplicate", "unknown", "paid", "effort", "cohort"])
def test_manifest_rejects_expansion_and_unapproved_cohort(manifest, mutation):
    if mutation == "repeat":
        manifest["repeats"] = True
    elif mutation == "fixture_count":
        manifest["fixtures"].append({"id": "extra", "prompt": "extra"})
    elif mutation == "duplicate":
        manifest["fixtures"][1] = dict(manifest["fixtures"][0])
    elif mutation == "unknown":
        manifest["approved"] = True
    elif mutation == "paid":
        manifest["conditions"][0]["billing"] = "api_credit"
    elif mutation == "effort":
        manifest["conditions"][0]["effort"] = "ultra"
    else:
        manifest["conditions"][0]["model"] = "gpt-6-astra"
    with pytest.raises(ValueError):
        grant.validate_manifest(manifest)


@pytest.mark.parametrize("change", [None, {"role": "worker", "is_orchestrator": False},
    {"name": "other-root"}, {"scope": "/some-other-project"}])
def test_issuance_needs_authenticated_canonical_root(actor, manifest, change):
    candidate = {**actor, **change} if change is not None else None
    with pytest.raises((PermissionError, temp_rules.RuleError)):
        issue(candidate, manifest)


@pytest.mark.parametrize("override", [
    {"task_id": "V-999'; DROP TABLE sessions;--"}, {"expected_hash": "wrong"},
    {"token_policy": "hard_cap"}, {"approval_ref": ""},
    {"expires_at": 0}, {"expires_at": float("inf")}, {"expires_at": time.time() + 10000}])
def test_issuance_refuses_mutable_approval_and_invalid_bounds(actor, manifest, override):
    with pytest.raises(ValueError):
        issue(actor, manifest, **override)


def test_grant_single_use_and_task_hash_scope_pinning(actor, manifest, bound):
    for patch in ({"task_id": "V-998"}, {"manifest_hash": "other"}, {"run_id": "eval-2"}):
        args = {key: value for key, value in identity(bound).items() if key != "invocation"}
        args.update(patch)
        with pytest.raises(ValueError):
            grant.bind(actor, **args)
    with pytest.raises(sqlite3.IntegrityError):
        issue(actor, manifest)
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_grants").fetchone())
    assert row["task_id"] == "V-999" and row["run_id"] == "eval-test"
    assert row["token_policy"] == grant.TOKEN_POLICY


@pytest.mark.parametrize("patch", [{"task_id": "V-1"}, {"run_id": "wrong"},
    {"manifest_hash": "bad"}, {"grant_id": "x' OR 1=1 --"}, {"invocation": -1},
    {"invocation": 56}, {"invocation": True}, {"invocation": 1}])
def test_reserve_rejects_mismatch_or_injection_before_consumption(bound, patch):
    with pytest.raises(ValueError):
        grant.reserve(**{**identity(bound), **patch})
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM eval_invocations").fetchone()[0] == 0


def test_concurrent_consume_and_crash_replay_are_at_most_once(bound):
    def attempt():
        try:
            grant.reserve(**identity(bound))
            return "reserved"
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert outcomes.count("reserved") == 1
    assert any("outcome_unknown" in outcome for outcome in outcomes)
    with pytest.raises(ValueError, match="unknown usage or unresolved"):
        grant.reserve(**identity(bound, 1))
    with pytest.raises(ValueError, match="outcome_unknown"):
        grant.reserve(**identity(bound))


def test_56_slots_not_internal_requests_and_terminal_replay(bound):
    for invocation in range(56):
        args = identity(bound, invocation)
        grant.reserve(**args)
        row = result(tokens=1)
        grant.finish(bound["grant_id"], invocation, row)
        _, replay = grant.reserve(**args)
        assert replay == row
    with pytest.raises(ValueError):
        grant.reserve(**identity(bound, 56))
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM eval_invocations").fetchone()[0] == 56
        assert connection.execute("SELECT count(*) FROM turn_usage").fetchone()[0] == 56


@pytest.mark.parametrize("first,second_allowed", [(499999, True), (500000, False), (900000, False)])
def test_generated_soft_stop_counts_output_once_excludes_input_cache(bound, first, second_allowed):
    grant.reserve(**identity(bound))
    grant.finish(bound["grant_id"], 0, result(tokens=first, reasoning_tokens=first // 2))
    if second_allowed:
        grant.reserve(**identity(bound, 1))
    else:
        with pytest.raises(ValueError, match="planned budget exhausted"):
            grant.reserve(**identity(bound, 1))
    with db._conn() as connection:
        assert connection.execute("SELECT generated_tokens FROM eval_invocations WHERE invocation=0").fetchone()[0] == first


def test_unknown_usage_stops_remaining_and_preserves_original_failure(bound):
    grant.reserve(**identity(bound))
    original = result(ok=False, error="native refused original detail", usage_known=False,
                      cost_usd=None, cost_unaccounted=True)
    grant.finish(bound["grant_id"], 0, original)
    with pytest.raises(ValueError, match="unknown usage"):
        grant.reserve(**identity(bound, 1))
    _, replay = grant.reserve(**identity(bound))
    assert replay == original
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_invocations").fetchone())
        assert row["generated_tokens"] is None
        assert row["origin"] == "workflow_eval_worker"
        usage = dict(connection.execute("SELECT * FROM turn_usage").fetchone())
        assert usage["session_id"] == row["actor_id"] != "root-eval-test"
        assert usage["task_id"] == "V-999" and usage["billing_mode"] == "subscription"
        assert usage["cost_unaccounted"] == 1 and usage["cost_usd"] is None


def test_accounting_failure_never_reopens_reservation(bound, monkeypatch):
    grant.reserve(**identity(bound))
    def fail(**kwargs):
        raise RuntimeError("accounting unavailable")
    monkeypatch.setattr(db, "turn_usage_add", fail)
    with pytest.raises(RuntimeError, match="accounting unavailable"):
        grant.finish(bound["grant_id"], 0, result())
    with pytest.raises(ValueError, match="outcome_unknown"):
        grant.reserve(**identity(bound))


def test_expiry_and_deadline_before_dispatch(bound, monkeypatch):
    monkeypatch.setattr(grant.time, "time", lambda: bound["deadline"])
    with pytest.raises(ValueError, match="deadline"):
        grant.reserve(**identity(bound))


@pytest.fixture
def fake_provider(monkeypatch):
    calls = []
    async def fake(row, invocation, task):
        with db._conn() as connection:
            reservation = connection.execute("SELECT result FROM eval_invocations WHERE grant_id=? AND invocation=?",
                                             (row["id"], invocation)).fetchone()
        assert reservation is not None and reservation["result"] is None
        calls.append((row, invocation, task))
        return result(task["model"])
    monkeypatch.setattr(grant, "managed_call", fake)
    monkeypatch.setattr(grant, "check_slot", lambda slot_id, run_id: None)
    async def admission(model):
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", admission)
    return calls


def dispatch_args(bound, index=0):
    task = bound["tasks"][index]
    return {**identity(bound, index), "slot_id": "test-slot", "prompt": task["prompt"],
            "model": task["model"], "effort": task["effort"]}


@pytest.mark.asyncio
async def test_valid_grant_unknown_quota_preserves_existing_semantics_and_replay(bound, fake_provider):
    answer = await grant.dispatch(**dispatch_args(bound))
    assert answer["ok"]
    assert await grant.dispatch(**dispatch_args(bound)) == answer
    assert len(fake_provider) == 1
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM turn_usage").fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["quota", "slot", "task", "hidden", "disabled", "runtime", "prompt", "effort", "provider"])
async def test_each_admission_guard_precedes_provider_and_keeps_failed_slot(bound, fake_provider, monkeypatch, failure):
    args = dispatch_args(bound)
    if failure == "quota":
        async def blocked(model):
            return replace(quota_gate.evaluate_worker_admission(model, {}, {}), state="blocked", utilization=100)
        monkeypatch.setattr(quota_gate, "get_worker_admission", blocked)
    elif failure == "slot":
        def no_slot(*args):
            raise ValueError("missing scheduler")
        monkeypatch.setattr(grant, "check_slot", no_slot)
    elif failure == "task":
        monkeypatch.setattr(tm, "resolve_scoped_task_identity", lambda *args: {"stable_id": "changed"})
    elif failure == "hidden":
        models.set_model_flags(args["model"], dashboard=False)
    elif failure == "disabled":
        models.set_model_flags(args["model"], agents=False)
    elif failure == "runtime":
        spec = models.get_model_spec(args["model"])
        monkeypatch.setattr(models, "get_model_spec", lambda model: replace(spec, runtime="claude"))
    elif failure in {"prompt", "effort"}:
        args[failure] = "caller modified"
    else:
        async def fail(*args):
            raise RuntimeError("original provider failure")
        monkeypatch.setattr(grant, "managed_call", fail)
    answer = await grant.dispatch(**args)
    assert not answer["ok"] and answer["error"]
    assert not answer["usage_known"] and answer["cost_usd"] is None
    assert len(fake_provider) == 0
    assert await grant.dispatch(**args) == answer
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM eval_invocations").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_deadline_rechecked_after_async_quota(bound, fake_provider, monkeypatch):
    async def expire(model):
        monkeypatch.setattr(grant.time, "time", lambda: bound["deadline"])
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", expire)
    row = await grant.dispatch(**dispatch_args(bound))
    assert not row["ok"] and "deadline" in row["error"]
    assert fake_provider == []


def test_scheduler_slot_is_live_and_bound_to_run(tmp_path, monkeypatch):
    from app import workflow_scheduler
    scheduler = workflow_scheduler.WorkflowScheduler(tmp_path / "scheduler.db")
    monkeypatch.setattr(workflow_scheduler, "get_scheduler", lambda: scheduler)
    with pytest.raises(ValueError):
        grant.check_slot("slot", "run")
    with scheduler._connect() as connection:
        connection.execute("INSERT INTO requests(request_id,run_id,queued_at,last_seen,lease_until) VALUES (?,?,?,?,?)",
                           ("slot", "run", time.time(), time.time(), time.time() + 50))
    grant.check_slot("slot", "run")
    with pytest.raises(ValueError):
        grant.check_slot("slot", "another-run")
    with scheduler._connect() as connection:
        connection.execute("UPDATE requests SET lease_until=0")
    with pytest.raises(ValueError):
        grant.check_slot("slot", "run")


def test_http_issue_and_bind_require_real_proof_not_mutable_flags(actor, manifest, monkeypatch):
    from app.routes import bg, temp_rules as rules_route
    from app.mcp_proof import issue_mcp_proof
    app = FastAPI()
    app.include_router(bg.router)
    monkeypatch.setattr(rules_route, "get_session", lambda sid: actor)
    body = dict(task_id="V-999", manifest=manifest, expected_hash=grant.manifest_hash(manifest),
        approval_ref="owner-http-record", expires_at=time.time() + 5000, token_policy=grant.TOKEN_POLICY)
    with TestClient(app) as client:
        headers = {"x-orchestra-session-id": actor["id"]}
        assert client.post("/api/bg/eval/grants", json=body, headers=headers).status_code == 403
        headers["x-orchestra-mcp-proof"] = issue_mcp_proof(actor["id"])
        response = client.post("/api/bg/eval/grants", json=body, headers=headers)
        assert response.status_code == 200, response.text
        args = {key: response.json()[key] for key in ("grant_id", "task_id", "manifest_hash")}
        args["run_id"] = "http-test"
        assert client.post("/api/bg/eval/bind", json=args).status_code == 403
        assert client.post("/api/bg/eval/bind", json=args, headers=headers).status_code == 200
        assert client.post("/api/bg/eval/bind", json=args, headers=headers).status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("late_guard", ["allowed", "slot_lost", "quota_blocked", "catalog_hidden"])
async def test_managed_backend_uses_worker_identity_and_exact_effort(bound, monkeypatch, tmp_path, late_guard):
    from app import backend_codex, manager
    seen = {}
    monkeypatch.setattr(db, "_REPO_ROOT", tmp_path)
    def slot(*args):
        if late_guard == "slot_lost":
            raise ValueError("lease lost during connect")
    monkeypatch.setattr(grant, "check_slot", slot)
    async def admission(model):
        decision = quota_gate.evaluate_worker_admission(model, {}, {})
        return replace(decision, state="blocked", utilization=100) if late_guard == "quota_blocked" else decision
    monkeypatch.setattr(quota_gate, "get_worker_admission", admission)
    class FakeBackend:
        session_id = "fake-thread"
        def __init__(self, **kwargs):
            seen.update(kwargs)
        async def connect(self):
            seen["connected"] = True
        async def send(self, prompt):
            seen["prompt"] = prompt
        async def _request(self, method, params):
            if method == "mcpServerStatus/list":
                return {"data": [], "nextCursor": None}
            if method == "account/read":
                assert params == {"refreshToken": False}
                return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
            assert method == "model/list"
            if late_guard == "catalog_hidden":
                models.set_model_flags(bound["tasks"][0]["model"], dashboard=False)
            return {"data": [{"model": bound["tasks"][0]["model"],
                "supportedReasoningEfforts": [{"reasoningEffort": bound["tasks"][0]["effort"]}]}]}
        async def events(self):
            yield AgentEvent("text", "synthetic result")
            yield AgentEvent("turn_end", metadata={"ok": True, "stop_reason": "end_turn", "reasoning_tokens": 7},
                usage=TurnUsage(AggregateUsage(100, 10, 80), current_context(100, 1000)))
        async def disconnect(self):
            seen["disconnected"] = True
        async def interrupt(self):
            seen["interrupted"] = True
    monkeypatch.setattr(backend_codex, "CodexBackend", FakeBackend)
    monkeypatch.setattr(manager, "_make_mcp_config", lambda *args, **kwargs: {"orchestra": {"env": kwargs}})
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_grants").fetchone())
    row["dispatch_slot_id"] = "test-slot"
    answer = await grant.managed_call(row, 0, bound["tasks"][0])
    if late_guard != "allowed":
        assert not answer["ok"] and answer["error"] and not answer["usage_known"]
        assert "prompt" not in seen and seen["disconnected"]
        return
    assert answer["ok"] and answer["usage"]["output_tokens"] == 10
    assert answer["reasoning_tokens"] == 7
    assert seen["is_orchestrator"] is False and seen["reasoning_effort"] == bound["tasks"][0]["effort"]
    assert "mcp_servers" not in seen and "mcp_env" not in seen
    assert seen["evaluation_actor_id"].startswith("eval-")
    assert seen["disconnected"]


@pytest.mark.asyncio
async def test_eval_runner_no_schema_retry_usd_gate_or_duplicate_accounting(bound, tmp_path, monkeypatch):
    async def slot(path, payload):
        return {"released": True} if path.endswith("release") else {"granted": True}
    monkeypatch.setattr(wf_run, "_workflow_slot_request", slot)
    calls = []
    async def adapter(prompt, **kwargs):
        calls.append(kwargs)
        return wf_adapters.AdapterResult(**{**result(kwargs["model"], ok=False, error="refused original"),
                                           "usage": wf_adapters.Usage(10, 10)})
    def forbidden(**kwargs):
        raise AssertionError("server owns eval accounting")
    engine = wf_run.WorkflowEngine("eval-test", tmp_path / "run", budget_usd=0, max_calls=56,
                                  adapter=adapter, usage_writer=forbidden, eval_grant=bound)
    values = await engine.execute_spec({"mode": "eval", "tasks": bound["tasks"]})
    assert len(calls) == 1 and len(values) == 1 and values[0]["result"] is None
    assert calls[0]["eval_context"]["invocation"] == 0
    assert json.loads((engine.steps_dir / "eval-0.json").read_text())["error"] == "refused original"


@pytest.mark.asyncio
async def test_eval_scheduler_missing_refuses_but_legacy_remains_compatible(bound, tmp_path, monkeypatch):
    async def missing(path, payload):
        return {"scheduler_missing": True}
    monkeypatch.setattr(wf_run, "_workflow_slot_request", missing)
    async def refused_admission(*args, **kwargs):
        assert kwargs["eval_context"]["slot_id"] == ""
        return wf_adapters._failed("codex", kwargs["model"], "scheduler missing", stop_reason="eval_refused")
    engine = wf_run.WorkflowEngine("eval-test", tmp_path / "eval", budget_usd=0,
                                  adapter=refused_admission, eval_grant=bound)
    await engine.execute_spec({"mode": "eval", "tasks": bound["tasks"]})
    assert engine.partial_reason == "eval_refused"
    assert "scheduler missing" in next(iter(engine._step_records.values()))["error"]
    legacy = wf_run.WorkflowEngine("legacy", tmp_path / "legacy", budget_usd=1,
                                   workspace_base_commit="a" * 40)
    assert await legacy._acquire_workflow_slot("key", 1, "label") == ""


@pytest.mark.asyncio
async def test_no_grant_keeps_generic_native_policy_denied(monkeypatch, tmp_path):
    async def never(*args, **kwargs):
        raise AssertionError("native runtime must not be entered")
    monkeypatch.setattr(wf_adapters, "run_codex", never)
    for model in ("gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-luna"):
        with pytest.raises(ValueError):
            models.ensure_spawn_allowed(model)
        answer = await wf_adapters.run_adapter("task", model=model, cwd=tmp_path, timeout=1)
        assert answer.stop_reason == "model_policy_refused"
    # The existing protected local Luna exception is retained.
    models.ensure_spawn_allowed("gpt-6-luna", model_reason="protected local fixture")


def test_recovery_snapshot_distinguishes_unknown_from_zero(bound):
    grant.reserve(**identity(bound))
    receipt = grant.snapshot(bound["grant_id"])
    assert receipt["consumed_task_invocations"] == 1
    assert receipt["unknown_usage_invocations"] == 1
    assert receipt["invocations"][0]["state"] == "outcome_unknown"
    assert receipt["invocations"][0]["generated_tokens"] is None
    assert receipt["invocations"][0]["result"] is None


@pytest.mark.asyncio
async def test_model_disable_between_calls_revalidated(bound, fake_provider):
    assert (await grant.dispatch(**dispatch_args(bound)))["ok"]
    second = dispatch_args(bound, 1)
    models.set_model_flags(second["model"], dashboard=False)
    refused = await grant.dispatch(**second)
    assert not refused["ok"] and "hidden" in refused["error"]
    assert len(fake_provider) == 1


@pytest.mark.asyncio
async def test_catalog_rechecked_after_quota_wait(bound, fake_provider, monkeypatch):
    async def changed(model):
        models.set_model_flags(model, dashboard=False)
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", changed)
    row = await grant.dispatch(**dispatch_args(bound))
    assert not row["ok"] and "hidden" in row["error"]
    assert fake_provider == []


@pytest.mark.asyncio
async def test_dynamic_workflow_binds_frozen_server_spec_and_zero_usd(actor, manifest, tmp_path, monkeypatch):
    from app import mcp_stdio, workspace
    issued = issue(actor, manifest)
    seen = {}
    async def api(method, path, **kwargs):
        if path == "/api/bg/eval/bind":
            return grant.bind(actor, **kwargs["json"])
        assert path == "/api/bg/jobs"
        seen.update(kwargs["json"])
        return {"id": "test-bg-job"}
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(mcp_stdio, "__file__", str(tmp_path / "app" / "mcp_stdio.py"))
    monkeypatch.setattr(mcp_stdio, "_api", api)
    monkeypatch.setattr(workspace, "resolve_worktree_context", lambda repo: (tmp_path, "a" * 40))
    response = await mcp_stdio.dynamic_workflow(budget_usd=0, max_calls=56, max_concurrency=1,
        task_id="V-999", repo=str(tmp_path), eval_grant_id=issued["grant_id"],
        eval_manifest_hash=issued["manifest_hash"])
    assert "queued" in response
    request_file = next(tmp_path.glob("data/workflow-runs/*/request.json"))
    spec = json.loads(request_file.read_text())
    assert spec["mode"] == "eval" and len(spec["tasks"]) == 56
    assert spec["tasks"] == grant.validate_manifest(manifest)
    assert spec["dashboard"]["budget_usd"] == 0
    assert spec["eval_grant"]["token_policy"] == grant.TOKEN_POLICY
    assert seen["timeout_seconds"] == 5400
    assert "--budget-usd 0" in seen["config"]["command"]
    for field, invalid in (("budget_usd", 1), ("max_calls", 57), ("max_concurrency", 2)):
        args = dict(budget_usd=0, max_calls=56, max_concurrency=1, task_id="V-999", repo=str(tmp_path),
                    eval_grant_id="unissued", eval_manifest_hash="bad")
        args[field] = invalid
        assert (await mcp_stdio.dynamic_workflow(**args)).startswith("Error:")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["legacy", "coding"])
async def test_offline_full_cohort_engine_adapter_http_ledger(actor, manifest, coding_pack, tmp_path, monkeypatch, stage):
    import httpx
    from app.routes.bg import router
    from app import workflow_scheduler
    app = FastAPI()
    app.state.agent_cgroup = "fake-test-cgroup"
    app.include_router(router)
    if stage == "coding":
        pack, inputs, csv_text = coding_pack
        issued = issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
        expected = 48
        expected_conditions = {(model, effort) for model, efforts in pack["runtime_supported_efforts"].items() for effort in efforts}
    else:
        issued = issue(actor, manifest)
        expected, expected_conditions = 56, grant.CONDITIONS
    bound = grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999", manifest_hash=issued["manifest_hash"], run_id="eval-test")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
                        real_client(transport=httpx.ASGITransport(app=app), **kwargs))
    scheduler = workflow_scheduler.WorkflowScheduler(tmp_path / "scheduler.db")
    monkeypatch.setattr(workflow_scheduler, "get_scheduler", lambda: scheduler)
    calls = []
    async def provider(row, invocation, task):
        calls.append((invocation, task["model"], task["effort"]))
        return result(task["model"], tokens=1)
    async def admission(model):
        return quota_gate.evaluate_worker_admission(model, {}, {})
    async def slots(path, payload):
        if path.endswith("release"):
            scheduler.release(payload["request_id"])
            return {"released": True}
        with scheduler._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO requests(request_id,run_id,queued_at,last_seen,lease_until) VALUES (?,?,?,?,?)",
                (payload["request_id"], payload["run_id"], time.time(), time.time(), time.time() + 80))
        return {"granted": True}
    monkeypatch.setattr(grant, "managed_call", provider)
    monkeypatch.setattr(quota_gate, "get_worker_admission", admission)
    monkeypatch.setattr(wf_run, "_workflow_slot_request", slots)
    engine = wf_run.WorkflowEngine("eval-test", tmp_path / "run", budget_usd=0, max_calls=56,
        adapter=wf_adapters.run_adapter, usage_writer=lambda **kwargs: pytest.fail("duplicate accounting"),
        eval_grant=bound)
    values = await engine.execute_spec({"mode": "eval", "tasks": bound["tasks"]})
    assert len(values) == len(calls) == expected
    assert {(model, effort) for _, model, effort in calls} == expected_conditions
    receipt = grant.snapshot(bound["grant_id"])
    assert receipt["consumed_task_invocations"] == expected and receipt["known_generated_tokens"] == expected
    assert receipt["planned_task_invocations"] == expected and receipt["max_task_invocations"] == 56
    assert receipt["unknown_usage_invocations"] == 0
    assert engine.write_manifest()["complete"]
    # Process/journal recovery sees completed results; it must not rerun the provider.
    resumed = wf_run.WorkflowEngine("eval-test", tmp_path / "run", budget_usd=0, max_calls=56,
        adapter=wf_adapters.run_adapter, eval_grant=bound)
    await resumed.execute_spec({"mode": "eval", "tasks": bound["tasks"]})
    assert len(calls) == expected
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM turn_usage").fetchone()[0] == expected
    with pytest.raises(ValueError, match="outside"):
        grant.reserve(**identity(bound, expected))
    assert grant.snapshot(bound["grant_id"])["consumed_task_invocations"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", ["api_key", "no_auth", "non_openai", "missing_model", "effort", "hidden", "rpc"])
async def test_runtime_auth_catalog_fail_closed_before_send(bound, tmp_path, monkeypatch, refusal):
    from app import backend_codex, manager
    monkeypatch.setattr(db, "_REPO_ROOT", tmp_path)
    sends = []
    class Backend:
        session_id = "fake-thread"
        def __init__(self, **kwargs):
            assert kwargs["is_orchestrator"] is False
        async def connect(self):
            pass
        async def disconnect(self):
            pass
        async def interrupt(self):
            pass
        async def send(self, prompt):
            sends.append(prompt)
        async def _request(self, method, params):
            if method == "mcpServerStatus/list":
                return {"data": []}
            if refusal == "rpc":
                raise RuntimeError("unsupported runtime method original error")
            if method == "account/read":
                return {"account": {"type": "apiKey" if refusal == "api_key" else "chatgpt"}
                        if refusal != "no_auth" else None,
                        "requiresOpenaiAuth": refusal != "non_openai"}
            return {"data": [] if refusal == "missing_model" else [{
                "model": bound["tasks"][0]["model"], "hidden": refusal == "hidden",
                "supportedReasoningEfforts": [] if refusal == "effort" else [
                    {"reasoningEffort": bound["tasks"][0]["effort"]}]}]}
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    monkeypatch.setattr(manager, "_make_mcp_config", lambda *args, **kwargs: {"orchestra": {"env": kwargs}})
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_grants").fetchone())
    answer = await grant.managed_call(row, 0, bound["tasks"][0])
    assert not answer["ok"] and answer["error"] and not answer["usage_known"]
    assert sends == []


@pytest.mark.asyncio
async def test_managed_partial_timeout_retains_partial_and_unknown_usage(bound, tmp_path, monkeypatch):
    from app import backend_codex, manager
    monkeypatch.setattr(db, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(grant, "check_slot", lambda *args: None)
    async def admission(model):
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", admission)
    class Backend:
        session_id = "fake-thread"
        def __init__(self, **kwargs):
            pass
        async def connect(self):
            pass
        async def disconnect(self):
            pass
        async def interrupt(self):
            pass
        async def send(self, prompt):
            pass
        async def _request(self, method, params):
            if method == "mcpServerStatus/list":
                return {"data": []}
            if method == "account/read":
                return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
            return {"data": [{"model": bound["tasks"][0]["model"], "supportedReasoningEfforts": [
                {"reasoningEffort": bound["tasks"][0]["effort"]}]}]}
        async def events(self):
            yield AgentEvent("text", "partial answer")
            raise RuntimeError("original disconnected provider")
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    monkeypatch.setattr(manager, "_make_mcp_config", lambda *args, **kwargs: {"orchestra": {"env": kwargs}})
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_grants").fetchone())
    row["dispatch_slot_id"] = "test-slot"
    answer = await grant.managed_call(row, 0, bound["tasks"][0])
    assert not answer["ok"] and answer["text"] == "partial answer"
    assert answer["error"] == "RuntimeError: original disconnected provider"
    assert not answer["usage_known"] and answer["cost_usd"] is None


@pytest.mark.asyncio
async def test_http_scheduler_absent_consumes_refused_slot(bound, fake_provider, monkeypatch):
    import httpx
    from app.routes.bg import router
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # No cgroup means no scheduler capability even if an old lease row survives.
        response = await client.post("/api/bg/eval/dispatch", json=dispatch_args(bound),
            headers={"Authorization": "Bearer orchestra-pytest-only-token"})
    assert response.status_code == 200
    assert response.json()["ok"] is False and "scheduler missing" in response.json()["error"]
    assert fake_provider == []
    receipt = grant.snapshot(bound["grant_id"])
    assert receipt["consumed_task_invocations"] == receipt["unknown_usage_invocations"] == 1


@pytest.mark.asyncio
async def test_http_mutable_grant_flag_or_bad_transport_cannot_dispatch(bound, fake_provider):
    import httpx
    from app.routes.bg import router
    app = FastAPI()
    app.state.agent_cgroup = "fake"
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/bg/eval/dispatch", json=dispatch_args(bound))
        assert response.status_code == 403
        headers = {"Authorization": "Bearer orchestra-pytest-only-token"}
        for patch in ({"approved": True}, {"billing": "api_credit"}, {"invocation": False}):
            response = await client.post("/api/bg/eval/dispatch", json={**dispatch_args(bound), **patch}, headers=headers)
            assert response.status_code == 422
        assert (await client.get(f"/api/bg/eval/grants/{bound['grant_id']}")).status_code == 403
    assert grant.snapshot(bound["grant_id"])["consumed_task_invocations"] == 0
    assert fake_provider == []


@pytest.fixture
def frozen_pack(manifest):
    import csv
    import io
    from app.eval_fixtures import digest
    configs = [{"id": f"c-{n}", **row} for n, row in enumerate(manifest["conditions"])]
    inputs, tasks, controls = {}, [], []
    for fixture in manifest["fixtures"]:
        name = fixture["id"]
        prompt = f"fixtures/{name}/prompt.md"
        seed = f"fixtures/{name}/seed/src/example.py"
        inputs[prompt] = fixture["prompt"]
        inputs[seed] = "value = 'synthetic seed'\n"
        tasks.append({"id": name, "model_input_files": {prompt: digest(inputs[prompt]), seed: digest(inputs[seed])},
                      "hidden_validator_reference_files": {f"fixtures/{name}/oracle/validate.py": "0" * 64}})
        for label, color, rc in (("base-red", "RED", 1), ("reference-green", "GREEN", 0)):
            controls.append({"fixture": name, "control": label, "actual": color,
                             "expected": color, "returncode": rc, "outcome": "PASS"})
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["sequence", "fixture_id", "repeat", "condition_id", "model", "effort", "billing", "attempt"])
    # Deliberately reverse the conditions and fixtures: the server must retain supplied
    # order, not silently replace the benchmark randomization with its own nested loop.
    number = 0
    for fixture in reversed(tasks):
        for repeat in (2, 1):
            for config in reversed(configs):
                number += 1
                writer.writerow([number, fixture["id"], repeat, config["id"], config["model"],
                                 config["effort"], "subscription", 1])
    csv_text = output.getvalue()
    pack = {"version": 1, "task_id": "V-999", "dispatch_ready": False, "tasks": tasks,
        "run_order_sha256": digest(csv_text), "fixture_controls": controls,
        "grant": {"task_id": "V-999", "billing": "subscription", "api_credit_fallback": False,
            "max_task_invocations": 56, "max_generated_output_plus_reasoning_tokens": 500000,
            "max_wall_seconds": 5400, "retry_policy": "none", "max_concurrency": 1,
            "allowed_models_efforts": configs}}
    pack["manifest_sha256"] = grant.manifest_hash(pack)
    return pack, inputs, csv_text


def test_frozen_handoff_inputs_hashes_order_and_task_identity(actor, frozen_pack):
    pack, inputs, csv_text = frozen_pack
    issued = issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    bound = grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999",
        manifest_hash=pack["manifest_sha256"], run_id="frozen-run")
    assert len(bound["tasks"]) == 56
    assert bound["tasks"][0]["task_id"] == "fixture-3-r2-c-6"
    assert bound["tasks"][0]["seed_files"] == {"src/example.py": "value = 'synthetic seed'\n"}
    assert all("oracle" not in str(task) for task in bound["tasks"])
    assert issued["manifest_hash"] == pack["manifest_sha256"]


@pytest.mark.parametrize("mutation", ["seed", "hidden", "csv", "hash", "cohort", "policy", "control", "traversal", "duplicate"])
def test_frozen_handoff_refuses_mutations_before_grant(actor, frozen_pack, mutation):
    from app.eval_fixtures import digest
    pack, inputs, csv_text = frozen_pack
    if mutation == "seed":
        inputs[next(path for path in inputs if "/seed/" in path)] += "changed"
    elif mutation == "hidden":
        inputs["fixtures/fixture-0/oracle/validate.py"] = "hidden solution"
    elif mutation == "csv":
        csv_text += "changed"
    elif mutation == "hash":
        pack["dispatch_ready"] = True
    elif mutation == "cohort":
        pack["grant"]["allowed_models_efforts"][0]["model"] = "gpt-6-astra"
    elif mutation == "policy":
        pack["grant"]["api_credit_fallback"] = True
    elif mutation == "control":
        pack["fixture_controls"][0]["returncode"] = 2
    elif mutation == "duplicate":
        lines = csv_text.splitlines(keepends=True)
        lines[2] = lines[1]
        csv_text = "".join(lines)
        pack["run_order_sha256"] = digest(csv_text)
    else:
        fixture = pack["tasks"][0]
        name = "fixtures/fixture-0/seed/src/../../oracle/solution.py"
        inputs[name] = "hidden"
        fixture["model_input_files"][name] = digest("hidden")
    if mutation != "hash":
        pack["manifest_sha256"] = grant.manifest_hash(pack)
    with pytest.raises(ValueError):
        issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    with db._conn() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='eval_grants'").fetchone() is None


@pytest.mark.asyncio
async def test_only_frozen_seed_source_materialized_and_scope_is_synthetic(actor, frozen_pack, tmp_path, monkeypatch):
    from app import backend_codex, manager
    pack, inputs, csv_text = frozen_pack
    issued = issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999", manifest_hash=issued["manifest_hash"], run_id="pack-run")
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_grants").fetchone())
    task = json.loads(row["plan"])[0]
    monkeypatch.setattr(db, "_REPO_ROOT", tmp_path)
    seen = {}
    def config(name, scope, **kwargs):
        pytest.fail("real Orchestra MCP must not be configured for synthetic input")
    class Backend:
        def __init__(self, **kwargs):
            from pathlib import Path
            cwd = Path(kwargs["cwd"])
            assert sorted(str(path.relative_to(cwd)) for path in cwd.rglob("*")
                          if path.is_file() and ".git" not in path.relative_to(cwd).parts) == ["prompt.md", "src/example.py"]
            import subprocess
            assert subprocess.check_output(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], text=True).strip() == str(cwd)
            assert cwd.parent == tmp_path and str(cwd) != actor["scope"]
            assert "mcp_servers" not in kwargs and "mcp_env" not in kwargs
            assert (cwd / "src/example.py").read_text() == "value = 'synthetic seed'\n"
            seen["cwd"] = str(cwd)
        async def connect(self):
            raise RuntimeError("fake stop before any provider")
        async def disconnect(self):
            pass
        async def interrupt(self):
            pass
    monkeypatch.setattr(manager, "_make_mcp_config", config)
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    answer = await grant.managed_call(row, 0, task)
    assert not answer["ok"] and answer["workspace_path"] == seen["cwd"]
    assert seen["cwd"] != actor["scope"]


@pytest.mark.asyncio
@pytest.mark.parametrize("late_change", ["stable_id", "project_id"])
async def test_task_identity_revalidated_after_managed_connection(bound, monkeypatch, late_change):
    from app import backend_codex
    sends, stopped = [], []
    monkeypatch.setattr(grant, "check_slot", lambda *args: None)
    async def quota(model):
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", quota)
    class Backend:
        session_id = "fake-late-task"
        def __init__(self, **kwargs):
            pass
        async def connect(self):
            monkeypatch.setattr(tm, "resolve_scoped_task_identity", lambda *args:
                {"stable_id": "changed"} if late_change == "stable_id" else
                {"stable_id": "task-stable", "project_id": "another-project"})
        async def _request(self, method, params):
            if method == "mcpServerStatus/list":
                return {"data": []}
            if method == "account/read":
                return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
            return {"data": [{"model": bound["tasks"][0]["model"], "supportedReasoningEfforts": [
                {"reasoningEffort": bound["tasks"][0]["effort"]}]}]}
        async def send(self, prompt):
            sends.append(prompt)
        async def events(self):
            yield AgentEvent("turn_end", metadata={"ok": True, "stop_reason": "end_turn", "cost_usd": 0.001},
                usage=TurnUsage(AggregateUsage(100, 10, 80), current_context(100, 1000)))
        async def interrupt(self):
            stopped.append("interrupt")
        async def disconnect(self):
            stopped.append("disconnect")
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    row = await grant.dispatch(**dispatch_args(bound))
    assert sends == [], "late task identity change must prevent provider send"
    assert not row["ok"] and "identity or project scope changed" in row["error"]
    assert sends == [] and stopped == ["interrupt", "disconnect"]
    assert grant.snapshot(bound["grant_id"])["unknown_usage_invocations"] == 1
    with pytest.raises(ValueError, match="unknown usage"):
        grant.reserve(**identity(bound, 1))


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["lease_withdrawal", "lease_expiry", "caller_cancel", "http_disconnect"])
async def test_blocked_managed_backend_stops_locally_and_never_dispatches_remaining(bound, tmp_path, monkeypatch, stop):
    from app import backend_codex, workflow_scheduler
    from app.routes.bg import EvalDispatchRequest, dispatch_eval
    scheduler = workflow_scheduler.WorkflowScheduler(tmp_path / "lease.db")
    monkeypatch.setattr(workflow_scheduler, "get_scheduler", lambda: scheduler)
    monkeypatch.setattr(grant, "LEASE_CHECK_SECONDS", 0.005)
    with scheduler._connect() as connection:
        connection.execute("INSERT INTO requests(request_id,run_id,queued_at,last_seen,lease_until) VALUES(?,?,?,?,?)",
                           ("test-slot", "eval-test", time.time(), time.time(), time.time() + 80))
    async def quota(model):
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", quota)
    started = asyncio.Event()
    cancelled = asyncio.Event()
    stop_trace, sends = [], []
    class Backend:
        session_id = "fake-blocked"
        def __init__(self, **kwargs):
            pass
        async def connect(self):
            pass
        async def _request(self, method, params):
            if method == "mcpServerStatus/list":
                return {"data": []}
            if method == "account/read":
                return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
            return {"data": [{"model": bound["tasks"][0]["model"], "supportedReasoningEfforts": [
                {"reasoningEffort": bound["tasks"][0]["effort"]}]}]}
        async def send(self, prompt):
            sends.append(prompt)
        async def events(self):
            started.set()
            yield AgentEvent("text", "partial before stop")
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        async def interrupt(self):
            stop_trace.append("interrupt")
        async def disconnect(self):
            stop_trace.append("disconnect")
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    disconnected = asyncio.Event()
    if stop == "http_disconnect":
        class Request:
            headers = {"authorization": "Bearer orchestra-pytest-only-token"}
            app = SimpleNamespace(state=SimpleNamespace(agent_cgroup="test"))
            async def receive(self):
                await disconnected.wait()
                return {"type": "http.disconnect"}
        running = asyncio.create_task(dispatch_eval(EvalDispatchRequest(**dispatch_args(bound)), Request()))
    else:
        running = asyncio.create_task(grant.dispatch(**dispatch_args(bound)))
    await asyncio.wait_for(started.wait(), 2)
    if stop == "caller_cancel":
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 2)
    elif stop == "http_disconnect":
        disconnected.set()
        response = await asyncio.wait_for(running, 2)
        assert response.status_code == 409
    else:
        with scheduler._connect() as connection:
            if stop == "lease_withdrawal":
                connection.execute("DELETE FROM requests WHERE request_id='test-slot'")
            else:
                connection.execute("UPDATE requests SET lease_until=0 WHERE request_id='test-slot'")
        response = await asyncio.wait_for(running, 2)
        assert not response["ok"] and not response["usage_known"]
        assert response["text"] == "partial before stop"
    assert cancelled.is_set() and stop_trace == ["interrupt", "disconnect"]
    assert len(sends) == 1
    receipt = grant.snapshot(bound["grant_id"])
    assert receipt["consumed_task_invocations"] == receipt["unknown_usage_invocations"] == 1
    invocation = receipt["invocations"][0]
    assert invocation["generated_tokens"] is None
    if stop in {"caller_cancel", "http_disconnect"}:
        assert invocation["result"] is None and invocation["state"] == "outcome_unknown"
    with pytest.raises(ValueError, match="unknown usage|unresolved"):
        grant.reserve(**identity(bound, 1))
    assert len(sends) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_mcp", [
    {"data": [{"name": "orchestra"}], "nextCursor": None},
    {"data": [{"name": "codex_apps"}], "nextCursor": None},
    {"data": [{"name": "unknown"}], "nextCursor": None},
    {}, {"data": [], "nextCursor": "more"},
])
async def test_runtime_mcp_registry_must_be_confirmed_empty(bound, monkeypatch, runtime_mcp):
    from app import backend_codex
    sends = []
    class Backend:
        session_id = "fake-mcp"
        def __init__(self, **kwargs):
            assert kwargs.get("mcp_servers", {}) == {} and kwargs.get("mcp_env", {}) == {}
        async def connect(self):
            pass
        async def _request(self, method, params):
            assert method == "mcpServerStatus/list"
            return runtime_mcp
        async def send(self, prompt):
            sends.append(prompt)
        async def interrupt(self):
            pass
        async def disconnect(self):
            pass
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    with db._conn() as connection:
        row = dict(connection.execute("SELECT * FROM eval_grants").fetchone())
    answer = await grant.managed_call(row, 0, bound["tasks"][0])
    assert not answer["ok"] and "confirmed empty MCP" in answer["error"]
    assert sends == []


def test_synthetic_workspace_refuses_checkout_ancestor(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(grant, "tempfile", SimpleNamespace(gettempdir=lambda: str(tmp_path)))
    with pytest.raises(ValueError, match="inside a real checkout"):
        grant.prepare_synthetic_workspace({"prompt": "synthetic only", "seed_files": {}})


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["", "eval-wire-test"])
@pytest.mark.parametrize("old_response", ["missing_policy", "no_read_only_access"])
@pytest.mark.parametrize("requested_effort", ["high", "ultra", "future-advertised-effort"])
async def test_native_thread_and_turn_use_normal_backend_without_experiment_sandbox(tmp_path, monkeypatch, actor, old_response, requested_effort):
    from unittest.mock import AsyncMock
    from app import backend_codex as native
    from tests.test_backend_codex import _FakeProcess
    workspace = grant.prepare_synthetic_workspace({"prompt": "test", "seed_files": {}})
    backend = native.CodexBackend(model="gpt-6.1-terra", cwd=str(workspace),
        evaluation_actor_id=actor, reasoning_effort=requested_effort)
    expected_effort = requested_effort if actor or requested_effort in native.CODEX_REASONING_EFFORTS else "high"
    assert backend.reasoning_effort == expected_effort
    monkeypatch.setattr(native, "_base_codex_home", lambda: tmp_path / "fake-auth-base")
    monkeypatch.setattr(native.RuntimeProcessGroup, "create", lambda **kwargs: (None, "offline fake"))
    monkeypatch.setattr(native.asyncio, "create_subprocess_exec", AsyncMock(return_value=_FakeProcess()))
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    backend._disconnect_direct = AsyncMock()
    backend._finalize_disconnect = AsyncMock()
    requests = []
    async def request(method, params):
        requests.append((method, params))
        if method == "thread/start":
            assert params == {"cwd": str(workspace), "model": "gpt-6.1-terra",
                              "approvalPolicy": "never", "sandbox": "danger-full-access"}
            response = {"thread": {"id": "eval-native-thread"}}
            if old_response == "no_read_only_access":
                response["sandbox"] = {"type": "dangerFullAccess"}
            return response
        if method == "turn/start":
            assert params == {"threadId": "eval-native-thread", "input": [{"type": "text", "text": "synthetic task"}],
                              "model": "gpt-6.1-terra", "effort": expected_effort}
            return {"turn": {"id": "turn-eval"}}
        return {}
    backend._request = AsyncMock(side_effect=request)
    await backend.connect()
    await backend.send("synthetic task")
    assert [method for method, _ in requests] == ["initialize", "thread/start", "turn/start"]
    if actor:
        import tomllib
        config = tomllib.loads((backend._codex_home / "config.toml").read_text())
        assert config.get("mcp_servers", {}) == {}
        assert "sandbox_workspace_write" not in config and "shell_environment_policy" not in config
        assert backend._managed_codex_home_path().name == actor
        assert backend._mcp_servers == {} and backend._mcp_env == {}
    assert 'web_search="live"' in backend._codex_command()
    assert f'model_reasoning_effort="{expected_effort}"' in backend._codex_command()
    if actor:
        await backend.disconnect()
        with pytest.raises(RuntimeError, match="stopped"):
            await backend.send("must not restart locally")


def test_evaluation_identity_cannot_reuse_orchestrator_mcp_or_history(tmp_path):
    from app.backend_codex import CodexBackend
    for kwargs in ({"is_orchestrator": True}, {"mcp_servers": {"orchestra": {"command": "forbidden"}}},
                   {"mcp_env": {"ORCHESTRA_SESSION_ID": "real"}}, {"resume_thread_id": "history"}):
        with pytest.raises(ValueError, match="fresh worker without MCP/history"):
            CodexBackend("gpt-6.1-terra", str(tmp_path), evaluation_actor_id="eval-test", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6.1-terra"])
@pytest.mark.parametrize("purpose_state", ["valid", "hidden", "unavailable", "invalid_grant"])
async def test_serialized_manual_only_false_is_worker_policy_not_eval_revocation(actor, manifest, fake_provider, monkeypatch, model, purpose_state):
    # Exercise the real serialization, including the True -> False clamp. A later
    # dashboard write retains this same False; no live KV workaround is required.
    models.set_model_flags(model, agents=True, dashboard=True)
    assert models._load_model_flags()[model]["agents"] is False
    models.set_model_flags(model, dashboard=True)
    assert models._load_model_flags()[model]["agents"] is False
    assert models.get_model_flags(model)["agents"] is False
    # Put this model first in a newly frozen plan: the test does not bypass order.
    manifest["conditions"].sort(key=lambda row: row["model"] != model)
    issued = issue(actor, manifest)
    bound = grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999",
        manifest_hash=issued["manifest_hash"], run_id="eval-test")
    args = dispatch_args(bound)
    assert args["model"] == model
    if purpose_state == "hidden":
        models.set_model_flags(model, dashboard=False)
    elif purpose_state == "unavailable":
        spec = models.get_model_spec(model)
        get_spec = models.get_model_spec
        monkeypatch.setattr(models, "get_model_spec", lambda requested:
                            replace(spec, available=False) if requested == model else get_spec(requested))
    elif purpose_state == "invalid_grant":
        args["grant_id"] = "unissued-eval-grant"
    if purpose_state == "invalid_grant":
        with pytest.raises(ValueError, match="unknown evaluation grant"):
            await grant.dispatch(**args)
    else:
        answer = await grant.dispatch(**args)
        assert answer["ok"] is (purpose_state == "valid")
    assert len(fake_provider) == (1 if purpose_state == "valid" else 0)
    # Purpose exception never changes ordinary spawn/dynamic-workflow admission.
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(model)
    from app.mcp_stdio import _normalize_dynamic_task
    normalized, error = _normalize_dynamic_task({"prompt": "ordinary work", "model": model}, label="task")
    assert normalized == {} and "not allowed" in error
    assert models._load_model_flags()[model]["agents"] is False


@pytest.fixture
def coding_pack(frozen_pack):
    import csv
    import io
    from app.eval_fixtures import digest
    pack, inputs, _ = frozen_pack
    supported = {model: ["low", "medium", "high", "xhigh", "max", "ultra"] for model in sorted(grant.CODING_MODELS)}
    configs = [{"id": f"condition-{index}", "model": model, "effort": effort}
               for index, (model, effort) in enumerate((model, effort) for model, efforts in supported.items() for effort in efforts)]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["sequence", "fixture_id", "repeat", "condition_id", "model", "effort", "billing", "attempt"], lineterminator="\n")
    writer.writeheader()
    number = 0
    for fixture in reversed(pack["tasks"]):
        for config in reversed(configs):
            number += 1
            writer.writerow({"sequence": number, "fixture_id": fixture["id"], "repeat": 1,
                "condition_id": config["id"], "model": config["model"], "effort": config["effort"],
                "billing": "subscription", "attempt": 1})
    csv_text = output.getvalue()
    pack.update(version=2, stage="coding", runtime_supported_efforts=supported, run_order_sha256=digest(csv_text))
    pack["grant"]["allowed_models_efforts"] = configs
    pack["manifest_sha256"] = grant.manifest_hash(pack)
    return pack, inputs, csv_text


@pytest.mark.parametrize("change", ["omit_effort", "extra_effort", "luna", "repeat", "duplicate", "stage", "budget"])
def test_coding_frozen_matrix_refuses_unapproved_expansion(actor, coding_pack, change):
    import csv
    import io
    from app.eval_fixtures import digest
    pack, inputs, csv_text = coding_pack
    if change == "omit_effort":
        pack["grant"]["allowed_models_efforts"].pop()
    elif change == "extra_effort":
        pack["runtime_supported_efforts"]["gpt-6.1-sol"].append("not-in-frozen-conditions")
    elif change == "luna":
        pack["grant"]["allowed_models_efforts"][0]["model"] = "gpt-6-luna"
    elif change == "stage":
        pack["stage"] = "orchestration"
    elif change == "budget":
        pack["grant"]["max_task_invocations"] = 80
    else:
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        if change == "repeat":
            rows[0]["repeat"] = "2"
        else:
            rows[1] = rows[0]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
        csv_text = output.getvalue()
        pack["run_order_sha256"] = digest(csv_text)
    pack["manifest_sha256"] = grant.manifest_hash(pack)
    with pytest.raises(ValueError):
        issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    with db._conn() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='eval_grants'").fetchone() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", ["matching", "lost_effort", "extra_effort"])
async def test_coding_runtime_efforts_are_frozen_and_checked_before_send(actor, coding_pack, monkeypatch, catalog):
    from app import backend_codex
    pack, inputs, csv_text = coding_pack
    issued = issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    bound = grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999", manifest_hash=issued["manifest_hash"], run_id="eval-test")
    monkeypatch.setattr(grant, "check_slot", lambda *args: None)
    async def quota(model):
        return quota_gate.evaluate_worker_admission(model, {}, {})
    monkeypatch.setattr(quota_gate, "get_worker_admission", quota)
    sends = []
    selected = bound["tasks"][0]["model"]
    class Backend:
        session_id = "fake-coding-thread"
        def __init__(self, **kwargs):
            assert kwargs["evaluation_actor_id"].startswith("eval-") and not kwargs["is_orchestrator"]
            assert not kwargs.get("mcp_servers")
        async def connect(self):
            pass
        async def _request(self, method, params):
            if method == "mcpServerStatus/list":
                return {"data": []}
            if method == "account/read":
                return {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
            efforts = list(pack["runtime_supported_efforts"][selected])
            if catalog == "lost_effort":
                efforts.remove("low")
            elif catalog == "extra_effort":
                efforts.append("minimal")
            return {"data": [{"model": selected, "supportedReasoningEfforts": [{"reasoningEffort": effort} for effort in efforts]}]}
        async def send(self, prompt):
            sends.append(prompt)
        async def events(self):
            yield AgentEvent("turn_end", metadata={"ok": True, "stop_reason": "end_turn"},
                usage=TurnUsage(AggregateUsage(100, 10, 80), current_context(100, 1000)))
        async def interrupt(self):
            pass
        async def disconnect(self):
            pass
    monkeypatch.setattr(backend_codex, "CodexBackend", Backend)
    answer = await grant.dispatch(**dispatch_args(bound))
    assert answer["ok"] is (catalog == "matching")
    assert len(sends) == (1 if catalog == "matching" else 0)
    if catalog != "matching":
        assert "runtime effort catalog differs" in answer["error"]
        assert not answer["usage_known"]
        with pytest.raises(ValueError, match="unknown usage"):
            grant.reserve(**identity(bound, 1))


def test_coding_stage_uses_actual_effort_subset_without_inventing_extra_cells(actor, manifest):
    manifest.update(stage="coding", repeats=1, runtime_supported_efforts={model: ["high"] for model in grant.CODING_MODELS},
        conditions=[{"model": model, "effort": "high"} for model in sorted(grant.CODING_MODELS)])
    issued = issue(actor, manifest)
    assert issued["planned_task_invocations"] == 8 and issued["max_calls"] == 56
    bound = grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999", manifest_hash=issued["manifest_hash"], run_id="eval-test")
    assert len(bound["tasks"]) == 8
    with pytest.raises(ValueError, match="outside the frozen task plan"):
        grant.reserve(**identity(bound, 8))


@pytest.mark.asyncio
async def test_dynamic_workflow_accepts_frozen_48_call_coding_stage(actor, coding_pack, tmp_path, monkeypatch):
    from app import mcp_stdio, workspace
    pack, inputs, csv_text = coding_pack
    issued = issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    queued = []
    async def api(method, path, **kwargs):
        if path == "/api/bg/eval/bind":
            return grant.bind(actor, **kwargs["json"])
        assert path == "/api/bg/jobs"
        queued.append(kwargs["json"])
        return {"id": "fake-coding-job"}
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(mcp_stdio, "__file__", str(tmp_path / "app/mcp_stdio.py"))
    monkeypatch.setattr(mcp_stdio, "_api", api)
    monkeypatch.setattr(workspace, "resolve_worktree_context", lambda repo: (tmp_path, "a" * 40))
    response = await mcp_stdio.dynamic_workflow(budget_usd=0, max_calls=48, max_concurrency=1,
        task_id="V-999", repo=str(tmp_path), eval_grant_id=issued["grant_id"], eval_manifest_hash=issued["manifest_hash"])
    assert "queued" in response and len(queued) == 1
    import shlex
    args = shlex.split(queued[0]["config"]["command"])
    spec = json.loads((tmp_path / args[args.index("--spec") + 1]).read_text())
    assert spec["mode"] == "eval" and len(spec["tasks"]) == 48
    assert spec["dashboard"]["max_calls"] == 48 and spec["dashboard"]["budget_usd"] == 0
    assert args[args.index("--max-calls") + 1] == "48"
    assert spec["eval_grant"]["token_policy"] == grant.TOKEN_POLICY
    assert queued[0]["timeout_seconds"] == 5400


@pytest.mark.parametrize("effort", [None, "", "   ", 1, True, []])
def test_eval_identity_rejects_empty_or_nonstring_effort(tmp_path, effort):
    from app.backend_codex import CodexBackend
    with pytest.raises(ValueError, match="non-empty advertised string"):
        CodexBackend("gpt-6.1-terra", str(tmp_path), evaluation_actor_id="eval-effort-test", reasoning_effort=effort)


@pytest.mark.parametrize("count", [7, 8])
def test_open_advertised_effort_strings_do_not_raise_original_call_cap(actor, manifest, count):
    efforts = [f"advertised-effort-{n}" for n in range(count)]
    manifest.update(stage="coding", repeats=1,
        runtime_supported_efforts={model: list(efforts) for model in grant.CODING_MODELS},
        conditions=[{"model": model, "effort": effort} for model in sorted(grant.CODING_MODELS) for effort in efforts])
    if count == 8:
        with pytest.raises(ValueError, match="task-invocation cap"):
            issue(actor, manifest)
    else:
        issued = issue(actor, manifest)
        assert issued["planned_task_invocations"] == issued["max_calls"] == 56


@pytest.mark.asyncio
async def test_unadvertised_coding_effort_cannot_override_issued_plan(actor, coding_pack, fake_provider):
    pack, inputs, csv_text = coding_pack
    issued = issue(actor, pack, fixture_inputs=inputs, run_order_csv=csv_text)
    bound = grant.bind(actor, grant_id=issued["grant_id"], task_id="V-999", manifest_hash=issued["manifest_hash"], run_id="eval-test")
    args = dispatch_args(bound)
    args["effort"] = "not-advertised-by-the-model"
    answer = await grant.dispatch(**args)
    assert not answer["ok"] and not answer["usage_known"]
    assert fake_provider == []
    with pytest.raises(ValueError, match="unknown usage"):
        grant.reserve(**identity(bound, 1))
