# #506 Phase 3 report

## Status

- T1 complete and ready to merge.
- T2 not started. It remains blocked on #490 merge, T1 merge, owner-initiated restart, MCP reconnect, successful live size-skip receipt probe, and prompt-tree handover.

## T1 implementation

- `app/mcp_stdio.py:3647-3780` — one owner for the 40-line/3-file constants, verbatim evidence weakness, NUL-safe complete-diff numstat parser, and fail-safe decision.
- `app/mcp_stdio.py:4154-4179` — `codex_review(required: Any = True)`; only Python identity `required is False` unlocks arithmetic skip, so omitted/null/string/number/true all review.
- `app/mcp_stdio.py:4255-4332` — implementation-mode size decision before project-context/quota/model work; deterministic `review-size-skip:` receipt using the existing schema; structured and human-readable result.
- Complete diff is `git diff --numstat -z target_sha...worker_head` without a path filter. `production_paths_json` is not passed into the size decision.
- Skip receipt `outcome_evidence_ref` carries changed lines, changed files, threshold, and verbatim: `` `n=2`, and the first observed blocker sits three lines above it (#502 round 1, 43 lines / 2 files). ``
- No path-keyword risk classifier, database migration, merge-gate edit, JSONL execution-evidence edit, `_PLATFORM_OWNED_STATUSES` edit, ceiling change, or routing change.

Implementation commit: `3fcf9dda` (`#506: gate small low-risk final reviews`).

## Oracle correction before implementation

The originally frozen console-script command was not an oracle for this branch:

- `uv run pytest ...` loaded `/mnt/data/Projects/Python/orchestra/app/mcp_stdio.py` from the main checkout because inherited `PYTHONPATH=/mnt/data/Projects/Python/orchestra` preceded the worktree for the pytest console script.
- `uv run python -m pytest ...` loaded `/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/review-policy/app/mcp_stdio.py` because module execution put the current worktree first.

The production attempt was removed before re-closing. The test files stayed byte-identical to `25c3b4f8` and `c25e6632`; only the named command changed in `176010b6`. Full corrected RED output is `.orchestra/tasks/506/red-command-output.txt`: `8 failed`, first missing behavior `AssertionError: T1 missing complete-diff review size gate`.

## Verification

- Corrected immutable T1 oracle: `uv run python -m pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py` → `8 passed in 1.37s`.
- Plan-focused regressions: `uv run python -m pytest -q tests/test_mcp_codex_review.py tests/test_review_coverage_gate_462.py tests/test_review_receipt_storage_436.py` → `42 passed in 6.11s`.
- Combined T1 + focused regressions: `uv run python -m pytest -q .orchestra/tasks/506/test_t1_review_size_gate.py .orchestra/tasks/506/test_t1_review_size_gate_edges.py tests/test_mcp_codex_review.py tests/test_review_coverage_gate_462.py tests/test_review_receipt_storage_436.py` → `50 passed in 6.54s`.
- Rename/path probe: Git emitted `b'0\t0\t\x00old\tname.py\x00new\nname.py\x00'`; `_parse_review_numstat` returned `(0, 1, 0)`.
- End-to-end scratch probe: `{'kind': 'review_skipped_by_size', 'lines': 20, 'files': 1, 'coverage': 'satisfied', 'outcome': 'skipped', 'same_receipt': True, 'weakness': True}`.
- Tool schema probe: `required` has default `true` and no coercing type schema, so the implementation receives the original JSON value and checks literal identity.
- `git diff --check` → no output.
- `ruff` was unavailable in the worktree environment: `No module named ruff`; this is not reported as a passing lint run.

A broader 81-test review surface produced 72 passes and 9 failures. The same nine tests fail on current main (`15 passed, 9 failed` when limited to their two files), all before this change at project-context setup on non-repository fixture paths. They are not attributed to T1 and were not modified.

## Pre-mortem and checks

1. **Wrong checkout tested** → false green/red unrelated to worker code. Check: both absolute import paths recorded above; corrected command loads the worktree.
2. **Foreign project has empty `production_paths_json`** → whole project silently skips. Check: 100-line `foreign/core.py` diff with no `app/**`/`scripts/**` projection returns `review` with `changed_lines=100`.
3. **Caller forgets or malforms risk input** → authorization/credential diff skips. Check: `True`, omitted, `None`, string `"false"`, and integer `0` all start review; only literal `False` skips.
4. **Binary or broken Git measurement is counted as small** → unsafe skip. Check: binary returns `binary_diff`; malformed numstat and unresolved ref fail safe to review.
5. **Retry creates multiple authoritative skips** → ambiguous audit history. Check: identical retry returns the same receipt ID and the database contains one skipped row.
6. **Receipt exists but merge consumer cannot use it** → apparent skip still blocks delivery. Check: scratch `coverage_decision()` returned `status='satisfied'`, `coverage_outcome='skipped'`, and the identical receipt ID.
7. **Prompt advertises code before live owner works** → fleet-wide broken requirement. Check: T2 remains untouched and blocked until merge/restart/reconnect/live probe.

## Review

- Route: Luna, two rounds on the same thread.
- Round 1: no T1 code defect; one blocking finding incorrectly treated intentionally RED, out-of-scope T2 as part of T1.
- Author outcome on snapshot-bound receipt `review-receipt:f8fa06b1-2b02-4385-9ddc-3afae2329f90`: `disputed`, with Round-2 evidence.
- Round 2: reviewer withdrew the T2 finding and returned `T1 implementation: PASS`; exact changed line checked: `if required is not False:`. Artifact: `.orchestra/tasks/506/review-t1-implementation-luna.md`.

## Merge coordination

Other branches changed the same file outside T1: `_PLATFORM_OWNED_STATUSES` and `_CODEX_EXECUTION_FAILURE_JSONL_CHECK`. T1 did not touch either region. Determine T1 ownership from its commits, not from `git diff main HEAD`; the T1 production commit is `3fcf9dda` and contains only `app/mcp_stdio.py` size-decision/receipt hunks.
