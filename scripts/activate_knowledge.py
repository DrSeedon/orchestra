#!/usr/bin/env python3
"""Proof-bound command line for staged typed-knowledge activation."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request


def _payload(command: str) -> dict:
    if command in {"preflight", "shadow", "state"}:
        return {"operation": "cutover", "payload": {"request": {"operation": "state"}}}
    if command == "verify":
        return {"operation": "verify", "payload": {}}
    if command == "canonical":
        return {
            "operation": "cutover",
            "payload": {"request": {
                "operation": "canonical",
                "expected_generation": 2,
                "required_gates": [
                    "live_cutover", "privacy", "projection", "prompt_delivery", "rollback",
                    "shadow_parity",
                ],
            }},
        }
    return {
        "operation": "cutover",
        "payload": {"request": {
            "operation": "rollback",
            "expected_generation": 3,
            "target_owner": "legacy",
        }},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("preflight", "shadow", "verify", "canonical", "rollback", "state"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("INTERNAL_TOKEN", "")
    session = os.environ.get("ORCHESTRA_SESSION_ID", "")
    proof = os.environ.get("ORCHESTRA_MCP_PROOF", "")
    if not token or not session or not proof:
        print(json.dumps({"ok": False, "error": "proof-bound session environment is required"}))
        return 2
    request = urllib.request.Request(
        "http://127.0.0.1:8888/api/knowledge",
        data=json.dumps(_payload(args.command)).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Orchestra-Session-Id": session,
            "X-Orchestra-Mcp-Proof": proof,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, ValueError) as error:
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
