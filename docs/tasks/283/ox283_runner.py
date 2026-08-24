#!/usr/bin/env python3
"""#283: guarded Ox-only production HarnessBackend/AgentLoop run.

The runner is copied to a remote scratch directory, never to the live checkout.  It reads the
remote .env key into process memory, isolates the OpenRouter counter and session store, and emits
sanitized JSON only.  No model other than stealth/ox-alpha is present in this file.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

MODEL = "stealth/ox-alpha"
MAX_HTTP_ATTEMPTS = 40
MAX_TASK_HTTP_ATTEMPTS = 10
MIN_MEM_KIB = 4 * 1024 * 1024
MAX_STARTS_PER_MINUTE = 18
PRICE_FIELDS = {
    "prompt", "completion", "request", "image", "web_search", "internal_reasoning",
    "input_cache_read", "input_cache_write",
}
OVERRIDE_CONDITIONS = {"min_prompt_tokens", "utc_start", "utc_end"}
SECRET_RE = re.compile(
    r"sk-or-v1-[A-Za-z0-9_-]+|y0_[A-Za-z0-9_-]+|ya29\.[A-Za-z0-9._-]+|"
    r"gh[pousr]_[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]{25,}"
)

TASKS = {
    "closed_edit": {
        "max_rounds": 12,
        "prompt": (
            "Fix registry.py only. eligible(entries, required_features) must preserve input "
            "order; keep only enabled, non-expired entries whose price is exactly numeric zero "
            "and whose feature set contains every required feature. Booleans are not numeric "
            "prices. Use the available tools, call test until it passes, then summarize."
        ),
        "files": {
            "registry.py": '''def eligible(entries, required_features):
    """Return entries safe for the requested feature set."""
    return [entry for entry in entries if entry.get("enabled", True)]
''',
            "test_registry.py": '''import unittest
from registry import eligible

class RegistryTests(unittest.TestCase):
    def test_preserves_order(self):
        rows = [{"id": "b", "price": 0, "features": ["tools"]}, {"id": "a", "price": 0, "features": ["tools"]}]
        self.assertEqual([r["id"] for r in eligible(rows, {"tools"})], ["b", "a"])
    def test_disabled_rejected(self):
        self.assertEqual(eligible([{"id": "x", "enabled": False, "price": 0, "features": ["tools"]}], {"tools"}), [])
    def test_expired_rejected(self):
        self.assertEqual(eligible([{"id": "x", "expired": True, "price": 0, "features": ["tools"]}], {"tools"}), [])
    def test_positive_and_string_price_rejected(self):
        rows = [{"id": "p", "price": 0.01, "features": ["tools"]}, {"id": "s", "price": "0", "features": ["tools"]}]
        self.assertEqual(eligible(rows, {"tools"}), [])
    def test_boolean_price_rejected(self):
        self.assertEqual(eligible([{"id": "x", "price": False, "features": ["tools"]}], {"tools"}), [])
    def test_all_required_features(self):
        rows = [{"id": "one", "price": 0, "features": ["tools"]}, {"id": "both", "price": 0.0, "features": ["tools", "json"]}]
        self.assertEqual([r["id"] for r in eligible(rows, {"tools", "json"})], ["both"])
''',
        },
    },
    "closed_trace": {
        "max_rounds": 10,
        "prompt": (
            "Trace the production call path starting at api.create('alpha'). Ignore decoy.py. "
            "Write answer.json with keys path (ordered list of function names), runtime, "
            "post_url, and paid_fallback_reachable (boolean). Use test to validate only the "
            "answer shape; the exact answer is graded after you finish."
        ),
        "files": {
            "api.py": "from registry import build\ndef create(name):\n    return build(name).send()\n",
            "registry.py": "from backend import HarnessBackend\nROUTES = {'alpha': ('harness', HarnessBackend)}\ndef build(name):\n    runtime, factory = ROUTES[name]\n    return factory(runtime)\n",
            "backend.py": "from client import Client\nclass HarnessBackend:\n    def __init__(self, runtime): self.runtime = runtime\n    def send(self): return Client(self.runtime).complete()\n",
            "client.py": "class Client:\n    def __init__(self, runtime): self.runtime = runtime\n    def complete(self): return self.post('/v1/chat/completions')\n    def post(self, url): return {'runtime': self.runtime, 'url': url}\n",
            "decoy.py": "def paid_fallback():\n    return 'paid/model'\n",
        },
    },
    "open_audit": {
        "max_rounds": 14,
        "prompt": (
            "Audit budget.py for correctness and paid-request risk. Do not fix it. Write "
            "findings.json as {\"categories\": [...]} using only these categories: late_count, "
            "local_timezone, incomplete_price_check, paid_fallback, unhealthy_remaining, "
            "lock_contention, integer_overflow, duplicate_retry. Include every supported finding "
            "and no speculative category. Use read/grep and finish with a short verdict."
        ),
        "files": {
            "budget.py": '''from datetime import datetime

LIMIT = 1000
attempts = []
healthy = True

def request(client, model, body):
    try:
        response = client.post(model=model, body=body)
        attempts.append((datetime.now().date().isoformat(), response.status_code))
        return response
    except OSError:
        return None

def free_metadata(pricing):
    return float(pricing.get("prompt", 0)) == 0 and float(pricing.get("completion", 0)) == 0

def fallback(model):
    return model.removesuffix(":free")

def remaining():
    return max(LIMIT - len(attempts), 0)
''',
            "README.md": "The counter must include every HTTP attempt, reset on UTC dates, and fail closed when unhealthy. Paid fallbacks are forbidden. Price metadata may add fields over time.\n",
        },
    },
}


def _sanitize(value):
    if isinstance(value, str):
        return SECRET_RE.sub("[REDACTED_SECRET]", value)
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()
                if str(k).lower() not in {"authorization", "api_key"}}
    return value


def _load_key(path: Path) -> str:
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() in {"OPENROUTER_API_KEY", "OPENROUTER_KEY"}:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def _mem_available_kib() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    return 0


class RollingLimiter:
    def __init__(self):
        self.starts = deque()

    async def acquire(self):
        while True:
            now = time.monotonic()
            while self.starts and now - self.starts[0] >= 60:
                self.starts.popleft()
            if len(self.starts) < MAX_STARTS_PER_MINUTE:
                self.starts.append(now)
                return
            await asyncio.sleep(min(10.0, 60 - (now - self.starts[0]) + 0.05))


class MemoryStore:
    """SessionStore-compatible in-memory object: no live repo/session file writes."""
    def __init__(self, _directory, session_id=None):
        self.session_id = session_id or "283-memory-session"
        self.messages = []

    def load(self):
        return list(self.messages)

    async def append_messages(self, messages):
        self.messages.extend(messages)

    async def close(self):
        return None


class TestMCP:
    SCHEMA = {"type": "function", "function": {
        "name": "test",
        "description": "Run the fixed external task check; hidden expected answers are not shown.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }}

    def __init__(self, task, cwd):
        self.task, self.cwd = task, cwd

    def has_tool(self, name):
        return name == "test"

    async def call(self, name, _args):
        if name != "test":
            return "[mcp error] unknown tool"
        if self.task == "closed_edit":
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "unittest", "-q", cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await proc.communicate()
            return f"exit_code={proc.returncode}\n" + out.decode(errors="replace")[-4000:]
        target = "answer.json" if self.task == "closed_trace" else "findings.json"
        try:
            obj = json.loads((self.cwd / target).read_text())
        except Exception as exc:
            return f"shape_invalid: {type(exc).__name__}: {exc}"
        return "shape_valid" if isinstance(obj, dict) else "shape_invalid: root must be object"


def _score(task, cwd):
    if task == "closed_edit":
        proc = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=cwd,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=30)
        outcomes = re.findall(r"\.\.\. (ok|FAIL|ERROR)$", proc.stdout, flags=re.M)
        return {"score": sum(v == "ok" for v in outcomes) / len(outcomes) if outcomes else 0.0,
                "passed": sum(v == "ok" for v in outcomes), "total": len(outcomes),
                "exit_code": proc.returncode, "tail": proc.stdout[-2000:]}
    if task == "closed_trace":
        expected_subsequence = ["create", "build", "HarnessBackend.send", "Client.complete", "Client.post"]
        try:
            got = json.loads((cwd / "answer.json").read_text())
            path = got.get("path")
            pos = -1
            for item in expected_subsequence:
                pos = path.index(item, pos + 1)
        except Exception as exc:
            return {"score": 0.0, "matched": 0, "total": 4,
                    "error": f"{type(exc).__name__}: {exc}"}
        checks = [
            all(isinstance(path, list) for _ in [0]),
            got.get("runtime") == "harness",
            got.get("post_url") == "/v1/chat/completions",
            got.get("paid_fallback_reachable") is False,
        ]
        return {"score": sum(checks) / 4, "matched": sum(checks), "total": 4,
                "path_subsequence": True}
    real = {"late_count", "local_timezone", "incomplete_price_check", "paid_fallback", "unhealthy_remaining"}
    allowed = real | {"lock_contention", "integer_overflow", "duplicate_retry"}
    try:
        got = set(json.loads((cwd / "findings.json").read_text()).get("categories", []))
    except Exception as exc:
        return {"score": 0, "tp": 0, "fp": 0, "error": f"{type(exc).__name__}: {exc}"}
    got &= allowed
    tp, fp = len(got & real), len(got - real)
    return {"score": max(0, min(10, 2 * tp - fp)), "tp": tp, "fp": fp,
            "missed": sorted(real - got), "reported": sorted(got)}


def _valid_alternate_control():
    """Positive control: a structurally different valid edit must pass the RED oracle."""
    def alternate(entries, required_features):
        return [entry for entry in entries
                if entry.get("enabled", True)
                and not entry.get("expired", False)
                and isinstance(entry.get("price"), (int, float))
                and not isinstance(entry.get("price"), bool)
                and entry.get("price") == 0
                and set(required_features).issubset(entry.get("features", []))]
    checks = [
        [r["id"] for r in alternate([{"id": "b", "price": 0, "features": ["tools"]},
                                     {"id": "a", "price": 0, "features": ["tools"]}], {"tools"})] == ["b", "a"],
        alternate([{"enabled": False, "price": 0, "features": ["tools"]}], {"tools"}) == [],
        alternate([{"expired": True, "price": 0, "features": ["tools"]}], {"tools"}) == [],
        alternate([{"price": 0.01, "features": ["tools"]}, {"price": "0", "features": ["tools"]}], {"tools"}) == [],
        alternate([{"price": False, "features": ["tools"]}], {"tools"}) == [],
        [r["id"] for r in alternate([{"id": "one", "price": 0, "features": ["tools"]},
                                      {"id": "both", "price": 0.0, "features": ["tools", "json"]}], {"tools", "json"})] == ["both"],
    ]
    return all(checks)


async def _page_receipt(http):
    url = "https://openrouter.ai/stealth/ox-alpha"
    resp = await http.get(url)
    body = resp.content
    return {"url": url, "status_code": resp.status_code, "content_sha256": hashlib.sha256(body).hexdigest(),
            "content_bytes": len(body), "content_head": body[:300].decode(errors="replace")}


async def main(args):
    scratch = Path(args.scratch).resolve()
    output = Path(args.output).resolve()
    repo = Path(args.repo).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    if scratch == repo or scratch in repo.parents or repo in scratch.parents:
        raise SystemExit("scratch must be outside live repo/worktrees")
    mem = _mem_available_kib()
    key = _load_key(repo / ".env")
    if mem < MIN_MEM_KIB:
        raise SystemExit(f"MemAvailable<{MIN_MEM_KIB}: {mem}")
    if not key:
        raise SystemExit("OpenRouter key missing")
    os.environ["OPENROUTER_DB_PATH"] = str(scratch / "isolated-counter.db")
    os.environ["ORCHESTRA_DB_PATH"] = str(scratch / "isolated-counter.db")
    os.environ["OPENROUTER_API_KEY"] = key
    sys.path.insert(0, str(repo))
    import httpx
    from app import backend_harness as backend_mod, db
    from app.harness import llm as llm_mod, tools as builtin
    db.init_db()
    backend_mod.SessionStore = MemoryStore

    limiter = RollingLimiter()
    guard_rows = []
    global_attempts = 0
    task_attempts = 0
    current_task = ""
    consecutive_empty = 0
    fatal = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30), trust_env=False) as http:
        page = await _page_receipt(http)
        (output / "provider-page.json").write_text(json.dumps(_sanitize(page), indent=2) + "\n")

        async def guard(model):
            nonlocal global_attempts, task_attempts
            if global_attempts >= MAX_HTTP_ATTEMPTS:
                raise RuntimeError("global inference-attempt cap reached")
            if task_attempts >= MAX_TASK_HTTP_ATTEMPTS:
                raise RuntimeError(f"task attempt cap reached: {current_task}")
            meta_url = "https://openrouter.ai/api/v1/model/" + model
            resp = await http.get(meta_url)
            resp.raise_for_status()
            row = resp.json().get("data") or {}
            if row.get("id") != model:
                raise RuntimeError(f"metadata id mismatch: {row.get('id')!r}")
            pricing = row.get("pricing") or {}
            if not pricing:
                raise RuntimeError("metadata pricing missing")
            unknown = set(pricing) - PRICE_FIELDS - {"overrides"}
            if unknown:
                raise RuntimeError(f"unknown pricing fields: {sorted(unknown)}")
            def zero(v):
                if isinstance(v, bool):
                    return False
                try:
                    return float(v) == 0.0
                except (TypeError, ValueError):
                    return False
            allowed = all(zero(v) for k, v in pricing.items() if k in PRICE_FIELDS)
            for override in pricing.get("overrides") or []:
                extra = set(override) - PRICE_FIELDS - OVERRIDE_CONDITIONS
                if extra or not all(zero(v) for k, v in override.items() if k in PRICE_FIELDS):
                    allowed = False
            if not allowed:
                raise RuntimeError("free guard rejected nonzero/unknown price")
            guard_rows.append({"task": current_task, "attempt": global_attempts + 1,
                               "url": meta_url, "id": row.get("id"), "pricing": pricing,
                               "supported_parameters": row.get("supported_parameters"),
                               "context_length": row.get("context_length"), "allowed": True})
            await limiter.acquire()
            global_attempts += 1
            task_attempts += 1

        class GuardedClient(llm_mod.OpenRouterClient):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.attempts = 0
                self.rate_kinds = {"platform": 0, "upstream": 0}
                self.raw_usages = []

            async def _one_attempt(self, body, headers, attempt_row=None):
                if body.get("model") != self.model or "models" in body:
                    raise RuntimeError("request model/fallback invariant violated")
                await guard(self.model)
                self.attempts += 1
                try:
                    async for event in super()._one_attempt(body, headers, attempt_row):
                        if event.kind == "final":
                            self.raw_usages.append(dict(event.usage or {}))
                        yield event
                except llm_mod._RetryableStatus as exc:
                    self.rate_kinds[exc.kind] += 1
                    if exc.kind == "platform":
                        raise RuntimeError("platform 429: terminal stop") from exc
                    raise

        results = []
        order = ["closed_edit", "closed_trace", "open_audit", "open_audit", "closed_trace", "closed_edit"]
        for index, task_name in enumerate(order, start=1):
            if fatal:
                break
            repetition = 1 if index <= 3 else 2
            task = TASKS[task_name]
            current_task, task_attempts = task_name, 0
            run_id = f"r{repetition}-{task_name}"
            cwd = scratch / "fixtures" / run_id
            cwd.mkdir(parents=True)
            for rel, content in task["files"].items():
                path = cwd / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            backend = None
            started = time.monotonic()
            try:
                backend = backend_mod.HarnessBackend(
                    model=MODEL, cwd=str(cwd),
                    system_prompt=("You are an agent in a public isolated fixture. Use only the "
                                   "offered fixture tools. Never use review, never access paths "
                                   "outside cwd, and verify the requested artifact before ending."),
                    mcp_servers={}, is_orchestrator=False)
                await backend.connect()
                if backend._mcp is not None:
                    await backend._mcp.disconnect()
                backend._mcp = TestMCP(task_name, cwd)
                backend._llm = GuardedClient(key, MODEL, http=http)
                backend._tool_schemas = [s for s in builtin.tool_schemas()
                                         if s["function"]["name"] != "bash"] + [TestMCP.SCHEMA]
                backend._turn_tool_schemas = lambda _effort, allow_review=True: backend._tool_schemas
                await backend.send(task["prompt"])
                events = []
                async for event in backend.events():
                    events.append({"type": event.type, "content": event.content,
                                   "metadata": event.metadata, "usage": getattr(event.usage, "metadata", lambda: {})() if event.usage else {}})
                client = backend._llm
                usage_costs = [float(usage["cost"]) for usage in client.raw_usages
                               if usage.get("cost") is not None]
                tool_calls = sum(event["type"] == "tool_use" for event in events)
                round_count = sum(event["type"] == "thinking" for event in events)
                empty = tool_calls == 0 and not any(event["type"] == "text" and event["content"] for event in events)
                consecutive_empty = consecutive_empty + 1 if empty else 0
                row = {
                    "run_id": run_id, "repetition": repetition, "task": task_name, "model": MODEL,
                    "elapsed_seconds": round(time.monotonic() - started, 3), "ok": True,
                    "stop_reason": events[-1]["metadata"].get("stop_reason") if events else "no_events",
                    "effort": ("high" if task_name != "open_audit" else "medium"),
                    "http_attempts": client.attempts, "tool_calls": tool_calls,
                    "event_round_markers": round_count, "rate_limits": client.rate_kinds,
                    "reported_costs": usage_costs, "empty_response": empty,
                    "grade": _score(task_name, cwd), "events": _sanitize(events),
                }
                results.append(_sanitize(row))
                (output / f"{run_id}.json").write_text(json.dumps(_sanitize(row), ensure_ascii=False, indent=2) + "\n")
                if any(cost != 0 for cost in usage_costs):
                    fatal = "nonzero usage.cost"
                elif consecutive_empty >= 2:
                    fatal = "two consecutive empty responses"
            except Exception as exc:
                fatal = f"{type(exc).__name__}: {exc}"
                row = {"run_id": run_id, "task": task_name, "model": MODEL,
                       "error": fatal, "elapsed_seconds": round(time.monotonic() - started, 3),
                       "http_attempts": task_attempts, "empty_response": False}
                results.append(row)
                (output / f"{run_id}.json").write_text(json.dumps(row, indent=2) + "\n")
            finally:
                if backend is not None:
                    try:
                        await backend.disconnect()
                    except Exception as exc:
                        fatal = fatal or f"incomplete cleanup: {type(exc).__name__}: {exc}"

    (output / "guard.json").write_text(json.dumps(_sanitize(guard_rows), ensure_ascii=False, indent=2) + "\n")
    summary = {"model": MODEL, "runs": len(results), "global_http_attempts": global_attempts,
               "valid_alternate_control": _valid_alternate_control(),
               "fatal": fatal or None, "mem_available_kib": mem,
               "tasks": [{"run_id": row.get("run_id"), "task": row.get("task"),
                          "score": (row.get("grade") or {}).get("score"),
                          "http_attempts": row.get("http_attempts"),
                          "empty_response": row.get("empty_response")} for row in results]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    if fatal:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/home/kesha/orchestra")
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
