import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


PROJECT_CONTEXT = """PROJECT CONTEXT (calibrate review severity):
- Scale: distributed platform team, production
- Users: high-load multi-project orchestration
- Stack: Python, FastAPI, SQLite, Codex app-server
- Philosophy: simple shared runtime with explicit contracts
- What matters: correctness, isolation, data integrity
- What does NOT matter: enterprise ceremony
"""

# Three deliberately different models. The reviewer model is chosen by the CALLER
# (or falls back to the server-owned default); the readiness endpoint reports a model
# of its own and must never decide it. Keeping READINESS_MODEL distinct from both the
# default and the explicit lane is what makes these assertions falsifiable.
DEFAULT_MODEL = "gpt-5.6-luna"
EXPLICIT_MODEL = "gpt-5.6-terra"
READINESS_MODEL = "gpt-5.6-sol"


def _review_text(result):
    if isinstance(result, str):
        return result
    return "\n".join(block.text for block in result.content if block.type == "text")


def readiness_response():
    return {
        "policy": "worker-weekly-v1", "state": "available",
        "model": READINESS_MODEL,
        "provider": "codex", "provider_label": "Codex",
        "weekly_utilization": 1, "threshold": 95,
        "observed_at": 2_000_000_000,
        "valid_until": 2_000_000_300,
        "alternatives": [], "reason": "test",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exec", "review"])
async def test_codex_review_uses_caller_context_and_declares_success_contract(
    tmp_path, monkeypatch, mode,
):
    import app.mcp_stdio as mcp

    captured = {}

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return readiness_response()
        if method == "GET":
            return {
                "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                "scope": str(tmp_path), "task_id": "215", "id": "requester-id",
            }
        captured.update(kwargs["json"])
        return {"id": "bg-test"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "sol-pilot")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)

    assert "END YOUR TURN NOW" in mcp.codex_review.__doc__
    result = await mcp.codex_review(
        context=PROJECT_CONTEXT,
        target="research.md", output="docs/review.md", mode=mode,
    )

    text = _review_text(result)
    assert "bg-test" in text
    assert "END YOUR TURN NOW" in text
    assert "required, not optional" in text
    assert "Orchestra will wake you" in text
    assert "do NOT poll" not in text
    assert "just wait" not in text
    config = captured["config"]
    assert "target_session_id" not in captured
    assert set(config) == {"command", "success_file", "success_pattern"}
    output = str(tmp_path / "docs/review.md")
    assert config["success_file"] == output
    if mode == "exec":
        assert "Verdict" in config["success_pattern"]
    command = config["command"]
    # Model omitted → server-owned default reaches the Codex CLI and the usage record,
    # and the model advertised by readiness does not leak into either.
    assert command.count(f"-m {DEFAULT_MODEL}") == 1
    assert f"--usage-model {DEFAULT_MODEL}" in command
    assert READINESS_MODEL not in command
    assert "--usage-session-id requester-id" in command
    assert "--usage-scope" in command
    assert "--usage-task-id 215" in command
    assert f"-o {output}.round" in command
    assert "codex_review_artifact.py" in command
    assert '[ "$FINALIZE_RC" -eq 0 ] || exit "$FINALIZE_RC"' in command
    assert ("--require-verdict" in command) is (mode == "exec")
    assert command.index("rm -f") < command.index(" | tee ")
    assert "PROJECT CONTEXT IS UNKNOWN" in command
    assert "high-load multi-project orchestration" not in command
    assert "small team" not in command and "MVP stage" not in command
    if mode == "review":
        assert "exec review" in command
        assert "--uncommitted" not in command
        assert "staged, unstaged, and untracked" in command
        assert "- < /tmp/codex_review_sol-pilot_review.txt" in command

    # Parse only; do not execute Codex.
    import subprocess
    parsed = subprocess.run(["dash", "-n", "-c", command], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [EXPLICIT_MODEL, "gpt5.6terra"])
async def test_codex_review_explicit_model_overrides_default_and_readiness(
    tmp_path, monkeypatch, requested,
):
    import app.mcp_stdio as mcp

    captured = {}
    readiness_params = []

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            readiness_params.append(kwargs.get("params"))
            return readiness_response()
        if method == "GET":
            return {
                "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                "scope": str(tmp_path), "task_id": "215", "id": "requester-id",
            }
        captured.update(kwargs["json"])
        return {"id": "bg-test"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "sol-pilot")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)

    result = await mcp.codex_review(
        context=PROJECT_CONTEXT, target="research.md", output="review.md",
        mode="exec", model=requested,
    )

    command = captured["config"]["command"]
    # The caller's model (alias resolved to its canonical id) wins over both the
    # server-owned default and the model advertised by readiness.
    assert command.count(f"-m {EXPLICIT_MODEL}") == 1
    assert f"--usage-model {EXPLICIT_MODEL}" in command
    assert DEFAULT_MODEL not in command
    assert READINESS_MODEL not in command
    assert EXPLICIT_MODEL in _review_text(result)
    # The quota gate is asked about the model that will actually run.
    assert readiness_params == [{"model": EXPLICIT_MODEL}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_kwargs, expected",
    [({}, DEFAULT_MODEL), ({"model": EXPLICIT_MODEL}, EXPLICIT_MODEL)],
)
async def test_codex_review_resume_command_passes_usage_arguments(
    tmp_path, monkeypatch, model_kwargs, expected,
):
    import app.mcp_stdio as mcp

    captured = {}
    output = tmp_path / "review.md"
    sessions = output.parent / "codex_sessions.json"
    sessions.write_text('{"sessions": {"review": {"uuid": "stored-uuid"}}}')

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return readiness_response()
        if method == "GET":
            return {
                "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                "scope": str(tmp_path), "task_id": "215", "id": "requester-id",
            }
        captured.update(kwargs["json"])
        return {"id": "bg-test"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "sol-pilot")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)

    await mcp.codex_review(
        context=PROJECT_CONTEXT, target="research.md", output="review.md",
        mode="exec", resume=True, **model_kwargs,
    )

    command = captured["config"]["command"]
    assert "exec resume stored-uuid" in command
    assert "--usage-event-id codex-review:" in command
    assert "--usage-session-id requester-id" in command
    # The resume path builds two CLI invocations (resume + stale-session fallback);
    # every one of them must run the selected model, not readiness's.
    cli_invocations = command.count("-m ")
    assert cli_invocations >= 1
    assert command.count(f"-m {expected}") == cli_invocations
    assert f"--usage-model {expected}" in command
    assert READINESS_MODEL not in command


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "",                        # empty
        "not-a-registered-model",  # unknown id
        "claude-opus-5[1m]",       # registered, but wrong runtime
        "gpt-5.3-codex-spark",     # Codex runtime, but forbidden as reviewer
    ],
)
async def test_codex_review_rejects_unusable_model_before_any_api_call(monkeypatch, model):
    import app.mcp_stdio as mcp

    calls = []

    async def fake_api(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("model validation must run before readiness or background-job calls")

    monkeypatch.setattr(mcp, "_api", fake_api)

    with pytest.raises(mcp.ApiToolError) as caught:
        await mcp.codex_review(
            context=PROJECT_CONTEXT, target="x", output="review.md",
            mode="exec", model=model,
        )

    # Refusal, never silent substitution of the default.
    assert caught.value.code == "invalid_argument"
    assert caught.value.details["field"] == "model"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["", "  "])
async def test_codex_review_rejects_missing_project_context_before_any_api_call(
    monkeypatch, context,
):
    import app.mcp_stdio as mcp

    calls = []

    async def fake_api(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("validation must run before readiness or background-job API calls")

    monkeypatch.setattr(mcp, "_api", fake_api)

    with pytest.raises(mcp.ApiToolError) as caught:
        await mcp.codex_review(context=context, target="x", output="review.md", mode="exec")

    assert caught.value.code == "invalid_argument"
    assert caught.value.details == {"field": "context"}
    assert calls == []


def test_compact_worker_description_is_runtime_specific():
    import app.mcp_stdio as mcp

    description = mcp.compact_worker.__doc__
    assert "Codex compacts natively in the same thread" in description
    assert "Claude creates a summary, reconnects fresh" in description
    assert ">80%" not in description


def test_codex_review_tool_schema_requires_project_context():
    import app.mcp_stdio as mcp

    tool = next(t for t in mcp.mcp._tool_manager.list_tools() if t.name == "codex_review")
    assert tool.parameters["required"] == ["context"]
    assert "Project calibration is loaded from the reviewed repo" in tool.description


@pytest.mark.asyncio
async def test_new_mcp_records_usage_through_unchanged_bg_route(tmp_path, monkeypatch):
    import app.bg_jobs as jobs
    import app.db as db
    import app.mcp_stdio as mcp
    import app.routes.bg as bg_route

    db_path = tmp_path / "usage.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text("""#!/bin/sh
out=
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then shift; out=$1; fi
    shift
done
printf '%s\n' '## Summary' 'Reviewed.' '## Verdict' 'APPROVED' > "$out"
printf '%s\n' '{"type":"thread.started","thread_id":"compat-thread"}'
printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":60,"cache_write_input_tokens":10,"output_tokens":20}}'
""")
    os.chmod(fake_codex, 0o755)

    class Session:
        id = "immutable-requester-id"

    monkeypatch.setattr(bg_route.manager, "get_by_name", lambda *_args: Session())
    monkeypatch.setattr(jobs.bg_manager, "_trigger", AsyncMock())
    created = {}

    async def api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return readiness_response()
        if method == "GET":
            return {
                "id": Session.id, "cwd": str(tmp_path),
                "worktree_path": str(tmp_path), "task_id": "215",
            }
        request = bg_route.BgJobCreateRequest(**kwargs["json"])
        created.update(kwargs["json"])
        result = await bg_route.bg_job_create(request)
        created["job_id"] = result["id"]
        return result

    monkeypatch.setattr(mcp, "_api", api)
    monkeypatch.setattr(mcp, "_codex_bin", lambda: str(fake_codex))
    monkeypatch.setattr(mcp, "WORKER_NAME", "requester")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)

    result = await mcp.codex_review(
        context=PROJECT_CONTEXT, target="artifact.py",
        output="review.md", mode="exec", model=EXPLICIT_MODEL,
    )
    await jobs.bg_manager._tasks[created["job_id"]]

    assert "started" in _review_text(result)
    assert "target_session_id" not in created
    assert set(created["config"]) == {"command", "success_file", "success_pattern"}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM turn_usage").fetchone())
    assert row["session_id"] == Session.id
    assert row["runtime"] == "codex"
    # Accounting records the model the caller selected — not the default, not readiness's.
    assert row["model"] == EXPLICIT_MODEL
    assert row["input_tokens"] > 0
    assert row["output_tokens"] > 0


@pytest.mark.asyncio
async def test_t1_385_codex_review_success_returns_exact_deferred_control_provenance(
    tmp_path, monkeypatch,
):
    """RED #385 R1: only a successfully created job may arm app-server control."""
    import app.mcp_stdio as mcp

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return readiness_response()
        if method == "GET":
            return {
                "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                "scope": str(tmp_path), "task_id": "385", "id": "requester-id",
            }
        return {"id": "bg-review-385"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "review-requester")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))

    result = await mcp.codex_review(
        context=PROJECT_CONTEXT,
        target=".orchestra/tasks/385/plan.md",
        output=".orchestra/tasks/385/codex-review-plan.md",
        mode="exec",
    )

    assert not isinstance(result, str), (
        "successful codex_review still returns flattened prose instead of a structured result"
    )
    assert result.isError is False
    text = "\n".join(block.text for block in result.content if block.type == "text")
    assert "bg-review-385" in text
    assert "END YOUR TURN NOW" in text
    assert result.structuredContent == {
        "result": {
            "kind": "deferred_job",
            "origin": "orchestra.bg_jobs",
            "job_id": "bg-review-385",
            "event_id": "bgjob:v1:bg-review-385:completed",
            "turn_control": "interrupt",
        },
        "error": None,
    }


@pytest.mark.asyncio
async def test_t1_385_codex_review_creation_failure_has_no_deferred_control(
    tmp_path, monkeypatch,
):
    """#385 negative control: a heading/error string never arms deferred control."""
    import app.mcp_stdio as mcp

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return readiness_response()
        if method == "GET":
            return {
                "cwd": str(tmp_path), "worktree_path": str(tmp_path),
                "scope": str(tmp_path), "task_id": "385", "id": "requester-id",
            }
        return {"error": "job creation refused"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "review-requester")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))

    result = await mcp.codex_review(
        context=PROJECT_CONTEXT,
        target=".orchestra/tasks/385/plan.md",
        output=".orchestra/tasks/385/codex-review-plan.md",
        mode="exec",
    )

    structured = getattr(result, "structuredContent", None)
    assert "turn_control" not in str(structured)
    assert "bgjob:v1:" not in str(structured)
