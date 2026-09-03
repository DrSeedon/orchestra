#!/usr/bin/env python3
"""One exact-JSON measurement-path canary per transport-live route."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from run_pilot import API, ROOT, SYSTEM, load_key, parse_exact_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--availability", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    availability = json.loads(Path(args.availability).read_text(encoding="utf-8"))
    routes = [
        run["route"] for run in availability["runs"]
        if run["call_outcome"] == "provider_success"
    ]
    case = json.loads(Path(__file__).with_name("pilot_cases.json").read_text(encoding="utf-8"))["cases"][0]
    packet = {
        "case_id": case["case_id"],
        "step": 1,
        "steps_total": len(case["observations"]),
        "memory_mode": "mutable_state",
        "current_state": {},
        "latest_observation": {"event_id": f"{case['case_id']}-E01", "text": case["observations"][0]},
        "final": False,
        "final_action_keys": [],
    }
    headers = {"Authorization": f"Bearer {load_key()}", "Content-Type": "application/json"}
    output = {"schema": "skillstate430-format-canary-v1", "runs": []}
    with httpx.Client(timeout=args.timeout) as client:
        for route in routes:
            body = {
                "model": route,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(packet, ensure_ascii=False, sort_keys=True)},
                ],
                "stream": False,
                "temperature": 0,
                "max_tokens": 700,
                "usage": {"include": True},
            }
            record = {"route": route, "http_attempts": 1}
            try:
                response = client.post(API, headers=headers, json=body)
                record["http_status"] = response.status_code
                payload = response.json()
                record["payload_error"] = payload.get("error")
                choices = payload.get("choices") or []
                if response.status_code >= 400:
                    record["call_outcome"] = f"provider_http_{response.status_code}"
                elif not choices:
                    record["call_outcome"] = "provider_malformed_success"
                    record["payload_keys"] = sorted(payload)
                else:
                    message = choices[0].get("message") or {}
                    content = message.get("content") or ""
                    _, parse_outcome = parse_exact_json(content)
                    record.update({
                        "call_outcome": "provider_success",
                        "model_parse_outcome": parse_outcome,
                        "response_model": payload.get("model"),
                        "usage": payload.get("usage") or {},
                        "content": content,
                    })
            except (ValueError, httpx.TimeoutException, httpx.TransportError) as exc:
                record.update({
                    "call_outcome": "provider_transport_error",
                    "detail": type(exc).__name__,
                })
            output["runs"].append(record)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
