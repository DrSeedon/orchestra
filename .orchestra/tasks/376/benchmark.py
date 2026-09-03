#!/usr/bin/env python3
"""Reproducible #376 Codex app-server versus codex exec benchmark.

Provider-backed runs are intentionally sequential.  The script writes timestamped raw JSONL,
rollout copies, and one normalized summary per run beneath docs/tasks/376/raw/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import selectors
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
TASK_PATH = ROOT / "task.txt"
SCHEMA_PATH = ROOT / "output-schema.json"
RAW_ROOT = ROOT / "raw"
MODEL = "gpt-5.6-sol"
EFFORT = "medium"
EXPECTED = {"answer": "ORCHESTRA-376-OK"}
FIXTURE_CWD = Path("/var/tmp/orchestra-376-fixture")
RUN_HOME = Path("/var/tmp/orchestra-376-benchmark-home")
METER_HOME = Path("/var/tmp/orchestra-376-meter-home")
CODEX = shutil.which("codex") or "codex"
TIMEOUT_S = 180.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def machine_snapshot() -> dict[str, Any]:
    load = Path("/proc/loadavg").read_text().split()
    mem_kb = None
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            mem_kb = int(line.split()[1])
            break
    return {
        "utc": utc_now(),
        "loadavg_1": float(load[0]),
        "loadavg_5": float(load[1]),
        "loadavg_15": float(load[2]),
        "mem_available_kb": mem_kb,
    }


def print_snapshot(label: str, arm: str, phase: str, snap: dict[str, Any]) -> None:
    print(
        f"RUN={label} ARM={arm} PHASE={phase} "
        f"loadavg={snap['loadavg_1']:.2f}/{snap['loadavg_5']:.2f}/{snap['loadavg_15']:.2f} "
        f"MemAvailable={snap['mem_available_kb']}kB utc={snap['utc']}",
        flush=True,
    )


def controlled_home(label: str, *, meter: bool = False) -> Path:
    # The absolute CODEX_HOME path is model-visible through the built-in skill catalog.
    # Reuse one fixed pathname while recreating its contents before every sequential run:
    # this keeps context byte-identical without carrying thread/state between runs.
    home = METER_HOME if meter else RUN_HOME
    if home.exists() or home.is_symlink():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    auth = Path.home() / ".codex" / "auth.json"
    if not auth.exists():
        raise RuntimeError(f"ChatGPT auth is unavailable: {auth}")
    (home / "auth.json").symlink_to(auth)
    (home / "config.toml").write_text(
        "\n".join(
            (
                'model_reasoning_effort = "medium"',
                'service_tier = "standard"',
                'web_search = "disabled"',
                "model_context_window = 872000",
                "model_auto_compact_token_limit = 784800",
                "",
                "[features]",
                "apps = false",
                "multi_agent = false",
                "current_time_reminder = false",
                "",
            )
        ),
        encoding="utf-8",
    )
    return home


def controlled_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["CODEX_HOME"] = str(home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "NOTIFY_SOCKET"):
        env.pop(key, None)
    return env


def common_global_args() -> list[str]:
    return [
        CODEX,
        "-c", 'model_reasoning_effort="medium"',
        "-c", 'service_tier="standard"',
        "-c", 'web_search="disabled"',
        "-c", "model_context_window=872000",
        "-c", "model_auto_compact_token_limit=784800",
        "-c", "features.apps=false",
        "-c", "features.multi_agent=false",
        "-c", "features.current_time_reminder=false",
        "-m", MODEL,
        "-s", "read-only",
        "-a", "never",
        "-C", str(FIXTURE_CWD),
    ]


def raw_write(fh, started: float, stream: str, payload: Any) -> float:
    observed = time.perf_counter()
    row = {
        "observed_utc": utc_now(),
        "t_s": observed - started,
        "stream": stream,
        "payload": payload,
    }
    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    fh.flush()
    return observed


class JsonlProcess:
    def __init__(self, cmd: list[str], env: dict[str, str], cwd: Path,
                 raw_path: Path, stderr_path: Path):
        self.cmd = cmd
        self.raw_path = raw_path
        self.raw_fh = raw_path.open("w", encoding="utf-8")
        self.stderr_fh = stderr_path.open("wb")
        self.started = time.perf_counter()
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_fh,
            bufsize=0,
        )
        assert self.proc.stdout is not None
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.events: list[dict[str, Any]] = []
        self._request_id = 0

    def send(self, payload: dict[str, Any]) -> float:
        assert self.proc.stdin is not None
        t = raw_write(self.raw_fh, self.started, "stdin", payload)
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
        self.proc.stdin.flush()
        return t

    def read(self, timeout: float = TIMEOUT_S) -> tuple[float, dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout reading {' '.join(self.cmd[:4])}")
            ready = self.selector.select(remaining)
            if not ready:
                continue
            assert self.proc.stdout is not None
            line = self.proc.stdout.readline()
            if not line:
                raise EOFError(f"process exited {self.proc.poll()}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"_non_json": line.decode(errors="replace").rstrip("\n")}
            t = raw_write(self.raw_fh, self.started, "stdout", payload)
            self.events.append({"at": t, "payload": payload})
            if isinstance(payload, dict) and payload.get("method") and payload.get("id") is not None:
                self.send({
                    "id": payload["id"],
                    "error": {"code": -32601, "message": "benchmark implements no server tools"},
                })
                continue
            return t, payload

    def request(self, method: str, params: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
        self._request_id += 1
        req_id = self._request_id
        sent = self.send({"id": req_id, "method": method, "params": params})
        while True:
            at, payload = self.read()
            if payload.get("id") != req_id:
                continue
            if "error" in payload:
                raise RuntimeError(f"{method}: {payload['error']}")
            return sent, at, payload.get("result") or {}

    def wait_method(self, method: str) -> tuple[float, dict[str, Any]]:
        for event in self.events:
            if event["payload"].get("method") == method and not event.get("consumed"):
                event["consumed"] = True
                return event["at"], event["payload"]
        while True:
            at, payload = self.read()
            if payload.get("method") == method:
                return at, payload

    def stop(self) -> tuple[float, int | None]:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        ended = time.perf_counter()
        raw_write(self.raw_fh, self.started, "process", {"returncode": self.proc.returncode})
        self.raw_fh.close()
        self.stderr_fh.close()
        return ended, self.proc.returncode


def app_server_cmd() -> list[str]:
    cmd = common_global_args()
    cmd += ["app-server", "--stdio"]
    return cmd


def initialize_server(server: JsonlProcess, *, start_thread: bool) -> dict[str, Any]:
    init_sent, init_at, _ = server.request(
        "initialize",
        {"clientInfo": {"name": "orchestra", "title": "Orchestra", "version": "1"}},
    )
    server.send({"method": "initialized", "params": {}})
    result: dict[str, Any] = {
        "initialize_send_at": init_sent,
        "initialize_response_at": init_at,
    }
    if start_thread:
        thread_sent, thread_at, thread = server.request(
            "thread/start",
            {
                "cwd": str(FIXTURE_CWD),
                "model": MODEL,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": False,
                "serviceTier": "standard",
            },
        )
        thread_id = ((thread.get("thread") or {}).get("id"))
        if not thread_id:
            raise RuntimeError("thread/start returned no id")
        result.update({
            "thread_send_at": thread_sent,
            "thread_response_at": thread_at,
            "thread_id": thread_id,
        })
    return result


def find_app_event(events: list[dict[str, Any]], method: str, *, item_type: str = ""):
    for event in events:
        payload = event["payload"]
        if payload.get("method") != method:
            continue
        if item_type:
            item = (payload.get("params") or {}).get("item") or {}
            if str(item.get("type") or "").lower() != item_type.lower():
                continue
        return event
    return None


def agent_text_from_app(events: list[dict[str, Any]]) -> tuple[float | None, str]:
    for event in reversed(events):
        payload = event["payload"]
        if payload.get("method") != "item/completed":
            continue
        item = (payload.get("params") or {}).get("item") or {}
        if item.get("type") == "agentMessage":
            return event["at"], str(item.get("text") or "")
    return None, ""


def app_usage(events: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    last_total: dict[str, Any] = {}
    calls = 0
    for event in events:
        payload = event["payload"]
        if payload.get("method") != "thread/tokenUsage/updated":
            continue
        usage = ((payload.get("params") or {}).get("tokenUsage") or {})
        total = usage.get("total") or {}
        last = usage.get("last") or {}
        if total:
            last_total = total
        if sum(int(v or 0) for v in last.values() if isinstance(v, (int, float))) > 0:
            calls += 1
    def pick(d: dict[str, Any], camel: str, snake: str) -> int:
        return int(d.get(camel, d.get(snake, 0)) or 0)
    normalized = {
        "input_tokens": pick(last_total, "inputTokens", "input_tokens"),
        "cached_input_tokens": pick(last_total, "cachedInputTokens", "cached_input_tokens"),
        "cache_write_input_tokens": pick(last_total, "cacheWriteInputTokens", "cache_write_input_tokens"),
        "output_tokens": pick(last_total, "outputTokens", "output_tokens"),
        "reasoning_output_tokens": pick(last_total, "reasoningOutputTokens", "reasoning_output_tokens"),
    }
    return normalized, calls


def exec_event(raw_events: list[dict[str, Any]], event_type: str):
    for event in raw_events:
        if event["payload"].get("type") == event_type:
            return event
    return None


def exec_agent_text(raw_events: list[dict[str, Any]]) -> tuple[float | None, str]:
    for event in reversed(raw_events):
        payload = event["payload"]
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item") or {}
        if item.get("type") == "agent_message":
            return event["at"], str(item.get("text") or "")
    return None, ""


def count_tools_exec(raw_events: list[dict[str, Any]]) -> int:
    tool_types = {"command_execution", "mcp_tool_call", "file_change", "web_search"}
    return sum(
        1 for event in raw_events
        if event["payload"].get("type") == "item.completed"
        and ((event["payload"].get("item") or {}).get("type") in tool_types)
    )


def count_tools_app(events: list[dict[str, Any]]) -> int:
    non_tools = {"userMessage", "agentMessage", "reasoning", "plan"}
    return sum(
        1 for event in events
        if event["payload"].get("method") == "item/completed"
        and ((event["payload"].get("params") or {}).get("item") or {}).get("type") not in non_tools
    )


def parse_json_ac(text: str) -> tuple[bool, str]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"
    if value != EXPECTED:
        return False, f"value mismatch: {value!r}"
    return True, "exact JSON match"


def rollout_metrics(home: Path, destination: Path) -> dict[str, Any]:
    candidates = list((home / "sessions").glob("**/*.jsonl"))
    if not candidates:
        return {"rollout_found": False}
    rollout = max(candidates, key=lambda p: p.stat().st_mtime)
    shutil.copy2(rollout, destination)
    rows = []
    for line in rollout.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    meta = next((r.get("payload") or {} for r in rows if r.get("type") == "session_meta"), {})
    base = str(meta.get("base_instructions") or "")
    prefix = []
    for row in rows:
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload") or {}
        record = {
            "type": payload.get("type"),
            "role": payload.get("role"),
            "content": payload.get("content"),
        }
        prefix.append(record)
        if payload.get("role") == "user":
            break
    turn = next((r.get("payload") or {} for r in rows if r.get("type") == "turn_context"), {})
    token_calls = []
    for row in rows:
        if row.get("type") != "event_msg":
            continue
        payload = row.get("payload") or {}
        if payload.get("type") != "token_count":
            continue
        info = payload.get("info") or {}
        last = info.get("last_token_usage") or {}
        if sum(int(v or 0) for v in last.values() if isinstance(v, (int, float))) > 0:
            token_calls.append(last)
    return {
        "rollout_found": True,
        "rollout_name": rollout.name,
        "cli_version": meta.get("cli_version"),
        "originator": meta.get("originator"),
        "source": meta.get("source"),
        "base_instructions_sha256": sha256_bytes(base.encode()),
        "base_instructions_bytes": len(base.encode()),
        "model_visible_prefix_sha256": sha256_bytes(
            json.dumps(prefix, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ),
        "model_visible_prefix_items": [
            {"type": p["type"], "role": p["role"], "content_bytes": len(json.dumps(p["content"], ensure_ascii=False).encode())}
            for p in prefix
        ],
        "turn_context": {
            key: turn.get(key)
            for key in ("model", "effort", "cwd", "current_date", "timezone", "personality")
        },
        "rollout_model_calls": len(token_calls),
    }


def start_meter(stage_dir: Path) -> tuple[JsonlProcess, Path]:
    home = controlled_home(f"meter-{uuid.uuid4().hex[:8]}", meter=True)
    meter = JsonlProcess(
        app_server_cmd(), controlled_env(home), FIXTURE_CWD,
        stage_dir / "meter.raw.jsonl", stage_dir / "meter.stderr.txt",
    )
    initialize_server(meter, start_thread=False)
    return meter, home


def quota_snapshot(meter: JsonlProcess) -> dict[str, Any]:
    _, _, result = meter.request("account/rateLimits/read", {})
    return result


def run_app(label: str, stage_dir: Path, quota_before: dict[str, Any]) -> dict[str, Any]:
    run_dir = stage_dir / label
    run_dir.mkdir(parents=True, exist_ok=False)
    home = controlled_home(label)
    before = machine_snapshot()
    print_snapshot(label, "app-server", "before", before)
    server = JsonlProcess(
        app_server_cmd(), controlled_env(home), FIXTURE_CWD,
        run_dir / "transport.raw.jsonl", run_dir / "stderr.txt",
    )
    try:
        init = initialize_server(server, start_thread=True)
        turn_sent, turn_response_at, _ = server.request(
            "turn/start",
            {
                "threadId": init["thread_id"],
                "input": [{"type": "text", "text": TASK_PATH.read_text(encoding="utf-8").strip()}],
                "model": MODEL,
                "effort": EFFORT,
                "cwd": str(FIXTURE_CWD),
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly"},
                "serviceTier": "standard",
                "outputSchema": json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
            },
        )
        completed_at, completed = server.wait_method("turn/completed")
        turn_started = find_app_event(server.events, "turn/started")
        agent_at, text = agent_text_from_app(server.events)
        if turn_started is None or agent_at is None:
            raise RuntimeError("missing app-server lifecycle event")
        usage, calls = app_usage(server.events)
        tools = count_tools_app(server.events)
        ac, ac_detail = parse_json_ac(text)
        stopped_at, returncode = server.stop()
        after = machine_snapshot()
        print_snapshot(label, "app-server", "after", after)
        rollout = rollout_metrics(home, run_dir / "rollout.jsonl")
        summary = {
            "label": label,
            "arm": "app-server",
            "model": MODEL,
            "effort": EFFORT,
            "task_sha256": sha256_bytes(TASK_PATH.read_bytes()),
            "schema_sha256": sha256_bytes(SCHEMA_PATH.read_bytes()),
            "cwd": str(FIXTURE_CWD),
            "thread_id": init["thread_id"],
            "load_before": before,
            "load_after": after,
            "quota_before": quota_before,
            "timing_s": {
                "cold_process_handshake": init["thread_response_at"] - server.started,
                "initialize": init["initialize_response_at"] - init["initialize_send_at"],
                "thread_start": init["thread_response_at"] - init["thread_send_at"],
                "steady_total": completed_at - turn_sent,
                "queue": turn_started["at"] - turn_sent,
                "turn_start_ack": turn_response_at - turn_sent,
                "model_wait": agent_at - turn_started["at"],
                "tool_work": 0.0,
                "post_processing": completed_at - agent_at,
                "teardown": stopped_at - completed_at,
            },
            "usage": usage,
            "calls": calls or rollout.get("rollout_model_calls", 0),
            "tools": tools,
            "final_text": text,
            "ac_pass": ac and tools == 0,
            "ac_detail": ac_detail if tools == 0 else f"unexpected tools={tools}",
            "process_returncode": returncode,
            "turn_status": ((completed.get("params") or {}).get("turn") or {}).get("status"),
            "rollout": rollout,
        }
        return summary
    finally:
        if server.proc.poll() is None:
            server.stop()
        shutil.rmtree(home)


def run_exec(label: str, stage_dir: Path, quota_before: dict[str, Any]) -> dict[str, Any]:
    run_dir = stage_dir / label
    run_dir.mkdir(parents=True, exist_ok=False)
    home = controlled_home(label)
    before = machine_snapshot()
    print_snapshot(label, "exec", "before", before)
    cmd = common_global_args() + [
        "exec", "--skip-git-repo-check", "--json",
        "--output-schema", str(SCHEMA_PATH), "-",
    ]
    raw_path = run_dir / "transport.raw.jsonl"
    stderr_path = run_dir / "stderr.txt"
    raw_fh = raw_path.open("w", encoding="utf-8")
    stderr_fh = stderr_path.open("wb")
    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd, cwd=FIXTURE_CWD, env=controlled_env(home),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_fh, bufsize=0,
    )
    assert proc.stdin is not None and proc.stdout is not None
    prompt = TASK_PATH.read_bytes()
    proc.stdin.write(prompt)
    proc.stdin.close()
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + TIMEOUT_S
    try:
        while True:
            if time.monotonic() >= deadline:
                proc.kill()
                raise TimeoutError(f"exec timeout: {label}")
            ready = sel.select(0.5)
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"_non_json": line.decode(errors="replace").rstrip("\n")}
            at = raw_write(raw_fh, started, "stdout", payload)
            events.append({"at": at, "payload": payload})
        returncode = proc.wait(timeout=5)
        ended = time.perf_counter()
        raw_write(raw_fh, started, "process", {"returncode": returncode})
        after = machine_snapshot()
        print_snapshot(label, "exec", "after", after)
        thread = exec_event(events, "thread.started")
        turn_started = exec_event(events, "turn.started")
        turn_completed = exec_event(events, "turn.completed")
        agent_at, text = exec_agent_text(events)
        if thread is None or turn_started is None or turn_completed is None or agent_at is None:
            raise RuntimeError("missing codex exec lifecycle event")
        usage = turn_completed["payload"].get("usage") or {}
        normalized_usage = {
            key: int(usage.get(key, 0) or 0)
            for key in (
                "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens",
            )
        }
        tools = count_tools_exec(events)
        ac, ac_detail = parse_json_ac(text)
        rollout = rollout_metrics(home, run_dir / "rollout.jsonl")
        summary = {
            "label": label,
            "arm": "exec",
            "model": MODEL,
            "effort": EFFORT,
            "task_sha256": sha256_bytes(TASK_PATH.read_bytes()),
            "schema_sha256": sha256_bytes(SCHEMA_PATH.read_bytes()),
            "cwd": str(FIXTURE_CWD),
            "thread_id": thread["payload"].get("thread_id"),
            "load_before": before,
            "load_after": after,
            "quota_before": quota_before,
            "timing_s": {
                "total": ended - started,
                "process_handshake": thread["at"] - started,
                "queue": turn_started["at"] - thread["at"],
                "model_wait": agent_at - turn_started["at"],
                "tool_work": 0.0,
                "post_processing": ended - agent_at,
                "turn_completed_after_agent": turn_completed["at"] - agent_at,
            },
            "usage": normalized_usage,
            "calls": rollout.get("rollout_model_calls", 0),
            "tools": tools,
            "final_text": text,
            "ac_pass": ac and tools == 0 and returncode == 0,
            "ac_detail": ac_detail if tools == 0 else f"unexpected tools={tools}",
            "process_returncode": returncode,
            "rollout": rollout,
        }
        return summary
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        raw_fh.close()
        stderr_fh.close()
        shutil.rmtree(home)


def save_summary(summary: dict[str, Any], stage_dir: Path) -> None:
    path = stage_dir / summary["label"] / "summary.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def run_one(arm: str, label: str, stage_dir: Path, meter: JsonlProcess) -> dict[str, Any]:
    quota_before = quota_snapshot(meter)
    if arm == "app-server":
        summary = run_app(label, stage_dir, quota_before)
    elif arm == "exec":
        summary = run_exec(label, stage_dir, quota_before)
    else:
        raise ValueError(arm)
    summary["quota_after"] = quota_snapshot(meter)
    save_summary(summary, stage_dir)
    return summary


def stage_aa() -> None:
    stage_dir = RAW_ROOT / "aa"
    if stage_dir.exists():
        raise RuntimeError(f"refusing to overwrite {stage_dir}")
    stage_dir.mkdir(parents=True)
    meter, meter_home = start_meter(stage_dir)
    summaries = []
    try:
        summaries.append(run_one("exec", "warmup-exec", stage_dir, meter))
        for index in range(1, 4):
            summaries.append(run_one("exec", f"aa-exec-{index}", stage_dir, meter))
    finally:
        meter.stop()
        shutil.rmtree(meter_home)
    (stage_dir / "stage-summary.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def stage_ab() -> None:
    gate_path = ROOT / "aa-gate.json"
    gate = json.loads(gate_path.read_text())
    if not gate.get("pass"):
        raise RuntimeError(f"A/B forbidden by preregistered gate: {gate}")
    stage_dir = RAW_ROOT / "ab"
    if stage_dir.exists():
        raise RuntimeError(f"refusing to overwrite {stage_dir}")
    stage_dir.mkdir(parents=True)
    meter, meter_home = start_meter(stage_dir)
    summaries = []
    order = [
        ("app-server", "warmup-app"),
        ("exec", "warmup-exec"),
        ("app-server", "ab-app-1"),
        ("exec", "ab-exec-1"),
        ("app-server", "ab-app-2"),
        ("exec", "ab-exec-2"),
    ]
    try:
        for arm, label in order:
            summaries.append(run_one(arm, label, stage_dir, meter))
    finally:
        meter.stop()
        shutil.rmtree(meter_home)
    (stage_dir / "stage-summary.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("aa", "ab"))
    args = parser.parse_args()
    FIXTURE_CWD.mkdir(parents=True, exist_ok=True)
    if any(FIXTURE_CWD.iterdir()):
        raise RuntimeError(f"fixture cwd must stay empty: {FIXTURE_CWD}")
    if args.stage == "aa":
        stage_aa()
    else:
        stage_ab()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
