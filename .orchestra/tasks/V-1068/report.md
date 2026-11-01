# V-1068 — DONE

Source changes are limited to `app/error_watch.py`, `tests/test_error_watch.py`
and `CHANGELOG.md`; evidence stays under this task directory.
Expected Russian Codex exhaustion refusals now enter the existing
`quota/rate limit` noise class in both raw and normalized form. Matching is anchored
to the complete session refusal, recognized reset labels and time/unknown fields.
English matching and signature normalization are unchanged. A single compiled
`_CODEX_QUOTA_REFUSAL` matcher is reused by noise classification and
`post_fix_verdict`: only these recognized expected events are excluded from
recurrence. Normal `record_fix` registration and observation completion still
work; the fix record is retained. Other noise keeps its previous recurrence policy.

Source inspection: `backend_codex.py` marks `usageLimitExceeded` and
`sessionBudgetExceeded` as `codex_quota_exhausted`; `session.py` handles that flag
and emits the Russian refusal. Reset labels are `5h`, `7d`, `primary`, `secondary`;
missing, invalid or already elapsed reset observations produce `неизвестно`.
Numeric normalization partially replaces ISO timestamp components with `<N>`,
so matching only the raw date format would leave the aggregate defect unfixed.
This change makes no claim of an accounting failure or of current gate state.

Checks used the provisioned uv **0.11.28**, the frozen lock and default `.venv`:
`uv run --frozen python -m pytest tests/test_error_watch.py -q`.
Imported app: `/remote/workspace/app/__init__.py` (absolute path, sanitized).

- Initial classifier checks in the preceding turn: baseline **22 passed**, new
  regressions **8 failed** before the fix, final **43 passed**. Removing the
  Russian match and broadening it each caused **8 assertion failures**.
- Post-fix follow-up before the new exclusion: **3 failed, 2 passed, 43 deselected**.
  Both normal `record_fix → scan` controls falsely reported expected recurrence;
  the completed-observation control also counted the expected refusal.
- Post-fix full-suite control: **48 passed**. The required rerun after restoring
  the post-fix mutation also passed; its actual output is retained below.
- One bounded post-fix mutation (60-second subprocess timeout) removed only
  `and not _CODEX_QUOTA_REFUSAL.fullmatch(event_signature)`, retaining correct
  noise classification: **3 assertion failures, 45 deselected**. Source restored
  exactly before the final full-suite rerun.
- Final acceptance cleanup changed only tests and task evidence. Literal CLI
  wording assertions were replaced with structured signal/post-fix data,
  persisted fix/alert/recurrence state and reporting call counts. The test spy
  wraps the real formatter; deduplication checks ensure a second scan does not
  dispatch another report. Existing brittle checks in this same test file were
  converted too, including known-series growth and hub recurrence controls.
  Production source and CHANGELOG are byte-identical to the accepted version.
- After this cleanup the full file passed **48 tests**. The narrow post-fix
  mutation still caused **3 assertion failures, 45 deselected**: the two
  registration controls observed an unwanted report, and the completed-window
  control observed count one instead of zero. After exact restoration the final
  full-file rerun was **48 passed in 3.60 s**. No CLI wording is an oracle.
- Behavior checks cover ten refusals with varying reset times forming one noise
  aggregate, dry-run noise counts, no regular alert/state entry, a separate
  accounting failure alert and subsequent alert deduplication. Negative cases
  retain provider, accounting, parser and availability failures, including errors
  wrapped around the otherwise expected refusal. Reset fallbacks, two windows,
  fractional seconds, timezone offsets and existing English behavior are covered.
- New integration controls register both the expected refusal and a real
  accounting failure, scan ten expected events without a signal or recurrence
  flag, then add one real failure below the aggregate threshold and verify its
  post-fix alert. Both records survive; a subsequent scan deduplicates that alert.
  Known and unknown reset forms are covered. Separate controls preserve recurrence
  for English quota and hook-policy noise and allow expected-fix observation to
  complete with count zero.
- Reviewed the added diff and checked added content for credential shapes.
  Temporary fixtures were removed; actual command stdout/stderr logs were retained
  with the workspace prefix replaced by `/remote/workspace`:
  [runner](runner.stdout.log), [before fix](postfix-before.stdout.log),
  [full control](postfix-control.stdout.log),
  [mutation runner](postfix-mutation.stdout.log),
  [mutant pytest](postfix-mutant-pytest.stdout.log),
  [final full suite](postfix-final.stdout.log).
  Final behavior-only acceptance evidence:
  [full control](behavior-control.stdout.log),
  [mutation runner](behavior-mutation.stdout.log),
  [mutant pytest](behavior-mutant-pytest.stdout.log),
  [final full suite](behavior-final.stdout.log),
  [source integrity, runner/import and publication review](behavior-review.stdout.log).

Collectors were mocked for scan tests; SQLite collector coverage uses only a
fixture database. No real provider, source DB, SSH, service or restart was used.
The full suite and live deployment were not run. Future emitter wording outside
the recognized refusal remains actionable. No source guard, admission gate or
service was changed. The broker handles commit/import onto
`task-V-1068/fix-quota-noise`; no manual Git operation was performed.

## Host acceptance, 2026-10-24

Full report and final diff read. Complete `tests/test_error_watch.py` on VPS:48passed; imported app `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-quota-noise/app/__init__.py`. Independent in-memory post-fix-only mutation produced3committed-test assertion failures after a green48-test control; source untouched. Actual stdout retained in `.orchestra/private/V-1068/host-final-{control,mutation}.txt`. Real failures, other-noise recurrence, state retention and dedup remain tested. All final changed files scanned for credential forms and local literal/forbidden values. Private identifiers in three worker stdout files were replaced and explicitly marked; original verbatim output retained only in `.orchestra/private/V-1068/raw-worker-evidence/`. No modelreview under ownerfreeze.

Live detector jobbg-eafbc9d22e launches a fresh standalone `python -m app.error_watch` from main on each hourly run. This source path therefore needs NO Orchestra restart. After merge, register V1068 with the existing record-fix CLI and verify the expected live signature reads as noise; do not modify gates, source logs, or service state.
