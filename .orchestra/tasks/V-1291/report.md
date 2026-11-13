# V-1291 — Antigravity read of a missing file

## Scope and initial evidence

- Authorized files: `app/error_watch.py`, `tests/test_error_watch.py`,
  `CHANGELOG.md`, and this task directory. Work stays in the private worker copy.
- The task supplies the production observation: 8 ordinary `read_file` tool
  results and 8 legacy `error` banners with the same JSON. No production DB is
  accessed; checks use synthetic SQLite and mocked journal output.
- Existing `_event_noise` checks raw message/provenance before aggregation;
  `_POST_FIX_EVENT_NOISE` independently controls registered-fix observations.
  Both paths need the change. A signature-only rule would also hide legacy errors.
- Match the exact single-line response, including its spelling and spacing.
  Extra keys, multiline/concatenated messages, other tools and other provenance
  must remain actionable.
- HEAD is unavailable: this broker-provided copy has no `.git` or revision
  metadata. No commit/hash is invented; the importing platform owns the resulting
  `task-V-1291/error-watch-agy-read-1291` commit.
- Validation uses provisioned uv 0.11.28 and the default `<workspace>/.venv`.
  Temporary test files and pytest caches will stay under this task directory.
- Resource preflight: about 79 GiB available on the host, cgroup memory roughly
  16/49 GiB and 416/4096 PIDs; one sequential focused pytest run is appropriate.

## Validation

- Pre-fix regression run: 39 passed, 3 failed, 284 deselected. Two failures
  reproduce the missing noise classification and false completed-window recurrence.
  The third exposed a fixture assumption: journal collection's existing word
  filter does not admit standalone `TOOL_ERROR` JSON (`_` is a word character).
  Correct the journal fixture once to include the normal `ERROR:logger:` prefix;
  direct provenance tests still cover the exact JSON from `journalctl`.
  This does not change the collector or weaken the actionable-event contract.
  Evidence: `before-fix.log`.

## Delivered behavior

- `app/error_watch.py`: a raw string comparison in `_event_noise` requires all
  three exact provenance fields (`logs`, `tool_result`, `read_file`). The reused
  `agent read of missing file` class is added to `_POST_FIX_EVENT_NOISE`.
  No JSON parsing, substring/normalized matching, DB mutation or backend change.
- `tests/test_error_watch.py`: 42 new parameterized regression cases exercise
  real synthetic SQLite collection, aggregation, dry-run and stateful scan,
  registered-fix recurrence, completed observation and repeat-scan idempotency.
  The supplied 8-pair shape produces 8 noise events plus 8 actionable legacy
  banners; noise alone produces no alert or post-fix recurrence.
- Negative coverage retains `error`, wrong/missing tool/type/source metadata,
  `call_mcp_tool`, `Bash`, `write_file`, `edit_file`, journal records, extra JSON
  keys, arrays, malformed/concatenated JSON, case/format changes, newline/CR,
  whitespace and appended/prepended errors. Raw event inputs and SQLite rows are
  checked unchanged.
- `CHANGELOG.md`: manually added the V-1291 entry under Unreleased.

## Final checks and evidence

The required runner was available; no interpreter or dependency fallback was used.
The initial uv setup installed 76 locked packages.
The final suite and mutation probe ran with `UV_OFFLINE=1`.

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="<workspace>/.orchestra/tasks/V-1291/tmp"
export PYTEST_ADDOPTS="--basetemp=<workspace>/.orchestra/tasks/V-1291/pytest-tmp -o cache_dir=<workspace>/.orchestra/tasks/V-1291/pytest-cache"
export UV_PYTHON_DOWNLOADS=never
export UV_OFFLINE=1
uv run --frozen python -m pytest tests/test_error_watch.py -q
```

- **PASS: 326 passed in 4.20s**, exit 0, no failures/skips (`pytest.log`).
- **PASS negative control:** `mutation_probe.py` disables only the new
  `read_file` condition in memory. The positive DB/aggregate/scan regression
  fails at its candidate assertion: the 8 expected noise rows become a candidate.
  The probe requires pytest exit 1 and itself exits 0 (`mutation.log`). No source
  file is changed by this probe. Reproduce with the same environment, local temp
  directory and `PYTHONPATH=<workspace>`:
  `uv run --frozen python .orchestra/tasks/V-1291/mutation_probe.py`.
- **PASS import/runner identity:** `<workspace>/app` and
  `<workspace>/app/error_watch.py`, Python 3.12.3 from
  `<workspace>/.venv/bin/python` (`runtime-check.log`).
- **PASS scope/diff inspection:** `changes.patch` contains the complete diff.
  Removing only its three intentional insertions reconstructs the initial
  SHA-256 of each source file exactly, confirming pre-existing tests are intact.
  Initial/final hashes: `baseline-sha256.json`, `final-sha256.json`.
  `app/backend_antigravity.py`, `pyproject.toml` and `uv.lock` hashes are unchanged.
- Task-owned temporary databases and pytest caches were removed. Test commands
  terminated; no services, providers, production DB or real journal were used.
  Artifact paths are sanitized to `<workspace>`. Final audit: `audit.log`.

## Handoff limits

Required focused validation is complete. Full-suite validation and production
activation were not requested and were not performed. No service was started or
restarted. Exact source/result HEAD cannot be read or created in this `.git`-less
copy: the orchestrator must record the platform-created commit after import on
`task-V-1291/error-watch-agy-read-1291`. File hashes identify the checked source
without claiming they are Git HEAD.
