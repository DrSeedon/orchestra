> Historical report copy, updated 2026-11-02. The body below records the earlier profile-based candidate and its checks. Owner decision 2026-11-02 18:27 replaced that profile with the existing native Codex path; the old readOnlyAccess/bwrap activation blocker below is superseded, and this body is not the source worker's current native-path report. The native delivery metadata expected a newer REPORT.md, but the source branch retained this older copy. Current source policy is in `closure.md` and `handoff-notes.md`; current host integration evidence is in `.orchestra/tasks/V-1170/receipt.md`.

# V-1166 — deduplicated delivery, safety corrections and catalog purpose

**No actual grant, inference, provider/account/model RPC or service activation.**
Parent accepts the subscription soft-stop contract as a PLAN, not issuance; a
separate parent receipt follows host QA/activation. Owner's 22:19 approval did not
authorize new API payments. No model review, alternate runtime or OAuth copy.

## Concrete safety changes

1. `managed_call` no longer puts the model workspace inside Orchestra or installs
   real Orchestra MCP. It creates an outside-checkout temporary directory with an
   independent synthetic Git root, prompt.md and only frozen seed source. An
   optional `CodexEvaluationProfile` keeps the existing managed auth path and
   non-orchestrator identity while requesting workspace-write, restricted reads,
   disabled tool network/web search, no shared tmp write roots and no MCP. The
   thread response must confirm cwd, approval, full sandbox restrictions and empty
   instructionSources; runtime MCP listing must be explicitly empty. turn/start
   repeats the sandbox. Unsupported/missing confirmation refuses the experiment;
   ordinary Codex configuration and existing spawn/catalog guards are unchanged.
2. A managed-call lease watch cancels its run coroutine, interrupts and disconnects
   the local backend on lease withdrawal/expiry. The HTTP handler watches ASGI
   disconnect/cancellation and waits for local cleanup. Pending/unknown receipts
   stop remaining dispatches. Local stop is not proof of remote cancellation.
3. Stable task identity, project identity and task reference are re-read after
   quota, connection and runtime reads immediately before send. A changed task or
   scope refuses generation. The owner permission reference remains audit text
   supplied by the proved root issuer, not cryptographic proof of user text.
4. Real set_model_flags serialization clamps agents=False for manual-only Sol/Terra
   even for True input; dashboard updates retain it. This is ordinary-worker
   policy, not an independently represented eval revocation. Valid grants admit
   visible/available Sol/Terra with that actual stored False; hidden/unavailable or
   invalid grants refuse. No global flags changed; ordinary spawn/workflow and
   Luna worker-disable behavior remain denied/unchanged as applicable.

These are implemented and tested wire/config contracts, **not proof of installed
Codex 0.166 or OS sandbox enforcement**. Host must verify actual profile support
before issuance; no broader-profile fallback is permitted. Only the existing
backend gained optional experiment configuration; no new workflow runtime.

56 means task invocations, not internal provider requests. 500000 generated tokens
is an observed serial stop-remaining threshold, not a hard cap. Output/reasoning is
counted once; input/cache excluded. Unknown usage or pending reservation stops all.
No retry/API/fallback; ordinary quota/non-orchestrator accounting remains. The
90-minute controller deadline and local cleanup give **no verified finite remote
token-overshoot bound**. See `token-cap-decision.md` and `handoff-notes.md`.

## Exactly public

Product: `app/eval_admission.py`, `app/eval_fixtures.py`, `app/backend_codex.py`,
`app/routes/bg.py`, `app/mcp_stdio.py`, `scripts/wf_run.py`,
`scripts/wf_adapters.py`, `tests/test_eval_admission.py`, `CHANGELOG.md`.
Safety follow-up edits only eval_admission/backend_codex/bg/test_eval_admission and
our changelog paragraph. Catalog-owner/Stage-A text and other product files remain.

Task root, exactly `PUBLIC_ALLOWLIST`: `.gitignore`, `PUBLIC_ALLOWLIST`,
`REPORT.md`, `handoff-notes.md`, `token-cap-decision.md`, `mutation_check.py`.
Ignore rules control publication only: they do **not** filter full return transport
or untrack the parent's old index. Parent handles canonical private preservation,
index cleanup and resulting HEAD after delivery. Do not force-add raw evidence.

## One canonical raw copy; explicit duplicate deletion proof

Canonical plain folder: `private-evidence/original/`. Frozen inventory:
`private-evidence/original-manifest.json`, SHA-256
`275bb7610a7946b1e94adaeb66d37b25b50bd1930f3acbefb7ad79aec288f844`.
It contains all **5445 original regular paths / 495361335 bytes**, **857 DB** and
**21 logs**, plus preserved directory/symlink metadata (6323/737). All original
bytes still hash-match. A source→canonical map covers every regular path:
**3469 transport-retained**, **1976 explicit standard source/cache exclusions**;
**all 857 DB are transport-retained**. No arbitrary raw exclusions or cache archive.

Parent-authorized dedup removed **7367 exact regular-file duplicates / 988343719
bytes**, individually from an explicit manifest using `cmp`, SHA checks before
and after, and `rm -i` on each named file. No recursive deletion, symlink deletion,
canonical deletion or product edit during dedup. This removed the old task-root
raw copies and redundant flat hash copy, never the canonical original/ tree.
Empty directories remain. Pre-dedup 8 product hashes matched; safety product edits
occurred afterward. Private receipts: `dedup-explicit-manifest.json`,
`dedup-completed.json`, `canonical-delivery-map.json`, `canonical-delivery-summary.json`.
No active/unknown workload held testtmp. Same-UID SSH/system supervisors with
unreadable /proc entries were recorded as a visibility limitation, not workload
quiescence proof; the only open task log was this dedup command's own output.

**One** standard HubSsh.get tar measurement after dedup: **540712960 bytes** against
**629145600 bytes**, headroom **88432640 bytes**, rc=0, stderr empty. It used exact
BLOCKED_DIRS and `--exclude-tag=pyvenv.cfg`, no custom raw filters, no stored archive.
Receipt: `private-evidence/standard-return-size.json`. This checkpoint precedes the
small safety/source/log follow-up; the final conservative non-tar growth bound is
recorded separately. No second tar measurement or limit increase was performed.

Current HEAD is unavailable in this no-.git worker copy (prior one-shot rc128).
`01e328e2` is only the parent-reported pre-correction HEAD, not verified current
HEAD. Actual source/import paths are private; public notation is
`worker-copy/app/__init__.py`. Broker/parent must confirm host transfer/index/HEAD.

## Actual checks and every red/skip

Required runner: provisioned uv 0.11.28, frozen lock, default `.venv`. New testtmp
is scoped under /tmp, cacheprovider disabled; no new DB/testtmp trees in return.
Final logs/manifests alone are kept under task-local ignored private-evidence.

| Run | Result |
| --- | --- |
| `private-evidence/pytest-safety-corrections.log` | Interrupted rc130 after 60 passed; fake HTTP completion hung. Not a successful/full run. |
| `private-evidence/pytest-http-diagnostic.log` | 1 failed at 12-second pytest timeout; reproduced the new watcher teardown bug. |
| `private-evidence/pytest-safety-profile-final.log` | **208 passed**, zero skipped, 23.57 s. Complete grant safety tests plus ordinary Codex backend regression suite. |
| `private-evidence/pytest-safety-purpose-final.log` | **241 passed**, zero skipped, 24.57 s. Final code: grant tests, ordinary Codex backend and model catalog regressions, including the real stored-manual-only-False positive/negative controls. |

The introduced hang came from Starlette is_disconnected() using an inner cancel
scope that could absorb watcher teardown cancellation. The fix waits directly for
ASGI http.disconnect after body parsing. Tests now cover full fake56 dispatch/replay,
lease withdrawal/expiry, caller cancellation and ASGI disconnect while backend is
blocked; interrupt/disconnect is observed, unknown ledger truth retained and
remaining dispatch count zero. Late stable-id/project changes prevent send. Actual
thread/start + turn/start fakes inspect restricted wire params, reject broader or
missing policies/foreign instruction sources, verify empty MCP and independent
Git root, and ordinary backend tests retain their previous behavior.

Historical QA remains in `private-evidence/original/`, never hidden or reclassified:

| Original log | Result |
| --- | --- |
| `pytest-eval.log` | 52 passed, 1 failed; new no-Git fixture corrected with explicit base commit. |
| `pytest-targeted.log` | 193 passed, 5 checkout Git-branch failures. |
| `pytest-eval-final.log` | 66 passed, earlier implementation revision. |
| `pytest-safety.log` | 226 passed, 1 auth/startup Git-author failure. |
| `pytest-final.log` | 295 passed, 1 auth/startup bootstrap-model failure after proxy metadata HTTP400. |
| `pytest-regression.log` | 354 passed, 5 checkout Git-branch failures. |
| `pytest-grant-complete.log` | 82 passed, before these three safety corrections. |
| `mutations.log`, `mutations-final.log` | Each 6/6 old admission mutants killed, source restored; not rerun as a claim about new profile code. |
| `audit.log`, `audit-final.log` | Initial ModuleNotFoundError for app; sys.path corrected, then syntax/hash audit passed. |

No historical skips. Five cases: `test_manifest_contains_ready_resume_command`,
`test_manifest_can_use_a_runner_specific_resume_command`,
`test_missing_scheduler_route_runs_without_admission`, and
`test_unavailable_scheduler_keeps_waiting[503/None]`.
Raw error: `RuntimeError: cannot resolve workflow workspace base branch: fatal:
not a git repository (or any of the parent directories): .git`.
Auth errors: `TaskConflict: Author identity unknown`; then proxy `/v1/models`
**HTTP400** followed by `ValueError: unknown model 'claude-sonnet-5-5[1m]'; registered
models: GigaChat-2, GigaChat-2-Max, GigaChat-2-Pro, GigaChat-3-Lightning,
GigaChat-3-Pro, GigaChat-3-Ultra`. These are observed reds, not baseline-proven
"environment only" findings. Parent owns host baseline/full-suite QA, actual
profile activation and new issuance. No source-colleague V1160 changes were touched.

Final conservative return bound: **604630528 bytes**, below the 629145600 cap by
**24515072 bytes**. It adds every current eligible noncanonical entry in full to
the single measured checkpoint, plus 2 MiB for final receipts/docs. This is an
upper bound, not a second actual tar count. Source SHA/syntax/changelog-only audit
passed; `private-evidence/safety-product-manifest.json` is current (older manifests
are historical). The four untouched eval_fixtures/mcp_stdio/wf_run/wf_adapters
files matched their preserved original hashes. Original raw files remain intact.

## Parent delivery and installed-runtime check

The broker completed delta import at 2256caf86c3bfd9632da595d6e8fb0a4d128e6b6. Host verification matched all nine product files, six public task files and 3424 canonical original files. Exactly 2021 original paths were excluded by existing transport policy (1976 source/cache exclusions and 45 fixture .env/.mcp.json/.git files); these bytes were not fetched through another route or fabricated. All 857 generated DB files were delivered. All 3484 physically delivered private evidence files (508458914 bytes) were moved on the same filesystem to canonical local private storage and rehashed before the 2079 private artifact paths were removed from the worker Git index. No file contents were deleted. Original public documents and preservation receipts remain private.

Installed Codex 0.166.0 metadata preflight started one empty synthetic thread without generation and did not confirm the candidate restricted-read policy: writableRoots was empty and readOnlyAccess was absent. The installed schema also lacks that read-access field. The existing local benchmark isolation preflight independently stopped at bubblewrap UID-map permission refusal under the current AppArmor setting; later isolation checks were not reached. Neither protection was relaxed. This implementation is not accepted for issuance or activated; actual benchmark generation remains zero. A different verified execution boundary is a separate architecture decision before implementation. Host QA and full-suite validation remain pending.
