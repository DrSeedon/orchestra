from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


LIVE_DIR = Path(__file__).resolve().parent
REPO_ROOT = LIVE_DIR.parents[3]
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
SCRATCH = Path(tempfile.gettempdir()) / f"v846-live-{RUN_ID}"
SCRATCH.mkdir(mode=0o700)
DB_PATH = SCRATCH / "session-logs.sqlite"
os.environ["ORCHESTRA_DB_PATH"] = str(DB_PATH)
os.environ["ORCHESTRA_TASK_REPOSITORY"] = str(SCRATCH / "tasks")
sys.path.insert(0, str(REPO_ROOT))

from app import db  # noqa: E402
from app.backend_claude import ClaudeBackend  # noqa: E402
from app.backend_codex import CodexBackend  # noqa: E402
from app.backend_grok import GrokBackend  # noqa: E402
from app.events import AgentEvent  # noqa: E402
from app.session import AgentSession  # noqa: E402


SYSTEM_PROMPT = (
    "This is a shell-policy integration check. When asked to run one command, use the "
    "shell tool exactly once with the exact command supplied. Do not edit, wrap, substitute, "
    "or retry it. After the tool result, report only whether it ran or was refused. "
    "Never claim a command ran unless the tool returned its result."
)

COMMAND_CASES = (
    ("sleep_10", "sleep 10", True),
    ("recursive_find", "find . -name '*.py' | head -3", True),
    ("short_sleep", "echo ok && sleep 1", False),
)
CODEX_EXTRA_CASES = (
    (
        "python_subprocess_sleep",
        "python -c 'import subprocess; subprocess.run([\"sleep\", \"6\"], check=True)'",
    ),
    ("script_sleep", "./x.sh"),
    (
        "orchestra_bg_jobs_subprocess_test",
        "cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-tool-guard && "
        "uv run --frozen python -m pytest "
        "tests/test_bg_jobs.py::TestPidfdProcessLifecycle::"
        "test_live_leader_and_child_are_terminated_but_unrelated_survives -q",
    ),
)


def _record(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        stream.flush()


def _session(runtime: str, model: str, cwd: Path) -> AgentSession:
    backend_type = "claude" if runtime.startswith("claude-") else runtime
    session = AgentSession(
        id=f"v846-{runtime}-{uuid.uuid4().hex[:12]}",
        name=f"v846-live-{RUN_ID}-{runtime}",
        scope="v846-live",
        cwd=str(cwd),
        model=model,
        system_prompt=SYSTEM_PROMPT,
        backend_type=backend_type,
    )
    db.save_session(session._to_db_dict())
    return session


async def _drain_log_writes(session: AgentSession) -> None:
    while session._log_futures:
        await asyncio.gather(*tuple(session._log_futures), return_exceptions=False)


async def _turn(
    backend,
    session: AgentSession,
    runtime: str,
    model: str,
    case: str,
    command: str,
    log_path: Path,
    timeout_seconds: float = 90,
    shell_command: bool = True,
) -> dict:
    if shell_command:
        prompt = (
            "Use the Bash/shell tool to execute exactly one command, once. Do not change, "
            "wrap, substitute, or retry it. The exact command is:\n\n"
            f"```sh\n{command}\n```\n\n"
            "After the tool response, report whether it ran or was refused."
        )
    else:
        prompt = command
    result = {"case": case, "command": command, "events": [], "turn_end": False}
    await backend.send(prompt)
    events = backend.events()
    try:
        async with asyncio.timeout(timeout_seconds):
            async for event in events:
                if event.type in {
                    "text", "tool_use", "tool_result", "policy_violation", "turn_end", "status",
                }:
                    record = {
                        "run_id": RUN_ID,
                        "runtime": runtime,
                        "model": model,
                        "case": case,
                        "event_type": event.type,
                        "content": event.content,
                        "metadata": event.metadata,
                    }
                    _record(log_path, record)
                    result["events"].append(record)
                if event.type in {"text", "tool_use", "tool_result", "policy_violation"}:
                    session._handle_event(event)
                if event.type == "turn_end":
                    result["turn_end"] = True
                    break
    finally:
        await events.aclose()
    await _drain_log_writes(session)
    result["log_rows"] = _session_log_rows(session.id)
    return result


def _session_log_rows(session_id: str) -> list[dict]:
    with db._conn() as connection:
        rows = connection.execute(
            "SELECT id, type, content, tool_name, tool_is_error "
            "FROM logs WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


async def _run_runtime(runtime: str, model: str) -> dict:
    cwd = SCRATCH / f"workspace-{runtime}"
    cwd.mkdir()
    (cwd / "fixture.py").write_text("value = 'v846 fixture'\n", encoding="utf-8")
    session = _session(runtime, model, cwd)

    if runtime.startswith("claude-"):
        backend = ClaudeBackend(
            model=model,
            cwd=str(cwd),
            system_prompt=SYSTEM_PROMPT,
            inherit_claude_md=False,
        )
    elif runtime == "codex":
        import app.backend_codex as backend_codex

        backend_codex._CODEX_HOME_ROOT = SCRATCH / "codex-home"
        backend = CodexBackend(
            model=model,
            cwd=str(cwd),
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"orchestra": {"env": {"ORCHESTRA_SESSION_ID": f"v846-{RUN_ID}"}}},
        )
        script = cwd / "x.sh"
        script.write_text("#!/bin/sh\nsleep 6\n", encoding="utf-8")
        script.chmod(0o700)
    elif runtime == "grok":
        import app.backend_grok as backend_grok

        backend_grok.GROK_HOME_DIR = SCRATCH / "grok-home"
        backend = GrokBackend(model=model, cwd=str(cwd), system_prompt=SYSTEM_PROMPT)
    else:
        raise ValueError(runtime)

    log_path = LIVE_DIR / f"{RUN_ID}-{runtime}.jsonl"
    summary = {
        "run_id": RUN_ID,
        "runtime": runtime,
        "model": model,
        "workspace": str(cwd),
        "session_id": session.id,
        "turns": [],
        "error": None,
    }
    try:
        async with asyncio.timeout(90):
            await backend.connect()
        if runtime == "codex" and os.environ.get("V846_TRACE_CODEX_PROCESS_TREE"):
            trace_path = LIVE_DIR / f"{RUN_ID}-codex-process-tree.txt"
            policy_bin = Path(backend._codex_home) / "policy-bin"
            config_path = Path(backend._codex_home) / "config.toml"
            backend._refresh_managed_config_sha256 = lambda: hashlib.sha256(
                config_path.read_bytes(),
            ).hexdigest()
            for wrapper in policy_bin.iterdir():
                original = wrapper.read_text(encoding="utf-8")
                parent_log = (
                    f"printf 'wrapper=%s parent=%s\\n' {wrapper.name!r} \"$PPID\" "
                    f">> {str(trace_path)!r}\n"
                    f"ps -o pid=,ppid=,comm=,args= -p \"$PPID\" >> {str(trace_path)!r}\n"
                    "grandparent=$(ps -o ppid= -p \"$PPID\" | tr -d ' ')\n"
                    f"ps -o pid=,ppid=,comm=,args= -p \"$grandparent\" >> {str(trace_path)!r}\n"
                )
                wrapper.write_text(
                    "#!/bin/sh\n" + parent_log + original.split("\n", 1)[1],
                    encoding="utf-8",
                )
            summary["process_tree_trace_path"] = str(trace_path)
        cases = COMMAND_CASES
        if runtime == "codex":
            cases += tuple((case, command, False) for case, command in CODEX_EXTRA_CASES)
        for case, command, _blocked in cases:
            summary["turns"].append(await _turn(
                backend, session, runtime, model, case, command, log_path,
            ))

        if runtime == "grok":
            (cwd / "probe.txt").write_text("grok-read-ok\n", encoding="utf-8")
            summary["turns"].append(await _turn(
                backend, session, runtime, model, "non_shell_read",
                "Use the built-in file-reading tool, not Bash or shell, to read `probe.txt`. "
                "Return its contents exactly and do not use any other tool.",
                log_path,
                shell_command=False,
            ))
            summary["turns"].append(await _turn(
                backend, session, runtime, model, "non_shell_write",
                "Use the built-in file-writing tool, not Bash or shell, to create "
                "`written.txt` containing exactly `grok-write-ok`. Do not use any other tool.",
                log_path,
                shell_command=False,
            ))
            written = cwd / "written.txt"
            summary["grok_written_file"] = (
                written.read_text(encoding="utf-8") if written.is_file() else None
            )
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        _record(log_path, {
            "run_id": RUN_ID,
            "runtime": runtime,
            "model": model,
            "event_type": "runner_error",
            "content": summary["error"],
        })
    finally:
        try:
            await backend.disconnect()
        except Exception as error:
            summary["disconnect_error"] = f"{type(error).__name__}: {error}"

    await _drain_log_writes(session)
    summary["session_logs"] = _session_log_rows(session.id)
    trace_path = summary.get("process_tree_trace_path")
    if trace_path and Path(trace_path).is_file():
        summary["process_tree_trace"] = Path(trace_path).read_text(encoding="utf-8")
    summary_path = LIVE_DIR / f"{RUN_ID}-{runtime}-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return summary


async def main() -> None:
    db.init_db()
    runtimes = (
        ("claude-haiku", "claude-haiku-5-5"),
        ("claude-sonnet", "claude-sonnet-5-5[1m]"),
        ("codex", "gpt-6-luna"),
        ("grok", "grok-4.6"),
    )
    selected = set(sys.argv[1:])
    if selected:
        runtimes = tuple(item for item in runtimes if item[0] in selected)
    summaries = []
    for runtime, model in runtimes:
        try:
            summaries.append(await _run_runtime(runtime, model))
        except Exception as error:
            summaries.append({
                "run_id": RUN_ID,
                "runtime": runtime,
                "model": model,
                "error": f"{type(error).__name__}: {error}",
            })
    (LIVE_DIR / f"{RUN_ID}-summary.json").write_text(
        json.dumps({"run_id": RUN_ID, "runtimes": summaries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_id": RUN_ID, "runtimes": summaries}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
