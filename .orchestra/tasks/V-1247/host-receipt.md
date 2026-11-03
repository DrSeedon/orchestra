# V-1247 host acceptance receipt — V-1244 host-outcome corrections

## Candidate integration and preserved QA inputs

Fresh source candidate: `cf1a86568677a6a5b77db015a98e91ff04c9bb6f`, parent `23bd5155d9b4d57046432e0b59c57f9adad99652`. Only that worker-authored commit was cherry-picked, as `ac6f36621fa1615f0b5b7a0157ad562ad95d4b8f`, onto the QA branch. Prior QA commit `f5eb0d5e6bb956df2bae7a8ebf0bf4c6d801eb4d` and `a2d31070a0459b2f57c8ab52140e6f29d96d9090` remain ancestors. Against source HEAD `cf1a…`, the QA tree differs only in three canonical pin files and this receipt. No old whole-module, enforcer, routing, or canonical-file overlay was applied.

The full source manifest SHA-256 `8825239827e0b5013e33d96f86bedad6440fad1506c827bb388b7ee138b0d1fe` has 29/29 Git blob matches and 24/24 physical checkout matches. Five task mutation artifacts are sparse and verified from Git. The corrective seven-file manifest SHA-256 `fd2f4bf90cbdb0f50ebb636fd919a1eec7aaffc2a49ccf07099a47708e3d6a20` has 7/7 blob matches and 6/6 physical matches; only its task-local mutator is sparse.

QA-owned inputs remain byte-equal to accepted pin `0bbb0b96eb9b50cacee41023542d1d25cb560310`, each with zero Git diff:

- `.orchestra/pipelines/default/pipeline.yaml` — `76240fd6d9b15ae1de739306c75f9f22bec6ab0db47adc59863c2dad6e1a2a16`
- `app/static/js/app.js` — `4b83b28dfda71cb1116869c863596f6f48ce14cbb4d1e1ec7cd6317afbaa8a7a`
- `app/static/js/i18n.js` — `c98a095e65f3f11d5e6af7c88dae9fb7da5660bd3090f08b3c11a5b9a12f4a29`

Protected models, manager, session, merge operations, the two cron fixtures, and these three canonical files are unchanged by the source correction relative to its parent. The frozen stale-snapshot regression body is AST-identical to the parent; only its fixture imports changed.

## Host tests and contracts

Tests used the existing `.venv`, `uv run --frozen`, clean child environments, local synthetic Git, temporary SQLite/worktrees, external command timeouts and pytest `--timeout=30`. No new clone or dependency cache was created. Python executable: `{{PRIVATE_PYTHON_EXECUTABLE_01}}`; pytest 9.0.3; imported app: `{{PRIVATE_APP_IMPORT_PATH_01}}`.

- Two-worker `--dist=loadscope` run covering the full changed Hub-input, native-cleanup, completion-identity, stale-generation modules plus the archive-before-generation fixture control: **98 passed in 16.74 s**. This exercised actual fixture ordering with the explicit imports and all six missing/empty identity variants.
- Serial archive, cancellation, native-ownership, stale-generation, completion-receipt, report-order and worktree-cleanup boundaries: **131 passed in 18.33 s**. No skips or failures.
- Actual `scripts/check_pipeline_manifest.py --check`: exit 0.
- Actual `scripts/check_instruction_contract.py`: exit 0; `CLAUDE.md` is a symlink to `AGENTS.md`.

The two batches overlap and are not summed. The full suite was not run; V-1248 remains separate. Tests contain no live provider/model/network/credential/DB calls.

## Fresh committed mutations and restoration

The committed `mutate_host_outcomes.py` logic was copied to the designated private test area with its repository-root pointer set to this QA worktree (the private directory resolves through a shared symlink). Its first unadjusted invocation stopped at the source precondition before mutation; another log-directory setup attempt restored in `finally` before any pytest run. The corrected private runner then executed all three committed mutation cases sequentially:

- Unsafe direct identity reads: expected RED **4 failed / 2 passed**, including `AttributeError`/missing-action assertions. Safe `app/backend_hub.py` restored exactly; SHA `391c2ca3094b10ad75befa5acef47f4a6ca087d5999e81c876ea73821ca0f4f1` matches the fresh manifest.
- Disabled native cleanup return: expected RED **1 failed / 1 passed**; the failed-merge negative remains passing. Safe `app/merge_operations.py` restored exactly; SHA `bf67215b977fde326e6dd2a97cc6d0142c462cea3b162261c7c82a360b47e4ca` matches the manifest.
- Reverted fixture imports to `pytest_plugins`: expected **1 pass / 1 setup error** under two-worker `loadscope`, specifically missing `history` fixture. This is the intentional fixture-registration mutation, not a product failure. Safe test file restored exactly; SHA `b3973c6c88c7c6f92f7718bea96e36dbcbc0a220a7ef1956357b713c3abc3ea4` matches the manifest.

All three runs reached their intended assertion/setup outcomes without timeouts; source hashes after restoration match candidate blobs. The corrective patch's reverse `git apply --check` passed for materialized paths; the one sparse mutator artifact was separately verified by its Git blob hash. The prior archive→purge mutation remains bound to unchanged `app/hub_workspace.py` SHA `3febaf5d2084b3ae92cda91989b04365ba90fb58de448ad1b4046ac9bce3998f`; it was not repeated because this source delta does not touch that file. Earlier cancellation mutation likewise remains bound to unchanged merge-operation SHA, and the serial boundary suite reran its cancellation/ownership tests.

## Exact corrective delta

The seven-path delta is generated from exact Git range `23bd5155d9b4d57046432e0b59c57f9adad99652` → `cf1a86568677a6a5b77db015a98e91ff04c9bb6f` using `git diff --binary --full-index`; actual stats are **188 additions / 29 deletions**. `changed-files.json`, `host-outcomes-proof.json`, `stage.md`, `integration.md`, `summary.md`, and `artifact-hashes.sha256` now bind to this range and count. The prior captured patch was relative to a slightly different Git-free baseline and remains reachable at `cf1a86568677a6a5b77db015a98e91ff04c9bb6f:.orchestra/tasks/V-1244/host-outcomes-delta.patch`; it and raw evidence were not deleted. The 29-file source manifest and seven-file source delta manifest are unchanged.

No live close, kill, purge, merge, push, restart, or activation occurred. Detailed raw output remains local in the private V-1247 area.

Machine-local execution provenance is retained privately for verification; absolute paths and identifier values are omitted from this public receipt.
