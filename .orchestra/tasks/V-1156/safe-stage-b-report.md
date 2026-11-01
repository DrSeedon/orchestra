# V-1156 — SAFE Stage B READY; Terra High manifest remains gated

Stage A accepted/merged `460d12c2`, host receipt (including Chromium) — supplied by the parent, not rerun or claimed as this worker's check.

## Applied source changes

- `app/routes/system.py::list_models` exposes the **current** default-pipeline orchestrator model, only if dashboard-visible. Missing/invalid manifest metadata yields no preferred default, while the model catalog remains available. No Terra ID is hardcoded in this lookup.
- `app/routes/sessions.py::CreateSessionRequest.validate_worktree` resolves the role default only for a new orchestrator request with omitted model. Explicit choices and worker/ad-hoc defaults retain their paths. Invalid default metadata refuses creation rather than inventing a model; existing admission still owns permissions.
- `app/static/js/app.js::_renderModels` distinguishes an explicit user choice from an automatic default. Explicit valid choices survive refresh; automatic choices follow the server's current default; removed/hidden models cannot become sticky choices. Opening the new-orchestrator form refreshes models through the existing coalesced request.
- Test file `tests/test_orchestrator_defaults_v1156.py` is included in the source result, and CHANGELOG updated. No whole candidate files were copied over product source; edits were narrow hunks. V-1160 coordination points are the two Python symbols above, JS `_renderModels` and the `#new-orch-btn` click handler.

Hot `pipeline.yaml` and `model-routing.md`, `app/models.py` and `app/backend_codex.py` are **byte-identical to this task's starting baseline**. No live/stored sessions, registry auto-reload, services, CLI configuration, credentials or ordinary-worker admission were changed. Source readiness is not Python runtime activation and grants no restart permission.

## Checks actually run

Provisioned **uv 0.11.28**, `uv run --frozen python -m pytest`, locked default `.venv`, `UV_OFFLINE=1`, task-private TMPDIR and synthetic CODEX_HOME; NOTIFY_SOCKET unset. Lifespan tests use shell-local synthetic Git identity, never Git config changes. Imported app:

`worker-copy/app/__init__.py`

- First targeted attempt: **95 passed / 9 failed**, 14.22s: malformed new fixture YAML plus missing synthetic Git identity; corrected. The broken-YAML case also established the need to handle `YAMLError` at the new lookup boundary.
- Broader relevant run: **392 passed / 5 failed**, 150.63s. Five failures were missing mandatory labels in the new fixture, now corrected. Existing API/create-session, model catalog/registry, gates, local Luna, pipeline/default-pipeline and instruction tests passed. The attempted one-shot interrupt found the test PID already gone; the run completed normally. This run is not presented as all-green.
- Final targeted run: **24 passed / 0 failed / 0 skipped / 1 browser deselected**, 14.47s. Command: `uv run --frozen python -m pytest tests/test_orchestrator_defaults_v1156.py tests/test_api.py::TestCreateSession tests/test_model_catalog_frontend.py -m 'not browser' -q --tb=short --timeout=20`.
- **5/5 mutations caught**, expected RC1 behavioral failures: hardcoded future Terra default with legacy registry; bypassing visibility; overwriting explicit model; applying orchestrator default to workers; forgetting explicit picker choice. Every source file restored byte-for-byte in finally. Post-mutation final file check: **16 passed**, 9.88s.
- Future manifest candidate: **3 passed**, 6.56s, using real current routes/backend construction and a preparation-only pytest plugin redirecting `PIPELINES_DIR` to the private candidate. No inference; no writes to hot YAML. Temporary root future-test file removed in finally.
- Reviewed scoped diff, parsed Python AST, checked patch syntax with `git apply --numstat`; token/key-form scan of changed product/test files found no matches. No `.git` exists here: diff is reconstructed from saved task-start bytes, not a Git base comparison. Real Git diff/commit and concurrent-hunk preservation remain platform/parent duties.

The browser exclusion is explicit: this copy still lacks the Playwright Chromium installation. The new UI checks execute actual JS functions under offline Node with small DOM stubs; they are not a full browser/host check. No full suite repeat, live provider call, model review or real benchmark was performed.

## Deferred manifest-only patch

Use `private/safe-stage-b/manifest-only.patch`, **not** the historical five-file `private/stage-b/stage-b.patch` (marked superseded). The new patch contains only:

1. Hot YAML: orchestrator/sub-orchestrator default `gpt-6.1-terra`, exact explicit `high` in their effort map. Global and ordinary worker defaults stay intact.
2. Dated English owner-choice summary in model-routing, without installation-specific names.
3. Future committed acceptance tests `tests/test_orchestrator_terra_manifest_v1156.py`.

No Python routes or JS hunks remain in that patch. Apply it **only after the parent/protected executor confirms both running host registries recognize Terra**; files on disk or CLI listing alone do not satisfy the gate. The safe mechanics can activate with Stage A while the old manifest remains valid. After that, selecting the new default is a manifest-only hot change; this is not permission for another Python restart or for automatic migration of live sessions. Existing-session rollout remains V-1163; real bench remains V-1162; model review frozen. Neither host activation nor the actual Terra default is claimed complete here.

## Hashes and evidence

Full before/after SHA-256 and unchanged flags: `private/safe-stage-b/source-hashes.json`.

| Source | SHA-256 after |
|---|---|
| app/routes/system.py | 04dc04b2a869151355c477fa521c3447ff0024c02cb5400db14ccfccc06722b2 |
| app/routes/sessions.py | 7de0ac976e4b8e062fb9aac416931dc7f9530d57cd91ba20ca3fde587ae284b1 |
| app/static/js/app.js | f157dba1cf4ce80fa216498c90e2f2c9bef45bb5e61c8c8ee80936908759ad35 |
| tests/test_orchestrator_defaults_v1156.py | af76fea9c9ea8284380c9def4c78af8ef85d2f48cece61f5f23bbdaa7b80e827 |

Raw logs, mutations, scoped diff, before bytes and retained future candidate are under ignored `private/safe-stage-b/`. Test scratch homes were removed after checks. Safe source is ready for parent acceptance; no commit, merge, push or production activation was performed from this copy.
