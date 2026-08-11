import asyncio
import json
import os
import subprocess

import pytest


PROJECT_CONTEXT = """PROJECT CONTEXT:
- production Python service
- review must inspect the requested file
"""


def _fake_api(tmp_path, captured):
    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return {
                "policy": "worker-weekly-v1", "state": "available",
                "model": "gpt-5.6-sol", "provider": "codex",
                "provider_label": "Codex", "weekly_utilization": 1,
                "threshold": 95, "observed_at": 2_000_000_000,
                "valid_until": 2_000_000_300, "alternatives": [],
                "reason": "test",
            }
        if method == "GET":
            return {"cwd": str(tmp_path), "worktree_path": str(tmp_path)}
        captured.update(kwargs["json"])
        return {"id": "bg-test"}

    return fake_api


@pytest.mark.parametrize("mode", ["exec", "review"])
@pytest.mark.parametrize("resume", [False, True])
def test_codex_review_disables_unusable_namespace_sandbox(
    tmp_path, monkeypatch, mode, resume,
):
    import app.mcp_stdio as mcp

    if resume:
        (tmp_path / "codex_sessions.json").write_text(json.dumps({
            "sessions": {"review": {"uuid": "019f0000-0000-7000-8000-000000000001"}},
        }))
    captured = {}
    monkeypatch.setattr(mcp, "_api", _fake_api(tmp_path, captured))
    monkeypatch.setattr(mcp, "WORKER_NAME", "sandbox-test")
    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)

    asyncio.run(mcp.codex_review(
        context=PROJECT_CONTEXT, target="artifact.txt",
        output="review.md", mode=mode, resume=resume,
    ))

    command = captured["config"]["command"]
    assert "-s danger-full-access -a never exec" in command
    assert "workspace-write" not in command
    assert "--full-auto" not in command


def test_codex_review_rejects_blind_verdict_from_successful_process(tmp_path, monkeypatch):
    import app.mcp_stdio as mcp

    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text("""#!/bin/sh
out=
while [ \"$#\" -gt 0 ]; do
    if [ \"$1\" = \"-o\" ]; then
        shift
        out=$1
    fi
    shift
done
printf '%s\\n' '## Summary' 'Unable to review: bwrap: setting up uid map: Permission denied' '## Verdict' 'PASS' > \"$out\"
printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"blind-thread\"}'
exit 0
""")
    os.chmod(fake_codex, 0o755)

    captured = {}
    monkeypatch.setattr(mcp, "_api", _fake_api(tmp_path, captured))
    monkeypatch.setattr(mcp, "_codex_bin", lambda: str(fake_codex))
    monkeypatch.setattr(mcp, "WORKER_NAME", "sandbox-test")
    monkeypatch.setattr(mcp.time, "time", lambda: 2_000_000_001)

    asyncio.run(mcp.codex_review(
        context=PROJECT_CONTEXT, target="artifact.txt",
        output="review.md", mode="exec",
    ))
    result = subprocess.run(
        ["dash", "-c", captured["config"]["command"]],
        capture_output=True, text=True,
    )

    assert result.returncode == 70
    assert "could not execute workspace commands" in result.stderr
    assert not (tmp_path / "review.md").exists()
