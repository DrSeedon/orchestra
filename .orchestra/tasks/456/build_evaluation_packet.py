#!/usr/bin/env python3
"""Build the frozen, blinded #456 design-review evaluation packet."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


CASES = [
    {
        "id": "A",
        "commit": "0f415e84",
        "paths": ["app/static/js/usage.js"],
        "anchor": "function _quotaMapLaneHeadroomText",
        "radius": 38,
        "gold": "PASS",
        "basis": "presentation-only formatting of an already supplied quota value",
    },
    {
        "id": "B",
        "commit": "e3f95f98",
        "paths": ["scripts/kb_promote_facts.py"],
        "anchor": "def stable_fact_id",
        "radius": 24,
        "gold": "STOP",
        "basis": "a durable fact identity is derived from mutable statement text",
    },
    {
        "id": "C",
        "commit": "a10f1451",
        "paths": ["app/tm.py", "tests/test_task_par_collision_406.py"],
        "anchor": "if par_number is None",
        "radius": 34,
        "gold": "PASS",
        "basis": "paired fix enforces one authoritative task-number allocator",
    },
    {
        "id": "D",
        "commit": "01a666ed",
        "paths": ["app/routes/subagent.py"],
        "anchor": "sdk_id = sess.get(\"session_id\")",
        "radius": 24,
        "context": {
            "ref": "01a666ed^",
            "path": "app/routes/sessions.py",
            "anchor": "session.session_id = entry[\"session_id\"]",
            "radius": 22,
        },
        "gold": "STOP",
        "basis": "the new transcript address uses a current session identifier that an existing lifecycle path replaces",
    },
    {
        "id": "E",
        "commit": "18fdb7b8",
        "paths": ["scripts/secret_scan.py"],
        "anchor": "RULES:",
        "radius": 44,
        "gold": "PASS",
        "basis": "content-pattern classification does not identify a durable logical entity",
    },
    {
        "id": "F",
        "commit": "71240bd4",
        "paths": ["app/status_policy.py"],
        "anchor": "def is_internal_telemetry_status",
        "radius": 20,
        "gold": "PASS",
        "basis": "one-way audience classification has no persisted identity or second writer",
    },
    {
        "id": "G",
        "commit": "baf501c7",
        "paths": ["app/tm.py"],
        "anchor": "candidate = store.task_create",
        "radius": 45,
        "context": {
            "ref": "6f874ace",
            "path": "app/tm.py",
            "anchor": "def create_task_for_scope",
            "radius": 34,
        },
        "gold": "STOP",
        "basis": "canonical task-number allocation was added beside an existing legacy allocator",
    },
    {
        "id": "H",
        "commit": "38caf30b",
        "paths": ["app/routes/subagent.py", "tests/test_subagent_routes.py"],
        "anchor": "telemetry = get_subagent(session_id, agent_id)",
        "radius": 42,
        "gold": "PASS",
        "basis": "paired fix reads the historical SDK identifier from telemetry and proves it",
    },
    {
        "id": "I",
        "commit": "90e5a526",
        "paths": [".gitignore"],
        "anchor": ".orchestra/infra/",
        "radius": 18,
        "gold": "PASS",
        "basis": "repository-local ignore rule has no logical entity identity or state writer",
    },
]


def run(*args: str) -> str:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


def window(text: str, anchor: str, radius: int) -> str:
    lines = text.splitlines()
    matches = [index for index, line in enumerate(lines) if anchor in line]
    if not matches:
        raise RuntimeError(f"anchor not found: {anchor!r}")
    index = matches[0]
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    selected = lines[start:end]
    if start:
        selected.insert(0, "... earlier lines omitted ...")
    if end < len(lines):
        selected.append("... later lines omitted ...")
    return "\n".join(selected)


def main() -> None:
    packet = [
        "# Blinded design-stop evaluation packet",
        "",
        "Judge only the supplied excerpts. Case letters are in a fixed pre-registered order.",
    ]
    gold: dict[str, dict[str, str]] = {}
    for case in CASES:
        diff = run(
            "git",
            "show",
            "--format=",
            "--no-ext-diff",
            "--unified=12",
            case["commit"],
            "--",
            *case["paths"],
        )
        packet.extend(
            [
                "",
                f"## Case {case['id']}",
                "",
                "### Changed excerpt",
                "",
                "```diff",
                window(diff, case["anchor"], case["radius"]),
                "```",
            ]
        )
        context = case.get("context")
        if context:
            source = run("git", "show", f"{context['ref']}:{context['path']}")
            packet.extend(
                [
                    "",
                    "### Pre-existing consumer context",
                    "",
                    "```python",
                    window(source, context["anchor"], context["radius"]),
                    "```",
                ]
            )
        gold[case["id"]] = {
            "expected": case["gold"],
            "basis": case["basis"],
            "commit": case["commit"],
        }
    (OUT / "evaluation-packet.md").write_text("\n".join(packet) + "\n", encoding="utf-8")
    (OUT / "evaluation-gold.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
