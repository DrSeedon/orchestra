#!/usr/bin/env python3
"""Executable state-model check for every crash prefix in the #454 drain order."""

from __future__ import annotations

import copy
import json


def initial() -> dict:
    return {
        "status": "in_progress",
        "worker_bound": True,
        "source_manifest": False,
        "candidates": False,
        "approved": False,
        "fact_reachable": False,
        "release_validated": False,
        "raw_current": True,
        "source_history_reachable": True,
        "deletion_reachable": False,
        "done_receipt": False,
        "completed_at": False,
    }


def steps():
    return (
        ("pending_unbind", lambda state: state.update(
            status="knowledge_pending", worker_bound=False, source_manifest=True
        )),
        ("candidates", lambda state: state.update(candidates=True)),
        ("approval", lambda state: state.update(approved=True)),
        ("fact_commit", lambda state: state.update(fact_reachable=True)),
        ("release_validation", lambda state: state.update(release_validated=True)),
        ("deletion_commit", lambda state: state.update(
            raw_current=False, deletion_reachable=True
        )),
        ("done_event", lambda state: state.update(
            status="done", done_receipt=True, completed_at=True
        )),
    )


def assert_invariants(state: dict) -> None:
    if state["status"] == "done":
        assert state["fact_reachable"]
        assert state["deletion_reachable"]
        assert state["done_receipt"]
        assert state["completed_at"]
    if not state["raw_current"]:
        assert state["fact_reachable"]
        assert state["source_history_reachable"]
        assert state["deletion_reachable"]
    if not state["fact_reachable"]:
        assert state["raw_current"]


def main() -> None:
    ordered = steps()
    rows = []
    for cut in range(len(ordered) + 1):
        crashed = initial()
        for _name, apply in ordered[:cut]:
            apply(crashed)
        assert_invariants(crashed)

        replayed = copy.deepcopy(crashed)
        for _name, apply in ordered[cut:]:
            apply(replayed)
            assert_invariants(replayed)
        assert replayed["status"] == "done"
        assert replayed["fact_reachable"] and not replayed["raw_current"]
        rows.append({
            "crash_after": "none" if cut == 0 else ordered[cut - 1][0],
            "status": crashed["status"],
            "worker_bound": crashed["worker_bound"],
            "fact_reachable": crashed["fact_reachable"],
            "raw_current": crashed["raw_current"],
            "deletion_reachable": crashed["deletion_reachable"],
            "replay_to_done": True,
        })

    failed = initial()
    ordered[0][1](failed)
    failed.update(status="knowledge_blocked")
    assert_invariants(failed)
    assert failed["raw_current"] and not failed["fact_reachable"]
    print(json.dumps({
        "prefixes_ok": len(rows),
        "failed_attempt_raw_retained": True,
        "rows": rows,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
