# #503 — register `gpt-6-astra`

## Change

- `app/models.py`: registered `gpt-6-astra` as `ModelSpec(runtime="codex", provider="openai")` with `context_length=258400`; added aliases `astra` and `gpt6astra`.
- `app/backend_codex.py`: added context fallback `258400` and Standard prices per 1M tokens: input `10.0`, cached `1.0`, cache-write `12.5`, output `50.0`.
- `app/runtime_history.py`: updated the plain current Codex history pin from `0.150.1` to `0.153.4`; this file contains one current constant, not a version history, so no prior entry was overwritten. The installed binary moved from `0.153.2` to `0.153.4` before merge; the same-edit comment states that the pin follows the installed binary while #498/#503 validation is from the preceding `0.153.2`.
- Removed `minimal` from global `CODEX_REASONING_EFFORTS`. #498 measured Astra's server error for `minimal`; a grep found no pipeline/app call sites beyond the old set/comment, and a read-only historical query found `0` sessions with `effort='minimal'`. `ultra` remains excluded because it is a client-side subagent mode, not a server effort value.

## Context decision

The live catalog reports default context `272000` and max `872000`. Orchestra's `ModelSpec.context_length` is the effective planning budget used by the Codex runtime, not the raw catalog maximum; under ChatGPT auth the measured effective budget is `258400`, already used by Sol/Terra/Luna. Astra therefore uses `context_length=258400` and no new max-context field.

## Verification

- Frozen acceptance oracle: initial run before implementation: `5 failed`; after implementation and after mutation restoration: `5 passed`.
- Fresh registry process:

  ```text
  {"alias_astra": "gpt-6-astra", "alias_gpt6astra": "gpt-6-astra", "spec": {"context_length": 258400, "id": "gpt-6-astra", "name": "GPT-6 Astra", "provider": "openai", "runtime": "codex"}}
  ```

- Price/cost process:

  ```text
  {'input': 10.0, 'cached': 1.0, 'write': 12.5, 'output': 50.0}
  0.00645
  ```

- Live proof (`codex-cli 0.153.2`, model `gpt-6-astra`, effort `high`) returned exactly:

  ```text
  ASTRA_OK
  ```

- Regression command: `uv run pytest -q tests/test_backend_codex.py tests/test_models.py tests/test_quota_gate.py` → `174 passed` after updating the pin to installed `0.153.4`.

## Mutation evidence

- Price-row mutation: marker count `1 → 0`; `tests/test_model_registry_503.py::test_gpt6_astra_cost_computation_is_nonzero` → `1 failed`; restored row, `touch app/backend_codex.py`, marker `0 → 1`, test → `1 passed`.
- Alias mutation: marker count `1 → 0`; `tests/test_model_registry_503.py::test_gpt6_astra_aliases_resolve` → `1 failed, 1 passed`; restored alias, `touch app/models.py`, marker `0 → 1`, test → `2 passed`.
- CLI-version mutation: a temporary `codex` lookup ahead of `PATH` returned `codex-cli 0.99.0` (marker `1`); `tests/test_backend_codex.py::test_installed_codex_history_version_matches_pin` → `1 failed`. Removed the lookup, `touch app/runtime_history.py`, marker `0`, and the test → `1 passed` with the real `codex-cli 0.153.2`.

## Deliberate consequences

`gpt-6-astra` is now a legal `codex_review` model automatically: review accepts registered Codex-runtime models in bucket `codex` and rejects only Spark. Review routing was not changed. `quota_gate.py` was not changed; Astra follows the existing `codex` bucket and `sol` lane, so registration splits existing capacity and adds none. `pipeline.yaml:44` already supplied `gpt-6-astra: medium`.

## Review decision gate

- Changed files and consumers: `app/models.py` (model registry, alias resolution, context view), `app/backend_codex.py` (Codex context fallback, price accounting, effort validation), `app/runtime_history.py` (Codex native-history version compatibility), and `tests/test_model_registry_503.py`; downstream consumers include worker construction, dashboard cost recording, quota admission, `codex_review` model admission, and Codex history import.
- Author metadata from the session record: model `gpt-5.6-luna`, runtime/backend `codex`, role `worker`, task `503`.
- Exact AC: both aliases resolve to `gpt-6-astra`; the price row exists with non-zero values; synthetic `_codex_cost` is non-zero; `minimal` is not globally admitted; live CLI responds exactly `ASTRA_OK`; existing model/backend/quota regression command is run.
- Named checks and observed outputs: `uv run pytest -q tests/test_model_registry_503.py` → `5 passed`; `uv run pytest -q tests/test_backend_codex.py tests/test_models.py tests/test_quota_gate.py` → `174 passed`.
- Route: **orchestrator skip**, explicitly decided by `Orchestra-orchestrator`. The orchestrator inspected implementation commit `cf612f43` (15 lines in `app/`) and verified that the frozen oracle plus mutations cover each changed behavior; Sol is not authorized. This is an explicit skip decision, not a failed or unavailable review.

## Follow-up finding (pre-existing, not fixed here)

`context_length` has two owners: `ModelSpec.context_length` in `app/models.py` and `CODEX_CONTEXT_LIMITS` in `app/backend_codex.py:46`. They agree today for Astra (`258400`), as they already do for Sol, Terra, Luna, and 5.5, but no invariant enforces continued agreement. Astra is the sixth model exposed to this existing drift risk; queue a separate task to establish one owner.

The version-pin test's current failure text is also a defect: `assert 'codex-cli 0.153.2' == 'codex-cli 0.150.1'` does not say whether to bump the pin or downgrade the binary, or who decides. The same defect occurred twice in one day as the installed binary advanced first to `0.153.2` and then to `0.153.4`; each time the message gave no action guidance. Suggested future message: `Codex CLI version mismatch: installed {actual}, pinned {expected}; update the pin only after validating the installed version, or install the pinned CLI.` This report does not redesign the assertion.

## Pre-mortem checks

- Missing accounting row would make `_codex_cost` fail-soft to dashboard cost `0.0`; exact row and non-zero synthetic cost were printed and mutation-tested.
- Wrong alias or unregistered spec would leave worker/review resolution broken; both aliases and the fresh-process spec were resolved and mutation-tested.
- Raw catalog context could be copied as a second planning rule; sibling parity (`258400`) and the catalog/effective distinction are recorded above.
- Removing `minimal` could break a live manifest; grep found no call sites and history contains zero `minimal` sessions; the frozen test asserts it is absent.
- Native history compatibility could be lost by an unvalidated pin bump; the pin is now installed `0.153.4`, while validation remains explicitly attributed to #498's nine effort probes and #503's live call on `0.153.2`; the mismatch test still rejects a temporary `0.99.0` lookup.
- Quota/review policy could drift accidentally; diff is limited to the requested model/backend/test/task paths, and no `app/quota_gate.py`, routing, or pipeline file changed.
