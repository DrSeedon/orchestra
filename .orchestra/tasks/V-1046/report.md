# V-1046 — hub error-watch signatures

## Changes

- `app/error_watch.py` derives hub-turn signatures from the exception class,
  HTTP status, or the explicit hub-thread-failed outcome. `ReadError` and
  `RemoteProtocolError` differ; HTTP 400 and HTTP 503 differ. Request/thread
  identifiers, paths, numeric details and variable exception messages do not
  split these classes. Unknown hub causes retain the usual normalization.
- `hub_provider_limit`, hub usage-limit messages and the exact credential-guard
  refusal become expected noise. Recognition precedes the 1,000-character
  truncation and generic exception extraction, including `(no output)` wrappers.
- These two noise classes are excluded explicitly from post-fix counts.
  Existing noise classes and non-hub normalization retain their previous paths.
- Seven new tests in `tests/test_error_watch.py` cover distinct signatures,
  normalization stability/idempotence, recurring and post-fix exclusions,
  threshold boundaries for real transport errors, long wrappers, and scan/state
  recovery with legacy `(no output)` state. The scan test also checks that a
  real post-fix recurrence is reported exactly once and fix records survive.

## Actual checks

Required command attempted:

```text
uv run --frozen python -m pytest tests/test_error_watch.py -q
uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)
```

`python -m pytest ...` also could not run (`python: command not found`).
`python3 -m pytest ...` could not run (`/usr/bin/python3: No module named pytest`).
No dependencies were downloaded and no provider/service was contacted.

Additional, limited offline command actually run using Python 3.12.3:

```text
python3 .orchestra/tasks/V-1046/validate_offline.py
```

- All 22 test functions succeeded in this standalone harness.
- Reverting the entire fix in memory made all seven new tests fail with
  assertion failures. Reverting only the post-fix exclusion also made its
  dedicated regression test fail.
- The harness imports the actual changed `app.error_watch`, but substitutes
  unavailable `app.db.DB_PATH` and an identity `app.secret_mask.mask_secrets`.
  It supplies small equivalents of `tmp_path`, `monkeypatch`, and `capsys`.
  This is supplementary evidence, **not the required pytest check** and not
  verification of real secret masking, pytest plugins, or application imports.
- The harness uses nice 15, a 2 GiB address-space limit, and temporary SQLite
  databases/directories only beneath this task directory. It deletes these
  temporary directories after each case.
- Exact output and the reproducible harness are in `offline-validation.txt`
  and `validate_offline.py` alongside this report.
- Python syntax and trailing-whitespace checks passed for changed source, tests
  and task artifacts. A local credential-shape scan found no private-key,
  OpenAI/GitHub token or Telegram bot-token forms in these five files; the
  project's real `mask_secrets` filter is absent from this private cone.

Imported `app` namespace path:
`<hub-workspace>`.
Imported watcher:
`<hub-workspace>`.

## Findings and limits

- `post_fix_verdict` previously matched signatures independently of noise
  classification; marking a row as noise in aggregation alone was insufficient.
- HTTP status must be extracted before the existing numeric scrubber, otherwise
  different statuses become the same `<N>` signature.
- Legacy state is readable without migration. Obsolete alerts leave the active
  set naturally; stored fixes are preserved. A legacy `(no output)` fix cannot
  be mapped unambiguously to one of the new cause signatures. Register the
  relevant cause signature for future targeted post-fix observation.
- A row containing only literal `(no output)` and no cause/stop reason cannot
  be reconstructed by this text-only watcher. Such rows are not silently
  suppressed. This change classifies rows carrying the error text specified in
  the task; the historical incident and production journal were not accessed.
- Required targeted pytest, full-suite and instruction-contract checks remain
  unrun: no usable uv/pytest, and the private cone lacks `app.db`,
  `app.secret_mask`, and project test/contract scripts. Run the required targeted
  check in the complete worktree before accepting the result.
- Only supplied source/test files and this task's artifacts were changed;
  no git operations, deployment, or restarts were performed. All new examples
  are synthetic; no production logs, credentials or raw secret dumps were used.
