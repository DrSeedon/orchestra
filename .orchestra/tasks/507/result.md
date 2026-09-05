# #507 — bounded handoff packet, no duplicated constraint bodies

Handoff `1112dbe9-af1b-5f8d-9b9e-e9a09d4170e6` (session `07233e67-…`, snapshot log 605651,
32 006 rows) failed `handoff_fallback_exhausted`: both attempts hit `context_overflow`.

## What changed

`app/runtime_history.py`
- `TOOL_EFFECT_BUDGET = 16_000` — `_bounded_tool_effects` keeps the newest effects that
  fit: non-completed first, then completed. `pending` is exempt from the budget outright
  (it is what makes `classify_handoff_effects` block a snapshot taken under a running
  tool; an oversized one must still block).
- `RAW_EVENT_REF_LIMIT = 256` — `raw_event_refs.event_ids` keeps the newest 256 and
  `min_log_id` names the surviving range. `resolve_runtime_handoff_events` answers at
  most 32 ids per call anyway.
- `build_runtime_delivery_packet` — the delivered candidate keeps `path` + `authority`
  (incl. sha256) of each constraint and drops `content`, but only for the two origin
  kinds the target already receives as its own manifest components
  (`current_system_prompt`, `tracked_project_doc`). Anything else keeps its body.
- Both truncations report exact counts in `packet["omissions"]`.

`app/session.py` — `_stage_runtime_handoff_target` verifies the LEDGER packet against
`prepared.packet_sha256` first (previously only the packet mode was verified, and only
against itself), then delivers `build_runtime_delivery_packet(...)`, plus
`build_runtime_packet_fallback` in mode 2. `candidate_sha256` is the recomputed hash of
what actually leaves.

`app/db.py` — `confirm_runtime_handoff` recomputes the expected candidate hash from
`packet_json` for `packet_delta` as well as `fallback_packet`. `native_resume` still
compares against `packet_sha256`, and a ledger packet with no `integrity` block (legacy
rows) still falls back to the recorded hash.

The ledger packet is untouched: `_prepare_runtime_handoff` still restores
`frozen_project_docs` from `packet_json` on an idempotent replay, and
`/handoffs/{id}/events` still verifies `runtime_packet_sha256(packet_json)` against
`packet_sha256`.

## Measured on the real failing handoff

`.orchestra/tasks/507/measure_real_packet.py` rebuilds the packet from the 32 006 live
log rows with the same 99 289 B system prompt and 32 230 B of project docs, then counts
the staging manifest. Full output: `measured.txt`. All figures are UTF-8 bytes of the
canonical JSON — the same `utf8_bytes_upper_bound` the preflight uses.

| packet key | BEFORE | AFTER (ledger) | AFTER (delivered) |
|---|---:|---:|---:|
| tool_effects | 3 196 895 | 15 975 | 15 975 |
| raw_event_refs | 223 800 | 2 019 | 2 019 |
| constraints | 133 475 | 133 475 | 524 |
| recent_messages | 93 785 | 93 785 | 93 785 |
| omissions | 159 | 351 | 400 |
| identity / integrity / typed_state / rest | 667 | 667 | 667 |
| **total** | **3 648 964** | **246 455** | **113 553** |

Manifest against `effective_window=258400`, input budget 158 304 B:

| component | mode `packet` | mode `fallback_packet` |
|---|---:|---:|
| system_prompt | 99 289 | 99 289 |
| project_docs | 32 285 | 32 285 |
| packet | 19 749 | 19 786 |
| recent_delta | 93 785 | 2 |
| tool_schemas / canary / validation_profile | 233 | 233 |
| **candidate total** | **245 341** | **151 595** |
| **fits** | **no** (−87 037) | **yes** (+6 709) |

**Straight answer: the fallback mode now fits, the main mode still does not.** Attempt 1
overflows, `context_overflow` is fallback-eligible, attempt 2 delivers and the switch
completes. The remaining 87 037 B of the main mode is `recent_messages`: 43 messages
under the pre-existing `recent_budget = 64_000` char budget that render as 93 785 B —
already more than the whole 158 304 B input budget minus a 99 KB system prompt. Nothing
in this task's scope can make the main mode fit; see "Left open".

Effects actually carried: 55 of 8 881 — the 55 newest non-completed ones, all
`unresolved`. The budget was exhausted before the completed pass, so **zero completed
effects travel** in this session, and so do zero of the 44 `ambiguous`. 8 826 dropped,
itemised in `omissions.tool_effects.dropped_by_status`.
Event refs: 256 of 31 939, `min_log_id` 316 963 → 602 315.

## Tests

`.venv/bin/python -m pytest tests/test_runtime_handoff_v2.py tests/test_runtime_history.py -q`
→ **62 passed, 1 deselected**. Imported `app`:
`/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-handoff-packet/app/runtime_history.py`.

New oracles in `tests/test_runtime_history.py`:
- `test_long_session_packet_fits_the_target_window_next_to_its_own_prompt` — 12 000
  tool/tool_result rows, 99 200 B system prompt, 32 230 B project docs, preflight at
  `effective_window=258400`.
- `test_delivered_candidate_drops_the_bodies_the_ledger_packet_keeps`
- `test_effect_budget_keeps_the_call_that_blocks_and_names_what_it_dropped`
- `test_event_refs_are_bounded_and_min_log_id_describes_what_survived`

Mutation check — each defect reverted separately reddens the committed oracle:

| mutation | red tests |
|---|---|
| `TOOL_EFFECT_BUDGET = 100_000_000` | `…fits_the_target_window…`, `…keeps_the_call_that_blocks…` |
| `RAW_EVENT_REF_LIMIT = 10_000_000` | `…fits_the_target_window…`, `…event_refs_are_bounded…` |
| `_DELIVERED_CONSTRAINT_KINDS = frozenset()` | `…fits_the_target_window…`, `…drops_the_bodies…` |

Regression sweep (no full suite): `test_runtime_handoff_recovery`,
`test_runtime_handoff_v2`, `test_handoff_effect_classification`, `test_runtime_history`,
`test_native_history_import`, `test_backend_claude`, `test_db` → 204 passed;
`test_session`, `test_api` → 393 passed.

`tests/test_handoff_effect_classification.py::test_change_model_refusal_names_the_blocking_call_not_only_its_code`
is red **on HEAD 7fb6dc66 as well** (verified in a clean detached worktree: 1 failed,
67 passed, `KeyError: 'error_code'`). Not this task's; owner said out of scope.

## Authorized test edits

Three pre-existing tests in `tests/test_runtime_handoff_v2.py` hard-coded
`delivered_sha == prepared.packet_sha256`. Edits authorized by the orchestrator, and
strengthened at its instruction — the expectation is computed independently of the
builder under test, via `runtime_packet_sha256(kwargs["packet"])`, i.e. from the packet
that actually left, and each of the three now also asserts positively that the delivered
constraints are non-empty, carry `authority.sha256` and carry no `content`.
Helpers `_stub_ledger_packet` / `_delivered_candidate_sha256`. No assert removed, no
skip/xfail added.

## Left open (not in scope, flagged)

1. **Main mode still overflows on any session with real dialogue.** `recent_budget =
   64_000` (chars) in `build_runtime_state_packet` predates this task and is not one of
   the three fixes. To make mode `packet` fit next to a 99 KB system prompt it would
   have to drop to roughly 20 000. Owner's call.
2. **Headroom is 6 709 B, and `skill_index` was 0 in this session.** A worker with a
   populated skill index would overflow the fallback too. The real lever is the 99 289 B
   system prompt, which this task was told not to touch.
3. codex (parallel, `fix/handoff-context-window`) is raising the Astra window to
   828 400. It re-ran `measure_real_packet.py` with `WINDOW=828400` and reported the
   main mode fitting: candidate 245 341 against a 728 304 B budget, headroom 482 963,
   `recent_delta` 93 785 preserved. Independent of this change; with both landed the
   warm switch works in mode `packet`, with only this one it works in the fallback.
4. codex also asked to carry a compact summary / current goal in `typed_state` for the
   fallback mode (it stays `"unknown"` and the fallback drops `recent_messages`
   entirely). That is a new feature, declined here as out of scope — it is a real cold-
   start gap and needs its own ticket.
