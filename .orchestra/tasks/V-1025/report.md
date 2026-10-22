# V-1025 — forward pipeline effort to hub workers

Suggested platform commit header: `V-1025: forward and validate hub model effort`.

## Changes

- `app/backend_hub.py` retains constructor effort and includes it in modelSelection.options on thread launch and model configure. A resumed existing thread is configured before sending, covering backend reconstruction after pipeline effort changes.
- Provider/model option definitions are fetched once per backend from `orchestrator_capabilities`, then cached. Validation uses the target provider instance and model. Unsupported values raise ValueError naming the model, rejected value and allowed values, before launch/configure or the configure fallback can mutate state. Missing advertised options also fail explicitly. None omits options and does not fetch capabilities.
- Model changes resolve effort for the target model from the current pipeline/role when available. `app/runtime_registry.py` passes that context into HubBackend. Callers without pipeline/role retain their constructor effort.
- Both effort-policy maps now include hub Sol=high, hub Sonnet=medium and hub Haiku=low. Hub Opus mirrors native Opus: high for orchestrator roles and medium for worker roles.

### Catalog detail

A read-only `orchestrator_capabilities` call in this session confirmed Sol's option id is `reasoningEffort`, but Claude's is `effort`. The implementation uses the advertised id: Sol/Grok send `{"reasoningEffort": value}` and Claude sends `{"effort": value}`. Sending reasoningEffort for Claude would use an option absent from its catalog. No model turns were launched for this check.

## Verification

`uv --version` failed: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`. Used the existing non-system `/tmp/venv/bin/python`, offline, with nice=15 and a 2 GiB virtual-memory cap (`ulimit -v 2097152`). TMPDIR and pytest basetemp were inside this task directory; temporary data was removed after verification.

- `/tmp/venv/bin/python -m pytest tests/test_hub_effort.py tests/test_runtime_registry.py -q -p no:cacheprovider --basetemp=<task>/tmp/final`: **26 passed**. Log: `final-tests.log`.
- `/tmp/venv/bin/python -m pytest tests/test_hub_effort.py tests/test_hub_workspace.py tests/test_hub_pool.py -q -p no:cacheprovider --basetemp=<task>/tmp/pytest`: **97 passed, 2 failed** (before the final factory test was added). Log: `tests.log`.
- The two failures are `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools` and `test_hub_prompt_has_no_outbox_section_when_nothing_can_run_it`. This task copy lacks `.orchestra/pipelines/default/prompts/hub/worker.md`; the unchanged preamble function therefore supplies the fallback prompt, missing the identity text and expected capitalized `Do not run git push/clone/commit`. No prompt code was modified for this task. These tests require the full checkout/template.
- Mutation: `mutation_check.py` wraps the real model-selection builder and removes options after validation. Running the 13 effort tests yields **4 failed, 9 passed**, including failures for launch, configure, target-policy/Claude mapping and resumed-thread forwarding. Log: `mutation.log`. Production source was never mutated.
- Tests cover unsupported effort on launch/configure, target-specific allowed values, missing options, no-effort omission, catalog caching, policy parity, factory context, and resumed-thread configuration.

Imported app: `/home/<hub-user>/orchestra-ws/vmi3407579/hub-b3128d7d964a4725/app/__init__.py`.
Imported backend: `/home/<hub-user>/orchestra-ws/vmi3407579/hub-b3128d7d964a4725/app/backend_hub.py`.

Reviewed the changed source/policy/test sections. Saved logs were checked with `app.secret_mask.mask_secrets`: no secret-shape matches. No credentials were inspected, no service was restarted, and no repository commit/push was performed; the platform owns the commit.

## Remaining verification

Rerun the two prompt tests in the full checkout. The complete project suite was not run, and Python changes have not been loaded into any live service. Cached capability definitions refresh on a new backend instance.
