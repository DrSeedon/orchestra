import json
import sqlite3
from pathlib import Path

import pytest

from scripts.wf_adapters import (
    AdapterResult,
    Usage,
    parse_claude_output,
    parse_codex_output,
    persist_turn_usage,
)
from scripts.wf_run import WorkflowEngine, validate_pilot_manifest


FIXTURES = Path(__file__).parent / "fixtures" / "wf"


def _result(text: str, *, cost: float = 0.01, runtime: str = "codex", model: str = "gpt-5.6-luna"):
    return AdapterResult(
        text=text,
        runtime=runtime,
        model=model,
        ok=True,
        stop_reason="end_turn",
        cost_usd=cost,
        usage=Usage(input_tokens=10, output_tokens=2),
    )


@pytest.mark.asyncio
async def test_resume_ignores_a_truncated_tail_and_continues_after_completed_calls(tmp_path):
    first_calls = []

    async def first_adapter(prompt, **_kwargs):
        first_calls.append(prompt)
        return _result("first-result")

    engine = WorkflowEngine("resume-case", tmp_path, budget_usd=2, adapter=first_adapter)
    first = await engine.agent("first", model="luna")
    assert first.data == "first-result"
    with engine.journal.path.open("ab") as fh:
        fh.write(b'{"event":"completed","call_key":')

    resumed_calls = []

    async def resumed_adapter(prompt, **_kwargs):
        resumed_calls.append(prompt)
        return _result("second-result")

    resumed = WorkflowEngine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
    cached = await resumed.agent("first", model="luna")
    second = await resumed.agent("second", model="luna")

    assert cached.data == "first-result"
    assert second.data == "second-result"
    assert resumed_calls == ["second"]
    replay = WorkflowEngine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
    assert (await replay.agent("first", model="luna")).data == "first-result"
    assert (await replay.agent("second", model="luna")).data == "second-result"
    assert resumed_calls == ["second"]


@pytest.mark.asyncio
async def test_budget_exhaustion_returns_none_and_marks_manifest_partial(tmp_path):
    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        return _result(prompt, cost=1.01)

    engine = WorkflowEngine("budget-case", tmp_path, budget_usd=1, adapter=adapter)
    assert await engine.agent("spends-the-budget", model="luna") is not None
    assert await engine.agent("must-not-dispatch", model="luna") is None

    manifest = engine.write_manifest()
    assert calls == ["spends-the-budget"]
    assert manifest["complete"] is False
    assert manifest["partial_reason"] == "budget"


@pytest.mark.asyncio
async def test_parallel_calls_reserve_max_call_budget_before_dispatch(tmp_path):
    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        await __import__("asyncio").sleep(0)
        return _result(prompt)

    engine = WorkflowEngine(
        "call-reservation", tmp_path, budget_usd=2, max_calls=1, adapter=adapter,
    )
    values = await engine.parallel([
        lambda: engine.agent("one", model="luna"),
        lambda: engine.agent("two", model="luna"),
    ])
    assert len(calls) == 1
    assert sum(value is not None for value in values) == 1
    assert engine.budget.dispatched_calls == 1


@pytest.mark.asyncio
async def test_schema_retries_twice_with_validation_error_then_returns_none(tmp_path):
    prompts = []
    outputs = iter(['{"answer": 1}', "not-json", '{"answer": 3}'])

    async def adapter(prompt, **_kwargs):
        prompts.append(prompt)
        return _result(next(outputs))

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    engine = WorkflowEngine("schema-case", tmp_path, budget_usd=2, adapter=adapter)
    assert await engine.agent("give answer", model="luna", schema=schema) is None
    assert len(prompts) == 3
    assert "Validation error:" not in prompts[0]
    assert "Validation error:" in prompts[1]
    assert "Validation error:" in prompts[2]
    assert engine.write_manifest()["partial_reason"] == "schema"


@pytest.mark.asyncio
async def test_schema_retry_accepts_a_later_valid_response(tmp_path):
    prompts = []
    outputs = iter(["not-json", '{"answer": "ok"}'])

    async def adapter(prompt, **_kwargs):
        prompts.append(prompt)
        return _result(next(outputs))

    engine = WorkflowEngine("schema-recovers", tmp_path, budget_usd=2, adapter=adapter)
    value = await engine.agent(
        "give answer",
        model="luna",
        schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )
    assert value.data == {"answer": "ok"}
    assert len(prompts) == 2
    assert "Validation error:" in prompts[1]


@pytest.mark.asyncio
async def test_dispatched_is_fsynced_before_adapter_invocation(tmp_path):
    engine = None

    async def adapter(_prompt, **_kwargs):
        rows = engine.journal.load()
        assert rows[-1]["event"] == "dispatched"
        return _result("done")

    engine = WorkflowEngine("write-ahead", tmp_path, budget_usd=2, adapter=adapter)
    assert await engine.agent("work", model="luna") is not None


@pytest.mark.asyncio
async def test_engine_persists_usage_before_terminal_journal_record(tmp_path):
    engine = None
    receipts = []

    async def adapter(_prompt, **_kwargs):
        return _result("done")

    def usage_writer(**kwargs):
        assert engine.journal.load()[-1]["event"] == "dispatched"
        receipts.append(kwargs)
        return True

    engine = WorkflowEngine(
        "usage-integration",
        tmp_path,
        budget_usd=2,
        adapter=adapter,
        usage_writer=usage_writer,
    )
    assert await engine.agent("work", model="luna") is not None
    assert len(receipts) == 1
    assert receipts[0]["event_id"].startswith("wf:usage-integration:")
    assert [row["event"] for row in engine.journal.load()] == [
        "dispatched",
        "attempt_finished",
        "completed",
    ]


@pytest.mark.asyncio
async def test_free_output_requires_a_verify_step_before_synthesis(tmp_path):
    calls = []

    async def adapter(prompt, model, **_kwargs):
        calls.append((prompt, model))
        runtime = "harness" if model.endswith(":free") else "codex"
        return _result('{"ok": true}', runtime=runtime, model=model)

    engine = WorkflowEngine("free-gate", tmp_path, budget_usd=2, adapter=adapter)
    with pytest.raises(ValueError, match="loss_tolerant"):
        await engine.agent("unsafe draft", model="z-ai/glm-5.2:free")
    free = await engine.agent(
        "draft", model="z-ai/glm-5.2:free", loss_tolerant=True,
    )
    with pytest.raises(ValueError, match="non-free"):
        await engine.agent(
            "self check",
            purpose="verify",
            inputs=[free],
            model="z-ai/glm-5.2:free",
            loss_tolerant=True,
        )
    with pytest.raises(ValueError, match="verify"):
        await engine.agent("synthesize", purpose="synthesis", inputs=[free])

    checked = await engine.agent("check", purpose="verify", inputs=[free], model="luna")
    final = await engine.agent(
        "synthesize", purpose="synthesis", inputs=[free, checked], model="luna",
    )
    assert final is not None
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_dispatched_without_terminal_event_resumes_as_unknown_not_a_second_charge(tmp_path):
    async def interrupted(_prompt, **_kwargs):
        raise RuntimeError("simulated process loss")

    first = WorkflowEngine("unknown-call", tmp_path, budget_usd=2, adapter=interrupted)
    with pytest.raises(RuntimeError, match="process loss"):
        await first.agent("work", model="luna")

    calls = []

    async def must_not_run(prompt, **_kwargs):
        calls.append(prompt)
        return _result("duplicate")

    resumed = WorkflowEngine("unknown-call", tmp_path, budget_usd=2, adapter=must_not_run)
    assert await resumed.agent("work", model="luna") is None
    assert calls == []
    assert resumed.write_manifest()["partial_reason"] == "outcome_unknown"


@pytest.mark.asyncio
async def test_attempt_finished_without_completed_resumes_as_unknown(tmp_path):
    async def adapter(_prompt, **_kwargs):
        return _result("charged-result")

    first = WorkflowEngine("finished-no-result", tmp_path, budget_usd=2, adapter=adapter)

    def lose_completion(*_args, **_kwargs):
        raise RuntimeError("crash before completed")

    first._finish = lose_completion
    with pytest.raises(RuntimeError, match="before completed"):
        await first.agent("work", model="luna")

    calls = []

    async def must_not_run(prompt, **_kwargs):
        calls.append(prompt)
        return _result("duplicate")

    resumed = WorkflowEngine(
        "finished-no-result", tmp_path, budget_usd=2, adapter=must_not_run,
    )
    assert await resumed.agent("work", model="luna") is None
    assert calls == []
    assert resumed.write_manifest()["partial_reason"] == "outcome_unknown"


@pytest.mark.asyncio
async def test_schema_retry_deferred_by_call_budget_resumes_at_next_attempt(tmp_path):
    first_calls = []

    async def invalid(prompt, **_kwargs):
        first_calls.append(prompt)
        return _result("not-json")

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    first = WorkflowEngine(
        "deferred-schema", tmp_path, budget_usd=2, max_calls=1, adapter=invalid,
    )
    assert await first.agent("work", model="luna", schema=schema) is None
    first_manifest = first.write_manifest()
    assert first_manifest["partial_reason"] == "budget"
    assert first_calls == ["work"]

    resumed_calls = []

    async def valid(prompt, **_kwargs):
        resumed_calls.append(prompt)
        return _result('{"answer": "ok"}')

    resumed = WorkflowEngine(
        "deferred-schema", tmp_path, budget_usd=2, max_calls=2, adapter=valid,
    )
    value = await resumed.agent("work", model="luna", schema=schema)
    assert value.data == {"answer": "ok"}
    assert len(resumed_calls) == 1
    assert "Validation error:" in resumed_calls[0]
    assert resumed.budget.dispatched_calls == 2
    assert resumed.write_manifest()["complete"] is True


@pytest.mark.asyncio
async def test_unknown_spend_conservatively_exhausts_dollar_budget(tmp_path):
    ledger = []

    async def costly(_prompt, **_kwargs):
        return _result("charged", cost=1.1)

    def commit_then_crash(**kwargs):
        ledger.append(kwargs["result"].cost_usd)
        raise RuntimeError("crash after ledger commit")

    first = WorkflowEngine(
        "unknown-spend",
        tmp_path,
        budget_usd=1,
        adapter=costly,
        usage_writer=commit_then_crash,
    )
    with pytest.raises(RuntimeError, match="turn_usage accounting failed"):
        await first.agent("charged-call", model="luna")
    assert ledger == [1.1]

    resumed_calls = []

    async def must_not_run(prompt, **_kwargs):
        resumed_calls.append(prompt)
        return _result("extra", cost=0.1)

    resumed = WorkflowEngine("unknown-spend", tmp_path, budget_usd=1, adapter=must_not_run)
    assert await resumed.agent("charged-call", model="luna") is None
    assert await resumed.agent("another-call", model="luna") is None
    assert resumed_calls == []
    assert resumed.budget.remaining_usd() == 0


@pytest.mark.asyncio
async def test_crash_after_final_schema_checkpoint_restores_schema_failure(tmp_path):
    async def invalid(_prompt, **_kwargs):
        return _result("not-json")

    schema = {"type": "object"}
    first = WorkflowEngine("final-schema", tmp_path, budget_usd=2, adapter=invalid)

    def lose_completion(*_args, **_kwargs):
        raise RuntimeError("crash before schema completion")

    first._finish = lose_completion
    with pytest.raises(RuntimeError, match="schema completion"):
        await first.agent("work", model="luna", schema=schema)

    calls = []

    async def must_not_run(prompt, **_kwargs):
        calls.append(prompt)
        return _result('{"ok": true}')

    resumed = WorkflowEngine("final-schema", tmp_path, budget_usd=2, adapter=must_not_run)
    assert await resumed.agent("work", model="luna", schema=schema) is None
    assert calls == []
    assert resumed.write_manifest()["partial_reason"] == "schema"
    completed = [row for row in resumed.journal.load() if row["event"] == "completed"]
    assert completed[-1]["reason"] == "schema"


@pytest.mark.asyncio
async def test_transient_quota_skip_is_rechecked_on_resume(tmp_path):
    async def blocked(_model):
        return {"state": "blocked"}

    async def available(_model):
        return {"state": "available"}

    first = WorkflowEngine(
        "quota-resume", tmp_path, budget_usd=2, adapter=lambda *args, **kwargs: None,
        readiness_checker=blocked,
    )
    assert await first.agent("work", model="luna") is None

    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        return _result("done")

    resumed = WorkflowEngine(
        "quota-resume", tmp_path, budget_usd=2, adapter=adapter,
        readiness_checker=available,
    )
    assert await resumed.agent("work", model="luna") is not None
    assert calls == ["work"]
    assert resumed.write_manifest()["complete"] is True


@pytest.mark.asyncio
async def test_historical_budget_skip_clears_after_larger_budget_resume(tmp_path):
    first = WorkflowEngine("budget-resume", tmp_path, budget_usd=0, adapter=lambda *a, **k: None)
    assert await first.agent("work", model="luna") is None

    async def adapter(_prompt, **_kwargs):
        return _result("done")

    resumed = WorkflowEngine("budget-resume", tmp_path, budget_usd=1, adapter=adapter)
    assert await resumed.agent("work", model="luna") is not None
    assert resumed.write_manifest()["complete"] is True


def test_adapter_parsers_use_captured_real_cli_outputs():
    codex = parse_codex_output(
        (FIXTURES / "codex-exec.jsonl").read_text(), "gpt-5.6-luna",
    )
    assert codex.text == "CODEX_PROBE_A"
    assert codex.usage == Usage(
        input_tokens=54757,
        output_tokens=9,
        cache_read_tokens=8960,
        cache_create_tokens=0,
    )
    assert codex.cost_usd == pytest.approx(0.0093494)

    claude = parse_claude_output(
        (FIXTURES / "claude-print.json").read_text(), "claude-haiku-4-5",
    )
    assert claude.text == "WF_PROBE_OK"
    assert claude.usage == Usage(
        input_tokens=10,
        output_tokens=57,
        cache_read_tokens=0,
        cache_create_tokens=7414,
    )
    assert claude.cost_usd == pytest.approx(0.016103)


def test_sessionless_usage_is_written_immediately_and_is_replay_safe(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "usage.db")
    db.init_db()
    result = parse_codex_output(
        (FIXTURES / "codex-exec.jsonl").read_text(), "gpt-5.6-luna",
    )
    kwargs = {
        "result": result,
        "event_id": "wf:run:call:1",
        "session_id": "wf:run",
        "scope": "test-scope",
        "task_id": "487",
    }
    assert persist_turn_usage(**kwargs) is True
    assert persist_turn_usage(**kwargs) is False
    with sqlite3.connect(db.DB_PATH) as conn:
        row = conn.execute(
            "SELECT runtime, model, cost_usd, input_tokens, output_tokens "
            "FROM turn_usage WHERE event_id=?",
            ("wf:run:call:1",),
        ).fetchone()
    assert row == ("codex", "gpt-5.6-luna", pytest.approx(0.0093494), 54757, 9)


def test_manifest_contains_ready_resume_command(tmp_path):
    engine = WorkflowEngine(
        "resume-command", tmp_path, budget_usd=3,
        workflow_path=Path("data/workflow-runs/sample.wf.py"),
    )
    command = engine.write_manifest()["resume_command"]
    assert "scripts/wf_run.py" in command
    assert "--resume resume-command" in command
    assert "--budget-usd 3" in command
    assert "--resume resume-command" in engine.write_manifest()["wake_message"]


def test_manifest_can_use_a_runner_specific_resume_command(tmp_path):
    command = "python scripts/wf_pilot.py --resume pilot-487 --budget-usd 1"
    engine = WorkflowEngine(
        "pilot-487",
        tmp_path,
        budget_usd=1,
        workflow_path=Path("scripts/wf_pilot.py"),
        resume_command_override=command,
    )
    manifest = engine.write_manifest()
    assert manifest["resume_command"] == command
    assert command in manifest["wake_message"]


@pytest.mark.asyncio
async def test_executes_a_top_level_await_workflow(tmp_path):
    workflow = tmp_path / "sample.wf.py"
    workflow.write_text(
        "phase('read')\n"
        "values = await parallel([lambda: agent('a', model='luna'), "
        "lambda: agent('b', model='luna')])\n"
        "result = [item.data for item in values]\n"
    )

    async def adapter(prompt, **_kwargs):
        return _result(prompt.upper())

    engine = WorkflowEngine(
        "exec-workflow", tmp_path / "run", budget_usd=2, adapter=adapter,
    )
    assert await engine.execute(workflow) == ["A", "B"]


def test_pilot_gate_requires_twenty_distinct_closed_ticket_results():
    nineteen = {
        "tickets": [
            {"ticket_id": str(index), "status": "completed", "schema_valid": True}
            for index in range(19)
        ]
    }
    with pytest.raises(ValueError, match="20"):
        validate_pilot_manifest(nineteen)
    twenty = {
        "tickets": nineteen["tickets"]
        + [{"ticket_id": "19", "status": "completed", "schema_valid": True}]
    }
    validate_pilot_manifest(twenty)
