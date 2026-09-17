#!/usr/bin/env python3
"""Probe OpenRouter `:free` routes for real tool-protocol capability (#V-581, #V-582).

What the catalog advertises and what a route actually does are different things. A route
passes here only if it walks the WHOLE protocol Orchestra's harness needs: call the tool,
pass a sane argument, then answer FROM the tool's result. A model that calls the tool and
then ignores what came back is a failure — that is exactly how
`nvidia/nemotron-3-ultra-550b-a55b:free` was dead while advertising tools.

Spend is bounded before the first call: `--requests-per-route` (default 2, the protocol
minimum) and `--budget-seconds`. Routes left unprobed when the budget runs out are
reported as `not_probed`, never silently dropped.

    python scripts/probe_free_models.py --out probe.json
    python scripts/probe_free_models.py --model cohere/north-mini-code:free
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1"
MARKER = 4242  # the tool's answer; the final text must contain it
TOOLS = [{
    "type": "function",
    "function": {
        "name": "line_count",
        "description": "Return the number of lines in a repository file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Repo-relative path"}},
            "required": ["path"],
        },
    },
}]
ASK = ("Use the line_count tool for the file app/quota_gate.py, then reply with the "
       "number it returned and nothing else.")


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise SystemExit("no API key: set OPENROUTER_API_KEY (or OPENROUTER_KEY)")
    return key


def _post(key: str, model: str, messages: list, timeout: int) -> tuple[int, dict, float]:
    body = json.dumps({"model": model, "messages": messages, "tools": TOOLS,
                       "tool_choice": "auto", "max_tokens": 700}).encode()
    req = urllib.request.Request(
        f"{API}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read()), time.time() - started
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")[:400]
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"error": {"message": raw}}
        return error.code, payload, time.time() - started
    except Exception as error:  # a timeout or a dropped connection is also a result
        return 0, {"error": {"message": f"{type(error).__name__}: {error}"}}, time.time() - started


def _error_text(payload: dict) -> str:
    return str((payload.get("error") or {}).get("message", ""))[:200]


def probe(key: str, model: str, *, timeout: int, max_requests: int) -> dict:
    """Run the tool protocol against one route and classify the outcome."""
    out = {"model": model, "status": "", "seconds": 0.0, "requests": 0,
           "tool_call": False, "argument_ok": False, "used_result": False, "detail": ""}
    messages = [{"role": "user", "content": ASK}]
    spent = 0.0

    code, data, took = _post(key, model, messages, timeout)
    out["requests"] += 1
    spent += took
    while code == 429 and out["requests"] < max_requests - 1:
        time.sleep(20)
        code, data, took = _post(key, model, messages, timeout)
        out["requests"] += 1
        spent += took
    out["seconds"] = round(spent, 1)
    if code != 200:
        out["status"] = "rate_limited" if code == 429 else (
            "timeout" if code == 0 else f"http_{code}"
        )
        out["detail"] = _error_text(data)
        return out

    message = ((data.get("choices") or [{}])[0].get("message") or {})
    calls = message.get("tool_calls") or []
    if not calls:
        out["status"] = "no_tool_call"
        out["detail"] = str(message.get("content", ""))[:200]
        return out
    out["tool_call"] = True
    function = calls[0].get("function") or {}
    try:
        args = json.loads(function.get("arguments") or "{}")
    except ValueError:
        args = {}
    out["argument_ok"] = (
        function.get("name") == "line_count" and "quota_gate" in str(args.get("path", ""))
    )

    if out["requests"] >= max_requests:
        out["status"] = "budget_exhausted"
        out["detail"] = f"tool call made, no request left for round 2 (max {max_requests})"
        return out

    messages += [
        {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls},
        {"role": "tool", "tool_call_id": calls[0].get("id", "call_1"),
         "name": "line_count", "content": str(MARKER)},
    ]
    code, data, took = _post(key, model, messages, timeout)
    out["requests"] += 1
    spent += took
    out["seconds"] = round(spent, 1)
    if code != 200:
        out["status"] = "rate_limited" if code == 429 else (
            "timeout" if code == 0 else f"http_{code}"
        )
        out["detail"] = _error_text(data)
        return out

    text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    out["used_result"] = str(MARKER) in text
    out["detail"] = text.strip().replace("\n", " ")[:200]
    if not out["used_result"]:
        out["status"] = "result_ignored"
    elif not out["argument_ok"]:
        out["status"] = "wrong_argument"
    else:
        out["status"] = "ok"
    return out


def free_tool_routes(timeout: int) -> list[dict]:
    """Live catalog, narrowed to exact `:free` routes that advertise tools."""
    with urllib.request.urlopen(f"{API}/models", timeout=timeout) as resp:
        catalog = json.loads(resp.read())["data"]
    routes = [entry for entry in catalog
              if str(entry.get("id", "")).endswith(":free")
              and "tools" in (entry.get("supported_parameters") or [])]
    routes.sort(key=lambda entry: -(entry.get("context_length") or 0))
    return routes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the JSON report here instead of stdout")
    parser.add_argument("--model", action="append", default=[],
                        help="probe only this route (repeatable)")
    parser.add_argument("--limit", type=int, default=0, help="probe at most N routes")
    parser.add_argument("--requests-per-route", type=int, default=2,
                        help="hard per-route request ceiling; 2 is the protocol minimum")
    parser.add_argument("--budget-seconds", type=float, default=1200.0,
                        help="stop probing after this much wall time")
    parser.add_argument("--timeout", type=int, default=90, help="per-request timeout")
    args = parser.parse_args(argv)

    if args.requests_per_route < 2:
        parser.error("--requests-per-route must be at least 2: the protocol needs two calls")

    key = _api_key()
    started = time.time()
    deadline = started + args.budget_seconds
    catalog = free_tool_routes(args.timeout)
    if args.model:
        wanted = set(args.model)
        known = {entry["id"]: entry for entry in catalog}
        catalog = [known.get(mid, {"id": mid, "context_length": None}) for mid in wanted]
    if args.limit:
        catalog = catalog[:args.limit]

    results = []
    for entry in catalog:
        if time.time() >= deadline:
            results.append({"model": entry["id"], "status": "not_probed", "seconds": 0.0,
                            "requests": 0, "tool_call": False, "argument_ok": False,
                            "used_result": False, "detail": "time budget exhausted",
                            "context_length": entry.get("context_length")})
            continue
        row = probe(key, entry["id"], timeout=args.timeout,
                    max_requests=args.requests_per_route)
        row["context_length"] = entry.get("context_length")
        results.append(row)
        print(f"{row['status']:<16} {row['model']:<50} {row['seconds']:>6}s "
              f"req={row['requests']} call={row['tool_call']} arg={row['argument_ok']} "
              f"used={row['used_result']} | {row['detail'][:100]}",
              file=sys.stderr, flush=True)

    report = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "seconds": round(time.time() - started, 1),
        "requests_per_route": args.requests_per_route,
        "candidates": len(catalog),
        "passed": [row["model"] for row in results if row["status"] == "ok"],
        "results": results,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        print(f"\nполный протокол прошли {len(report['passed'])} из {len(results)} "
              f"→ {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
