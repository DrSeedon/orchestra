from pathlib import Path

import pytest


PROJECT_CONTEXT = """PROJECT CONTEXT (calibrate review severity):
- Scale: distributed platform team, production
- Users: high-load multi-project orchestration
- Stack: Python, FastAPI, SQLite, Codex app-server
- Philosophy: simple shared runtime with explicit contracts
- What matters: correctness, isolation, data integrity
- What does NOT matter: enterprise ceremony
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exec", "review"])
async def test_codex_review_uses_caller_context_and_declares_success_contract(
    tmp_path, monkeypatch, mode,
):
    import app.mcp_stdio as mcp

    captured = {}

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return {
                "policy": "worker-weekly-v1", "state": "available",
                "model": "gpt-5.6-sol",
                "provider": "codex", "provider_label": "Codex",
                "weekly_utilization": 1, "threshold": 95,
                "observed_at": 2_000_000_000,
                "valid_until": 2_000_000_300,
                "alternatives": [], "reason": "test",
            }
        if method == "GET":
            return {"cwd": str(tmp_path), "worktree_path": str(tmp_path), "scope": str(tmp_path)}
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

    assert "bg-test" in result
    assert "END YOUR TURN NOW" in result
    assert "required, not optional" in result
    assert "Orchestra will wake you" in result
    assert "do NOT poll" not in result
    assert "just wait" not in result
    config = captured["config"]
    output = str(tmp_path / "docs/review.md")
    assert config["success_file"] == output
    if mode == "exec":
        assert "Verdict" in config["success_pattern"]
    command = config["command"]
    assert f"-o {output}.round" in command
    assert "codex_review_artifact.py" in command
    assert '[ "$FINALIZE_RC" -eq 0 ] || exit "$FINALIZE_RC"' in command
    assert ("--require-verdict" in command) is (mode == "exec")
    assert command.index("rm -f") < command.index(" | tee ")
    assert "high-load multi-project orchestration" in command
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
@pytest.mark.parametrize("context", ["", "review this diff without authority"])
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
    assert "PROJECT CONTEXT" in tool.description
