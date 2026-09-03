# #430 — Phase 2 plan: Luna benchmark before any production state loop

Approval: research approved by `Orchestra-orchestrator` as platform task #433 / user task #430. Architecture decision for this phase: **main benchmark uses Luna; free OpenRouter is excluded from the main cohort and may become only a later optional arm after the Luna verdict.** Additional Sol calls are not authorized.

## Outcome of this plan

Build and run a frozen, task-local benchmark that compares two memory representations on the same `gpt-5.6-luna` model:

- A: append-serialized observations and prior model outputs;
- B: mutable structured state plus the latest observation only.

The benchmark does **not** change `app/harness/` or claim that Codex CLI native history is replaceable. Every model step starts a fresh non-interactive `codex exec --ephemeral` process/thread, and the selected memory representation is supplied as data in that one prompt. `resume` is forbidden.

Official OpenAI Codex CLI documentation and local `codex exec --help` expose the required controls: `--ephemeral`, `--json`, `--sandbox read-only`, `--skip-git-repo-check`, stdin prompt and last-message output. Local executable at plan time: `/usr/bin/codex`, `codex-cli 0.149.0`; exact help is frozen in `docs/tasks/430/codex-exec-help.txt`. [Official Codex CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli#codex-exec).

## Runtime contract

Each step launches:

```text
codex exec
  --model gpt-5.6-luna
  --ephemeral
  --ignore-user-config
  --ignore-rules
  --sandbox read-only
  --skip-git-repo-check
  --cd <fresh empty /tmp dir>
  --output-last-message <absolute task-local step output>
  --json
  -
```

The controller sends the rendered prompt on stdin and records stdout JSONL verbatim. It never calls `codex exec resume`, never reuses a thread id, never exposes the repository/DB in the prompt, and invalidates any run that emits a tool call. The empty scratch directory is small; large/raw receipts stay on real disk under `docs/tasks/430/evidence/`, not `/tmp`.

The controller resolves scratch and output-message paths to absolute paths **before** building argv; T1 checks both. `--output-schema` is explicitly forbidden: Appendix A.4 asks for ordinary text containing a fenced JSON block, and provider strict schema was an excluded local variation. `--ignore-user-config` keeps Codex authentication but removes user configuration. The exact Codex binary SHA-256, CLI version, argv excluding output paths, environment-key allowlist, empty-workspace digest, system specification, fenced-output contract, action/tool manifest and controller parameters form `common_surface_hash`. The only allowed A/B difference is `memory_payload_hash`. A built-in tool schema cannot be read back from the CLI; identical binary+argv+sandbox and `tool_calls=0` are the fail-closed proof for that hidden part of the surface.

## Rendered memory surfaces

Common model-visible material:

- skill specification;
- exact text protocol: one fenced `json` block whose object has only `state_patch` and `action`; prose outside is discarded;
- full action enum vocabulary and every normalization rule;
- explicit action/tool manifest (`continue`, `finalize`, no external benchmark tools);
- controller/patch contract;
- latest observation.

A additionally gets the complete serialized observation/model-output transcript. B gets the current validated JSON state. The runner calculates hashes from the exact rendered bytes before the first response and fails if action schema, tool manifest, controller params or common surface differ.

State schema and patch rules remain those approved in research: keyed `current_facts` and `decisions`; recursive object merge; scalars replace; unknown paths rejected; an existing decision cannot be deleted, lose `because`, or flip accepted↔rejected without becoming `superseded` with new evidence.

## Measurement protocol

### Positive control — mandatory gate

Before calibration or main calls, run exact fixture `positive_control` from `scripts/skillstate430/luna_benchmark_spec.json` through `append`, `state`, `append_repeat` with strict rotating order. It has 3 fixed observations / 9 fresh calls. Its disclosed gold is `DELETE_DATA_VEC_DB`, keep normalized set `{KNOWLEDGE_CURRENT_DB, SEARCH_MEMORY}`, rejected `DELETE_CURRENT_DB`, reason `CURRENT_DB_IS_FTS_NOT_VECTOR`. It is green only when:

- all calls are provider-success and exact-schema model-success;
- the three arms give the frozen correct answer;
- every step has a unique thread id and one attempt;
- `common_surface_hash` and its action/tool/controller component hashes match;
- all enums/normalizers are present in both rendered prompts;
- tool calls and resumed sessions are zero.

Any failure → write the receipt, stop, do not run calibration/main, and report the blocker. No automatic retry or model substitution.

### Calibration and absolute thresholds

Only after the positive control is green: six frozen 8-step cases, at least one from each of the five strata, with `append/state/append_repeat`. Maximum 144 Luna calls. The exact stratum keys, top-down classifier, case format, enum-delivery requirement, allowed normalizers and quality definition are frozen in `scripts/skillstate430/luna_benchmark_spec.json`.

The five exact strata are `research_architecture`, `shared_runtime_auth_persistence_high_risk`, `incident_diagnosis`, `closed_behavioral_code_change`, and `readonly_extraction_docs_delivery`. `Q` is correct normalized gold-action fields divided by total gold-action fields; each field has weight 1; protocol-invalid or forbidden resurrection gives `Q=0`. Critical-reason loss remains a separate zero-tolerance metric.

All six three-arm cases must complete through provider/protocol success. Otherwise thresholds remain `null` and the main run is forbidden. For completed cases:

```text
token_noise_i   = |T_append_i - T_append_repeat_i| / mean(T_append_i, T_append_repeat_i)
quality_noise_i = |Q_append_i - Q_append_repeat_i|
η_tokens        = max(token_noise_i)
η_quality       = max(quality_noise_i)
```

`max` is a declared conservative guard, not a 90% estimator. Freeze exact values, raw receipt digest, model/binary/surface digests and `thresholds_frozen_at` before any main response.

### Main N=30 Luna run

- 30 historical Orchestra episodes, 6 from each of the five research-approved strata;
- classify every eligible case by first-match stratum, compute `sha256(utf8("skillstate430-luna-v1:" + decimal(case.task_id)))`, sort each stratum by `(selection_key_hex, numeric task_id)`, and take the first six;
- 8–12 steps per case, two arms → 480–720 fresh Luna calls;
- sequential, case-round-robin strict A/B order; first arm balanced by frozen hash;
- one HTTP/model attempt per Codex invocation, no resume/retry/imputation;
- `turn.completed.usage`: `total_tokens = input_tokens + output_tokens`; cached input is already within input, reasoning output is already within output;
- any provider/process failure stays in a provider bucket; any non-JSON/schema/patch/wrong action after a valid turn is a model bucket;
- missing/multiple/invalid/wrong-shape fenced JSON is `malformed_output`, a separate bucket that is neither provider failure nor model error;
- main result requires 30 completed pairs. A provider failure makes the revision incomplete; it is never converted into model error or silently excluded.

Worst-case approved Luna budget: positive control (short, ≤9 calls) + calibration 144 + main 720 = **≤873 `codex exec` calls**. Long execution goes through one server-side `bg_create(type="run")`; raw receipt is flushed after every call. An interrupted revision is retained as incomplete and never joined with another revision.

## Judge and decision

Deterministic judge only. A case succeeds when every step obeys the two-key protocol, the final action matches the disclosed enums/normalized sets, forbidden withdrawn values are absent, and all critical reason codes survive.

Full result uses frozen cluster-bootstrap seed and the calibration thresholds:

- token gate: `total_token_ratio_ci90_upper < 1 - η_tokens`;
- quality gate: `quality_diff_ci90_lower >= -η_quality`;
- critical-reason gate: state critical losses = 0.

Decision is mechanical:

- quality or critical gate fails → `state_harms`;
- all three pass → `state_wins`;
- quality/critical pass but token gate fails → `no_measured_win`.

The report also prints eligible/excluded counts and selection fraction per stratum. N=30 remains a screening result, not an equivalence proof.

Bootstrap is fully specified by the frozen spec: seed `43020260901`, 10,000 replicates, paired case as the resampling unit, N draws with replacement per replicate. Token statistic is `sum(T_state)/sum(T_append)`; quality statistic is `mean(Q_state-Q_append)`. Sort ascending; lower bound uses index `floor(0.10*(R-1))`, upper bound `ceil(0.90*(R-1))`. T4 independently recomputes both arrays and bounds from raw `episode_end` receipts.

## Safety and scope

- No production DB write or application import. Any SQLite connection uses URI `mode=ro`, sets `PRAGMA query_only=ON`, and must keep `total_changes=0`. A task-local `.scratch` snapshot is made with `sqlite3.Connection.backup`; any DB-dependent probe targets that backup. The controller and every Codex child run under `strace -ff` filtered to `orchestra.db`, `-wal`, and `-shm`; acceptance rejects any `O_WRONLY/O_RDWR/O_CREAT/O_TRUNC` or mutating path syscall on those paths. Read-only `sessions` counts are still recorded immediately before/after and must match, as the user required, but they are not the sole DB oracle.
- No API keys; Luna runs through the authenticated Codex subscription CLI.
- Any model tool call invalidates its run; sandbox is read-only.
- No prompt/role/platform changes.
- No `app/harness/`, `app/backend_codex.py`, `app/mcp_stdio.py`, test-suite, `pyproject.toml` or `uv.lock` changes.
- Free OpenRouter routes are not run in this phase. A later free arm requires the Luna verdict first and a new approved plan/revision.

## Files

New implementation files:

- `scripts/skillstate430/run_luna_benchmark.py` — fresh Codex executor, renderer, patch validator, receipts, usage parsing, ordering and analysis;
- `scripts/skillstate430/luna_output_schema.json` — excluded strict-schema v1 artifact retained for audit only; current argv/tests forbid its use;
- `scripts/skillstate430/luna_benchmark_spec.json` — already frozen positive control, strata, case/Q contract, bootstrap, decision and DB guard;
- `scripts/skillstate430/luna_calibration_cases.json` — six frozen calibration episodes;
- `scripts/skillstate430/luna_census_source.json` — full annotated census at a frozen Git source commit, including every independently discovered numeric task id, eligibility/exclusion, stratum, cited source paths, actual-byte digest and per-case selection key;
- `scripts/skillstate430/luna_cases.json` — selected N=30 full episodes;
- `docs/tasks/430/evidence/` — positive control, population, calibration, raw step receipts, full summary;
- `docs/tasks/430/report.md` — measured verdict and limitations.

Frozen acceptance files already added in Phase 2:

- `docs/tasks/430/acceptance/test_t1_luna_runner_contract.py`;
- `docs/tasks/430/acceptance/test_t2_luna_positive_control.py`;
- `docs/tasks/430/acceptance/test_t3_luna_calibration.py`;
- `docs/tasks/430/acceptance/test_t4_luna_main_benchmark.py`.

No migration. No production activation. What not to touch is the explicit safety list above.

Frozen spec SHA-256: `ab300f9e4b4b1bb7bc33b7199aefc2e2737b4deaf994ea53eade9da1b8a051da` in manually accepted oracle-fix commit `2cd13159`.

## Tickets

### T1 — Stateless Luna runner and rendered-surface gate

- Files: `scripts/skillstate430/run_luna_benchmark.py`; `luna_output_schema.json` remains excluded and unused.
- Test: `uv run --frozen python -m pytest -q docs/tasks/430/acceptance/test_t1_luna_runner_contract.py` — final acceptance state in `2cd13159` (`19dafd1b`, `89753fed`, `8c53f1ba` superseded before any implementation/model run).
- RED: `assert RUNNER.is_file(), "T1 missing stateless Luna runner"` → `1 failed`, exit 1.
- AC: named command is green; argv is fresh/ephemeral/read-only/ignore-config/no-resume, cwd/output paths are absolute, and `--output-schema` is absent; parser accepts exactly one valid fenced JSON block and rejects missing/multiple/invalid blocks as `malformed_output`; A/B common surface hashes match while memory hashes differ; every enum/normalizer/action is rendered; forbidden decision deletion/unknown paths fail; Codex token usage does not double-count cached/reasoning subsets; DB trace parser accepts read-only and rejects a protected-path write.
- blocked-by: none.

### T2 — Live Luna positive-control gate

- Files: `docs/tasks/430/evidence/luna-positive-control-v2-raw.jsonl`, `docs/tasks/430/evidence/luna-positive-control-v2.json`; strict-schema v1 receipts remain excluded.
- Test: `uv run --frozen python -m pytest -q docs/tasks/430/acceptance/test_t2_luna_positive_control.py` — final acceptance state in `2cd13159` (earlier freezes superseded).
- RED: `assert RECEIPT.is_file(), "T2 missing live Luna positive-control receipt"` → `1 failed`, exit 1.
- AC: named command is green; spec/raw/receipt digests bind exact `PC01-current-db-is-fts`; raw ledger has exactly 9 unique-thread step calls and 3 episode ends with the disclosed gold/Q=1; one comparable `append/state/append_repeat` episode completed on exact `gpt-5.6-luna`; surface hashes/enums/normalizers match; provider/protocol failures, tool calls and resume count are zero. Calibration/main are not invoked while this test is red.
- blocked-by: T1.

### T3 — Six-case Luna calibration and frozen thresholds

- Files: `scripts/skillstate430/luna_calibration_cases.json`, `docs/tasks/430/evidence/luna-calibration-raw.jsonl`, `docs/tasks/430/evidence/luna-calibration.json`.
- Test: `uv run --frozen python -m pytest -q docs/tasks/430/acceptance/test_t3_luna_calibration.py` — final acceptance state in `2cd13159` (earlier freezes superseded).
- RED: `assert CALIBRATION.is_file(), "T3 missing six-case Luna calibration receipt"` → `1 failed`, exit 1.
- AC: named command is green; all six three-arm cases complete with zero provider/protocol failure and zero tool calls; positive-control/raw digests and surface delivery are bound; the acceptance test derives 18 raw episode ends, independently recomputes each A/A discrepancy and exact `η_tokens`/`η_quality`, and confirms numeric thresholds frozen before main.
- blocked-by: T2.

### T4 — Frozen N=30 Luna benchmark and verdict

- Files: `scripts/skillstate430/luna_census_source.json`, `scripts/skillstate430/luna_cases.json`, `docs/tasks/430/evidence/luna-population.json`, `docs/tasks/430/evidence/luna-main-raw.jsonl`, `docs/tasks/430/evidence/luna-main-summary.json`, `docs/tasks/430/report.md`.
- Test: `uv run --frozen python -m pytest -q docs/tasks/430/acceptance/test_t4_luna_main_benchmark.py` — final acceptance state in `2cd13159` (earlier freezes superseded); focused census node is green while the main node remains RED on missing population.
- RED: `assert POPULATION.is_file(), "T4 missing frozen Luna population ledger"` → `1 failed`, exit 1.
- AC: named command is green; numeric `task_id` is mandatory; T4 independently enumerates numeric task ids with accepted artifact paths at the frozen Git source commit, requires census coverage of every discovered id, reads the actual cited bytes with `git show`, recomputes source digests and per-case selection keys, rebuilds sorted top-six per stratum, and rejects any population/cohort mismatch; population ledger then has 30 unique cases/6 per exact stratum; raw step count equals `sum(2×observations)` and raw episode ends contain all 60 case/arm pairs; every raw step is exact `model_valid`, protocol-valid, one-attempt, non-resumed, fresh-thread and in the assigned stratum; positive/calibration/spec/raw/binary/surface/threshold digests match; main starts after threshold freeze; the test independently recomputes bootstrap bounds, gates and decision; `report.md` states the decision, N, dangerous class and limitations; DB guard proves backup+ro/query-only+zero protected-path writes and `sessions` before=after; `git diff 2cd13159 -- app/harness app/backend_codex.py app/mcp_stdio.py pyproject.toml uv.lock` is empty.
- blocked-by: T3.

## Execution stop rules

1. T1 already green/missing? Run its exact command before code; anything but the committed RED assertion is a false oracle → stop.
2. T2 is the required live gate. Not green → stop, no T3/T4.
3. T3 lacks six complete triples or numeric thresholds → stop, no T4.
4. Any model/binary/surface change after calibration → new revision and new calibration; never mix.
5. Any Sol execution/review need → report blocker and wait for explicit additional Sol authorization.

## Appendix A.4 text-protocol revision

Strict Structured Outputs were not part of the paper and failed before model execution (`invalid_json_schema`, call 1/9). That run and strict-schema implementation commit are excluded permanently. The orchestrator authorized exactly one replacement 9-call revision using ordinary text with one fenced JSON block. Frozen revision commit `6dd0691a` updates spec/oracles; `malformed_output` is independent from provider and model buckets. A second replacement revision is forbidden without a new instruction.

## Review rounds 1–2 resolution

Luna round 1 returned four blockers and three oracle-strength suggestions; round 2 confirmed all seven fixed and found three new blockers. Final freeze `8c53f1ba` adds per-case selection ranking/top-six, exact `model_valid`, and raw step protocol/attempt/resume/thread/stratum checks. All are resolved before any Phase-3 or model run. Old RED commits `19dafd1b` and `89753fed` are superseded and excluded permanently.

Round 3 closed those three and reached the review ceiling with one cohort-provenance blocker. The orchestrator selected manual option A and prescribed four exact checks. Commit `3b816439` froze the focused RED (`T4 census rebuild guard missing`); commit `2cd13159` made it green with mandatory `task_id`, independent Git census discovery, actual-byte source hashing and deterministic top-six rejection. Evidence: `green-census-oracle.txt`; full T4 remains RED in `red4-t4.txt`. Mutation `mutation-census-oracle.txt` removes census rebuild, gives `MUTANT_RC=1`, restores the committed file, then gives `RESTORED_RC=0`. No fourth model review is run.
