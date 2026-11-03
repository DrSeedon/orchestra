# V-1259 — two test fixes complete; Phase B static contract blocked

**New integration blocker: Phase B static manifest contract is RED.** Existing
model-routing.md:47 quotes `hub-gemini-4-argon`; once the saved Phase B patch
puts that ID in the actual manifest, the unchanged canonical checker rejects it.
This was reported immediately; no production source or guard was changed beyond
the two authorized test files. Root must resolve this separately before calling
Phase B integration green. Affected tests pass in both states; that does not
override this independent required check.

Root reported accepted source generation `6f7f5117de49a59dab6c5d108e3f3d42b5b1f1d4`,
not yet merged. This follow-up changes exactly two test files; the five previously
accepted recovery files, producer app/rules and all other source remain unchanged.
No new import/commit SHA is available in this no-.git worker copy.

1. Recovered tests/test_default_pipeline.py from exact public main
   `b9d893ec8babd4b2052ac1f497962e1966206bcb`, with ONLY specialist added to the
   exact expected-role set. Entire frozen V-1256 research-closure test and its
   2 roles × 3 modules parametrization are byte-exact. All six cases collected
   and passed in both phases. Canonical URL and SHA: canonical-source.json.
2. Specialist pipeline contract now accepts exactly Sol or exact Argon and
   requires the resolved model to equal the declared model. Removed the
   stage-specific Argon-string-absence assertion and unused Path import.
   Existing can_spawn, parent, skills, effort, disabled tool, prompt delivery,
   other-role Sol, admission, privacy, quota, recovery and history assertions
   remain. No prose-string acceptance added.

| Changed source | Actual diff | Final SHA-256 |
|---|---:|---|
| `tests/test_default_pipeline.py` | +21/−0 | `975557b8880a48cffb0122cefacd05aaa6a782f01a87d9a53461b2ed7cf8a97b` |
| `tests/test_gemini_specialist_v1257.py` | +3/−4 | `0c2fe412212cf1fa7041fb19a7d8647ab7ddbe1d46f38dd1585e4cb2b89c7150` |

Exact follow-up diff: two-test-fixes.patch. Full final SHA set for these two tests
and the five unchanged accepted recovery files: verification.json. Source snapshot
compares every initial non-environment/cache file, not only named target paths.

Actual tested manifest SHA-256: Phase A `69af96dc84e32751257824e8cdbad493a63d9126e88d3268a304c132363a8df6`;
temporary Phase B `7af87574909ff66a8e99b915bfe7f4a912fa0cdefa5ad9207da6a788713c9493`. Exact restoration
returns the temporary manifest to the same Phase A SHA; the root manifest was
never written (bytes and inode/mtime/size unchanged).

| Actual offline check | Result | Evidence |
|---|---|---|
| Phase A on actual root Sol manifest, affected test files + available contract tests | 149 passed, 33.5 s, exit 0 | phase-a-pytest.log, phase-a-evidence.json |
| Phase B on a task-local actual manifest patched by the unchanged saved patch, same tests | 149 passed, 42.3 s, exit 0 | phase-b-pytest.log, phase-b-evidence.json |
| Static manifest contract on actual Phase A | PASS, exit 0 | phase-a-pipeline-contract.log |
| Static manifest contract on actual temporary Phase B | RED, exit 1: existing model-routing.md:47 quotes manifest model ID | phase-b-pipeline-contract.log |
| Phase B patch dry-run, fuzz=0 | PASS, exit 0 | phase-b-dry-run.log |
| Temporary Phase B tree restored byte-for-byte to copied Phase A; process-local pipeline pointer restored | PASS | phase-b-evidence.json |
| Root Phase A manifest bytes and inode/mtime/size unchanged throughout both runs | PASS | phase-a-evidence.json, phase-b-evidence.json |
| Actual-root instruction script | RED, exit 1: missing CLAUDE.md in sparse copy | instruction-contract.log |
| Old V-1257 and earlier V-1259 artifacts | 75 byte-identical; earlier 625-pass log and missing-CLAUDE red preserved | prior-artifacts-manifest.json, verification.json |

Both runs used provisioned uv 0.11.28 and default .venv, UV_OFFLINE=1,
serial/nice=10/OOM score=1000, 180-second outer timeout each. No failed or skipped
cases in either completed test run. The separate Phase B static check remains
red. Included checker tests still exercise their canonical real-root Phase A and
synthetic fixtures; the independent `--manifest` check above is the actual Phase B
contract result. No repeat of the 625-case set or full suite.
Exact app import was asserted against this workspace's app/__init__.py;
absolute resolved path SHA is in both evidence JSONs. The final handoff links
the actual absolute local app file. Tests used synthetic fixtures, not live DB,
provider turns, SSH, restart or service state.

Commands (prepend provisioned uv PATH in each test shell; prepend this task's
final-integration directory to PYTHONPATH for the task-local evidence plugin):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
# UV_OFFLINE=1, task-local TMPDIR; each test command: timeout 180s nice -n 10
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=A --basetemp=.orchestra/tasks/V-1259/final-integration/scratch/pytest-a -o cache_dir=.orchestra/tasks/V-1259/final-integration/scratch/cache-a
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=B --basetemp=.orchestra/tasks/V-1259/final-integration/scratch/pytest-b -o cache_dir=.orchestra/tasks/V-1259/final-integration/scratch/cache-b
uv run --frozen python .orchestra/tasks/V-1259/final-integration/finalize_followup.py
# Plugin runs --dry-run and applies this same patch ONLY inside task-local copied source:
patch --dry-run --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
patch --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
# Same .venv Python runs static checks on each phase's actual manifest:
uv run --frozen python scripts/check_pipeline_manifest.py --check --manifest <phase-manifest>
uv run --frozen python scripts/check_instruction_contract.py
```

phase_manifest_checks.py only redirects the in-process pipeline root for Phase B;
it verifies the exact loaded Argon model before tests, checks all native/default/
other-role YAML data unchanged except saved specialist model/description delta,
and restores the temporary manifest, tree and pointer afterward. It never edits
the actual root manifest. Task-owned scratch was removed after verification.

Remaining limit: complete-host root instruction/KB/link check, merge, normal idle
activation, live registry and normal admitted specialist smoke remain root's work.
The newly found Phase B manifest/prompt contract conflict also requires root action.
Phase B has NOT been hot-applied or activated. Source identity is accepted, not
merged. No new models/review/spawn, paid calls, restart/deploy, publication,
private DB/SSH, commit or push. Existing privacy/publication guards are unchanged.
Two unsuccessful preparatory attempts are retained: the mechanical recovery-anchor
script stopped before source writes (corrected unique anchor, notes.md); the first
Phase B pytest attempt exited 3 BEFORE collection because the task plugin aborted
on the real static-check failure. Its error/evidence are phase-b-pretest-error.log,
phase-b-pretest-error-evidence.json and phase-b-pretest-contract.log. Only the
workspace account path in that new error log was normalized; the original log
hash/size are preserved. The task plugin then recorded the separate red checker
without aborting the independent affected tests; no canonical guard/test assertion
was weakened or skipped. The original 625-case log and earlier red root check
remain byte-identical.
