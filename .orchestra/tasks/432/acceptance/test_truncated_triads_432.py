"""T-trunc: a triad the pool ceiling never started is DROPPED, not scored as a failure.

`build_ledger` walked all 12 tasks x 2 repetitions unconditionally and turned any missing
slot into `_failed_row(...)`, i.e. a B-arm failure. Under the pool ceiling most triads are
NOT_STARTED, so the frozen denominator of 24 would have counted ~21 never-executed triads
as failures of the scout arm and inverted the result.

Pre-registered stopping rule 4 (.orchestra/tasks/432/stopping-rule.md): only triads whose
A, B_scout and B_main are all COMPLETED enter the paired analysis; a triad cut by the
ceiling is dropped whole. A triad that RAN and failed the hidden oracle is a real
model_failure and must still count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "recon429"))

import finalize_432 as fin
import generation_432 as gen


def _state(overrides: dict[str, dict]) -> dict:
    """A generation state where only the named slots carry status/result."""
    slots = gen.build_slots()
    for item in slots:
        patch = overrides.get(str(item["id"]))
        if patch:
            item.update(patch)
    return {"slots": slots, "sessions_at_init": 0, "generation": "test"}


def _ran(arm: str, cost: float, classification: str = "success") -> dict:
    if arm == "A":
        payload = {"A": {"arm": "A", "classification": classification,
                         "total_cost_usd": cost}}
    elif arm == "B_main":
        payload = {"B": {"arm": "B", "classification": classification,
                         "total_cost_usd": cost}}
    else:
        payload = {"classification": classification, "cost_usd": cost}
    return {"status": "COMPLETED", "outcome": classification, "result": payload}


def test_never_started_triad_is_dropped_not_counted_as_failure():
    state = _state({
        "main-364-r1-A": _ran("A", 0.10, "model_failure"),
        "main-364-r1-B_scout": _ran("B_scout", 0.03),
        "main-364-r1-B_main": _ran("B_main", 0.05, "model_failure"),
    })
    ledger = fin.build_ledger(state)
    keys = {(p["task"], p["repetition"]) for p in ledger["pairs"]}
    assert keys == {(364, 1)}, (
        "only the complete triad may enter the ledger; "
        f"got {len(ledger['pairs'])} pairs"
    )


def test_a_triad_that_ran_and_failed_the_oracle_still_counts():
    state = _state({
        "main-364-r1-A": _ran("A", 0.10, "model_failure"),
        "main-364-r1-B_scout": _ran("B_scout", 0.03),
        "main-364-r1-B_main": _ran("B_main", 0.05, "model_failure"),
    })
    pair = fin.build_ledger(state)["pairs"][0]
    assert pair["A"]["classification"] == "model_failure"
    assert pair["B"]["classification"] == "model_failure"
    assert pair["A"]["total_cost_usd"] == 0.10


def test_partial_triad_is_dropped_whole():
    """A + B_scout done, B_main never started -> the whole triad leaves the analysis."""
    state = _state({
        "main-364-r1-A": _ran("A", 0.10),
        "main-364-r1-B_scout": _ran("B_scout", 0.03),
        "main-396-r1-A": _ran("A", 0.20),
        "main-396-r1-B_scout": _ran("B_scout", 0.04),
        "main-396-r1-B_main": _ran("B_main", 0.06),
    })
    ledger = fin.build_ledger(state)
    keys = {(p["task"], p["repetition"]) for p in ledger["pairs"]}
    assert keys == {(396, 1)}, f"partial triad must not be scored; got {sorted(keys)}"


def test_ledger_reports_planned_and_truncated_counts():
    state = _state({
        "main-364-r1-A": _ran("A", 0.10),
        "main-364-r1-B_scout": _ran("B_scout", 0.03),
        "main-364-r1-B_main": _ran("B_main", 0.05),
    })
    ledger = fin.build_ledger(state)
    assert ledger["planned_pairs"] == 24
    assert ledger["measured_pairs"] == 1
    assert ledger["truncated_pairs"] == 23
