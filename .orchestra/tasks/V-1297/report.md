# V-1297 — narrow optional shared-private warning classification

VERDICT: source change prepared; required runtime acceptance BLOCKED by incomplete task bundle.

## Change and scope

- `app/error_watch.py`: match the complete raw journal warning before normalization.
  Accept only the bare helper message or its `WARNING:app.private_folder:` form,
  identical nonempty cwd strings and the exact non-Git fatal cause. Reject ambiguous
  colon/newline/placeholder paths. Add this event class to registered-fix exclusions.
- Signature-only classification stays unchanged, so normalization cannot establish
  provenance or erase differing cwd strings before the decision. No broad
  `git-common-dir failed` exclusion was added.
- Permission/ownership/config/corrupt-Git failures, other sources/loggers/levels,
  truncated messages and mixed errors remain outside the new matcher.
- `tests/test_error_watch.py`: five new parameterized behavioral test functions cover
  aggregate/noise counts, real helper output, negative boundaries, synthetic journal
  JSON + SQLite scan, 12 raw / 10 deduplicated records, registered-fix observation
  completion, persisted flags/repeated scans, and actionable records sharing a
  normalized signature. Existing test/helper function ASTs are unchanged.
- `CHANGELOG.md`: manual Unreleased entry. No changes to private-folder API, manager,
  normalization, deduplication, production state, Git/config/credentials or services.

## Checks actually executed

Every Python shell used:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
```

1. Before source edits:
   `uv run --frozen python -m pytest tests/test_error_watch.py -q --basetemp=.orchestra/tasks/V-1297/pytest-tmp`
   — exit 2; collection failed with `ModuleNotFoundError: No module named 'app.db'`.
   uv 0.11.28 created the default `.venv` and installed 76 locked packages.
   Evidence: `baseline-pytest.log`.
2. After source edits:
   `uv run --frozen --offline python -m pytest tests/test_error_watch.py tests/test_main_private_v1142.py -q --basetemp=.orchestra/tasks/V-1297/pytest-tmp`
   — exit 2, two collection errors: the same missing `app.db` and
   `ImportError: cannot import name 'orchestra_layout' from 'app' (unknown location)`.
   Evidence: `final-pytest.log`.
3. Final standalone required-file attempt:
   `uv run --frozen --offline python -m pytest tests/test_error_watch.py -q --basetemp=.orchestra/tasks/V-1297/pytest-tmp`
   — exit 2; missing `app.db`, zero tests executed.
   Evidence: `error-watch-pytest.log`.
4. `uv run --frozen --offline python -c 'import runpy; runpy.run_path(".orchestra/tasks/V-1297/reproduce_helper.py", run_name="__main__")'`
   — exit 0. Real `ensure_main_private` plus read-only Git discovery in a fresh
   isolated standalone directory reproduced the exact warning, returned `None`,
   and left the directory empty. No Git repository/config was created. This tests
   the available helper only; it does not substitute for error-watch acceptance.
   Evidence: `reproduce_helper.py`, `helper-reproduction.log`.
5. `uv run --frozen --offline python -` with stdlib syntax/AST/diff checks
   — exit 0. Changed Python files and helper reproduction compile; the new regex
   compiles; `_event_noise` is the only changed production function; all original
   test/helper function ASTs match; final diff inspected. Evidence: `static-checks.log`.
6. An initial helper invocation used an invalid dotted module name
   (`uv run --frozen --offline python -m .orchestra.tasks.V-1297.reproduce_helper`)
   — exit 1, `Relative module names not supported`; corrected by step 4.

Logs replace the worker-copy absolute prefix with `<BUNDLE>`; warning paths in
reproduction evidence use `<PATH>`. Source tests contain only synthetic paths/data.

## HEAD, diff, and handoff

- Source branch specified by broker: `task-V-1297/errorwatch-private-v1297`.
- HEAD/commit: unavailable. This isolated hub copy has no `.git`, remotes or supplied
  HEAD metadata. The critical worker contract forbids `git commit`/push/clone;
  Orchestra must commit accepted imported changes on the task branch after handoff.
- Diff: `changes.patch`; `app/error_watch.py` +14/-1,
  `tests/test_error_watch.py` +204/-0, `CHANGELOG.md` +7/-0.
- No full `app` import succeeded: `app/error_watch.py` stops at its `app.db` import.
  `app/private_folder.py` was imported from this task's bundled source for step 4.
- No production DB/journal, provider CLI, backend route, deployment or service was
  accessed. No fallback modules or alternate pytest runner were introduced.

## Remaining acceptance / limitations

The bundle also omits `app/secret_mask.py`, `tests/conftest.py` and `scripts/`.
The required error-watch suite, related private-folder suite and behavioral
red-before/green-after proof remain UNVERIFIED; syntax checks do not prove them.
Aggregate and registered-fix outcomes above are regression assertions, not measured
runtime results in this incomplete checkout. The 12/10 production observation is
task-provided context, reproduced as synthetic input in the new tests, not recollected.
The parent must run the required suites in its complete isolated checkout, confirm
the new positive tests fail without the classifier change, and commit the imported
result. Do not infer live activation or deployment authorization from this report.
