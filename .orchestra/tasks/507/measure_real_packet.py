"""Recount the #507 handoff on its own live data: ledger packet vs rebuilt packet.

Read-only against data/orchestra.db. Run from the worktree root:
    .venv/bin/python .orchestra/tasks/507/measure_real_packet.py
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.runtime_history import (  # noqa: E402
    build_model_visible_manifest,
    build_runtime_delivery_packet,
    build_runtime_packet_fallback,
    build_runtime_state_packet,
    preflight_runtime_handoff,
)

DB = "/mnt/data/Projects/Python/orchestra/data/orchestra.db"
HANDOFF = "1112dbe9-af1b-5f8d-9b9e-e9a09d4170e6"
WINDOW = 258_400


def size(value) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    handoff = conn.execute(
        "SELECT * FROM runtime_handoffs WHERE handoff_id=?", (HANDOFF,)
    ).fetchone()
    ledger = json.loads(handoff["packet_json"])
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM logs WHERE session_id=? AND id<=? ORDER BY id",
            (handoff["session_id"], handoff["snapshot_log_id"]),
        )
    ]

    system_prompt = next(
        item["content"] for item in ledger["constraints"] if not item.get("path")
    )
    project_docs = [
        {"path": item["path"], "content": item["content"]}
        for item in ledger["constraints"]
        if item.get("path")
    ]
    rebuilt = build_runtime_state_packet(
        rows,
        session_meta=ledger["identity"],
        snapshot_id=int(handoff["snapshot_log_id"]),
        current_system_prompt=system_prompt,
        project_docs=project_docs,
        expected_target_capability=ledger["expected_target_capability"],
    )
    delivered = build_runtime_delivery_packet(rebuilt)
    fallback = build_runtime_packet_fallback(delivered)

    print(f"source rows={len(rows)}  system_prompt={len(system_prompt.encode()):_} B")
    print(f"{'packet key':<28}{'BEFORE':>12}{'AFTER':>12}{'AFTER(deliv)':>14}")
    for key in sorted(set(ledger) | set(rebuilt)):
        print(
            f"{key:<28}{size(ledger.get(key)):>12_}{size(rebuilt.get(key)):>12_}"
            f"{size(delivered.get(key)):>14_}"
        )
    print(f"{'TOTAL':<28}{size(ledger):>12_}{size(rebuilt):>12_}{size(delivered):>14_}")
    print()
    print("tool_effects kept/dropped:", delivered["omissions"]["tool_effects"])
    print("raw_event_refs:", delivered["omissions"]["raw_event_refs"])
    print(
        "min_log_id:", ledger["raw_event_refs"]["min_log_id"],
        "->", delivered["raw_event_refs"]["min_log_id"],
    )

    for label, candidate in (("packet", delivered), ("fallback_packet", fallback)):
        prepared = type("P", (), {
            "packet": candidate,
            "packet_sha256": candidate["integrity"]["canonical_sha256"],
        })()
        manifest = build_model_visible_manifest(
            runtime="codex",
            model=ledger["identity"]["target_model"],
            effective_window=WINDOW,
            system_prompt=system_prompt,
            prepared=prepared,
            validation_profile=False,
            project_docs=project_docs,
            mcp_servers={"orchestra": {"command": "orchestra-mcp", "args": []}},
        )
        receipt = preflight_runtime_handoff(manifest, native_context_tokens=0)
        budget = (
            receipt.effective_window - receipt.output_reserve
            - receipt.reasoning_reserve - receipt.next_user_reserve
        )
        print()
        print(f"--- mode={label}  budget={budget:_} B")
        for name, count in sorted(receipt.components.items()):
            if count:
                print(f"    {name:<24}{count:>12_}")
        print(f"    {'candidate total':<24}{receipt.candidate_upper_tokens:>12_}")
        print(f"    fits={receipt.fits}  headroom={budget - receipt.candidate_upper_tokens:_} B")


if __name__ == "__main__":
    main()
