import asyncio
import json
import os
import subprocess

import pytest


PROJECT_CONTEXT = """PROJECT CONTEXT:
- production Python service
- review must inspect the requested file
"""
PROJECT_CONTEXT_FILE = """schema_version = 1
scale = "production test service"
users = "test harness only"
stack = "Python"
philosophy = "explicit contracts"
what_matters = "sandbox and command correctness"
what_does_not_matter = "deployment scale"
"""

# The model asked for is neither the server-owned default (gpt-5.6-luna) nor the model the
# readiness fixture reports: an assert naming either would stay green whether or not the
# caller's model actually reaches the Codex CLI.
REVIEW_MODEL = "gpt-5.6-terra"
READINESS_MODEL = "gpt-5.6-sol"


def _prepare_project_context(repo):
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "sandbox@test.invalid"], cwd=repo, check=True,
    )
    subprocess.run(["git", "config", "user.name", "Sandbox Test"], cwd=repo, check=True)
    owner = repo / ".orchestra/project-context.toml"
    owner.parent.mkdir()
    owner.write_text(PROJECT_CONTEXT_FILE, encoding="utf-8")
    subprocess.run(
        ["git", "add", ".orchestra/project-context.toml"], cwd=repo, check=True,
    )
    subprocess.run(["git", "commit", "-m", "test owner"], cwd=repo, check=True, capture_output=True)
    shown = subprocess.run(
        ["git", "show", "main:.orchestra/project-context.toml"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    assert shown == PROJECT_CONTEXT_FILE, "sandbox fixture did not establish its context owner"


def _fake_api(tmp_path, captured):
    _prepare_project_context(tmp_path)

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return {
                "policy": "worker-weekly-v1", "state": "available",
                "model": READINESS_MODEL, "provider": "codex",
                "provider_label": "Codex", "weekly_utilization": 1,
                "threshold": 95, "observed_at": 2_000_000_000,
                "valid_until": 2_000_000_300, "alternatives": [],
                "reason": "test",
            }
        if method == "GET":
            return {
                "id": "sandbox-requester", "cwd": str(tmp_path),
                "worktree_path": str(tmp_path),
            }
        captured.update(kwargs["json"])
        return {"id": "bg-test"}

    return fake_api


def _prepare_usage_db(tmp_path, monkeypatch):
    import app.db as db

    path = tmp_path / "usage.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    db.init_db()


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
        output="review.md", mode=mode, resume=resume, model=REVIEW_MODEL,
    ))

    command = captured["config"]["command"]
    # This file's subject is the sandbox flags; the model assert is only here to pin that
    # every CLI invocation the command builds (one fresh, or resume + stale-session
    # fallback) runs the model the caller asked for — not the default, not readiness's.
    invocations = 2 if resume else 1
    assert command.count("-m ") == invocations
    assert command.count(f"-m {REVIEW_MODEL}") == invocations
    assert READINESS_MODEL not in command
    assert "-s danger-full-access -a never exec" in command
    assert "workspace-write" not in command
    assert "--full-auto" not in command


def test_codex_review_rejects_blind_verdict_from_successful_process(tmp_path, monkeypatch):
    import app.mcp_stdio as mcp

    _prepare_usage_db(tmp_path, monkeypatch)
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
printf '%s\\n' '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":100,\"cached_input_tokens\":60,\"output_tokens\":20}}'
printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"Unable to review: bwrap: setting up uid map: Permission denied\"}}'
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
    review = (tmp_path / "review.md").read_text()
    assert "Unable to review: bwrap: setting up uid map: Permission denied" in review
    assert "Execution guard failed" in review


def test_codex_review_failure_check_skips_scalar_jsonl_rows(tmp_path):
    import app.mcp_stdio as mcp

    jsonl = tmp_path / "review.jsonl"
    jsonl.write_text(
        '[]\n'
        '{"type":"item.completed","item":{"type":"agent_message",'
        '"text":"Unable to review: bwrap: permission denied"}}\n'
    )

    result = subprocess.run([
        mcp.sys.executable, "-c", mcp._CODEX_EXECUTION_FAILURE_JSONL_CHECK,
        str(jsonl), mcp._CODEX_EXECUTION_FAILURE_PATTERN,
    ], capture_output=True, text=True)

    assert result.returncode == 0


def test_codex_review_ignores_failure_marker_in_command_output(tmp_path, monkeypatch):
    import app.mcp_stdio as mcp

    _prepare_usage_db(tmp_path, monkeypatch)
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
printf '%s\\n' '## Summary' 'Reviewed the requested file successfully.' '## Verdict' 'PASS' > \"$out\"
printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"evidence-thread\"}'
printf '%s\\n' '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":100,\"cached_input_tokens\":60,\"output_tokens\":20}}'
printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"command_execution\",\"aggregated_output\":\"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\"}}'
printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"Review completed with evidence.\"}}'
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

    assert result.returncode == 0
    assert "Reviewed the requested file successfully." in (tmp_path / "review.md").read_text()


def test_codex_review_quotes_exec_resume_uuid(tmp_path, monkeypatch):
    import app.mcp_stdio as mcp

    _prepare_usage_db(tmp_path, monkeypatch)
    injected = tmp_path / "injected"
    resume_uuid = f"thread$(touch {injected})"
    (tmp_path / "codex_sessions.json").write_text(json.dumps({
        "sessions": {"resume-review": {"uuid": resume_uuid}},
    }))
    args_file = tmp_path / "args.txt"
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(f"""#!/bin/sh
printf '%s\\n' "$@" > "{args_file}"
out=
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then
        shift
        out=$1
    fi
    shift
done
printf '%s\\n' '## Summary' 'Resume completed.' '## Verdict' 'PASS' > "$out"
printf '%s\\n' '{{"type":"thread.started","thread_id":"resumed-thread"}}'
printf '%s\\n' '{{"type":"turn.completed","usage":{{"input_tokens":100,"cached_input_tokens":60,"output_tokens":20}}}}'
printf '%s\\n' '{{"type":"item.completed","item":{{"type":"agent_message","text":"Resume completed."}}}}'
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
        output="resume-review.md", mode="exec", resume=True,
    ))
    result = subprocess.run(
        ["dash", "-c", captured["config"]["command"]],
        capture_output=True, text=True,
    )

    assert result.returncode == 0
    assert resume_uuid in args_file.read_text().splitlines()
    assert not injected.exists()


def test_installed_codex_rejects_multiple_review_targets(tmp_path):
    import app.mcp_stdio as mcp

    codex_bin = mcp._codex_bin()
    if not codex_bin:
        pytest.skip("Codex CLI is not installed; generated-command test remains mandatory")

    result = subprocess.run(
        [codex_bin, "exec", "review", "--uncommitted", "-"],
        cwd=tmp_path, input="", capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 2
    assert "--uncommitted" in result.stderr
    assert "cannot be used with '[PROMPT]'" in result.stderr
