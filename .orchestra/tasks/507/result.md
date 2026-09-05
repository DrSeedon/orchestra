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
`packet_json` for `packet_delta` as well as `fallback_packet`, unconditionally, because
the projection in `_stage_runtime_handoff_target` is unconditional. `native_resume` still
compares against `packet_sha256`.

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

## Not a #507 defect: unblocking the merge test gate

`test_t2_total_context_preflight_refuses_codex_before_source_disconnect` went red on `main`
and the merge gate, which runs the suite on the merge, refused the operation. Nothing in
this task caused it, and it is fixed here only because the branch cannot merge past a red
gate and a separate branch could not merge either.

**Not a migration defect.** The differentiator was run before touching anything: a fresh
database through the normal path creates the table.

```
dbmod.DB_PATH = /tmp/507-probe.db; dbmod.init_db()
runtime_handoffs present: True   runtime_handoff_attempts present: True   (47 tables)
```

So `sqlite3.OperationalError: no such table: runtime_handoffs` at `app/db.py:2245` is not a
new installation failing — production initialisation is intact.

**What actually happened.** `e6277e32` ("Use configured catalog-bounded Codex window for
handoff preflight") made `_model_context_window` read the *installed* Codex config:
`min(model_context_window, max_context_window) * effective_context_window_percent // 100`.
On this machine that is 872 000 → 828 400 instead of the catalog's 258 400. The test feeds a
300 000-byte system prompt to prove the preflight refuses; against an 828 400 window it now
legitimately fits, so the flow no longer refuses and walks on into
`_prepare_runtime_handoff`, whose fixture has no ledger schema. Measured through the same
call the test uses:

```
_handoff_preflight_manifest("gpt-5.6-sol") -> fits=True window=828400 candidate=300130
```

The real defect is hermeticity, not arithmetic: the test's verdict came to depend on whether
the developer's `~/.codex` has a 872 000 window. Fixed by pinning what it means to not fit —
`monkeypatch.setenv("CODEX_HOME", tmp_path/"codex-home")`, so the target falls back to the
catalog value `CODEX_CONTEXT_LIMITS["gpt-5.6-sol"] = 258 400` the test was written against.
No production code touched, no assert weakened, the 300 000-byte prompt kept. Mutation:
`if not early.fits:` → `if False:` reddens it (1 failed), restored 1 passed.

Same class as the existing `_hermetic_dashboard_env` fixture in `tests/conftest.py`: any
other test reading the installed Codex config has the same exposure. Left alone deliberately
— that is a conftest-wide change, out of this task.

## Luna review, round 1 — one blocking, accepted

`codex-review-impl.md`, `app/db.py:2508-2511`, confidence 0.99. The first version of this
change recomputed the expected candidate hash only when the ledger packet carried an
`integrity` block, while `_stage_runtime_handoff_target` projects and rehashes
unconditionally. A ledger row without `integrity` would therefore stage with the
projected hash and be rejected at `confirm_runtime_handoff` with
`runtime handoff attempt hash mismatch` — **after the source was already released**,
i.e. the session lands in `recovery_required` on the last step.

Verified in the code, not taken on trust: `app/session.py:3872-3875` has no such guard,
and before this task both sides were symmetric (`fallback_packet` recomputed with no
guard at all). The asymmetry was introduced here, and it was introduced to keep
`test_t2_confirmation_updates_session_and_ledger_in_one_transaction` green with its
`packet_json='{}'` fixture — code bent to fit a test.

Fixed by removing the guard: one rule on both sides, the candidate hash is always the
hash of what actually left. The alternative — mirroring the guard into `session.py` —
was rejected: the ingress canary would then attest a checksum that does not describe the
delivered packet.

The fixture described a state production cannot reach (`build_runtime_state_packet`
always writes `integrity`; the orchestrator also checked the live `runtime_handoffs`
table read-only: 2 rows, both with `integrity`). Replaced with a real packet, so
**`packet_delta` now has coverage of the recompute path, which had none** — that is why
the defect passed 62 green tests. Mutation: reverting the branch to
`if attempt["mode"] == "fallback_packet":` reddens `…in_one_transaction` (1 failed,
38 passed), and the restored code is 39 passed.

## Luna review, round 2 — clean, on the final snapshot

`review-receipt:47d4ddd1-a404-4d7f-aaa9-25781cb19dc0`, `worker_head 82d741f8`,
`coverage_outcome=reviewed`. P1 reported FIXED, no new findings, verdict evidenced by the
verbatim line `expected_candidate_sha256 = packet["integrity"]["canonical_sha256"]`
(`app/db.py:2521`, absent from the round-2 request). Author outcome recorded `accepted`
on both receipts.

### Why the delta was re-reviewed instead of attested — a defect in our own gate

`record_review_outcome(outcome="attested", closed_findings=[...])` cannot succeed on a
round-1 artifact in this shape. `review_findings` (`app/review_coverage.py:139`) accepts
exactly two spellings: a `blocking: path:line — …` line (`FINDING_RE`, :33) or a heading
literally matching `### blocking:` followed by a `**File:**` line
(`FINDING_HEADING_RE`, :39). Luna wrote `### [P1] Сохранять legacy hash-контракт…` with
`**File:** \`app/db.py:2508-2511\``, so the heading never arms `finding_heading` and the
`**File:**` line is skipped. Run against the artifact itself:

```
review_findings(artifact_text, worktree=<worktree>) -> []
review_findings(artifact_text)                      -> []
```

Zero anchors → `attestation_findings_unknown` for any `closed_findings`, and
`attestation_findings_empty` for an empty one. The cheap route is therefore unusable by
default, because no review prompt template requires the anchor format the gate parses.
Two possible owners for the fix: the `context` templates in the `codex-debate` skill, or
`review_findings` learning the `### [P1]` + `**File:**` shape. Not decided here.

Also undocumented in the tool description: `outcome="attested"` before `outcome="accepted"`
is refused with `attestation_outcome_not_attestable: unknown` — the author verdict must be
recorded first.

## Round 3 — not run, Codex weekly quota exhausted

After merging `main` the reviewed bytes were unchanged (`git diff 82d741f8 HEAD -- app/db.py`
empty) but the coverage binding is `(target_sha, production_snapshot_sha256)`, and both moved
with `main`. Round 3 was requested on the post-merge snapshot and refused verbatim:

```
weekly_quota_blocked: New Codex worker turn blocked: Codex quota is 99% —
utilization 99% is at or above the hard stop 99%. Stop/model change remain available.
```

`weekly_quota_blocked` is in `MACHINE_UNAVAILABLE_CODES` (`app/review_coverage.py:25`), so the
platform wrote the coverage outcome itself. Twice, identically — once after the merge of
`main` (`review-receipt:cc7a89c1-2540-4564-b76e-c32f8892ad8f`, `worker_head c8d38ab5`) and
once after the test-gate fix (`review-receipt:fe4c12b1-a7c3-41ce-b45e-ec3bfc3faa9a`,
`worker_head a56a0cfd`, the current head). Both carry
`subject_kind=implementation`, `status=failed`, `return_code=None`,
`failure_code=weekly_quota_blocked`, `coverage_outcome=unavailable`, `policy_ref` equal to
`current_policy_ref()` — every condition of the `unavailable` branch
(`app/review_coverage.py:459-465`) satisfied. Quota resets 11.09.

Per the round-ceiling rule this is a tool refusal, not a reviewer answer: no round consumed,
one round of three still available. The substantive verdict remains round 2's, and it applies
to byte-identical content.

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
