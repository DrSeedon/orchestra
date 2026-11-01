# V-1146 — standalone provider capacity refusal

Worker: `fix-capacity-watch-class`; broker destination:
`task-V-1146/fix-capacity-watch-class`.

## Change

`app/error_watch.py` recognizes exactly
`Selected model is at capacity. Please try a different model.` as
`external provider capacity`, using case-sensitive absolute string anchors.
Existing `normalize_signature` remains the sole owner of logger-prefix and
whitespace normalization. The category is excluded from registered-fix
recurrence counts as well as normal candidate findings, so an old recorded fix
does not create another alert for this expected outcome.

The existing provider-limit matcher, normalization, raw log storage, frontend,
merge-gate rules, retry/model selection and backend calls are unchanged.
CHANGELOG has one concise Unreleased entry.

33 new parametrized cases cover raw/normalized signatures, both event sources,
unchanged event dictionaries and stored synthetic SQLite rows, grouping and
thresholds at 9/10, dry-run and persisted scans, repeated scans, retained legacy
fix state and observation-window completion. Negative controls include Hub
failed wrappers, application exceptions, data loss, prefix/suffix additions,
quoted text, partial/changed messages and unrelated capacity failures. Five real
error controls each produce a new finding after reaching the threshold beside
the expected refusal; repeats retain normal deduplication.

## Actual commands and results

Every Python shell used the broker runner:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
```

`command -v uv` returned
`/home/<private-identifier>/.local/share/orchestra/tools/uv/0.11.28/bin/uv`;
`uv --version` returned `uv 0.11.28 (x86_64-unknown-linux-gnu)`.
The frozen environment was created at the default `.venv` (76 locked packages).

1. Required targeted run:

   ```sh
   uv run --frozen python -m pytest tests/test_error_watch.py -q --basetemp=.orchestra/tasks/V-1146/pytest-tmp > .orchestra/tasks/V-1146/pytest.log 2>&1
   ```

   Exit 2 during collection. Raw evidence in `pytest.log`:

   ```text
   app/error_watch.py:18: in <module>
       from app.db import DB_PATH
   E   ModuleNotFoundError: No module named 'app.db'
   1 error in 0.63s
   ```

   This private source copy also lacks `app/secret_mask.py` and
   `app/hub_activity.py`, required by the module/existing tests. No replacement
   application dependency was added to the source tree.

2. Required full-suite entry point:

   ```sh
   uv run --frozen python scripts/run_tests.py > .orchestra/tasks/V-1146/full-suite.log 2>&1
   ```

   Exit 2: `scripts/run_tests.py` is absent from the supplied copy. Raw error is
   preserved in `full-suite.log`. The required full suite remains unrun.

3. Supplemental isolated diagnostic, NOT the required production-import check:

   ```sh
   uv run --frozen python .orchestra/tasks/V-1146/isolated_probe.py --basetemp=.orchestra/tasks/V-1146/probe-tmp > .orchestra/tasks/V-1146/isolated-probe.log 2>&1
   ```

   Exit 0; raw result: `71 passed, 132 deselected in 1.29s`.
   Includes all 33 new cases and existing quota, merge and selected Hub error
   controls. The diagnostic supplies an unused in-memory `app.db.DB_PATH`
   sentinel and an identity `app.secret_mask.mask_secrets` stand-in before
   importing the actual `app/error_watch.py`. It runs the unchanged pytest test
   functions; collectors use only synthetic SQLite or mocked journal input.
   This checks classification/aggregation/state logic with the real uv runner,
   but cannot establish real masking or missing-module integration correctness.
   The exclusions are diagnostic scope, not a passing full-suite claim.

4. In-memory negative control (production files unchanged):

   ```sh
   uv run --frozen python .orchestra/tasks/V-1146/isolated_probe.py --without-capacity-rule --basetemp=.orchestra/tasks/V-1146/negative-tmp > .orchestra/tasks/V-1146/negative-control.log 2>&1
   ```

   Exit 1 as intended. Raw result:
   `15 failed, 56 passed, 132 deselected in 1.23s`.
   Removing only the new classification entry makes all 10 positive event
   cases and all five scan controls fail. This demonstrates detection of the
   original defect; the recurrence exclusion stays enabled in this control.

5. Package location:

   ```sh
   uv run --frozen python -c 'import app; from pathlib import Path; print("app.__file__:", app.__file__); print("app.__path__:", [str(Path(p).resolve()) for p in app.__path__])' > .orchestra/tasks/V-1146/imports.log 2>&1
   ```

   Exit 0. This reduced copy has a namespace package (`app.__file__: None`):
   `/home/<private-identifier>/orchestra-ws/vmi3407579/hub-43e35c110430406d/app`.
   The diagnostic imported:
   `/home/<private-identifier>/orchestra-ws/vmi3407579/hub-43e35c110430406d/app/error_watch.py`.

Reviewed the changed source, tests and changelog. A secret-form search over
source and task artifacts found no matches for API/GitHub/AWS key shapes or
private-key headers; all newly introduced evidence is synthetic.

## Non-obvious findings and remaining acceptance

Noise classification alone is insufficient for old `record-fix` state:
`post_fix_verdict` has a separate recurrence path, which needs the same exact
exclusion. Existing quota/hook noise still follows its existing recurrence
policy; no blanket exclusion of all noise was added.

Hub normalization may collapse mixed failures into an exception/status
signature. The new matcher does not inspect inside these messages and does not
change that behavior; those failures remain actionable in the controls.

Parent must run the real targeted suite and full host suite with all original
source dependencies before acceptance. No live DB, journal, private files,
provider/native CLI workload or service was accessed. No worker was spawned,
and no Git command, service change, deployment or restart was performed. The
broker performs commit/sync-back when this turn ends.

Parent publication preparation: private source-copy identifiers in report/log paths were normalized to `<private-identifier>`; original artifacts are preserved locally outside Git. Source/test code and test results were not changed.
