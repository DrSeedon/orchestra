# #248 T2 — adversarial implementation review (Opus, not Codex)

**Reviewer:** Opus (`review248-opus`), acting as the sanctioned fallback reviewer.
**Why not Codex:** the Codex weekly pool is exhausted — `/api/usage` reported
`codex.primary.utilization = 97` against the 95% threshold, so `codex_review` returns
`weekly_quota_blocked`. No Codex round was run; nothing in this file is a Codex verdict.
**Date:** 2026-08-13.
**Subject:** `git diff b35795dc..60528bfc` only (T2). T1 (`b35795dc`) is given context.
Frozen oracle `tests/test_task_tracker_integration.py` @ `b7ad6c76` was read, never modified.

## Baseline reproduced (my own runs, not inherited)

```
uv run python -m pytest -q tests/test_task_tracker_integration.py -k 'test_t1_ or test_t2_'
8 passed, 15 deselected in 12.57s

uv run python -m pytest -q tests/test_workspace.py tests/test_tm.py tests/test_tm_sync_loop.py tests/test_merge_operations.py
175 passed in 65.22s

uv run python -m pytest -q tests/test_mcp_stdio.py tests/test_merge_branch_drift.py tests/test_merge_stuck.py tests/test_return_to_merged_branch.py
98 passed in 26.93s
```

Old-caller (schema-v1) replay identity is byte-identical — `normalize_request` adds keys only
when `merge_schema_version is not None`:

```
v1 new : {'name': 'w', 'scope': '/s', 'target': 'main', 'next_task_id': '7', 'squash': True}
v1 old : {'name': 'w', 'scope': '/s', 'target': 'main', 'next_task_id': '7', 'squash': True}
```

In-flight operations accepted by the running server keep their hash after the upgrade. The old
MCP never reads `/api/merge-operations/capabilities` at all (`git show b35795dc:app/mcp_stdio.py |
grep capabilit` → no hits), so the widened capability payload cannot break a connected agent.

---

## [blocking] The schema-v2 ref gate refuses honest merges over ordinary English words

`app/routes/sessions.py:1299-1317` → `app/workspace.py:869` (`_extract_task_refs`) →
`app/tm.py:447` (`resolve_scoped_task_identities`).

`_extract_task_refs` runs `_TASK_REF_RE = (?:\b([A-Z]{2,5})-(\d+)\b|#(\d+)\b)` over **every**
commit subject in `target..worker_head` and hands **every** match to
`resolve_scoped_task_identities`, which raises `ValueError` when the ref does not resolve inside
the scope's project. `execute_merge_session` turns that into `NOT_REACHED` / HTTP 409.

`[A-Z]{2,5}-<digits>` is not a task-ref shape, it is a shape that ordinary technical prose hits
constantly: `UTF-8`, `GPT-5`, `SHA-256`, `ISO-8601`, `RFC-7231`, `AES-256`, `CVE-2024`, `HTTP-2`.
Any one of them anywhere in any subject on the branch kills the merge.

**Failure scenario, run end to end** (real repo + real worktree + real
`execute_merge_session`, `data/t2probe/probe_e2e.py`, deleted after the run):

```
SUBJECT   : #42: fix UTF-8 decoding in the log reader
  ok=False commit_point=not_reached http=409
  error    : task 'UTF-8' belongs to project prefix UTF, not authoritative project project
  main moved=False main subject='initial'

SUBJECT   : #42: audit active prompts for GPT-5.6 Sol
  ok=False commit_point=not_reached http=409
  error    : task 'GPT-5' belongs to project prefix GPT, not authoritative project project
  main moved=False main subject='initial'

SUBJECT   : #42: plain honest subject          <-- permissive control arm
  ok=True commit_point=target_committed http=None
  main moved=True main subject='#42: plain honest subject'
```

The control arm matters: the gate is not refusing everything, it is refusing exactly the honest
subjects that contain a hyphen-number token.

**This is not hypothetical.** The second case is transcribed from this repository's own history.
Scanning the last 400 subjects on `main` against the live tracker (read-only, `mode=ro`):

```
subjects 400   no-ref 35   multi-ref 33
extra ref does not resolve -> merge would be REFUSED: 3
    (['GPT-5'], '#172, #5: #172: audit active prompts for GPT-5.6 Sol')
    (['159'],   'CLAUDE.md: два правила из #158 и #159 — ...')
    (['134','135'], 'docs: правила проверки перед работой — ... (#114, ...')
```

Commit `#172` shipped through the v1 path. Under v2 the same worker cannot merge at all.

**Why it is blocking and not a suggestion:** the refusal is permanent for that branch. The gate
reads commit *subjects already written*, so the worker cannot fix it by adding a commit; the only
escapes are amending/rebasing (forbidden by the project's git rules) or abandoning the branch and
recreating the work. That is "inability to merge" plus "work is lost" for a worker who did
nothing wrong. `#N`-that-does-not-exist has the same shape and the same consequence (last probe
line of `probe5.py`: `task '300' not found in session project project`).

The gate's intent — "no ref is taken on faith from message text" (plan line 109) — is right; the
extraction is what is wrong. A ref only carries authority when the worker meant it as a ref.
Two candidate narrowings, both cheap: (a) accept only refs in the leading `#N[, #N]*:` position
that `_LEADING_TASK_REFS_RE` already recognises, or (b) treat a non-resolving prefixed token as
prose rather than as a foreign task and drop it, keeping the hard failure only for `#N`. Either
keeps the forged-substitution defence (that lives in `_validated_squash_message`, and it is
tested — see below) while letting `UTF-8` through.

---

## [suggestion] A single vanished ref discards *all* commit links after the merge already landed

`app/tm.py:579-600`. `link_commits_to_tasks` resolves every ref first and raises
`"task refs disappeared before commit linking: ..."` if any one is missing, so no group is linked.
The old per-ref loop (`app/routes/sessions.py:1379-1397`, still used by v1) linked each ref
independently and recorded a per-ref error for the rest.

I saw this live while mutating the subject guard (see below): the merge committed to `main` and
the log read
`ERROR orchestra.sessions: Failed to link scoped merge commits: task refs disappeared before commit linking: 77`
— target mutated, tracker links zero. The window is narrow (a task deleted between the gate and
the link) and no data is corrupted, but all-or-nothing is the wrong trade *after* the commit
point: partial links beat none.

## [suggestion] `_build_squash_message` now emits duplicate refs (v1 path too)

`app/workspace.py:937`. `_extract_task_refs` dedups on the raw token, then the numeric is taken
with `rsplit('-', 1)[-1]`, so `#248` and `PAR-248` survive as two entries and collapse to the same
number only afterwards. Measured, new vs old on the same input:

```
['#248: a', 'PAR-248: b'] -> NEW '#248, #248: a'   OLD '#248: a'
['ORC-1: a', '#1: b']     -> NEW '#1, #1: a'       OLD '#1: a'
```

This lands in `main`'s permanent subject line for every caller, v1 included. `_parse_merged_commits`
dedups, so linking is unaffected — cosmetic, but it is a regression in the merge commit message.

## [suggestion] The leading-ref stripper is case-insensitive and eats non-refs

`app/workspace.py:924-945`. `_LEADING_TASK_REFS_RE` carries `re.IGNORECASE` while `_TASK_REF_RE`
does not, so a subject may be stripped of a token that was never recognised as a ref:

```
['wip-2: adjust parser'] -> NEW 'adjust parser'    OLD 'wip-2: adjust parser'
['fix-3: something']     -> NEW 'something'        OLD 'fix-3: something'
```

The branch/worktree naming in this project (`fix-*`, `impl-*`, `wip`) makes such subjects
plausible. Text is lost from the permanent commit subject on the v1 path as well. Dropping
`IGNORECASE` makes the two regexes agree.

## [suggestion] The cross-project check on candidate refs can never fail

`app/routes/sessions.py:1319`. `project_id` (strict path) comes from
`primary_resolution["project_id"]`, and `candidate_resolution["project_id"]` comes from the same
`get_project_by_scope(row_scope)` a few lines later — the two are equal by construction. The real
cross-project defence is the prefix check inside `resolve_task_ref` (`app/tm.py:407`). A guard
that cannot fire reads as coverage it does not provide; either remove it or make it compare
against something independently obtained.

## [suggestion] Malformed `merge_schema_version` escapes as a 500 instead of a typed refusal

`app/routes/merge_operations.py:51`. Verified:

```
create_merge_operation({"operation_id":"x","name":"w","scope":"/s","merge_schema_version":"two"})
-> ValueError: invalid literal for int() with base 10: 'two'
```

Every other bad input on this route returns a typed merge DTO; this one returns an untyped 500,
which the MCP's error mapping does not model. No current caller sends a non-int (the new MCP sends
literal `2`), so severity is low.

## [suggestion] Two of T2's own acceptance claims survive mutation

Method: `cp F F.bak` → mutate → run → `mv F.bak F` + `touch`, marker printed before the run and
after the restore. All mutations were applied to a **green** suite.

| mutated line | marker before/after | `-k 'test_t1_ or test_t2_'` |
|---|---|---|
| `app/workspace.py:1303` `if actual_refs != expected_candidate_refs:` → `if False:` | 1 / 0 | **8 passed — survived** |
| `app/workspace.py:904` `if _RESERVED_OPERATION_TRAILER_RE.search(body):` → `if False:` | 1 / 0 | **8 passed — survived** |
| `app/workspace.py:968` `if emitted_refs != expected_refs:` → `if False:` | 1 / 0 | 1 failed, 3 passed — **caught** |

The third row is the control arm proving the harness works and that the emitted-subject
revalidation is genuinely covered (`test_t2_repo_lock_recheck_rejects_substituted_or_foreign_ref`).
The first two are not: the AC line "candidate refs … are rechecked under repo lock against the
exact pinned HEAD" and "worker-provided `Orchestra-Operation:` is rejected as a reserved trailer
key" both pass with the guard deleted. `grep -rn "Orchestra-Operation" tests/` returns exactly one
hit, and it is in a T3 test (`:1175`).

Both guards do work — I exercised them against a real repository (below). The gap is in the frozen
oracle, which I must not edit; recording it here as instructed. T3 should not treat these two AC
lines as already defended.

## [question] The reserved-trailer guard scans the whole body; the plan says subjects

`app/workspace.py:904` matches `^\s*Orchestra-Operation\s*:` against `%B` (full raw body), while
plan line 111 says "Worker **subjects** с таким reserved key отвергаются до Git".

Worker bodies never reach `main`: both the squash path and the cherry-pick fallback build the
message from subjects only (`_build_squash_message` body is `- <subject>` lines). So a trailer in a
worker's *body* cannot forge anything, and the wider scan buys nothing while adding a refusal for
a worker who merely quotes the trailer in prose — which is exactly what someone implementing or
documenting T3 in this repository would do. Intentional widening, or drift from the plan?

## [question] The gate never requires the bound task's own ref to be present

`app/workspace.py:963-965`. The primary `#N` is prepended only when the candidate set is *empty*.
A worker bound to task 7 whose subjects say `#9` (a real task in the same project) merges cleanly,
and the commits link to 9 — while T3's `complete` will close 7. Measured on `main`: 30 of the last
400 subjects carry an extra ref that does resolve, e.g. `#248, #227: #248: audit task manager
integration`. Plan line 108 permits multiple refs, so this may be by design; flagging it because
the combination with T3's finalizer makes "commits filed under 9, task 7 marked done" reachable.

---

## What I checked and found clean (so T3 need not redo it)

Real scratch repositories under `data/t2probe/` (git-ignored, removed with `trash`), not mocks.

- **Refusal leaves nothing behind.** Under-lock ref mismatch and reserved-trailer rejection both
  return before `_branch_worktree_path`, before any checkout, before `git merge --squash`:
  ```
  REFUSAL result: {"ok": false, "state": "failed", "commit_point": "not_reached",
                   "error": "candidate task refs changed under repository lock: expected ['999'], found ['7']"}
  main after refusal same: True
  repo status: ''   wt status: ''
  repo MERGE_HEAD: False  SQUASH_MSG: False
  repo HEAD branch: main  wt HEAD branch: task-1/w
  ```
  Same for the trailer path (`worker commit contains reserved Orchestra-Operation: trailer`,
  `main unchanged: True`, both worktrees clean). No half-applied squash, no stranded checkout —
  the gate sits before `original_branch` is ever recorded, so the `finally` restore has nothing to
  restore.
- **Unrelated-history cherry-pick fallback** (real orphan branch, `git merge-base` exit 1) runs the
  gate and honours the prepared canonical message:
  `{'ok': True, 'state': 'merged', 'commit_point': 'target_committed', 'strategy': 'cherry-pick', 'commits_merged': 2}`,
  `main subject: #7: orphan work one`, `merged_commits keys: ['7']`, `repo status: ''`.
  `target_before..worker_head` degenerates to the orphan's full history, so the gate sees exactly
  the commits `rev-list --reverse <worker_head>` will replay — the two stay consistent.
- **`branch` → `worker_head` substitution** in `merge-base` / `merge-tree` / `rev-list --count` /
  `merge --squash` / `_get_commit_messages` / `_cherry_pick_branch`: the worktree HEAD is the branch
  tip, so the commit set is identical, and the SHA form additionally survives a detached worker
  HEAD where the branch name would have been the literal `HEAD`. No v1 regression; 175 + 98 tests
  above agree.
- **`-z` parsing of `git log --format=%H%x00%s%x00%B`** against adversarial inputs: empty commit
  message, multi-paragraph body, ESC and TAB in the subject, empty commit range, unknown revision.
  ```
  {'refs': ['7'], 'messages': ['', '#7: multi', 'subject with \x1b escape and \ttab']}
  empty range: {'refs': [], 'messages': []}
  bad ref -> RuntimeError cannot inspect candidate commits: fatal: ambiguous argument ...
  ```
  Field count stays a multiple of 3; the trailing empty field is popped correctly.
- **Ref-parsing consistency** between `_extract_task_refs` (`app/workspace.py:869`) and
  `_parse_merged_commits` (`app/workspace.py:1613`): both emit `group(3)` or `PREFIX-N` from the
  same `_TASK_REF_RE`, and the regex already forces uppercase, so the added `.upper()` is a no-op.
  The two agree; linking is not silently misdirected by a format mismatch.
- **`if result is None:` guards** added around `_branch_worktree_path` / `target_wt` fix a real
  pre-existing masking bug: previously "target branch does not exist" was overwritten by the
  downstream checkout error. `target_wt` cannot be referenced unbound — every use sits inside a
  `result is None` block that only runs after assignment.
- **Old callers**: `merge_worker` without `task_outcome` never touches the capability endpoint;
  `strict_task_merge` is false, `candidate_refs` stays `None`, and `expected_candidate_refs is not
  None` keeps the whole gate out of the v1 path. Orchestrator merges, adhoc branches, taskless
  workers, `next_task_id` and explicit `target` all keep their v1 behaviour.
- **MCP capability preflight fails closed**: an old server's `{"capability": "operation-v1",
  "schema_version": 1}` has no `capabilities` key → `MERGE_API_UPGRADE_REQUIRED`, `retryable=False`,
  `outcome_unknown=False`, and no POST is issued. Correct direction for a mixed old/new fleet.

## Verdict

CHANGES REQUESTED — 1 blocking

---

# Round 2 — `9c12ea96..5a81a10a` (diff taken from `60528bfc`)

Same reviewer, same reason (Opus instead of Codex; `codex.primary.utilization = 97` against the
95% threshold on 2026-08-13). Round 2 of a three-round ceiling. The frozen oracle was verified
untouched before anything else: `git diff b7ad6c76 5a81a10a -- tests/test_task_tracker_integration.py`
is empty, and the only test-layer change in the range is the new file
`tests/test_merge_ref_gate.py` (+198).

## The blocking finding is closed — verified independently, not accepted on report

Re-ran my own round-1 end-to-end harness against `5a81a10a` (real repo, real worktree, real
`execute_merge_session`), with task `#8` seeded so a mislink would be *observable*:

```
'#42: fix UTF-8 decoding in the log reader'
   ok=True cp=target_committed  main moved=True  subject='#42: fix UTF-8 decoding in the log reader'
   linked #42=1  linked #8=0
'#42: audit active prompts for GPT-5.6 Sol'
   ok=True cp=target_committed  main moved=True  subject='#42: audit active prompts for GPT-5.6 Sol'
   linked #42=1  linked #8=0
'#42: verify SHA-256 digest'
   ok=True cp=target_committed  main moved=True  subject='#42: verify SHA-256 digest'
   linked #42=1  linked #8=0
'#42: also touches #300'
   ok=True cp=target_committed  main moved=True  subject='#42: also touches #300'
   linked #42=1  linked #8=0
'#999: fabricated assignment'                              <-- refusing control arm
   ok=False cp=not_reached  err=task '999' not found in session project project
   main moved=False  subject='initial'  linked #42=0  linked #8=0
```

All three prose subjects merge, the subject survives verbatim, the neighbouring task is never
linked, and a genuinely fabricated leading ref is still refused before Git. Suites: frozen
`test_t1_ or test_t2_` → 8 passed; `tests/test_merge_ref_gate.py` → 4 passed; my eight-file
regression set (`workspace, tm, tm_sync_loop, merge_operations, mcp_stdio, merge_branch_drift,
merge_stuck, return_to_merged_branch`) → 273 passed. Full frozen oracle without `-x`:
`14 failed, 9 passed`, and the 14 are exactly `12 × test_t3_* + 2 × test_t4_*` (counted by
prefix) — no t1/t2 among them, as claimed.

## Your point 2 — accepted, and my finding was the narrower one

Confirmed at `b35795dc`: the same `f"#{m.group(2)}"` collapse was already there, so `UTF-8` → `#8`
predates T2. I reported the *refusal* direction and missed the *mislink* direction, which is
strictly worse: it is silent, it lands in `main` permanently, and it is the exact failure #248
exists to remove. Your framing is right and the fix belongs where you put it — one definition,
three consumers.

## Your point 3 — reproduced

`grep -rn "_LEADING_TASK_REFS_RE" app/ tests/` → `NO_REMAINING_REFERENCES`. Behaviour re-measured:
`wip-2: adjust parser` → `'wip-2: adjust parser'` (was `'adjust parser'`), `PAR-42: legacy form`
→ `'#42: legacy form'`. Round-1 suggestion closed.

## [suggestion] Your own edit orphaned `_TASK_REF_RE`; it is now a second, looser definition of "ref" with zero readers

`app/workspace.py:1635`. Round 2 removed both consumers (`_extract_task_refs` and
`_parse_merged_commits`). Repo-wide check over every `.py/.json/.yaml`:

```
app/workspace.py:872   _ONE_TASK_REF_RE = ...
app/workspace.py:888   for match in _ONE_TASK_REF_RE.finditer(header.group(1))
app/workspace.py:1635  _TASK_REF_RE = re.compile(r"(?:\b([A-Z]{2,5})-(\d+)\b|#(\d+)\b)")   <- no readers
```

This is the same hazard you removed `_LEADING_TASK_REFS_RE` for, one file over: a live-looking,
deliberately loose ref pattern sitting in the module whose whole point is now "a ref counts only
in the header position". The next agent greps `TASK_REF`, finds it, and reuses it. It was orphaned
by your own change, so deleting it is in scope rather than drive-by cleanup.

## Your point 4 — answered with an experiment: **not blocking for T3**

I reproduced the gap (`workspace.py:1328` → `if False:` → `12 passed`, marker 1 before / 0 after,
green repeat `12 passed`). Then I asked the question the mutation cannot: *does guard (A) protect
anything guard (B) does not?* Same drift (preflight believed `#42`, the pinned HEAD says `#99`),
run both ways on a real repository:

```
(A) enabled   error: candidate task refs changed under repository lock: expected ['42'], found ['99']
              commit_point=not_reached  main moved=False  repo status=''  wt status=''
(A) disabled  error: squash subject task refs changed under repository lock: expected ['42'], found ['99']
              commit_point=not_reached  main moved=False  repo status=''  wt status=''
(A) restored  error: candidate task refs changed under repository lock: expected ['42'], found ['99']
```

(B) refuses the same drift, at the same point, leaving the target byte-identical and both
worktrees clean — because `_validated_squash_message` still compares against the *preflight*
`validated_task_refs`. The only state where (A) fires and (B) stays silent is an alias change that
yields the same canonical numbers (`#42` → `PAR-42`), which is benign by construction. The
under-lock reserved-trailer scan is inside the same `_inspect_candidate_commits` call and is not
gated by (A), so removing (A) would not weaken it either.

So: do **not** carry a test debt into T3, and do not invent a test for (A) — any test you can
write for it is one (B) also passes, i.e. non-discriminating, which is exactly the shape this
project has been burned by. Either leave (A) as cheap defence-in-depth with a comment naming (B)
as the guard of record, or drop it. (B) is tested and mutation-confirmed (round 1).

## Your point 5 — reconciled; **your 1 is the number for the report**

My range: `git log main --format=%s -n 400` in `/home/kesha/orchestra` at `c0185e9d`, 400 subjects,
resolved against `tm_tasks` for project `/home/kesha/orchestra` (191 rows, max par 264), read-only
`mode=ro`. Three different definitions, all recomputed:

| definition | count |
|---|---|
| **D1a** prose token (`PREFIX-N`) that cannot resolve — *the class my blocking finding was about* | **1** (`GPT-5`) |
| D1b subject whose only unresolvable ref is a `#N` absent from the tracker | 33 |
| D1 = D1a + D1b, "any unresolvable ref anywhere in the subject" under the round-1 extractor | 34 |

My "3" was neither of these cleanly: it counted subjects where a **non-first** ref failed to
resolve (`refs[1:]`), which mixes one prose case with two `#N` cases. Arithmetically right,
wrong denominator for the claim it supported. **Use 1.** The round-1 artifact above keeps the
"3" as written — it is what I reported — and this section is the correction.

Two more numbers so nobody reads them as regressions later:

- Under the round-2 extractor, 29 of the 400 would still be refused — and all of it is `#N` for
  numbers that were never created in the tracker (`#259`, `#244`, `#243`, `#213`, `#167`, `#165`,
  `#159`, `#158`, `#156` — each verified absent from `tm_tasks`). That is the documented
  "number handed out in a message without `task_create`" practice, which T1 abolishes, not a gate
  defect. `test_t2_unknown_commit_header...` requires this class to be refused; agreed.
- Narrowing `_parse_merged_commits` costs 26 of 400 subjects a resolvable link — and **0** of
  those 26 have a machine-built leading header. Every one is a hand-written commit (`session
  notes …`, `правило: … (#162)`) that never travels the merge path. No link is lost on any code
  path that `_parse_merged_commits` actually runs on.

## Your point 6 — your oracle verified, and one claim inside it is not defended

Independently re-ran three mutations against `tests/test_merge_ref_gate.py`; protocol each time
`cp F F.bak` → mutate → marker printed before → run → `mv F.bak F` + `touch` → marker printed
after → green repeat. All applied to a green suite; anchor uniqueness asserted so a
silently-unapplied mutation cannot read as "survived".

| mutation | before/after | result |
|---|---|---|
| M1 `_leading_task_refs` scans the whole message (revert the fix) | 1 / 0 | **2 failed — caught** |
| M3 `_strip_leading_task_refs` becomes a no-op | 1 / 0 | **1 failed — caught** |
| M4 `_parse_merged_commits` stops extracting refs | 1 / 0 | **2 failed — caught** |
| M6 reserved-trailer guard disabled | 1 / 0 | **1 failed — caught** (your point 4 claim confirmed) |
| M5 under-lock candidate recheck disabled | 1 / 0 | 12 passed — survives (answered above) |

Then the one that matters:

| mutation | before/after | result |
|---|---|---|
| M2 `re.IGNORECASE` on `_HEADER_TASK_REFS_RE` (869) | 1 / 0 | 4 passed — **survives** |
| M2b `re.IGNORECASE` on `_ONE_TASK_REF_RE` (872) | 1 / 0 | 4 passed — **survives** |
| M2c both regexes IGNORECASE | 1 / 0 | **1 failed — caught** |

`test_lowercase_prose_prefix_is_not_a_task_ref` says in its own docstring "an IGNORECASE header
would refuse honest work" — but making the header IGNORECASE leaves it green. Case-sensitivity is
held by **two** regexes and the test only fails when **both** are broken: `_HEADER_TASK_REFS_RE`
gates entry, and if it lets `wip-2` through, `_ONE_TASK_REF_RE` finds nothing inside it. That is
the "several features / fallback masks the mutation" pattern, and it is the specific reason the
rule about mutating a test written for a reported finding exists: your mutation
(`header.group(1)` → `message`) proved the *position* narrowing, not the *case* claim printed
next to it in the same test. Not blocking — the production behaviour is correct today, and a
single-regex regression is behaviourally near-equivalent (`wip-2: adjust parser` still yields no
refs either way; they diverge only on a mixed header like `wip-2, #42: text`). Worth one added
assertion or a docstring that names `_ONE_TASK_REF_RE` as the co-owner, so the next agent who
"tidies" one of the two regexes gets a red.

## Your point 7 — agreed, leave it to T3

All-or-nothing linking is post-commit-point recovery, which is exactly what `PREPARED → trailer →
recoverable finalize` is designed to own; splitting it into T2 would put half a recovery mechanism
in the merge path. Nothing regresses in the meantime: round 2 did not touch `app/routes/sessions.py`,
so v1 merges keep the per-ref loop with per-ref errors, and v1 is every merge until T3 ships and
agents reconnect.

## Still open from round 1 (unchanged by this diff, not a blocker)

`app/workspace.py:962` still emits duplicate refs when one branch carries both spellings of the
same task — the header-position narrowing did not change it, because both spellings sit in header
position:

```
['#248: a', 'PAR-248: b'] -> '#248, #248: a'
['ORC-1: a', '#1: b']     -> '#1, #1: a'
```

Harmless (`_leading_task_refs` dedups on the way back out, so `_validated_squash_message` and
linking both agree), but it is a permanent string in `main`. Deduplicating `all_refs` after the
numeric collapse is one line.

## Ruled out this round

- **ReDoS on the new anchored header regex.** Commit subjects are worker-controlled, and the
  pattern nests a quantified alternation inside a `*` group. Measured on `_leading_task_refs`:
  100 / 400 / 1600 / 6400 comma-separated refs with no terminating colon → 0.03 / 0.34 / 4.45 /
  5.01 ms; with spaced separators → 0.04 / 0.17 / 0.82 / 3.00 ms. Linear, no backtracking blowup.
- **Machine-built subjects still parse.** `#42, #44: linked candidate` → `['42','44']`;
  `#248, #248: a` → `['248']`; emoji/dash prefixes (`🔴 #42: x`, `#42 - x`) yield no header refs
  and correctly receive the platform's primary `#N`, and `_validated_squash_message` stays
  consistent in every one of those cases.

## Verdict round 2

APPROVED — 0 blocking
