"""T-guard: run_all must stop on the Codex pool ceiling instead of burning the pool.

The experiment consumes ~1.29 points of the shared Codex 7d pool per slot (measured
2026-09-05: pool 51% -> 69% across 14 slots while no other Codex consumer was live).
The frozen 100-slot design therefore cannot finish inside the remaining window, and an
unguarded run would spend the whole fleet's pool and still not reach the last pair.

The guard is fail-CLOSED: an unreadable quota must never be read as "0%, keep going".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts" / "recon429"))

import generation_432 as gen


@pytest.fixture()
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    gen.init_generation(root)
    return root


def _executed(monkeypatch) -> list[str]:
    """Replace the provider call so the guard is measured, not the model."""
    seen: list[str] = []

    canary_pass = {
        "cli_authenticated": True,
        "absolute_oracle_read": "DENY",
        "traversal_oracle_read": "DENY",
        "auth_file_read": "DENY",
        "env_secret_read": "DENY",
    }

    def fake_execute(root: Path, slot_id: str | None) -> dict:
        state = json.loads((root / "generation-state.json").read_text())
        target = slot_id or gen.next_slot_id(state)
        seen.append(str(target))
        current = gen.begin_slot(root, str(target))
        result = canary_pass if current["role"] == "canary" else {"classification": "success"}
        return gen.complete_slot(root, str(target), result)

    monkeypatch.setattr(gen, "execute_slot", fake_execute)
    return seen


def test_run_all_stops_before_starting_a_slot_over_the_ceiling(run_root, monkeypatch):
    seen = _executed(monkeypatch)
    result = gen.run_all(run_root, pool_ceiling=85.0, utilization_reader=lambda: 95.0)
    assert seen == [], "no slot may start once the pool is over the ceiling"
    assert result["stopped_reason"] == "pool_ceiling_reached"
    assert result["pool_utilization"] == 95.0


def test_run_all_is_fail_closed_when_quota_is_unreadable(run_root, monkeypatch):
    seen = _executed(monkeypatch)
    result = gen.run_all(run_root, pool_ceiling=85.0, utilization_reader=lambda: None)
    assert seen == [], "unreadable quota must not be read as headroom"
    assert result["stopped_reason"] == "quota_unreadable"


def test_run_all_stops_mid_run_when_the_pool_crosses_the_ceiling(run_root, monkeypatch):
    seen = _executed(monkeypatch)
    readings = iter([50.0, 60.0, 90.0, 10.0, 10.0])

    result = gen.run_all(
        run_root, pool_ceiling=85.0, utilization_reader=lambda: next(readings)
    )
    assert len(seen) == 2, "the slot whose pre-check crossed the ceiling must not start"
    assert result["stopped_reason"] == "pool_ceiling_reached"

    state = json.loads((run_root / "generation-state.json").read_text())
    started = [s for s in state["slots"] if s["status"] != "NOT_STARTED"]
    assert len(started) == 2, "stopping leaves the remaining slots resumable"


def test_run_all_runs_when_the_pool_has_headroom(run_root, monkeypatch):
    seen = _executed(monkeypatch)
    result = gen.run_all(
        run_root, max_slots=3, pool_ceiling=85.0, utilization_reader=lambda: 50.0
    )
    assert len(seen) == 3
    assert result["stopped_reason"] == "max_slots"
