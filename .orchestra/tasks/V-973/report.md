# V-973 — платный маршрут DeepSeek V4.1 Flash 1017

## Provider evidence

Project registry `.orchestra/projects.yaml` lists `/home/kesha/openrouter-lab`. Its V-10 endpoint snapshot `raw/endpoints-deepseek-deepseek-v4.1-flash-1017.json` identifies the selected endpoint as `provider_name: InferenceNet`, `tag: inference-net/fp8`, `quantization: fp8`. V-11 `raw/probes/snapshot-inferencenet__text__r1-request.json` shows the request contract as `provider.order: ["InferenceNet"]`, `provider.only: ["InferenceNet"]`, `allow_fallbacks: false`; V-11 reports 81/81 successful probes and matching actual provider names. The request API value is therefore the provider name `InferenceNet`; the `inference-net/fp8` tag identifies its fp8 endpoint.

## Change

Added only `deepseek/deepseek-v4.1-flash-1017` to `PAID_HARNESS_ROUTES`. The request builder pins this exact model to InferenceNet in both `order` and `only` and disables fallbacks. Other models still use `_provider_order()` and `allow_fallbacks: true`. The body keeps the original message and tool payload construction.

## Verification

`uv run --frozen python -m pytest tests/test_harness_production.py -q` → 31 passed. The exact captured terminal output (stdout and stderr combined), command, and exit code are in [`artifacts/tests.output.json`](artifacts/tests.output.json). It covers exact paid-route admission and catalog eligibility, rejection of a different paid model, strict body pin, preservation of image and tool payloads, and unchanged environment-driven routing for other models. Imported `app`: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-openrouter-route/app/__init__.py`.

Mutation check: temporarily disabled the model-specific branch and ran the committed pinning test alone with `--tb=short` (exit 1). Exact captured terminal output (stdout and stderr combined), command, and exit code are in [`artifacts/mutation.output.json`](artifacts/mutation.output.json); it fails on the expected provider body mismatch (`allow_fallbacks: true`, default order, missing `only`). The implementation was restored, and the full target suite then passed.

## Limits and live model transition

The V-10 raw endpoint record reports `context_length=1040000` and `max_completion_tokens=131072` for the InferenceNet fp8 endpoint. The OpenRouter chat body builder does not set `max_tokens` (a source search found no such key in the Harness request/configuration path); it sends no explicit completion limit that could exceed 131072. `normalize_catalog_model` carries the endpoint's `context_length`, and `apply_model_catalog` registers it as the model spec context; `HarnessBackend._max_context()` reads `CONTEXT_LIMITS`, and the loop compacts at 85% of that window. On model change, `session._change_model_in_place_locked` checks the target spec's context against the current session usage, then `HarnessBackend.retarget_model` validates the current OpenRouter catalog entry and retargets the existing client. Thus the platform context guard remains below the 1,040,000-token endpoint window; no extra token-limit code was added. This verifies the code path, not the state of any live agent session; the owner will perform that switch after acceptance.

Restart: because this changes Python code, the Orchestra orchestrator must restart the service after merge before the route becomes active.

## Delivery verified by orchestrator, 19.10.2026

Merged and published to public origin/main as `2fe8af9f6d8bd6ee0e335f70375308486c8e62dd`; remote ref matched. Secret scan covered all seven changed files, both format patterns and exact credential values, with no findings. An independent in-memory mutation disabling the pin branch made the committed provider-body test fail.

Restart through the authenticated `/api/restart` endpoint changed MainPID from 377824 to 618950. The response named only Orchestra-orchestrator and openrouter-lab-orchestrator as cut turns; both received restart notices and resumed. Startup completed, root HTTP returned 302, restored jobs resumed, cgroup limits remained 14/16 GiB, and actual oom_score_adj was 800. A Telegram disconnect appeared around shutdown; it is not evidence that the resumed bridge remained unavailable.

Refreshed the live model catalog, enabled the exact new id for agents, then changed both active sessions in `/home/kesha/openrouter-lab`: `kotone` and `openrouter-lab-orchestrator`. Each API response confirmed `native_in_place`, no runtime change and no native session reset. A read-only check of the live service database confirmed both stored model ids. Archived sessions were untouched. New paid probes were not run: the actual selected provider on a new request remains unverified until normal traffic or the observability fix records it. The strict request body is covered by the tests and the project's earlier provider probes.

CI on the previous and new main remains red independently of this route's passing target checks; V-974 is assigned to fix-dashboard. The related OpenRouter billing/provider/timing reports are assigned to fix-harness-usage in V-975. Laptop synchronization is deferred until active fix workers finish. V-972 prompt-conflict research has been dispatched to research-prompt-conflicts on Sol after the restart.
