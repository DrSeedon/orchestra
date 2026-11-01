# V-1164 — independent acceptance of V-1156 Stage A

Acceptance target: `task-V-1156/feat-terra` at `69ff9ec7d1354bf1eaea72b41ba1086ec7912743`. Target worktree was clean before and after checks. The 11 source/task files changed from `origin/main` have identical SHA-1 blob IDs in the before/after snapshots; snapshot and full IDs are in `.orchestra/private/V-1164/source-hashes.txt`. No Stage B, hot pipeline, static frontend, or route file appears in the source diff.

The instruction contract passed. `uv run --frozen python -c 'import app; print(app.__file__)'` resolved the app from `worker-checkout/app/__init__.py`. The absolute host path is kept in private evidence.

Checks on the target HEAD:

- Exact browser case `tests/test_model_catalog_frontend.py::test_catalog_free_filter_and_admission_work_with_new_and_old_api_payloads`: **1 passed**; Chromium was available. Raw output: `.orchestra/private/V-1164/browser.log`.
- Relevant native Terra, alias/context/telemetry/pricing, legacy model, Sol/Luna, catalog/API, backend, quota, billing, and admission set: **323 passed**, no skips or setup errors. Raw output: `.orchestra/private/V-1164/relevant.log`.
- Process-local mutant changing Terra's input rate from 1 to 2: committed pricing tests failed at the expected price assertion (**2 failed, 3 passed**). Process-local mutant removing Terra from `MANUAL_ONLY_MODEL_IDS`: old stored-agent-flag tests failed at the expected refusal assertion (**3 failed**). Neither mutation wrote source files. Raw outputs and helper: `.orchestra/private/V-1164/mutant-rate.log`, `mutant-guard.log`, `process_mutant.py`.

No provider/API/native CLI call, deployment, service operation, or production config change was made. Full suite was not run. These checks establish host-side behavior against the source HEAD only; they do not establish production activation or real Terra inference. Feature branch remains unchanged and uncommitted; this receipt is committed only on the V-1164 QA branch.
