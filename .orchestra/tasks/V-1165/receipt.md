# V-1165 — Stage B source acceptance receipt

## Result

Stage B safe source on `feat-terra` HEAD `c8861db636b1946f662cb36a5af3b4c1128d9762` passes the assigned focused host QA. The checked-in default pipeline still selects Opus; Terra is registered as manual-only and the future manifest patch remains unapplied. This validates safe mechanics without activating a Terra default. The source worktree remained clean throughout.

The actual Git change set from `main...HEAD` is exactly six paths: `app/routes/system.py`, `app/routes/sessions.py`, `app/static/js/app.js`, `tests/test_orchestrator_defaults_v1156.py`, `CHANGELOG.md`, and the V-1156 safe-stage report. Current source SHA-256 matches the Stage B receipt: `app/routes/system.py` `04dc04b2a869151355c477fa521c3447ff0024c02cb5400db14ccfccc06722b2`; `app/routes/sessions.py` `7de0ac976e4b8e062fb9aac416931dc7f9530d57cd91ba20ca3fde587ae284b1`; `app/static/js/app.js` `f157dba1cf4ce80fa216498c90e2f2c9bef45bb5e61c8c8ee80936908759ad35`. The committed acceptance test hash is `af76fea9c9ea8284380c9def4c78af8ef85d2f48cece61f5f23bbdaa7b80e827`. `pipeline.yaml`, model-routing, `app/models.py`, and `app/backend_codex.py` are unchanged in the source commit; the manifest-only patch was not applied.

## Checks

| Check | Result |
|---|---|
| Imported app | `feat-terra/app/__init__.py`; full path and stdout are private evidence |
| Instruction contract | RC 0: `Instruction contract OK` |
| Focused source tests | RC 0: 86 passed, 0 failed, 0 skipped, 7.68 s; included default/session/catalog/gates/registry/pipeline invalidation cases and Playwright Chromium frontend test |
| Real-browser default UI probe | RC 0, 5 cases passed, 0 page errors; local-only page/API routes tested server-default refresh, explicit-choice preservation, removed-choice fallback, and missing-default fallback using production `_renderModels`, `_loadModelsNow`, `loadModels`, and new-orchestrator click binding |
| Committed-test mutants | Both clean-copy baselines passed; two independent process-local mutations each produced the intended assertion failure (RC 1): explicit picker choice overwritten, and hidden model returned as default. The mutated copy’s source file hashes matched before/after restoration; test file SHA-256 matched committed HEAD |
| Source integrity | Git diff confirms the six-path set above; source status clean; changed-source hashes match the Stage B receipt; protected hot/model files unchanged |
| Publication checks | `scripts/secret_scan.py --staged` and `git diff --check` pass on this receipt |
| Full suite | Not run; the focused set covers the assigned source paths and checks |

Test setup used the existing locked `.venv` through `uv 0.11.28`, `--frozen --no-sync --offline`, synthetic `CODEX_HOME`, unset `NOTIFY_SOCKET`, the repository’s production-DB/test-catalog isolation fixture, bytecode disabled, and `/tmp` basetemp. Chromium was already installed; nothing was installed. Provider/CLI calls, service/config changes, and source mutations were not performed. Mutants ran only in temporary copies archived from committed HEAD, then were removed. Scratch homes were moved out of `/tmp` after testing.

Focused command targets were the new defaults test module, `tests/test_api.py::TestCreateSession`, `tests/test_model_catalog_frontend.py`, `tests/test_model_gates.py`, `tests/test_model_registry_503.py`, `tests/test_model_catalog.py`, `tests/test_model_flags.py`, `tests/test_terra_v1156.py`, six default-manifest/default-role tests, and `tests/test_pipeline.py::TestLoadPipeline::test_cache_invalidated_when_file_changes`; pytest ran with `-q --tb=short --timeout=20 -p no:cacheprovider`. The absolute imported `app` path is recorded only in private `source-identity.json`; its public relative path is `feat-terra/app/__init__.py`.

## Limits and discrepancy

The browser probe exercised the production selector and click-binding code in a local Chromium page with mocked local JSON responses; it was not a full dashboard boot. No live server activation or Terra inference was tested. The tracked V-1156 report says its copy had no `.git`, while the exact assigned `feat-terra` worktree has functioning Git metadata; this receipt uses the current worktree’s actual `git diff` and HEAD.

Raw test logs, browser probe output, mutation baselines/failures, source identity/hashes, and exact commands remain local in `.orchestra/private/V-1165/`; `artifact-manifest.txt` lists the artifacts.
