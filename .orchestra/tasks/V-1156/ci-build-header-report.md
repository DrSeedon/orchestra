# V-1156 — CI build-header test fix READY

Parent supplied actual failed CI: commit `d26e625cc`, run **41215915239**, shard 2 job **124580284807**. Its result was 1 failed / 1058 passed / 12 skipped / 19 subtests; the other six jobs passed. Failure: `tests/test_build_signal.py::TestModelsHeader::test_header_present_and_body_unchanged` rejected the legitimate additive `default_orchestrator_model` key. The parent's canonical raw trace remains with the parent; this source-only copy did not fetch protected host data or rerun that CI.

## Fix

Only `tests/test_build_signal.py` and a test-only CHANGELOG entry changed in product/test source. Replaced the frozen exact body-key set with equality between the HTTP JSON and the direct endpoint result after normal FastAPI JSON encoding. The baseline includes all current/future endpoint fields instead of enumerating them. A second HTTP call changes only the build-header provider and must retain the same payload.

Existing checks still require status 200, actual build header equality, equal GET/HEAD build headers and an empty HEAD body. Two committed negative controls inject (1) a body change only on the wired HTTP route, absent from the direct endpoint baseline, and (2) a version value into both endpoint/HTTP JSON which changes with the header. Both must trip the payload check; call counts also confirm that the version-leak control reaches the changed-header request. These are behavioral controls, not wording assertions or another hardcoded key list.

No API fields removed, no rollback or product-interface bypass. Native gate, role/prompt YAML and default selection source remain unchanged. Model review stays frozen; no runtime activation, restart or live session migration was performed or authorized by this fix.

## Actual checks

Runner: provisioned **uv 0.11.28**, default locked `.venv`; `UV_OFFLINE=1`, task-private TMPDIR and synthetic CODEX_HOME, NOTIFY_SOCKET unset. Synthetic Git author/committer variables were local to the test shell; no Git configuration changed. Imported app:

`worker-copy/app/__init__.py`

- `uv run --frozen python -m pytest tests/test_build_signal.py tests/test_orchestrator_defaults_v1156.py tests/test_catalog_api.py tests/test_models.py tests/test_terra_v1156.py -q --tb=short --timeout=20`: **73 passed, 0 failed, 0 skipped**, 16.63 s. This run preceded adding the two negative controls.
- Final `uv run --frozen python -m pytest tests/test_build_signal.py -q --tb=short --timeout=20`: **10 passed, 0 failed, 0 skipped**, 12.08 s, including both committed negative controls.
- Reviewed scoped diff; Python AST parse and patch syntax check passed. SHA-256 comparison confirms all recorded product files, native model/accounting code and hot pipeline/model-routing files are unchanged.

No full suite repeat, browser check, provider call, model review or new CI run. **Full CI is not claimed green**; the next actual commit's CI remains the required global result. There were no local red tests in these two runs; the original CI red is explicitly recorded above.

## Result and artifacts

Ignored raw artifacts: `.orchestra/tasks/V-1156/private/ci-build-header/targeted.log`, `final-build.log`, `fix.diff`, `before-hashes.json`, `source-hashes.json`, `import-path.log`. Synthetic scratch directories removed after checks. SHA-256:

- `tests/test_build_signal.py`: `70456d636ae9dc7b4e8ec65fddec7e6092f33c6e89661a1088472a4dede9454b`
- `CHANGELOG.md`: `e19bdb77d1767c59a3013392addce5849c551f1474b1b6498255e90c5529352b`

Source-only copy has no `.git`: real branch diff, platform commit and clean-WIP verification belong to the platform/parent. No push was attempted. The deferred manifest-only Terra High patch remains unapplied and gated on both live host registries; this fix creates no new restart permission.
