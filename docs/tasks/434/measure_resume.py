"""Measure native Codex app-server resume without writing the production CODEX_HOME."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from typing import Any


def _backup(source: pathlib.Path, target: pathlib.Path) -> None:
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _rpc(process: subprocess.Popen[str], request_id: int, method: str,
         params: dict[str, Any] | None = None) -> tuple[dict[str, Any], float]:
    request = {"method": method, "id": request_id, "params": params or {}}
    started = time.monotonic()
    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    process.stdin.flush()
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(
                f"Codex exited before {method} response (rc={process.poll()})"
            )
        message = json.loads(line)
        if message.get("id") == request_id:
            return message, time.monotonic() - started


def _measure_thread(
    *,
    source_state: pathlib.Path,
    source_history: pathlib.Path,
    thread_id: str,
    codex_bin: str,
    strace_output: pathlib.Path | None = None,
    preserve_home: pathlib.Path | None = None,
    reuse_home: pathlib.Path | None = None,
    with_orchestra_mcp: bool = False,
    config_source: pathlib.Path | None = None,
    label: str = "",
) -> dict[str, Any]:
    home_context = (
        tempfile.TemporaryDirectory(prefix="codex-resume-434-")
        if reuse_home is None
        else contextlib.nullcontext(str(reuse_home))
    )
    with home_context as raw_home:
        home = pathlib.Path(raw_home)
        home.mkdir(parents=True, exist_ok=True)
        if not (home / "state_5.sqlite").exists():
            _backup(source_state, home / "state_5.sqlite")
        if not (home / "thread_history_1.sqlite").exists():
            _backup(source_history, home / "thread_history_1.sqlite")
        auth = home / "auth.json"
        if not auth.exists() and not auth.is_symlink():
            auth.symlink_to(pathlib.Path.home() / ".codex" / "auth.json")
        if config_source is not None:
            config = config_source.read_text(encoding="utf-8")
        else:
            config = (
                'model_context_window = 872000\n'
                'model_auto_compact_token_limit = 784800\n'
            )
            if with_orchestra_mcp:
                config += (
                    '\n[mcp_servers."orchestra"]\n'
                    'enabled = true\n'
                    'command = "/home/kesha/orchestra/.venv/bin/python"\n'
                    'args = ["/home/kesha/orchestra/app/mcp_stdio.py"]\n\n'
                    '[mcp_servers."orchestra".env]\n'
                    'PYTHONPATH = "/home/kesha/orchestra"\n'
                )
        (home / "config.toml").write_text(config, encoding="utf-8")
        state = sqlite3.connect(f"file:{home / 'state_5.sqlite'}?mode=ro", uri=True)
        state.row_factory = sqlite3.Row
        row = state.execute(
            "SELECT cwd, model, reasoning_effort, rollout_path, tokens_used, history_mode "
            "FROM threads WHERE id=?",
            (thread_id,),
        ).fetchone()
        state.close()
        if row is None:
            raise ValueError(f"thread not found: {thread_id}")
        rollout = pathlib.Path(row["rollout_path"])
        result: dict[str, Any] = {
            "thread_id": thread_id,
            "label": label,
            "cwd": row["cwd"],
            "model": row["model"],
            "reasoning_effort": row["reasoning_effort"],
            "tokens_used": row["tokens_used"],
            "history_mode": row["history_mode"],
            "rollout_path": str(rollout),
            "rollout_bytes": rollout.stat().st_size,
        }
        env = dict(os.environ)
        env["CODEX_HOME"] = str(home)
        command = [codex_bin, "app-server", "--stdio"]
        if strace_output is not None:
            command = [
                "strace", "-f", "-ttt", "-o", str(strace_output),
                "-e", "trace=pread64,preadv,preadv2,openat,openat2,statx,newfstatat,execve",
                *command,
            ]
        process = subprocess.Popen(
            command,
            cwd=row["cwd"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        try:
            initialize, initialize_seconds = _rpc(process, 1, "initialize", {
                "clientInfo": {"name": "resume-434", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            process.stdin.write('{"method":"initialized","params":{}}\n')
            process.stdin.flush()
            resume, resume_seconds = _rpc(process, 2, "thread/resume", {
                "cwd": row["cwd"],
                "model": row["model"],
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "threadId": thread_id,
                "excludeTurns": True,
            })
            result.update({
                "initialize_seconds": initialize_seconds,
                "resume_seconds": resume_seconds,
                "initialize_error": initialize.get("error"),
                "resume_error": resume.get("error"),
                "resumed_thread_id": (resume.get("result") or {}).get("thread", {}).get("id"),
            })
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            if preserve_home is not None:
                shutil.copytree(
                    home, preserve_home, dirs_exist_ok=True, symlinks=True,
                )
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=pathlib.Path, required=True)
    parser.add_argument("--history", type=pathlib.Path, required=True)
    parser.add_argument("--thread", action="append", required=True)
    parser.add_argument("--codex-bin", default="/usr/bin/codex")
    parser.add_argument("--strace-output", type=pathlib.Path)
    parser.add_argument("--preserve-home", type=pathlib.Path)
    parser.add_argument("--reuse-home", type=pathlib.Path)
    parser.add_argument("--with-orchestra-mcp", action="store_true")
    parser.add_argument("--config-source", type=pathlib.Path)
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    for thread_id in args.thread:
        print(json.dumps(_measure_thread(
            source_state=args.state,
            source_history=args.history,
            thread_id=thread_id,
            codex_bin=args.codex_bin,
            strace_output=args.strace_output,
            preserve_home=args.preserve_home,
            reuse_home=args.reuse_home,
            with_orchestra_mcp=args.with_orchestra_mcp,
            config_source=args.config_source,
            label=args.label,
        ), ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
