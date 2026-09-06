import json
import sqlite3
import subprocess
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


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "wf@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "WF Test"], cwd=path, check=True)
    (path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)
    return path


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


def _engine(*args, **kwargs):
    kwargs.setdefault("default_modules", ())
    return WorkflowEngine(*args, **kwargs)


@pytest.mark.asyncio
async def test_resume_ignores_a_truncated_tail_and_continues_after_completed_calls(tmp_path):
    first_calls = []

    async def first_adapter(prompt, **_kwargs):
        first_calls.append(prompt)
        return _result("first-result")

    engine = _engine("resume-case", tmp_path, budget_usd=2, adapter=first_adapter)
    first = await engine.agent("first", model="luna")
    assert first.data == "first-result"
    with engine.journal.path.open("ab") as fh:
        fh.write(b'{"event":"completed","call_key":')

    resumed_calls = []

    async def resumed_adapter(prompt, **_kwargs):
        resumed_calls.append(prompt)
        return _result("second-result")

    resumed = _engine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
    cached = await resumed.agent("first", model="luna")
    second = await resumed.agent("second", model="luna")

    assert cached.data == "first-result"
    assert second.data == "second-result"
    assert resumed_calls == ["second"]
    replay = _engine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
    assert (await replay.agent("first", model="luna")).data == "first-result"
    assert (await replay.agent("second", model="luna")).data == "second-result"
    assert resumed_calls == ["second"]


@pytest.mark.asyncio
async def test_budget_exhaustion_returns_none_and_marks_manifest_partial(tmp_path):
    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        return _result(prompt, cost=1.01)

    engine = _engine("budget-case", tmp_path, budget_usd=1, adapter=adapter)
    assert await engine.agent("spends-the-budget", model="luna") is not None
    assert await engine.agent("must-not-dispatch", model="luna") is None

    manifest = engine.write_manifest()
    assert calls == ["spends-the-budget"]
    assert manifest["complete"] is False
    assert manifest["partial_reason"] == "budget"


@pytest.mark.asyncio
async def test_full_tools_network_and_mcp_are_default_per_agent_call(tmp_path):
    seen = []

    async def adapter(prompt, **kwargs):
        seen.append((prompt, kwargs))
        return _result("done")

    engine = _engine("full-default", tmp_path, budget_usd=1, adapter=adapter)
    assert await engine.agent("work", model="luna") is not None
    assert seen[0][1]["tools"] == "all"
    assert seen[0][1]["network"] is True
    assert seen[0][1]["mcp"] is True
    assert await engine.agent(
        "offline", model="luna", network=False,
        capability_reason="offline deterministic check",
    ) is not None
    assert seen[1][1]["network"] is False
    assert seen[1][1]["mcp"] is False


@pytest.mark.asyncio
async def test_agent_modules_use_the_canonical_pipeline_builder(tmp_path):
    from app.pipeline import build_prompt_modules

    seen = []

    async def adapter(_prompt, **kwargs):
        seen.append(kwargs["system_prompt"])
        return _result("done")

    engine = _engine("module-subscription", tmp_path, budget_usd=1, adapter=adapter)
    await engine.agent("work", model="luna", modules=["code-quality"])
    assert seen == [build_prompt_modules("default", ["code-quality"])]


def test_build_system_prompt_still_flows_through_public_module_builder(monkeypatch):
    from app import pipeline

    original = pipeline.build_prompt_modules
    seen = []

    def recording_builder(pipeline_name, modules):
        seen.append((pipeline_name, tuple(modules)))
        return original(pipeline_name, modules)

    monkeypatch.setattr(pipeline, "build_prompt_modules", recording_builder)
    prompt = pipeline.build_system_prompt("default", "worker")
    assert prompt
    assert seen == [("default", tuple(pipeline.get_role("default", "worker").modules))]


def test_build_system_prompt_keeps_every_configured_worker_module():
    from app import pipeline

    prompt = pipeline.build_system_prompt("default", "worker")
    for name in pipeline.get_role("default", "worker").modules:
        body = pipeline.prompt_path("default", f"modules/{name}.md").read_text().strip()
        assert body in prompt, name


def test_missing_prompt_module_fails_loud():
    from app.pipeline import build_prompt_modules

    with pytest.raises(FileNotFoundError, match="missing-workflow-module"):
        build_prompt_modules("default", ["missing-workflow-module"])


def test_default_workflow_module_interface_is_frozen():
    from scripts.wf_run import DEFAULT_WORKFLOW_MODULES

    assert DEFAULT_WORKFLOW_MODULES == (
        "communication-style",
        "user-values",
        "knowledge",
        "code-quality",
    )


@pytest.mark.asyncio
async def test_parallel_writers_use_distinct_real_worktrees(tmp_path):
    import asyncio

    repo = _git_repo(tmp_path / "repo")
    arrived = 0
    lock = asyncio.Lock()
    both_ready = asyncio.Event()
    workspaces = {}

    async def adapter(prompt, *, cwd, **_kwargs):
        nonlocal arrived
        workspaces[prompt] = Path(cwd)
        (Path(cwd) / f"{prompt}.txt").write_text(prompt)
        async with lock:
            arrived += 1
            if arrived == 2:
                both_ready.set()
        await both_ready.wait()
        other = "two" if prompt == "one" else "one"
        assert not (Path(cwd) / f"{other}.txt").exists()
        return _result(prompt)

    engine = _engine(
        "isolated-writers",
        tmp_path / "run",
        budget_usd=1,
        adapter=adapter,
        workspace_repo=repo,
        workspace_base_branch="main",
    )
    values = await engine.parallel([
        lambda: engine.agent("one", model="luna"),
        lambda: engine.agent("two", model="luna"),
    ])
    assert workspaces["one"] != workspaces["two"]
    assert all(not path.exists() for path in workspaces.values())
    archived = [Path(value.workspace_path) for value in values]
    assert any((path / "one.txt").read_text() == "one" for path in archived if (path / "one.txt").is_file())
    assert any((path / "two.txt").read_text() == "two" for path in archived if (path / "two.txt").is_file())
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout
    assert listed.count("worktree ") == 1


@pytest.mark.asyncio
async def test_committed_workspace_is_archived_reset_and_discarded(tmp_path):
    repo = _git_repo(tmp_path / "repo")

    async def adapter(_prompt, *, cwd, **_kwargs):
        cwd = Path(cwd)
        (cwd / "committed.txt").write_text("committed output\n")
        subprocess.run(["git", "add", "committed.txt"], cwd=cwd, check=True)
        subprocess.run(
            ["git", "-c", "user.email=wf@example.invalid", "-c", "user.name=WF", "commit", "-m", "agent output"],
            cwd=cwd, check=True, capture_output=True,
        )
        return _result("done")

    engine = _engine(
        "committed-workspace", tmp_path / "run", budget_usd=1, adapter=adapter,
        workspace_repo=repo, workspace_base_branch="main",
    )
    value = await engine.agent("work", model="luna")
    assert (Path(value.workspace_path) / "committed.txt").read_text() == "committed output\n"
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout
    assert listed.count("worktree ") == 1
    branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert branches == ["main"]


@pytest.mark.asyncio
async def test_new_ignored_workspace_output_is_archived(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("*.log\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "ignore logs"], cwd=repo, check=True, capture_output=True)

    async def adapter(_prompt, *, cwd, **_kwargs):
        (Path(cwd) / "result.log").write_text("ignored but requested\n")
        return _result("done")

    engine = _engine(
        "ignored-output", tmp_path / "run", budget_usd=1, adapter=adapter,
        workspace_repo=repo, workspace_base_branch="main",
    )
    value = await engine.agent("work", model="luna")
    assert (Path(value.workspace_path) / "result.log").read_text() == "ignored but requested\n"


@pytest.mark.asyncio
async def test_workspace_setup_failure_is_retryable_not_paid_unknown(tmp_path, monkeypatch):
    import app.workspace as workspace

    repo = _git_repo(tmp_path / "repo")
    original = workspace.create_worktree
    with monkeypatch.context() as context:
        context.setattr(
            workspace, "create_worktree",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("disk full")),
        )
        first = _engine(
            "setup-retry", tmp_path / "run", budget_usd=1, adapter=lambda: None,
            workspace_repo=repo, workspace_base_branch="main",
        )
        with pytest.raises(RuntimeError, match="disk full"):
            await first.agent("work", model="luna")
    monkeypatch.setattr(workspace, "create_worktree", original)

    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        return _result("done")

    resumed = _engine(
        "setup-retry", tmp_path / "run", budget_usd=1, adapter=adapter,
        workspace_repo=repo, workspace_base_branch="main",
    )
    assert await resumed.agent("work", model="luna") is not None
    assert calls == ["work"]


@pytest.mark.asyncio
async def test_cancellation_during_worktree_create_discards_late_result(tmp_path, monkeypatch):
    import asyncio
    import threading
    import app.workspace as workspace

    repo = _git_repo(tmp_path / "repo")
    original = workspace.create_worktree
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def delayed_create(*args, **kwargs):
        started.set()
        assert release.wait(5)
        result = original(*args, **kwargs)
        finished.set()
        return result

    monkeypatch.setattr(workspace, "create_worktree", delayed_create)
    engine = _engine(
        "cancel-create", tmp_path / "run", budget_usd=1,
        adapter=lambda: None, workspace_repo=repo, workspace_base_branch="main",
    )
    task = asyncio.create_task(engine.agent("work", model="luna"))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(finished.wait, 5)
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout
    assert listed.count("worktree ") == 1
    assert subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines() == ["main"]


@pytest.mark.asyncio
async def test_cancellation_during_snapshot_still_resets_and_discards(tmp_path, monkeypatch):
    import asyncio
    import threading
    import scripts.wf_run as wf

    repo = _git_repo(tmp_path / "repo")
    original = wf._snapshot_worktree
    started = threading.Event()
    release = threading.Event()

    def delayed_snapshot(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    async def adapter(_prompt, *, cwd, **_kwargs):
        (Path(cwd) / "result.txt").write_text("result")
        return _result("done")

    monkeypatch.setattr(wf, "_snapshot_worktree", delayed_snapshot)
    engine = _engine(
        "cancel-snapshot", tmp_path / "run", budget_usd=1,
        adapter=adapter, workspace_repo=repo, workspace_base_branch="main",
    )
    task = asyncio.create_task(engine.agent("work", model="luna"))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout
    assert listed.count("worktree ") == 1
    assert subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines() == ["main"]


@pytest.mark.asyncio
async def test_parallel_calls_reserve_max_call_budget_before_dispatch(tmp_path):
    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        await __import__("asyncio").sleep(0)
        return _result(prompt)

    engine = _engine(
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
    engine = _engine("schema-case", tmp_path, budget_usd=2, adapter=adapter)
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

    engine = _engine("schema-recovers", tmp_path, budget_usd=2, adapter=adapter)
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

    engine = _engine("write-ahead", tmp_path, budget_usd=2, adapter=adapter)
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

    engine = _engine(
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
async def test_usage_is_persisted_for_full_and_restricted_capabilities(tmp_path):
    receipts = []

    async def adapter(prompt, **_kwargs):
        return _result(prompt)

    def usage_writer(**kwargs):
        receipts.append(kwargs)
        return True

    engine = _engine(
        "usage-capabilities", tmp_path, budget_usd=1,
        adapter=adapter, usage_writer=usage_writer,
    )
    await engine.agent("full", model="luna")
    await engine.agent(
        "restricted", model="luna", tools="read",
        capability_reason="read-only audit",
    )
    assert len(receipts) == 2
    assert all(row["result"].cost_usd == 0.01 for row in receipts)


@pytest.mark.asyncio
async def test_restricted_capabilities_require_an_inline_reason(tmp_path):
    engine = _engine("restriction-reason", tmp_path, budget_usd=1, adapter=lambda: None)
    with pytest.raises(ValueError, match="capability_reason"):
        await engine.agent("work", model="luna", tools="read")


@pytest.mark.asyncio
async def test_harness_read_capability_rejects_a_hallucinated_write(tmp_path, monkeypatch):
    from app.harness.llm import LLMEvent
    from app.harness.oneshot import run_oneshot

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    class FakeLLM:
        def __init__(self):
            self.round = 0
            self.saw_refusal = False

        async def stream(self, history, _schemas, **_kwargs):
            self.round += 1
            if self.round == 1:
                yield LLMEvent(
                    "tool_call_done",
                    tool_id="write-1",
                    tool_name="write",
                    arguments=json.dumps({"path": "forbidden.txt", "content": "bad"}),
                )
                yield LLMEvent("final", finish_reason="tool_calls", usage={})
                return
            self.saw_refusal = any(
                "[read-only]" in str(item.get("content")) for item in history
                if item.get("role") == "tool"
            )
            yield LLMEvent("text_delta", text="done")
            yield LLMEvent("final", finish_reason="stop", usage={})

        async def aclose(self):
            return None

    llm = FakeLLM()
    row = await run_oneshot(
        prompt="try to write",
        model="z-ai/glm-5.2:free",
        cwd=tmp_path,
        tools_level="read",
        network=True,
        mcp=False,
        system_prompt="",
        llm=llm,
    )
    assert row["ok"] is True
    assert llm.saw_refusal is True
    assert not (tmp_path / "forbidden.txt").exists()


@pytest.mark.asyncio
async def test_standalone_harness_default_is_not_writable(tmp_path, monkeypatch):
    from app.harness.llm import LLMEvent
    from app.harness.oneshot import run_oneshot

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    class FakeLLM:
        def __init__(self):
            self.round = 0

        async def stream(self, _history, _schemas, **_kwargs):
            self.round += 1
            if self.round == 1:
                yield LLMEvent(
                    "tool_call_done", tool_id="write-1", tool_name="write",
                    arguments=json.dumps({"path": "escaped.txt", "content": "bad"}),
                )
                yield LLMEvent("final", finish_reason="tool_calls", usage={})
                return
            yield LLMEvent("text_delta", text="done")
            yield LLMEvent("final", finish_reason="stop", usage={})

        async def aclose(self):
            return None

    row = await run_oneshot(
        prompt="write", model="z-ai/glm-5.2:free", cwd=tmp_path,
        network=True, mcp=False, system_prompt="", llm=FakeLLM(),
    )
    assert row["ok"] is True
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.asyncio
async def test_free_output_requires_a_verify_step_before_synthesis(tmp_path):
    calls = []

    async def adapter(prompt, model, **_kwargs):
        calls.append((prompt, model))
        runtime = "harness" if model.endswith(":free") else "codex"
        return _result('{"ok": true}', runtime=runtime, model=model)

    engine = _engine("free-gate", tmp_path, budget_usd=2, adapter=adapter)
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

    first = _engine("unknown-call", tmp_path, budget_usd=2, adapter=interrupted)
    with pytest.raises(RuntimeError, match="process loss"):
        await first.agent("work", model="luna")

    calls = []

    async def must_not_run(prompt, **_kwargs):
        calls.append(prompt)
        return _result("duplicate")

    resumed = _engine("unknown-call", tmp_path, budget_usd=2, adapter=must_not_run)
    assert await resumed.agent("work", model="luna") is None
    assert calls == []
    assert resumed.write_manifest()["partial_reason"] == "outcome_unknown"


@pytest.mark.asyncio
async def test_attempt_finished_without_completed_resumes_as_unknown(tmp_path):
    async def adapter(_prompt, **_kwargs):
        return _result("charged-result")

    first = _engine("finished-no-result", tmp_path, budget_usd=2, adapter=adapter)

    def lose_completion(*_args, **_kwargs):
        raise RuntimeError("crash before completed")

    first._finish = lose_completion
    with pytest.raises(RuntimeError, match="before completed"):
        await first.agent("work", model="luna")

    calls = []

    async def must_not_run(prompt, **_kwargs):
        calls.append(prompt)
        return _result("duplicate")

    resumed = _engine(
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
    first = _engine(
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

    resumed = _engine(
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

    first = _engine(
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

    resumed = _engine("unknown-spend", tmp_path, budget_usd=1, adapter=must_not_run)
    assert await resumed.agent("charged-call", model="luna") is None
    assert await resumed.agent("another-call", model="luna") is None
    assert resumed_calls == []
    assert resumed.budget.remaining_usd() == 0


@pytest.mark.asyncio
async def test_crash_after_final_schema_checkpoint_restores_schema_failure(tmp_path):
    async def invalid(_prompt, **_kwargs):
        return _result("not-json")

    schema = {"type": "object"}
    first = _engine("final-schema", tmp_path, budget_usd=2, adapter=invalid)

    def lose_completion(*_args, **_kwargs):
        raise RuntimeError("crash before schema completion")

    first._finish = lose_completion
    with pytest.raises(RuntimeError, match="schema completion"):
        await first.agent("work", model="luna", schema=schema)

    calls = []

    async def must_not_run(prompt, **_kwargs):
        calls.append(prompt)
        return _result('{"ok": true}')

    resumed = _engine("final-schema", tmp_path, budget_usd=2, adapter=must_not_run)
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

    first = _engine(
        "quota-resume", tmp_path, budget_usd=2, adapter=lambda *args, **kwargs: None,
        readiness_checker=blocked,
    )
    assert await first.agent("work", model="luna") is None

    calls = []

    async def adapter(prompt, **_kwargs):
        calls.append(prompt)
        return _result("done")

    resumed = _engine(
        "quota-resume", tmp_path, budget_usd=2, adapter=adapter,
        readiness_checker=available,
    )
    assert await resumed.agent("work", model="luna") is not None
    assert calls == ["work"]
    assert resumed.write_manifest()["complete"] is True


@pytest.mark.asyncio
async def test_historical_budget_skip_clears_after_larger_budget_resume(tmp_path):
    first = _engine("budget-resume", tmp_path, budget_usd=0, adapter=lambda *a, **k: None)
    assert await first.agent("work", model="luna") is None

    async def adapter(_prompt, **_kwargs):
        return _result("done")

    resumed = _engine("budget-resume", tmp_path, budget_usd=1, adapter=adapter)
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


@pytest.mark.asyncio
async def test_codex_capability_flags_make_full_network_the_default(tmp_path, monkeypatch):
    import scripts.wf_adapters as adapters

    calls = []
    raw = (FIXTURES / "codex-exec.jsonl").read_text()

    async def fake_process(argv, prompt, cwd, timeout, **kwargs):
        calls.append((argv, prompt, cwd, timeout, kwargs))
        return 0, raw, ""

    monkeypatch.setattr(adapters, "_run_process", fake_process)
    await adapters.run_codex(
        "work", model="gpt-5.6-luna", cwd=tmp_path, timeout=30,
        system_prompt="RULE", tools="all", network=True, mcp=True,
    )
    full = calls[-1][0]
    assert full[full.index("-s") + 1] == "danger-full-access"
    assert 'web_search="live"' in full
    assert "--ignore-user-config" not in full
    assert calls[-1][1].startswith("<workflow_rules>\nRULE")

    await adapters.run_codex(
        "work", model="gpt-5.6-luna", cwd=tmp_path, timeout=30,
        tools="read", network=False, mcp=False,
    )
    restricted = calls[-1][0]
    assert restricted[restricted.index("-s") + 1] == "read-only"
    assert 'web_search="disabled"' in restricted
    assert "--ignore-user-config" in restricted


@pytest.mark.asyncio
async def test_codex_mcp_uses_private_scope_config_not_global_home(tmp_path, monkeypatch):
    import scripts.wf_adapters as adapters

    cwd = tmp_path / "workspace"
    state = tmp_path / "state"
    cwd.mkdir()
    state.mkdir()
    (cwd / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"scope-only": {"command": "scope-mcp", "env": {"TOKEN": "secret"}}},
    }))
    captured = {}

    async def fake_process(argv, prompt, run_cwd, timeout, **kwargs):
        home = Path(kwargs["env"]["CODEX_HOME"])
        captured["home"] = home
        captured["config"] = (home / "config.toml").read_text()
        return 0, (FIXTURES / "codex-exec.jsonl").read_text(), ""

    monkeypatch.setattr(adapters, "_run_process", fake_process)
    await adapters.run_codex(
        "work", model="gpt-5.6-luna", cwd=cwd, state_dir=state,
        timeout=30, tools="all", network=True, mcp=True,
    )
    assert 'mcp_servers."scope-only"' in captured["config"]
    assert '"TOKEN" = "secret"' in captured["config"]
    assert not captured["home"].exists()


@pytest.mark.asyncio
async def test_claude_full_capability_loads_scoped_mcp_without_project_rules(tmp_path, monkeypatch):
    import scripts.wf_adapters as adapters

    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"local": {"command": "example-mcp", "args": ["--stdio"]}},
    }))
    captured = {}

    async def fake_process(argv, prompt, cwd, timeout, **_kwargs):
        captured["argv"] = argv
        config_path = Path(argv[argv.index("--mcp-config") + 1])
        captured["config"] = json.loads(config_path.read_text())
        return 0, (FIXTURES / "claude-print.json").read_text(), ""

    monkeypatch.setattr(adapters, "_run_process", fake_process)
    await adapters.run_claude(
        "work", model="claude-haiku-4-5", cwd=tmp_path, timeout=30,
        tools="all", network=True, mcp=True, system_prompt="RULE",
    )
    argv = captured["argv"]
    assert argv[argv.index("--tools") + 1] == "default"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--system-prompt") + 1] == "RULE"
    assert captured["config"]["mcpServers"]["local"]["command"] == "example-mcp"
    assert not (tmp_path / ".wf-mcp.json").exists()


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
    engine = _engine(
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
    engine = _engine(
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

    engine = _engine(
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
