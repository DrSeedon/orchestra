#!/usr/bin/env python3
"""Frozen #236 free-only model comparison; run only in an isolated scratch dir."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import deque
from pathlib import Path


MODELS = (
    "stealth/ox-alpha",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "inclusionai/ling-3.0-flash:free",
)
PRICE_FIELDS = {
    "prompt", "completion", "request", "image", "web_search",
    "internal_reasoning", "input_cache_read", "input_cache_write",
}
OVERRIDE_CONDITIONS = {"min_prompt_tokens", "utc_start", "utc_end"}
MAX_HTTP_ATTEMPTS = 220
MAX_STARTS_PER_MINUTE = 18
SECRET_RE = re.compile(
    r"sk-or-" r"v1-[A-Za-z0-9_-]+|y0_[A-Za-z0-9_-]+|ya29\.[A-Za-z0-9._-]+|"
    r"gh[pousr]_[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+|Bear" r"er\s+[A-Za-z0-9._-]{25,}"
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
    def test_positive_and_string_prices_rejected(self):
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
            "api.py": '''from registry import build
def create(name):
    return build(name).send()
''',
            "registry.py": '''from backend import HarnessBackend
ROUTES = {"alpha": ("harness", HarnessBackend)}
def build(name):
    runtime, factory = ROUTES[name]
    return factory(runtime)
''',
            "backend.py": '''from client import Client
class HarnessBackend:
    def __init__(self, runtime): self.runtime = runtime
    def send(self): return Client(self.runtime).complete()
''',
            "client.py": '''class Client:
    def __init__(self, runtime): self.runtime = runtime
    def complete(self): return self.post("/v1/chat/completions")
    def post(self, url): return {"runtime": self.runtime, "url": url}
''',
            "decoy.py": '''def paid_fallback():
    return "paid/model"
''',
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
            "README.md": '''The counter must include every HTTP attempt, reset on UTC dates, and fail closed when unhealthy. Paid fallbacks are forbidden. Price metadata may add fields over time.''',
        },
    },
}


def _load_env_value(path: Path, name: str) -> str:
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def _sanitize(value):
    if isinstance(value, str):
        return SECRET_RE.sub("[REDACTED_SECRET]", value)
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items() if str(k).lower() not in {"authorization", "api_key"}}
    return value


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


class TestMCP:
    SCHEMA = {"type": "function", "function": {
        "name": "test",
        "description": "Run the fixed task check. It never reveals hidden expected answers.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }}

    def __init__(self, task: str, cwd: Path):
        self.task = task
        self.cwd = cwd

    def has_tool(self, name):
        return name == "test"

    async def call(self, name, _args):
        if name != "test":
            return "[mcp error] unknown tool"
        if self.task == "closed_edit":
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "unittest", "-q", cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            return f"exit_code={proc.returncode}\n" + out.decode(errors="replace")[-4000:]
        target = "answer.json" if self.task == "closed_trace" else "findings.json"
        try:
            parsed = json.loads((self.cwd / target).read_text())
        except Exception as exc:
            return f"shape_invalid: {type(exc).__name__}: {exc}"
        return "shape_valid" if isinstance(parsed, dict) else "shape_invalid: root must be object"


def _score(task: str, cwd: Path) -> dict:
    if task == "closed_edit":
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "-v"], cwd=cwd,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
        )
        outcomes = re.findall(r"\.\.\. (ok|FAIL|ERROR)$", proc.stdout, flags=re.M)
        total = len(outcomes)
        passed = sum(value == "ok" for value in outcomes)
        return {"score": passed / total if total else 0.0,
                "passed": passed, "total": total,
                "exit_code": proc.returncode, "tail": proc.stdout[-2000:]}
    if task == "closed_trace":
        expected = {
            "path": ["create", "build", "HarnessBackend.send", "Client.complete", "Client.post"],
            "runtime": "harness", "post_url": "/v1/chat/completions",
            "paid_fallback_reachable": False,
        }
        try:
            got = json.loads((cwd / "answer.json").read_text())
        except Exception as exc:
            return {"score": 0.0, "matched": 0, "total": 4, "error": f"{type(exc).__name__}: {exc}"}
        matched = sum(got.get(k) == v for k, v in expected.items())
        return {"score": matched / 4, "matched": matched, "total": 4}
    real = {"late_count", "local_timezone", "incomplete_price_check", "paid_fallback", "unhealthy_remaining"}
    allowed = real | {"lock_contention", "integer_overflow", "duplicate_retry"}
    try:
        got = json.loads((cwd / "findings.json").read_text()).get("categories", [])
    except Exception as exc:
        return {"score": 0, "tp": 0, "fp": 0, "error": f"{type(exc).__name__}: {exc}"}
    categories = {str(v) for v in got if str(v) in allowed}
    tp, fp = len(categories & real), len(categories - real)
    return {"score": max(0, min(10, 2 * tp - fp)), "tp": tp, "fp": fp,
            "missed": sorted(real - categories), "reported": sorted(categories)}


async def main_async(args):
    scratch = Path(args.scratch).resolve()
    repo = Path(args.repo).resolve()
    output = Path(args.output).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    if repo == scratch or repo in scratch.parents or scratch in repo.parents:
        raise SystemExit("scratch must be outside the live repo and its worktrees")

    key = _load_env_value(repo / ".env", "OPENROUTER_API_KEY") or _load_env_value(repo / ".env", "OPENROUTER_KEY")
    if not key:
        raise SystemExit("OpenRouter key missing")
    os.environ["ORCHESTRA_DB_PATH"] = str(scratch / "isolated-counter.db")
    sys.path.insert(0, str(repo))
    from app import db
    db.init_db()
    from app.harness import llm as llm_mod
    from app.harness import tools as builtin
    from app.harness.loop import AgentLoop
    import httpx

    limiter = RollingLimiter()
    global_attempts = 0
    guard_rows = []

    async def guard(model: str):
        nonlocal global_attempts
        if global_attempts >= MAX_HTTP_ATTEMPTS:
            raise RuntimeError("global inference-attempt cap reached")
        url = "https://openrouter.ai/api/v1/model/" + model
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.get(url)
            response.raise_for_status()
            row = response.json().get("data") or {}
        if row.get("id") != model:
            raise RuntimeError(f"metadata id mismatch: {row.get('id')!r}")
        pricing = row.get("pricing") or {}
        unknown = set(pricing) - PRICE_FIELDS - {"overrides"}
        if unknown:
            raise RuntimeError(f"unknown pricing fields: {sorted(unknown)}")
        def is_zero(value):
            if isinstance(value, bool):
                return False
            try:
                return float(value) == 0.0
            except (TypeError, ValueError):
                return False
        zero = all(is_zero(v) for k, v in pricing.items() if k in PRICE_FIELDS)
        for override in pricing.get("overrides") or []:
            extra = set(override) - PRICE_FIELDS - OVERRIDE_CONDITIONS
            if extra or not all(is_zero(v) for k, v in override.items() if k in PRICE_FIELDS):
                zero = False
        allowed = model.endswith(":free") or (bool(pricing) and zero)
        guard_rows.append({"ts": time.time(), "model": model, "pricing": pricing,
                           "suffix_free": model.endswith(":free"), "allowed": allowed})
        if not allowed:
            raise RuntimeError(f"free-only guard rejected {model}")
        await limiter.acquire()
        global_attempts += 1

    class GuardedClient(llm_mod.OpenRouterClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.rate_kinds = {"platform": 0, "upstream": 0}
            self.attempts = 0

        async def _one_attempt(self, body, headers, attempt_row=None):
            await guard(self.model)
            self.attempts += 1
            try:
                async for event in super()._one_attempt(body, headers, attempt_row):
                    yield event
            except llm_mod._RetryableStatus as exc:
                self.rate_kinds[exc.kind] = self.rate_kinds.get(exc.kind, 0) + 1
                if exc.kind == "platform":
                    raise RuntimeError("platform free-request limit reached") from exc
                raise

    schemas = [s for s in builtin.tool_schemas() if s["function"]["name"] != "bash"] + [TestMCP.SCHEMA]
    orders = [list(MODELS), list(reversed(MODELS))]
    results = []
    fatal = ""
    for repetition, order in enumerate(orders, start=1):
        for task_name, task in TASKS.items():
            for model in order:
                if fatal:
                    break
                run_id = f"r{repetition}-{task_name}-{model.replace('/', '__').replace(':', '_')}"
                cwd = scratch / "fixtures" / run_id
                cwd.mkdir(parents=True)
                for rel, content in task["files"].items():
                    path = cwd / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                client = GuardedClient(key, model)
                history = [{"role": "system", "content": (
                    "You are a coding agent in an isolated fixture. Use only offered tools. "
                    "Do not access paths outside the fixture. Verify artifacts, finish promptly."
                )}]
                loop = AgentLoop(client, TestMCP(task_name, cwd), str(cwd), history,
                                 schemas, 128000, max_rounds=task["max_rounds"])
                events = []
                started = time.monotonic()
                try:
                    async for event in loop.run(task["prompt"]):
                        events.append({"type": event.type, "content": event.content,
                                       "metadata": event.metadata})
                except Exception as exc:
                    loop.ok = False
                    loop.error_detail = f"{type(exc).__name__}: {exc}"
                elapsed = time.monotonic() - started
                costs = [float(u.get("cost") or 0) for u in loop.round_usages]
                if any(cost != 0 for cost in costs):
                    fatal = f"nonzero usage.cost from {model}: {costs}"
                grade = _score(task_name, cwd)
                files = {}
                for target in ("registry.py", "answer.json", "findings.json"):
                    path = cwd / target
                    if path.exists():
                        files[target] = path.read_text(errors="replace")
                row = _sanitize({
                    "run_id": run_id, "repetition": repetition, "task": task_name,
                    "model": model, "elapsed_seconds": round(elapsed, 3),
                    "loadavg": list(os.getloadavg()), "ok": loop.ok,
                    "stop_reason": loop.stop_reason, "error": loop.error_detail,
                    "http_attempts": client.attempts,
                    "successful_rounds": len(loop.round_usages),
                    "tool_calls": sum(e["type"] == "tool_use" for e in events),
                    "rate_limits": client.rate_kinds, "reported_costs": costs,
                    "grade": grade, "events": events, "artifacts": files,
                })
                results.append(row)
                (output / f"{run_id}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
                await client.aclose()
            if fatal:
                break
        if fatal:
            break

    (output / "guard.json").write_text(json.dumps(_sanitize(guard_rows), ensure_ascii=False, indent=2) + "\n")
    aggregates = []
    for model in MODELS:
        rows = [r for r in results if r["model"] == model]
        normalized = []
        for row in rows:
            value = row["grade"]["score"]
            normalized.append(value / 10 if row["task"] == "open_audit" else value)
        completed = [r for r in rows if r["ok"] and r["grade"]["score"] > 0]
        attempts = sum(r["http_attempts"] for r in rows)
        rate429 = sum(sum(r["rate_limits"].values()) for r in rows)
        aggregates.append({
            "model": model, "runs": len(rows),
            "mean_normalized_score": round(statistics.mean(normalized), 4) if normalized else None,
            "completed": len(completed), "http_attempts": attempts,
            "requests_per_completed": round(attempts / len(completed), 3) if completed else None,
            "rate_limit_events": rate429,
            "failure_429_rate": round(rate429 / attempts, 4) if attempts else None,
            "median_task_latency_seconds": round(statistics.median(r["elapsed_seconds"] for r in rows), 3) if rows else None,
            "closed_eligible": all(r["grade"]["score"] == 1.0 for r in rows if r["task"].startswith("closed_")) and len([r for r in rows if r["task"].startswith("closed_")]) == 4,
            "open_eligible": all(r["grade"]["score"] >= 8 for r in rows if r["task"] == "open_audit") and len([r for r in rows if r["task"] == "open_audit"]) == 2,
        })
    summary = {"fatal": fatal or None, "global_http_attempts": global_attempts,
               "models": aggregates, "runs": len(results)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    if fatal:
        raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/home/kesha/orchestra")
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
