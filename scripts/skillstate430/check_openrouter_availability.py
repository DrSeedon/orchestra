#!/usr/bin/env python3
"""Transport-only availability canary for exact-free OpenRouter routes.

The canary does not grade model quality.  Every request has one attempt; HTTP/provider
failures are recorded separately so they cannot be mistaken for model outcomes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx


API = "https://openrouter.ai/api/v1"
PREFERRED = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"


def _load_key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if value:
        return value
    env_path = Path(__file__).resolve().parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("OPENROUTER_API_KEY="):
            continue
        value = line.split("=", 1)[1].strip().strip("\"'")
        if value:
            return value
    raise RuntimeError("OPENROUTER_API_KEY is missing")


def _eligible(model: dict) -> bool:
    architecture = model.get("architecture") or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []
    parameters = model.get("supported_parameters") or []
    return (
        str(model.get("id", "")).endswith(":free")
        and "text" in input_modalities
        and "text" in output_modalities
        and "tools" in parameters
    )


def _failure(status: int | None, detail: str) -> str:
    if status == 404:
        return "provider_404"
    if status == 429:
        return "provider_429"
    if status is not None:
        return f"provider_http_{status}"
    if "timeout" in detail.lower():
        return "provider_timeout"
    return "provider_transport_error"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-routes", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()
    key = _load_key()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    output: dict = {"schema": "skillstate430-availability-v1", "catalog": {}, "runs": []}
    with httpx.Client(timeout=args.timeout) as client:
        response = client.get(f"{API}/models", headers=headers)
        output["catalog"] = {"status": response.status_code}
        response.raise_for_status()
        eligible = [item for item in response.json().get("data", []) if _eligible(item)]
        by_id = {item["id"]: item for item in eligible}
        ordered = ([PREFERRED] if PREFERRED in by_id else []) + sorted(
            route for route in by_id if route != PREFERRED
        )
        output["catalog"]["eligible_exact_free_text_tools"] = len(ordered)
        output["catalog"]["selected"] = ordered[: args.max_routes]
        for route in ordered[: args.max_routes]:
            body = {
                "model": route,
                "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                "max_tokens": 8,
                "stream": False,
                "temperature": 0,
            }
            record = {"route": route, "attempts": 1}
            try:
                result = client.post(f"{API}/chat/completions", headers=headers, json=body)
                record["http_status"] = result.status_code
                if result.status_code >= 400:
                    record["call_outcome"] = _failure(result.status_code, result.text)
                    record["detail"] = result.text[:300]
                else:
                    payload = result.json()
                    choices = payload.get("choices") or []
                    if choices:
                        record["call_outcome"] = "provider_success"
                        record["response_model"] = payload.get("model")
                    else:
                        record["call_outcome"] = "provider_malformed_success"
                    usage = payload.get("usage") or {}
                    record["usage"] = {
                        key: usage.get(key)
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
                        if usage.get(key) is not None
                    }
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                record["call_outcome"] = _failure(None, type(exc).__name__)
                record["detail"] = type(exc).__name__
            output["runs"].append(record)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
