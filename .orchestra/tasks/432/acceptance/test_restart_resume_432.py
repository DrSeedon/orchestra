from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts/recon429"
sys.path.insert(0, str(SCRIPTS))

import generation_432 as generation


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_restart_recovery_preserves_done_and_replays_inconclusive(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "interrupted-a01.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"type":"provider_started"}\n', encoding="utf-8")
    state = {
        "schema_version": 2,
        "generation": "test",
        "slots": [
            {
                "id": "done",
                "phase": "noise",
                "role": "A",
                "pair": "done-pair",
                "status": "COMPLETED",
                "attempt": 1,
            },
            {
                "id": "interrupted",
                "phase": "noise",
                "role": "A",
                "pair": "interrupted-pair",
                "status": "STARTED",
                "attempt": 1,
                "started_at": 100.0,
                "provider_started_at": 101.0,
                "raw_path": str(raw),
            },
            {
                "id": "future",
                "phase": "noise",
                "role": "A",
                "pair": "future-pair",
                "status": "NOT_STARTED",
                "attempt": 1,
            },
        ],
    }
    generation.atomic_json(tmp_path / "generation-state.json", state)

    recovered = generation.reconcile_generation(tmp_path, timestamp=200.0)

    by_id = {slot["id"]: slot for slot in recovered["slots"]}
    assert by_id["done"]["status"] == "COMPLETED"
    assert by_id["done"]["attempt"] == 1
    assert by_id["interrupted"]["status"] == "NOT_STARTED"
    assert by_id["interrupted"]["attempt"] == 2
    assert generation.next_slot_id(recovered) == "interrupted"
    rows = _read_jsonl(tmp_path / "raw-slots.jsonl")
    assert rows == [
        {
            "arm": "A",
            "attempt": 1,
            "outcome": "inconclusive",
            "raw_response": '{"type":"provider_started"}\n',
            "slot": "interrupted",
            "timestamp": 200.0,
        }
    ]

    generation.begin_slot(tmp_path, "interrupted", timestamp=201.0)
    generation.complete_slot(
        tmp_path,
        "interrupted",
        {"classification": "success", "total_cost_usd": 0.125},
        raw_response='{"type":"turn.completed"}\n',
        timestamp=202.0,
    )
    final = json.loads((tmp_path / "generation-state.json").read_text())
    by_id = {slot["id"]: slot for slot in final["slots"]}
    assert by_id["done"]["status"] == "COMPLETED"
    assert by_id["interrupted"]["status"] == "COMPLETED"
    assert generation.next_slot_id(final) == "future"
    rows = _read_jsonl(tmp_path / "raw-slots.jsonl")
    assert [row["outcome"] for row in rows] == ["inconclusive", "success"]
    assert rows[-1] == {
        "arm": "A",
        "attempt": 2,
        "outcome": "success",
        "raw_response": '{"type":"turn.completed"}\n',
        "slot": "interrupted",
        "timestamp": 202.0,
    }


def test_main_arms_are_counterbalanced_and_alternating() -> None:
    slots = generation.build_slots()
    main = [slot for slot in slots if slot["phase"] == "main"]
    pairs: dict[str, list[str]] = {}
    for slot in main:
        arm = "A" if slot["role"] == "A" else "B"
        if not pairs.setdefault(slot["pair"], []) or pairs[slot["pair"]][-1] != arm:
            pairs[slot["pair"]].append(arm)

    assert len(pairs) == 24
    assert all(arms in (["A", "B"], ["B", "A"]) for arms in pairs.values())
    assert sum(arms == ["A", "B"] for arms in pairs.values()) == 12
    assert sum(arms == ["B", "A"] for arms in pairs.values()) == 12
