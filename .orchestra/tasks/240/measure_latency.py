#!/usr/bin/env python3
"""#240: bounded, isolated Codex CLI/app-server latency measurements.

The benchmark never writes the user's Codex config. Every arm gets a private CODEX_HOME on
real disk; only auth.json is symlinked read-only in practice. Raw output contains hashes and
timings, not config contents, tokens, or environment values.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import statistics
import sys
import time
import tomllib
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path("/mnt/data/Projects/Python/orchestra/data/bench-240")
CODEX = shutil.which("codex") or "codex"
MODEL = "gpt-5.6-sol"
EFFORT = "xhigh"
TIER = "default"
TASK = "Reply with exactly PONG and nothing else. Do not call tools."
TIMEOUT = 180

sys.path.insert(0, str(ROOT))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def proxy_route() -> str:
    raw = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "direct"
    if raw == "direct":
        return raw
    parsed = urlsplit(raw)
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


def loadavg() -> list[float]:
    return [round(x, 2) for x in os.getloadavg()]


def base_row(arm: str, rep: int, config_hash: str, argv: list[str]) -> dict:
    return {
        "arm": arm,
        "rep": rep,
        "ts": time.time(),
        "argv": argv,
        "argv_sha256": sha(json.dumps(argv, separators=(",", ":")).encode()),
        "config_sha256": config_hash,
        "cli_version": cli_version(),
        "model": MODEL,
        "effort": EFFORT,
        "tier": TIER,
        "input_bytes": len(TASK.encode()),
        "proxy_route": proxy_route(),
        "loadavg": loadavg(),
    }


_CLI_VERSION: str | None = None


def cli_version() -> str:
    global _CLI_VERSION
    if _CLI_VERSION is None:
        import subprocess

        _CLI_VERSION = subprocess.check_output([CODEX, "--version"], text=True).strip()
    return _CLI_VERSION


def copy_state(destination: Path) -> None:
    source = Path.home() / ".codex" / "state_5.sqlite"
    if not source.exists():
        return
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        src.execute("PRAGMA query_only=ON")
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
    os.chmod(destination, 0o600)


def make_home(label: str, *, project_doc_bytes: int = 262144, healthy_state: bool = True) -> Path:
    home = DATA_ROOT / f"{label}-{uuid.uuid4().hex[:10]}"
    home.mkdir(parents=True, mode=0o700)
    auth = Path.home() / ".codex" / "auth.json"
    if auth.exists():
        (home / "auth.json").symlink_to(auth)
    (home / "sessions").mkdir()
    config = "\n".join(
        [
            f'model = "{MODEL}"',
            f'model_reasoning_effort = "{EFFORT}"',
            f'service_tier = "{TIER}"',
            f"project_doc_max_bytes = {project_doc_bytes}",
            "model_context_window = 872000",
            "model_auto_compact_token_limit = 784800",
            "",
            f'[projects.{json.dumps(str(ROOT))}]',
            'trust_level = "trusted"',
            "",
        ]
    )
    (home / "config.toml").write_text(config)
    os.chmod(home / "config.toml", 0o600)
    if healthy_state:
        copy_state(home / "state_5.sqlite")
    return home


def config_hash(home: Path) -> str:
    return sha((home / "config.toml").read_bytes())


class Rpc:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc
        self.seq = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.notifications: asyncio.Queue[tuple[float, dict]] = asyncio.Queue()
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        assert self.proc.stdout and self.proc.stdin
        while raw := await self.proc.stdout.readline():
            now = time.perf_counter()
            msg = json.loads(raw)
            rid = msg.get("id")
            if rid is not None and msg.get("method"):
                self.proc.stdin.write(
                    (json.dumps({"id": rid, "error": {"code": -32601, "message": "benchmark client"}}) + "\n").encode()
                )
                await self.proc.stdin.drain()
            elif rid is not None:
                fut = self.pending.get(rid)
                if fut and not fut.done():
                    fut.set_result((now, msg))
            elif msg.get("method"):
                await self.notifications.put((now, msg))

    async def request(self, method: str, params: dict) -> tuple[float, dict]:
        assert self.proc.stdin
        self.seq += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.seq] = fut
        self.proc.stdin.write((json.dumps({"method": method, "id": self.seq, "params": params}) + "\n").encode())
        await self.proc.stdin.drain()
        try:
            return await fut
        finally:
            self.pending.pop(self.seq, None)

    async def notify(self, method: str, params: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write((json.dumps({"method": method, "params": params}) + "\n").encode())
        await self.proc.stdin.drain()

    async def close(self) -> str:
        if self.proc.returncode is None:
            self.proc.terminate()
        try:
            await asyncio.wait_for(self.proc.wait(), 10)
        except TimeoutError:
            self.proc.kill()
            await self.proc.wait()
        self.reader.cancel()
        stderr = b""
        if self.proc.stderr:
            stderr = await self.proc.stderr.read()
        return stderr.decode(errors="replace")[-2000:]


def model_event(msg: dict) -> bool:
    method = msg.get("method", "")
    if method.startswith("item/reasoning/") or method == "item/agentMessage/delta":
        return True
    if method == "item/started":
        return ((msg.get("params") or {}).get("item") or {}).get("type") in {"reasoning", "agentMessage"}
    return False


def usage_from_notification(msg: dict) -> dict:
    usage = ((msg.get("params") or {}).get("tokenUsage") or {})
    last = usage.get("last") or {}
    return {
        "input_tokens": last.get("inputTokens"),
        "cached_tokens": last.get("cachedInputTokens"),
        "output_tokens": last.get("outputTokens"),
        "reasoning_tokens": last.get("reasoningOutputTokens"),
        "context_window": usage.get("modelContextWindow"),
    }


async def start_rpc(home: Path, extra_args: list[str] | None = None) -> tuple[Rpc, list[str], float]:
    argv = [CODEX, *(extra_args or []), "app-server", "--stdio"]
    env = dict(os.environ)
    env["CODEX_HOME"] = str(home)
    t0 = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=ROOT,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=16 * 1024 * 1024,
    )
    return Rpc(proc), argv, t0


async def raw_appserver(arm: str, rep: int, home: Path, *, turn: bool = True) -> dict:
    rpc, argv, process_start = await start_rpc(home)
    row = base_row(arm, rep, config_hash(home), argv)
    try:
        init_sent = time.perf_counter()
        init_at, init = await asyncio.wait_for(
            rpc.request("initialize", {"clientInfo": {"name": "bench240", "title": "bench240", "version": "1"}}),
            TIMEOUT,
        )
        await rpc.notify("initialized", {})
        start_at, started = await asyncio.wait_for(
            rpc.request(
                "thread/start",
                {"cwd": str(ROOT), "model": MODEL, "approvalPolicy": "never", "sandbox": "danger-full-access"},
            ),
            TIMEOUT,
        )
        thread_id = ((started.get("result") or {}).get("thread") or {}).get("id")
        row.update(
            {
                "process_to_init_seconds": round(init_at - process_start, 6),
                "initialize_rpc_seconds": round(init_at - init_sent, 6),
                "thread_start_seconds": round(start_at - init_at, 6),
                "connect_init_seconds": round(start_at - process_start, 6),
            }
        )
        if not turn:
            row.update({"outcome": "no_model_ok", "final_wall_seconds": None})
            return row
        turn_zero = time.perf_counter()
        ack_at, turn_result = await asyncio.wait_for(
            rpc.request(
                "turn/start",
                {"threadId": thread_id, "input": [{"type": "text", "text": TASK}], "model": MODEL, "effort": EFFORT},
            ),
            TIMEOUT,
        )
        turn_id = ((turn_result.get("result") or {}).get("turn") or {}).get("id")
        first_model = None
        usage = {}
        tool_rounds = 0
        answer = ""
        outcome = "timeout"
        while True:
            event_at, msg = await asyncio.wait_for(rpc.notifications.get(), TIMEOUT)
            method = msg.get("method", "")
            if first_model is None and model_event(msg):
                first_model = event_at
            if method == "item/started":
                typ = (((msg.get("params") or {}).get("item") or {}).get("type"))
                if typ in {"commandExecution", "mcpToolCall", "fileChange"}:
                    tool_rounds += 1
            if method == "item/completed":
                item = ((msg.get("params") or {}).get("item") or {})
                if item.get("type") == "agentMessage":
                    answer = item.get("text") or answer
            if method == "thread/tokenUsage/updated":
                usage = usage_from_notification(msg)
            if method == "turn/completed":
                got = ((msg.get("params") or {}).get("turn") or {})
                if got.get("id") == turn_id:
                    outcome = got.get("status", "unknown")
                    final_at = event_at
                    break
        row.update(
            {
                "turn_start_ack_seconds": round(ack_at - turn_zero, 6),
                "ttft_seconds": round((first_model or final_at) - turn_zero, 6),
                "final_answer_wall_seconds": round(final_at - turn_zero, 6),
                "tool_round_count": tool_rounds,
                "answer": answer,
                "outcome": outcome,
                **usage,
            }
        )
        return row
    except Exception as exc:
        row.update({"outcome": "error", "error": f"{type(exc).__name__}: {exc}"})
        return row
    finally:
        row["stderr_tail"] = await rpc.close()


async def exec_arm(rep: int, home: Path) -> dict:
    argv = [
        CODEX,
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        str(ROOT),
        "-s",
        "danger-full-access",
        "-m",
        MODEL,
        "-c",
        f'model_reasoning_effort="{EFFORT}"',
        "-c",
        f'service_tier="{TIER}"',
        TASK,
    ]
    row = base_row("A_exec", rep, config_hash(home), argv)
    env = dict(os.environ)
    env["CODEX_HOME"] = str(home)
    t0 = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    first_model = None
    turn_ack = None
    tool_rounds = 0
    usage = {}
    events = []
    final_event = None
    answer = ""
    try:
        assert proc.stdout
        while raw := await asyncio.wait_for(proc.stdout.readline(), TIMEOUT):
            now = time.perf_counter()
            msg = json.loads(raw)
            typ = msg.get("type", "")
            events.append(typ)
            if turn_ack is None and typ in {"turn.started", "turn_started"}:
                turn_ack = now
            if first_model is None and typ not in {"thread.started", "turn.started", "turn_started"}:
                first_model = now
            if "tool" in typ or typ in {"command.started", "command_execution"}:
                tool_rounds += 1
            if "usage" in msg and isinstance(msg["usage"], dict):
                usage = msg["usage"]
            if typ == "item.completed":
                item = msg.get("item") or {}
                if item.get("type") in {"agent_message", "agentMessage"}:
                    answer = item.get("text") or answer
            if typ == "turn.completed":
                final_event = now
        rc = await asyncio.wait_for(proc.wait(), 10)
        process_exit = time.perf_counter()
        final = final_event or process_exit
        stderr = (await proc.stderr.read()).decode(errors="replace")[-2000:] if proc.stderr else ""
        row.update(
            {
                "connect_init_seconds": None,
                "turn_start_ack_seconds": round((turn_ack or first_model or final) - t0, 6),
                "ttft_seconds": round((first_model or final) - t0, 6),
                "final_answer_wall_seconds": round(final - t0, 6),
                "tool_round_count": tool_rounds,
                "input_tokens": usage.get("input_tokens"),
                "cached_tokens": usage.get("cached_input_tokens") or usage.get("cached_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "reasoning_tokens": usage.get("reasoning_output_tokens") or usage.get("reasoning_tokens"),
                "event_types": events,
                "answer": answer,
                "process_exit_wall_seconds": round(process_exit - t0, 6),
                "outcome": "completed" if rc == 0 else f"exit_{rc}",
                "stderr_tail": stderr,
            }
        )
    except Exception as exc:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        row.update({"outcome": "error", "error": f"{type(exc).__name__}: {exc}"})
    return row


def current_mcp_config(unique: str) -> dict:
    source = os.environ.get("BENCH_MCP_CONFIG_SOURCE")
    if source:
        current = Path(source)
    else:
        current = Path(os.environ["CODEX_HOME"]) / "config.toml"
    cfg = tomllib.loads(current.read_text())
    server = copy.deepcopy((cfg.get("mcp_servers") or {}).get("orchestra") or {})
    env = server.setdefault("env", {})
    env["ORCHESTRA_SESSION_ID"] = unique
    env["WORKER_NAME"] = f"bench240-{unique[-8:]}"
    return {"orchestra": server}


async def backend_arm(
    arm: str,
    rep: int,
    home: Path,
    managed_root: Path,
    *,
    system_prompt: str,
    with_mcp: bool,
    resume_thread_id: str | None = None,
) -> tuple[dict, str | None]:
    import app.backend_codex as bc

    bc._CODEX_HOME_ROOT = managed_root
    bc._base_codex_home = lambda: home

    async def no_scope():
        return False, {}, "#240 matched direct production launch"

    bc._codex_scope_support = no_scope
    unique = f"bench240-{arm.lower().replace('_', '-')}-{rep}-{uuid.uuid4().hex[:8]}"
    servers = current_mcp_config(unique) if with_mcp else {}
    backend = bc.CodexBackend(
        model=MODEL,
        cwd=str(ROOT),
        system_prompt=system_prompt,
        resume_thread_id=resume_thread_id,
        mcp_servers=servers,
        mcp_env={k: str(v) for cfg in servers.values() for k, v in (cfg.get("env") or {}).items()},
        reasoning_effort=EFFORT,
    )
    argv = backend._codex_command()
    row = base_row(arm, rep, "pending", argv)
    row.update(
        {
            "system_prompt_bytes": len(system_prompt.encode()),
            "project_doc_bytes": (ROOT / "AGENTS.md").stat().st_size if "project_doc_max_bytes = 0" not in (home / "config.toml").read_text() else 0,
            "mcp_schema_bytes": mcp_schema_bytes() if with_mcp else 0,
            "history_mode": "resumed" if resume_thread_id else "fresh",
        }
    )
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(backend.connect(), TIMEOUT)
        connected = time.perf_counter()
        actual_home = backend._codex_home or home
        row["config_sha256"] = config_hash(actual_home)
        send_at = time.perf_counter()
        await asyncio.wait_for(backend.send(TASK), TIMEOUT)
        ack_at = time.perf_counter()
        first_model = None
        tool_rounds = 0
        answer = ""
        end = None
        async for event in backend.events():
            now = time.perf_counter()
            if first_model is None and event.type in {"thinking_stream", "thinking", "stream", "text", "tool_use"}:
                first_model = now
            if event.type == "tool_use":
                tool_rounds += 1
            if event.type == "text":
                answer = event.content
            if event.type == "turn_end":
                end = event
                final_at = now
        if end is None:
            raise RuntimeError("backend emitted no turn_end")
        md = end.metadata
        row.update(
            {
                "connect_init_seconds": round(connected - t0, 6),
                "turn_start_ack_seconds": round(ack_at - send_at, 6),
                "ttft_seconds": round((first_model or final_at) - send_at, 6),
                "final_answer_wall_seconds": round(final_at - send_at, 6),
                "tool_round_count": tool_rounds,
                "input_tokens": md.get("input_tokens"),
                "cached_tokens": md.get("cached_input_tokens"),
                "output_tokens": md.get("output_tokens"),
                "reasoning_tokens": None,
                "context_tokens": md.get("context_tokens"),
                "context_window": md.get("max_tokens"),
                "answer": answer,
                "outcome": "completed" if md.get("ok") else md.get("stop_reason"),
            }
        )
        return row, backend.session_id
    except Exception as exc:
        row.update({"outcome": "error", "error": f"{type(exc).__name__}: {exc}"})
        return row, backend.session_id
    finally:
        await backend.disconnect()


_MCP_SCHEMA_BYTES: int | None = None


def mcp_schema_bytes() -> int:
    global _MCP_SCHEMA_BYTES
    if _MCP_SCHEMA_BYTES is None:
        from app.mcp_stdio import mcp

        total = 0
        for tool in mcp._tool_manager.list_tools():
            data = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.parameters,
                "outputSchema": tool.output_schema,
            }
            total += len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
        _MCP_SCHEMA_BYTES = total
    return _MCP_SCHEMA_BYTES


async def local_transport_control() -> dict:
    fake = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " m=json.loads(line); print(json.dumps({'id':m.get('id'),'result':m.get('params',{})}),flush=True)\n"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        fake,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    rpc = Rpc(proc)
    samples = []
    try:
        for i in range(200):
            t0 = time.perf_counter()
            await rpc.request("echo", {"i": i, "payload": "x" * 128})
            samples.append((time.perf_counter() - t0) * 1000)
    finally:
        await rpc.close()
    return {
        "arm": "L_local_jsonrpc",
        "samples": len(samples),
        "median_ms": round(statistics.median(samples), 6),
        "p95_ms": round(sorted(samples)[int(len(samples) * 0.95) - 1], 6),
        "max_ms": round(max(samples), 6),
        "loadavg": loadavg(),
    }


async def run(output: Path) -> None:
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = [await local_transport_control()]
    full_prompt = build_system_prompt(DEFAULT_PIPELINE, "full-cycle")

    # Interleave protocol arms; each gets a private, already-healthy state DB.
    for rep in (1, 2):
        for arm in ("A", "B", "C", "D"):
            home = make_home(f"{arm.lower()}{rep}")
            managed = home.parent / f"managed-{home.name}"
            managed.mkdir(mode=0o700)
            if arm == "A":
                row = await exec_arm(rep, home)
            elif arm == "B":
                row = await raw_appserver("B_appserver", rep, home)
                row.update({"system_prompt_bytes": 0, "project_doc_bytes": (ROOT / "AGENTS.md").stat().st_size, "mcp_schema_bytes": 0, "history_mode": "fresh"})
            elif arm == "C":
                row, _ = await backend_arm("C_wrapper", rep, home, managed, system_prompt="", with_mcp=False)
            else:
                row, thread = await backend_arm("D_managed_full", rep, home, managed, system_prompt=full_prompt, with_mcp=True)
                rows.append(row)
                # E resumes the exact persisted D thread through a fresh app-server process.
                e, _ = await backend_arm("E_warm_resume", rep, home, managed, system_prompt=full_prompt, with_mcp=True, resume_thread_id=thread)
                rows.append(e)
                continue
            rows.append(row)

    # Safe one-factor-at-a-time removals relative to D, one bounded run each.
    factors = [
        ("F_no_role_prompt", "", True, 262144),
        ("F_no_project_doc", full_prompt, True, 0),
        ("F_no_mcp", full_prompt, False, 262144),
    ]
    for idx, (arm, prompt, with_mcp, project_doc_bytes) in enumerate(factors, 1):
        home = make_home(f"factor{idx}", project_doc_bytes=project_doc_bytes)
        managed = home.parent / f"managed-{home.name}"
        managed.mkdir(mode=0o700)
        row, _ = await backend_arm(arm, 1, home, managed, system_prompt=prompt, with_mcp=with_mcp)
        rows.append(row)

    # Separate one-time state creation from per-turn costs; no model request is sent.
    cold = make_home("cold-migration", healthy_state=False)
    cold_row = await raw_appserver("N_cold_connect_no_model", 1, cold, turn=False)
    cold_row.update({"system_prompt_bytes": 0, "project_doc_bytes": (ROOT / "AGENTS.md").stat().st_size, "mcp_schema_bytes": 0, "history_mode": "none"})
    rows.append(cold_row)

    with output.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "rows": len(rows)}, ensure_ascii=False))


async def run_backend_subset(output: Path) -> None:
    """Repeat only C/D/E/F after instrumentation changes, preserving the first raw run."""
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    full_prompt = build_system_prompt(DEFAULT_PIPELINE, "full-cycle")
    rows = []
    for arm in ("C", "D"):
        home = make_home(f"rerun-{arm.lower()}")
        managed = home.parent / f"managed-{home.name}"
        managed.mkdir(mode=0o700)
        if arm == "C":
            row, _ = await backend_arm("C_wrapper", 3, home, managed, system_prompt="", with_mcp=False)
            rows.append(row)
        else:
            row, thread = await backend_arm("D_managed_full", 3, home, managed, system_prompt=full_prompt, with_mcp=True)
            rows.append(row)
            warm, _ = await backend_arm("E_warm_resume", 3, home, managed, system_prompt=full_prompt, with_mcp=True, resume_thread_id=thread)
            rows.append(warm)
    factors = [
        ("F_no_role_prompt", "", True, 262144),
        ("F_no_project_doc", full_prompt, True, 0),
        ("F_no_mcp", full_prompt, False, 262144),
    ]
    for idx, (arm, prompt, with_mcp, project_doc_bytes) in enumerate(factors, 1):
        home = make_home(f"rerun-factor{idx}", project_doc_bytes=project_doc_bytes)
        managed = home.parent / f"managed-{home.name}"
        managed.mkdir(mode=0o700)
        row, _ = await backend_arm(arm, 2, home, managed, system_prompt=prompt, with_mcp=with_mcp)
        rows.append(row)
    with output.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "rows": len(rows)}, ensure_ascii=False))


async def run_reload_control(output: Path) -> None:
    """Measure managed config digest no-op and reconnect without sending a model turn."""
    import app.backend_codex as bc

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rep in (1, 2):
        home = make_home(f"reload-{rep}")
        managed_root = home.parent / f"managed-{home.name}"
        managed_root.mkdir(mode=0o700)
        bc._CODEX_HOME_ROOT = managed_root
        bc._base_codex_home = lambda: home

        async def no_scope():
            return False, {}, "#240 matched direct production launch"

        bc._codex_scope_support = no_scope
        unique = f"bench240-reload-{rep}-{uuid.uuid4().hex[:8]}"
        servers = current_mcp_config(unique)
        backend = bc.CodexBackend(
            model=MODEL,
            cwd=str(ROOT),
            system_prompt="",
            mcp_servers=servers,
            mcp_env={k: str(v) for cfg in servers.values() for k, v in (cfg.get("env") or {}).items()},
            reasoning_effort=EFFORT,
        )
        try:
            start = time.perf_counter()
            await asyncio.wait_for(backend.connect(), TIMEOUT)
            connected = time.perf_counter()
            # A just-started thread has no rollout file and cannot be resumed. One bounded
            # PONG turn creates the persisted state required by the real reconnect path.
            warmup_start = time.perf_counter()
            await asyncio.wait_for(backend.send(TASK), TIMEOUT)
            async for event in backend.events():
                if event.type == "turn_end":
                    break
            warmup_end = time.perf_counter()
            noop_start = time.perf_counter()
            await backend._reload_stale_managed_config_before_turn()
            noop_end = time.perf_counter()
            config = home / "config.toml"
            text = config.read_text().replace(
                "project_doc_max_bytes = 262144", "project_doc_max_bytes = 262143"
            )
            config.write_text(text)
            reload_start = time.perf_counter()
            await asyncio.wait_for(backend._reload_stale_managed_config_before_turn(), TIMEOUT)
            reload_end = time.perf_counter()
            rows.append(
                {
                    "arm": "R_config_digest_reconnect_no_model",
                    "rep": rep,
                    "loadavg": loadavg(),
                    "cli_version": cli_version(),
                    "model": MODEL,
                    "effort": EFFORT,
                    "tier": TIER,
                    "proxy_route": proxy_route(),
                    "initial_connect_seconds": round(connected - start, 6),
                    "persisted_thread_warmup_seconds": round(warmup_end - warmup_start, 6),
                    "unchanged_digest_check_seconds": round(noop_end - noop_start, 6),
                    "changed_digest_reconnect_seconds": round(reload_end - reload_start, 6),
                    "outcome": "no_model_ok",
                }
            )
        finally:
            await backend.disconnect()
    with output.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "rows": len(rows)}, ensure_ascii=False))


async def run_real_history(output: Path) -> None:
    """Resume an isolated copy of a real archived full-cycle/xhigh Orchestra rollout.

    Codex stores an absolute rollout_path in state_5.sqlite. Merely copying both artifacts is
    not isolation: the copied DB still points at the original. Rewrite and verify that pointer
    before app-server starts.
    """
    from app.pipeline import DEFAULT_PIPELINE, build_system_prompt

    thread_id = "019f73cc-56cb-71f3-bc47-a1fe474511b8"
    source = Path.home() / ".codex/sessions/2026/07/18/rollout-2026-07-18T12-56-39-019f73cc-56cb-71f3-bc47-a1fe474511b8.jsonl"
    home = make_home("real-history")
    relative = source.relative_to(Path.home() / ".codex/sessions")
    destination = home / "sessions" / relative
    destination.parent.mkdir(parents=True)
    shutil.copy2(source, destination)
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        changed = conn.execute(
            "UPDATE threads SET rollout_path = ? WHERE id = ?", (str(destination), thread_id)
        ).rowcount
        conn.commit()
        stored = conn.execute(
            "SELECT rollout_path FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
    if changed != 1 or stored != (str(destination),):
        raise RuntimeError("scratch state rollout_path was not isolated")
    managed = home.parent / f"managed-{home.name}"
    managed.mkdir(mode=0o700)
    row, _ = await backend_arm(
        "E_real_archived_history",
        1,
        home,
        managed,
        system_prompt=build_system_prompt(DEFAULT_PIPELINE, "full-cycle"),
        with_mcp=True,
        resume_thread_id=thread_id,
    )
    row["history_source_bytes"] = source.stat().st_size
    row["history_source_thread"] = thread_id
    output.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "rows": 1}, ensure_ascii=False))


async def run_exec_subset(output: Path) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rep in (3, 4):
        rows.append(await exec_arm(rep, make_home(f"rerun-exec-{rep}")))
    with output.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "rows": len(rows)}, ensure_ascii=False))


async def run_ab_subset(output: Path) -> None:
    """Corrected final-event A/B/A/B control after validating the exec JSON event schema."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rep in (5, 6):
        rows.append(await exec_arm(rep, make_home(f"ab-a-{rep}")))
        home = make_home(f"ab-b-{rep}")
        row = await raw_appserver("B_appserver", rep, home)
        row.update(
            {
                "system_prompt_bytes": 0,
                "project_doc_bytes": (ROOT / "AGENTS.md").stat().st_size,
                "mcp_schema_bytes": 0,
                "history_mode": "fresh",
            }
        )
        rows.append(row)
    with output.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "rows": len(rows)}, ensure_ascii=False))


async def run_mcp_control(output: Path) -> None:
    """Positive no-model control: app-server reports ready MCP and the full tool names."""
    import app.backend_codex as bc
    from app.mcp_stdio import mcp

    home = make_home("mcp-control")
    managed_root = home.parent / f"managed-{home.name}"
    managed_root.mkdir(mode=0o700)
    bc._CODEX_HOME_ROOT = managed_root
    bc._base_codex_home = lambda: home

    async def no_scope():
        return False, {}, "#240 matched direct production launch"

    bc._codex_scope_support = no_scope
    unique = f"bench240-mcp-control-{uuid.uuid4().hex[:8]}"
    servers = current_mcp_config(unique)
    backend = bc.CodexBackend(
        model=MODEL,
        cwd=str(ROOT),
        system_prompt="",
        mcp_servers=servers,
        mcp_env={k: str(v) for cfg in servers.values() for k, v in (cfg.get("env") or {}).items()},
        reasoning_effort=EFFORT,
    )
    try:
        await asyncio.wait_for(backend.connect(), TIMEOUT)
        result = await asyncio.wait_for(
            backend._request(
                "mcpServerStatus/list",
                {
                    "threadId": backend.session_id,
                    "cursor": None,
                    "limit": 100,
                    "detail": "toolsAndAuthOnly",
                },
            ),
            TIMEOUT,
        )
        notifications = []
        while not backend._notifications.empty():
            message = backend._notifications.get_nowait()
            if message.get("method") == "mcpServer/startupStatus/updated":
                params = message.get("params") or {}
                notifications.append(
                    {k: params.get(k) for k in ("threadId", "name", "status", "error", "failureReason")}
                )
        data = result.get("data") or result.get("servers") or []
        returned = []
        server_rows = []
        for server in data:
            tools = server.get("tools") or []
            if isinstance(tools, dict):
                names = sorted(str(name) for name in tools)
            else:
                names = sorted(
                    str(tool.get("name") if isinstance(tool, dict) else tool)
                    for tool in tools
                )
            returned.extend(names)
            server_rows.append(
                {
                    "name": server.get("name"),
                    "status": server.get("status"),
                    "tool_count": len(names),
                    "tool_names": names,
                }
            )
        expected = sorted(tool.name for tool in mcp._tool_manager.list_tools())
        row = {
            "arm": "M_mcp_positive_no_model",
            "cli_version": cli_version(),
            "config_sha256": config_hash(backend._codex_home or home),
            "result_keys": sorted(result),
            "servers": server_rows,
            "startup_notifications": notifications,
            "expected_tool_count": len(expected),
            "returned_tool_count": len(returned),
            "missing_tools": sorted(set(expected) - set(returned)),
            "extra_tools": sorted(set(returned) - set(expected)),
            "outcome": "no_model_ok",
            "loadavg": loadavg(),
        }
        output.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(json.dumps({"output": str(output), "summary": row}, ensure_ascii=False))
    finally:
        await backend.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/tasks/240/raw-runs.jsonl")
    parser.add_argument(
        "--subset",
        choices=("full", "backend", "reload", "real-history", "exec", "ab", "mcp-control"),
        default="full",
    )
    args = parser.parse_args()
    target = {
        "full": run,
        "backend": run_backend_subset,
        "reload": run_reload_control,
        "real-history": run_real_history,
        "exec": run_exec_subset,
        "ab": run_ab_subset,
        "mcp-control": run_mcp_control,
    }[args.subset]
    asyncio.run(target(args.output))


if __name__ == "__main__":
    main()
