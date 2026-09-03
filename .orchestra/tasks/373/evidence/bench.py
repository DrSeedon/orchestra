#!/usr/bin/env python3
"""Sequential, isolated provider benchmarks for #373.

The script copies subscription auth into temporary homes, never edits the user's
Codex state, and writes only redacted aggregate metrics.
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
import statistics
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL = "gpt-5.6-sol"
TIMEOUT_S = 600
HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "effort-schema.json"

EFFORT_PROMPT = """You are evaluating a frozen research evidence packet. Do not call tools.
Return only the JSON object required by the supplied schema. Use exact enum strings.

FACTS
- CLI model catalog: raw default context=272000, raw maximum=872000, usable percent=95.
- CLI auto-compact limit is 90% of resolved raw context.
- Orchestra dashboard computes integer floor(last_call_input * 100 / effective_window).
- Incident A: effective window=258400, last-call input=239382, cumulative input=6353301,
  cached cumulative input=6099968, 48 provider calls.
- Incident B: effective window=121600, cumulative input=6438670, 76 provider calls.
- A prior isolated subscription-auth run with configured raw window=872000 accepted a
  second-turn request containing 509046 input tokens and reported effective window=828400.
- A configured maximum selects capacity advertised by the provider catalog; it does not
  create additional provider capacity. Larger active prompts can still increase each call.

REQUIRED VALUES
- primary_cause must be `repeated_round_trips_over_growing_context`.
- configured_window_effect must be `selects_advertised_capacity_and_changes_local_budget`.
- counter_evidence must be `larger_active_prompt_still_increases_each_call`.
- falsifier must be `equal_calls_equal_prompts_but_cumulative_differs_by_window`.
- mean_input_per_call and cache_percent: round to 2 decimals.
- smaller_window_counterexample is true iff Incident B refutes context-window size as a
  sufficient explanation of the ~6.4M cumulative input.
"""

INTERFACE_INITIAL = (
    "Controlled benchmark. Do not call tools. Remember nonce N373 and reply exactly BENCH-373."
)
INTERFACE_CONTINUE = (
    "Do not call tools. What nonce were you asked to remember? Reply exactly N373."
)
SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def loadavg() -> list[float]:
    return [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]


def proc_tree(root: int) -> list[int]:
    found, stack = [], [root]
    while stack:
        pid = stack.pop()
        if pid in found or not Path(f"/proc/{pid}").exists():
            continue
        found.append(pid)
        children = Path(f"/proc/{pid}/task/{pid}/children")
        try:
            stack.extend(int(x) for x in children.read_text().split())
        except (FileNotFoundError, PermissionError, ValueError):
            pass
    return found


def tree_rss_kib(root: int) -> int:
    total = 0
    for pid in proc_tree(root):
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
        except (FileNotFoundError, PermissionError, ValueError):
            pass
    return total


class RssSampler:
    def __init__(self, pid: int):
        self.pid = pid
        self.peak_kib = 0
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while self.running:
            self.peak_kib = max(self.peak_kib, tree_rss_kib(self.pid))
            time.sleep(0.05)

    def stop(self) -> int:
        self.running = False
        self.thread.join(timeout=1)
        self.peak_kib = max(self.peak_kib, tree_rss_kib(self.pid))
        return self.peak_kib


def auth_source() -> Path:
    candidates = [Path.home() / ".codex" / "auth.json"]
    if os.getenv("CODEX_HOME"):
        candidates.insert(0, Path(os.environ["CODEX_HOME"]) / "auth.json")
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise RuntimeError("subscription auth file not found")


def make_home(parent: Path, name: str) -> Path:
    home = parent / name
    home.mkdir(mode=0o700)
    target = home / "auth.json"
    shutil.copyfile(auth_source(), target)
    target.chmod(0o600)
    cache = Path.home() / ".codex" / "models_cache.json"
    if cache.is_file():
        shutil.copyfile(cache, home / "models_cache.json")
    return home


def redact_error(value: str) -> str:
    value = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", value)
    value = re.sub(r"(sk-[A-Za-z0-9_-]{12})[A-Za-z0-9_-]+", r"\1[REDACTED]", value)
    return value[-1200:]


def extract_text(msg: dict[str, Any]) -> str:
    payload = msg.get("item") or (msg.get("params") or {}).get("item") or {}
    if payload.get("type") in {"agent_message", "agentMessage"}:
        return str(payload.get("text") or payload.get("content") or "")
    if msg.get("type") == "item.completed" and isinstance(msg.get("item"), dict):
        item = msg["item"]
        if item.get("type") == "agent_message":
            return str(item.get("text") or "")
    return ""


def normalize_usage(value: dict[str, Any] | None) -> dict[str, int] | None:
    if not value:
        return None
    aliases = {
        "input_tokens": ("input_tokens", "inputTokens"),
        "cached_input_tokens": ("cached_input_tokens", "cachedInputTokens"),
        "output_tokens": ("output_tokens", "outputTokens"),
        "reasoning_output_tokens": ("reasoning_output_tokens", "reasoningOutputTokens"),
    }
    out = {}
    for dst, keys in aliases.items():
        out[dst] = next((int(value[k]) for k in keys if isinstance(value.get(k), int)), 0)
    return out


def exec_turn(
    *, home: Path, cwd: Path, prompt: str, effort: str, schema: Path | None,
    resume_id: str | None = None,
) -> dict[str, Any]:
    before = loadavg()
    started_wall = utc_now()
    start_ns = time.monotonic_ns()
    if resume_id:
        cmd = [
            "codex", "exec", "resume", "--ignore-user-config", "--skip-git-repo-check",
            "-m", MODEL, "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'web_search="disabled"', "-c", "features.multi_agent=false",
            "--json", resume_id, "-",
        ]
    else:
        cmd = [
            "codex", "exec", "--ignore-user-config", "--skip-git-repo-check",
            "-m", MODEL, "-s", "read-only",
            "-c", f'model_reasoning_effort="{effort}"',
            "-c", 'web_search="disabled"', "-c", "features.multi_agent=false",
            "--json", "-C", str(cwd),
        ]
        if schema:
            cmd.extend(["--output-schema", str(schema)])
        cmd.append("-")
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, cwd=cwd, env=env,
    )
    sampler = RssSampler(proc.pid)
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(prompt)
    proc.stdin.close()
    first_event_ns = first_model_ns = first_text_ns = completed_ns = None
    thread_id = None
    usage = None
    final_text = ""
    counts: dict[str, int] = {}
    deadline = time.monotonic() + TIMEOUT_S
    timed_out = False
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    while True:
        if time.monotonic() > deadline:
            timed_out = True
            proc.terminate()
            break
        ready = selector.select(timeout=min(0.25, max(0.0, deadline-time.monotonic())))
        if not ready:
            if proc.poll() is not None:
                break
            continue
        line = proc.stdout.readline()
        if not line:
            break
        now = time.monotonic_ns()
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if first_event_ns is None:
            first_event_ns = now
        kind = str(msg.get("type") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "thread.started":
            thread_id = msg.get("thread_id")
        if kind.startswith("item.") and first_model_ns is None:
            first_model_ns = now
        text = extract_text(msg)
        if text:
            if first_text_ns is None:
                first_text_ns = now
            final_text = text
        if kind == "turn.completed":
            usage = normalize_usage(msg.get("usage"))
            completed_ns = now
    try:
        rc = proc.wait(timeout=max(1, int(deadline - time.monotonic())))
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.terminate()
        try:
            rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait(timeout=5)
    peak = sampler.stop()
    stderr = redact_error(proc.stderr.read())
    end_ns = completed_ns or time.monotonic_ns()
    return {
        "interface": "exec_resume" if resume_id else "exec",
        "started_at": started_wall,
        "loadavg": before,
        "status": "timeout" if timed_out else ("completed" if rc == 0 else "failed"),
        "exit_code": rc,
        "thread_id": thread_id or resume_id,
        "first_event_ms": None if first_event_ns is None else (first_event_ns-start_ns)/1e6,
        "first_model_event_ms": None if first_model_ns is None else (first_model_ns-start_ns)/1e6,
        "first_text_ms": None if first_text_ns is None else (first_text_ns-start_ns)/1e6,
        "total_ms": (end_ns-start_ns)/1e6,
        "peak_rss_kib": peak,
        "usage": usage,
        "event_counts": counts,
        "final_text": final_text,
        "final_sha256": hashlib.sha256(final_text.encode()).hexdigest(),
        "stderr_tail": stderr if rc != 0 else "",
    }


class AppServer:
    def __init__(self, *, home: Path, cwd: Path, effort: str):
        self.cwd = cwd
        self.effort = effort
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        start = time.monotonic_ns()
        self.proc = subprocess.Popen(
            ["codex", "-c", 'web_search="disabled"', "-c", "features.multi_agent=false",
             "-c", "analytics.enabled=false", "app-server", "--stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=cwd, env=env,
        )
        self.sampler = RssSampler(self.proc.pid)
        self.q: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._stdout, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()
        self.next_id = 1
        _, _ = self.request("initialize", {
            "clientInfo": {"name": "orchestra_bench_373", "title": "#373", "version": "1"},
            "capabilities": {"experimentalApi": True},
        })
        self.send({"method": "initialized", "params": {}})
        self.handshake_ms = (time.monotonic_ns() - start) / 1e6
        self.initialized_rss_kib = tree_rss_kib(self.proc.pid)

    def _stdout(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            try:
                self.q.put((time.monotonic_ns(), json.loads(line)))
            except json.JSONDecodeError:
                self.stderr.append(f"non-json stdout: {line[-200:]}")

    def _stderr(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self.stderr.append(line[-400:])
            self.stderr[:] = self.stderr[-40:]

    def send(self, obj: dict[str, Any]) -> int:
        assert self.proc.stdin
        ts = time.monotonic_ns()
        self.proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()
        return ts

    def request(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any], list]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"method": method, "id": request_id, "params": params})
        side = []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ts, msg = self.q.get(timeout=max(0.1, deadline-time.monotonic()))
            if msg.get("id") == request_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result") or {}, side
            side.append((ts, msg))
        raise TimeoutError(method)

    def start_thread(self) -> tuple[str, float]:
        start = time.monotonic_ns()
        result, _ = self.request("thread/start", {
            "model": MODEL,
            "cwd": str(self.cwd),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "experimentalRawEvents": True,
        })
        return result["thread"]["id"], (time.monotonic_ns()-start)/1e6

    def turn(self, thread_id: str, prompt: str, schema: dict | None = None) -> dict[str, Any]:
        before = loadavg()
        started_wall = utc_now()
        request_id = self.next_id
        self.next_id += 1
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "model": MODEL,
            "effort": self.effort,
        }
        if schema:
            params["outputSchema"] = schema
        start_ns = self.send({"method": "turn/start", "id": request_id, "params": params})
        first_event_ns = first_model_ns = first_text_ns = completed_ns = None
        turn_id = None
        response_ms = None
        usage = None
        final_text = ""
        counts: dict[str, int] = {}
        errors = []
        deadline = time.monotonic() + TIMEOUT_S
        timed_out = False
        while time.monotonic() < deadline:
            try:
                ts, msg = self.q.get(timeout=max(0.1, deadline-time.monotonic()))
            except queue.Empty:
                timed_out = True
                break
            if msg.get("id") == request_id:
                response_ms = (ts-start_ns)/1e6
                if "error" in msg:
                    errors.append(msg["error"])
                    break
                turn_id = ((msg.get("result") or {}).get("turn") or {}).get("id")
                continue
            method = str(msg.get("method") or "unknown")
            counts[method] = counts.get(method, 0) + 1
            if first_event_ns is None:
                first_event_ns = ts
            params_msg = msg.get("params") or {}
            if method.startswith("item/") and first_model_ns is None:
                first_model_ns = ts
            if method == "item/agentMessage/delta" and params_msg.get("delta"):
                if first_text_ns is None:
                    first_text_ns = ts
            if method == "item/completed":
                item = params_msg.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("text"):
                    final_text = item["text"]
                    if first_text_ns is None:
                        first_text_ns = ts
            elif method == "thread/tokenUsage/updated":
                if not turn_id or params_msg.get("turnId") == turn_id:
                    usage = normalize_usage((params_msg.get("tokenUsage") or {}).get("last"))
            elif method == "turn/completed":
                turn = params_msg.get("turn") or {}
                if turn_id is None:
                    turn_id = turn.get("id")
                if turn.get("id") == turn_id:
                    completed_ns = ts
                    if turn.get("status") != "completed":
                        errors.append(turn.get("error") or turn.get("status"))
                    break
        return {
            "interface": "app_server",
            "started_at": started_wall,
            "loadavg": before,
            "status": "timeout" if timed_out else ("failed" if errors else "completed"),
            "turn_id": turn_id,
            "rpc_response_ms": response_ms,
            "first_event_ms": None if first_event_ns is None else (first_event_ns-start_ns)/1e6,
            "first_model_event_ms": None if first_model_ns is None else (first_model_ns-start_ns)/1e6,
            "first_text_ms": None if first_text_ns is None else (first_text_ns-start_ns)/1e6,
            "total_ms": None if completed_ns is None else (completed_ns-start_ns)/1e6,
            "process_rss_kib": tree_rss_kib(self.proc.pid),
            "usage": usage,
            "event_counts": counts,
            "final_text": final_text,
            "final_sha256": hashlib.sha256(final_text.encode()).hexdigest(),
            "errors": [redact_error(json.dumps(x, ensure_ascii=False)) for x in errors],
        }

    def close(self) -> dict[str, Any]:
        peak = self.sampler.stop()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        return {
            "handshake_ms": self.handshake_ms,
            "initialized_rss_kib": self.initialized_rss_kib,
            "peak_rss_kib": peak,
            "exit_code": self.proc.returncode,
            "stderr_tail": "" if self.proc.returncode in (0, -15) else redact_error("".join(self.stderr)),
        }


EXPECTED = {
    "default_effective_window": 258400,
    "override_effective_window": 828400,
    "default_auto_compact_limit": 244800,
    "override_auto_compact_limit": 784800,
    "dashboard_pct": 92,
    "cumulative_input": 6353301,
    "provider_calls": 48,
    "mean_input_per_call": 132360.44,
    "cache_percent": 96.01,
    "primary_cause": "repeated_round_trips_over_growing_context",
    "smaller_window_counterexample": True,
    "configured_window_effect": "selects_advertised_capacity_and_changes_local_budget",
    "counter_evidence": "larger_active_prompt_still_increases_each_call",
    "falsifier": "equal_calls_equal_prompts_but_cumulative_differs_by_window",
}


def grade_effort(text: str) -> dict[str, Any]:
    try:
        got = json.loads(text)
    except Exception as exc:
        return {"score": 0, "total": len(EXPECTED), "error": type(exc).__name__, "items": {}}
    items = {key: got.get(key) == value for key, value in EXPECTED.items()}
    return {"score": sum(items.values()), "total": len(items), "items": items}


def summarized_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in {"final_text", "thread_id", "turn_id"}}


def run_effort() -> dict[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text())
    with tempfile.TemporaryDirectory(prefix="t373-effort.") as root_s:
        root = Path(root_s)
        home = make_home(root, "home")
        cwd = root / "cwd"
        cwd.mkdir()
        rows = []
        order = ["high", "high", "high", "xhigh", "high", "xhigh"]
        for sequence, effort in enumerate(order, 1):
            row = exec_turn(
                home=home, cwd=cwd, prompt=EFFORT_PROMPT, effort=effort,
                schema=SCHEMA_PATH,
            )
            row["sequence"] = sequence
            row["phase"] = "aa_noise" if sequence <= 2 else "confirmatory"
            row["effort"] = effort
            row["grade"] = grade_effort(row["final_text"])
            rows.append(summarized_row(row))
        return {
            "meta": {"ts": utc_now(), "model": MODEL, "binary": shutil.which("codex"),
                     "version": subprocess.check_output(["codex", "--version"], text=True).strip(),
                     "order": order, "sequential": True},
            "rows": rows,
        }


def run_interface() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="t373-interface.") as root_s:
        root = Path(root_s)
        exec_home = make_home(root, "exec-home")
        app_home = make_home(root, "app-home")
        cwd = root / "cwd"
        cwd.mkdir()
        rows = []
        for sequence in range(1, 3):
            row = exec_turn(home=exec_home, cwd=cwd, prompt=INTERFACE_INITIAL,
                            effort="high", schema=None)
            row.update(sequence=sequence, phase="aa_noise", cell="exec", turn="initial")
            rows.append(summarized_row(row))

        app = AppServer(home=app_home, cwd=cwd, effort="high")
        app_meta = None
        try:
            for offset, cell in enumerate(["exec", "app_server", "exec", "app_server"], 3):
                if cell == "exec":
                    initial = exec_turn(home=exec_home, cwd=cwd, prompt=INTERFACE_INITIAL,
                                        effort="high", schema=None)
                    initial.update(sequence=offset, phase="confirmatory", cell=cell, turn="initial")
                    rows.append(summarized_row(initial))
                    continuation = exec_turn(
                        home=exec_home, cwd=cwd, prompt=INTERFACE_CONTINUE, effort="high",
                        schema=None, resume_id=initial.get("thread_id"),
                    )
                else:
                    thread_id, thread_start_ms = app.start_thread()
                    initial = app.turn(thread_id, INTERFACE_INITIAL)
                    initial.update(sequence=offset, phase="confirmatory", cell=cell,
                                   turn="initial", thread_start_ms=thread_start_ms)
                    rows.append(summarized_row(initial))
                    continuation = app.turn(thread_id, INTERFACE_CONTINUE)
                continuation.update(sequence=offset, phase="confirmatory", cell=cell,
                                    turn="continuation")
                rows.append(summarized_row(continuation))
        finally:
            app_meta = app.close()
        return {
            "meta": {"ts": utc_now(), "model": MODEL, "effort": "high",
                     "binary": shutil.which("codex"),
                     "version": subprocess.check_output(["codex", "--version"], text=True).strip(),
                     "aa_order": ["exec", "exec"],
                     "confirmatory_order": ["exec", "app_server", "exec", "app_server"],
                     "sequential": True, "app_server": app_meta},
            "rows": rows,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["effort", "interface"])
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run_effort() if args.suite == "effort" else run_interface()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
