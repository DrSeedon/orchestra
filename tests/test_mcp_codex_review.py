from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_codex_review_uses_temp_artifact_and_declares_success_contract(tmp_path, monkeypatch):
    import app.mcp_stdio as mcp

    captured = {}

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return {
                "policy": "worker-weekly-v1", "state": "available",
                "provider": "codex", "provider_label": "Codex",
                "weekly_utilization": 1, "threshold": 95,
                "alternatives": [], "reason": "test",
            }
        if method == "GET":
            return {"cwd": str(tmp_path), "worktree_path": str(tmp_path), "scope": str(tmp_path)}
        captured.update(kwargs["json"])
        return {"id": "bg-test"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "sol-pilot")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))

    assert "END YOUR TURN NOW" in mcp.codex_review.__doc__
    result = await mcp.codex_review(
        target="research.md", output="docs/review.md", mode="exec",
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
    assert "Verdict" in config["success_pattern"]
    command = config["command"]
    assert f"-o {output}.round" in command
    assert "codex_review_artifact.py" in command
    assert "--require-verdict" in command
    assert command.index("rm -f") < command.index(" | tee ")

    # Parse only; do not execute Codex.
    import subprocess
    parsed = subprocess.run(["dash", "-n", "-c", command], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
