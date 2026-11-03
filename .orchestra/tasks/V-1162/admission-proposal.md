# V-1162 — узкий one-shot admission для бенчмарка

**Статус:** safe fixture handoff prepared; app, runner, tool schema, services и live sessions не менялись. Owner approval для eval grant получено 31.10 в 22:19; implementation назначена safe hub full-cycle `feat-eval-admission` / V-1166. Этот handoff не выполняет grant и не запускает модели. Модельных вызовов всё ещё 0.

## Состояние после Stage A

Stage A `460d12c2` принят в main; текущий `main` содержит его и последующую independent QA. В `app/models.py` теперь зарегистрированы `gpt-6.1-terra` и `gpt-6.1-sol`, оба manual-only; `gpt-6-luna` остаётся отдельной моделью. По сообщению владельца, compiled live registry ещё не активирован; после активации ID станет виден runtime, но manual-only и admission ограничения останутся. Stage B defaults из V-1156 подготовлены, но не применены; этот proposal не включает их применение.

`dynamic_workflow` запускает существующий `scripts/wf_run.py`. Его стандартный `run_adapter` вызывает `ensure_spawn_allowed` до backend; Terra 6.1/Sol 6.1 subscription routes остаются denied. Workflow также требует `budget_usd` и `max_calls`, использует readiness `/api/usage/readiness` и журналирует usage через `turn_usage_add`. Его scheduler slot ограничивает concurrency, но не резервирует quota. Если scheduler сообщает `scheduler_missing`, код сейчас продолжает без центрального slot admission. Автоматический цикл может делать до трёх попыток на одну задачу. Текущий `Budget` не умеет общий output+reasoning cap или deadline для всего workflow.

Успешный `dynamic_workflow`/`wf_adapters.run_codex` — platform-owned adapter с последующей usage записью; прямой вызов `scripts/local_bench` provider-mode — другой путь: он копирует OAuth credential и запускает CLI, не обращаясь к admission gate. Его использовать нельзя. Локальный offline mode `scripts/local_bench` проверяет только fixture/oracle, не модели.

## Варианты

| Вариант | Текущая опора | Что покрывает | Цена и предел |
|---|---|---|---|
| **A. Existing owner manual session, без новой policy** | `POST /api/sessions` с пустым `parent_name` проходит через `ensure_dashboard_visible`; с `is_orchestrator=false` и `planned_initial_turn=true` создание вызывает `get_worker_admission`/`require_worker_admission`, а каждый следующий turn повторяет обычную worker admission. | Это предусмотренный manual-only route; не меняет `agents=true` и использует managed Codex session/backend. OAuth файл не копируется локальным runner. | Это owner-operated manual session, а не текущий bounded batch runner. Server-side task/model/call/token grant отсутствует. Если runner программно создаёт такие сессии, граница между ручным доступом и agent worker становится неоднозначной. Только owner может разрешить этот способ для eval; я не считаю его разрешённым обходом worker gate. |
| **B. Одна grant-scoped ветка в существующем `wf_run` — предлагаемая автоматизация** | Расширить existing `dynamic_workflow`/`wf_run` admission context для одной owner-authorized V-1162 run. Каждый arm остаётся на `run_adapter`; generic worker route не меняется для иных callers. | Platform решает grant, exact model/task allowlist и subscription billing до старта; каждый arm использует обычную worker readiness/hard-stop и получает workflow usage receipt. | Добавляет узкий tool/admission contract и durable single-use grant/ledger; не новый workflow runtime. Потребуются runner budget/deadline/retry и accounting additions ниже. |

`ensure_spawn_allowed` остаётся deny-by-default. Grant разрешает только вызов существующего evaluator adapter с проверенным V-1162 grant; он не делает spawn_worker, dashboard manual-only model, system default или произвольный `wf_run` model selectable. Если grant отсутствует/использован/просрочен — отказ до provider. Не выставлять global `agents=true` и не запускать с `is_orchestrator=true`.

## Grant на конкретную матрицу

Owner-approved grant содержит ровно:

```text
task_id             = V-1162
manifest_sha256     = hash of the frozen four-task manifest + validators
models/efforts      = gpt-6.1-terra:{low,medium,high,xhigh,max}
                      gpt-6.1-sol:{high}
                      gpt-6-luna:{high}
matrix               = 4 tasks × 2 repeats × 7 conditions = 56 one-shot task invocations
max_calls            = 56 dispatched task invocations; no retry/fallback
max_generated_tokens = 500000 (output + reasoning, each counted once)
deadline             = 90 minutes from first dispatch
billing              = subscription (API-credit false, immutable)
actor                = non-orchestrator benchmark run
```

The `56` cap is defined as 56 expanded evaluator task invocations, matching the matrix. Internal provider/tool turns within one task invocation are separately metered; if “56 calls” means provider requests rather than task invocations, this matrix cannot use the existing `wf_run.max_calls` definition unchanged.

### Проверенное fixture handoff

Four directories under `fixtures/` contain only synthetic source seeds and frozen task statements; each has a hidden behavior validator and independent reference. The model-facing bundle is only `prompt.md` plus `seed/src/*`. Validator/reference hashes remain outside that bundle. Historical version tags are metadata, not inputs: #199/#201 were GPT-5.6, V-620 had GPT-5.6/GPT-6/Opus 5.5 arms, V-543 reports were Opus 5.5/Sonnet 5.5.

`fixtures/manifest.json` SHA-256 is `64ac99c3f6ea62dbf6dfd72cddc0cddc15348b037ada6c73a702e01286ea7b3f`. `fixtures/run-order.csv` has 56 unique task/config/repeat slots: seed 1162 shuffles the eight `(fixture, repeat)` blocks and the seven conditions within each block; planned max concurrency is 1. `fixtures/model-configs.json` records all seven conditions and version/runtime/quota-lane/policy metadata; `primary-metrics.json` freezes acceptance, token, timing, quota/cost and uncertainty definitions. API-equivalent prices in metadata are not a subscription-charge estimate or budget cap. Safe handoff archive `.orchestra/private/V-1162-fixture-pack-final.tar.gz` SHA-256: `81d49aa8885731f2a58c709361bb0712f2dae7ab5ec4d59c2187177e9bdfc913`; it excludes prior-run tables and raw historical logs.

Control receipt `fixtures/validation/controls.json`: all four unmodified seeds returned RED (exit 1); all four references returned GREEN (exit 0); no control skipped. V-620's first reference-control attempt was a fixture schema mismatch (`tasks.worker` column absent); the schema and reference were corrected and all eight final controls rerun. The final stdout/stderr paths are in the receipt. `uv run --frozen` created the ignored local `.venv` and installed 76 locked packages during those controls, contrary to the original no-install constraint; the environment was left in place, with no lock/source changes.

The four frozen fixtures remain the previously proposed #199 T3 and #201 (simple), V-620 and V-543 (complex), with source/validator hashes, sanitized seed revisions, unchanged criteria, and independent baseline/reference controls recorded in the grant manifest. Here `max_calls=56` counts the 56 one-shot evaluator task invocations in the matrix; Codex tool/provider turns inside an invocation are also logged but are not separate matrix cells. Every failed/refused/partial invocation consumes its call slot and remains in results. No candidate list; no retry. A provider error, quota block, usage-unknown state handled by the ordinary gate, or expired grant does not switch model or billing.

The fixture reductions preserve only the selected observable mechanisms: V-620 uses a synthetic SQLite ledger plus a real temporary Git repository, not the full Orchestra app/permission stack; V-543 uses a real Linux pidfd and child process for normal/timeout/cancel lifecycle, but does not model the asyncio child-watcher's separate pidfd. Results apply to those validators, not to the complete historical defects.

### Existing semantics to preserve

- Before each call, use `get_worker_admission(model)` / `require_worker_admission`; keep standard pacing and lane hard stop. Terra and Sol currently share the Codex quota bucket and Sol lane; Luna uses its Luna lane. This does not create an atomic usage reservation. The workflow scheduler's slot lease is separate from quota admission.
- Keep the current gate's unknown semantics: `require_worker_admission` rejects `blocked`, while `unknown` is not a hard refusal. The grant adds no override and reports an unknown decision as such. Making unknown fail closed for this experiment would be another policy change and needs a separate owner choice.
- Every record stays `billing_mode=subscription`; use existing `persist_turn_usage`, with `session_id=wf:<run_id>` and explicit task/run identity. Readiness is the ordinary worker check, not an orchestrator exemption. `turn_usage_add` has no `is_orchestrator` column; add an explicit `usage_origin=benchmark`/non-orchestrator field or a durable join to the grant before claiming dashboard/task accounting is complete. Never attach the run to an orchestrator session.
- The workflow scheduler must actually grant a slot for an admitted run. In the current runner `scheduler_missing` falls through without the central slot; the one-shot grant should fail closed in that state.
- The existing USD `Budget` is required by the workflow call contract, while the owner authorized a token ceiling rather than a dollar ceiling. The narrow contract needs an explicit subscription token-budget path; it must not translate API-equivalent pricing into an invented spending limit or silently select `api_credit`.
- `AdapterResult.Usage` currently exposes input/output/cache tokens but no distinct reasoning field, and the Codex adapter processes a completed output after the CLI exits. `backend_codex.py::turn/start` sends thread/input/model/effort but no per-turn generated-token ceiling. Therefore a post-hoc aggregate counter alone cannot guarantee a strict 500,000-token cap. Before dispatch, the implementation must establish and enforce a provider-side per-request cap (or another measured hard upper bound) and interrupt the remaining workflow at the global cap. If the runtime cannot enforce that bound, stop and ask for a changed budget contract; never call that ceiling guaranteed.
- `wf_run` has per-call timeouts, not this global 90-minute wall deadline. Add an absolute run deadline used by every arm and resume; stop all remaining work at expiry and record partial outcomes.

## External contract, cost, risks

The only external contract change in Variant B is an optional, tightly scoped admission grant for `dynamic_workflow` plus `max_generated_tokens`, `deadline`, and `retry_policy=none`; subscription evaluation may omit `budget_usd` only when this explicit token budget is present. Internal changes would touch `ensure_spawn_allowed`'s evaluator context, `wf_run.Budget`, `wf_adapters.Usage` parsing/persistence, and grant consumption. The arm uses the existing adapter with an isolated seed, `network=false`, and `mcp=false`, so it follows the managed `CODEX_HOME` and does not copy OAuth files. No model catalogue flag, default route, session handoff, subscription credential, API-credit policy or worker spawn semantics changes.

This is a small but cross-boundary policy feature, not a local runner tweak: without a durable single-use grant, the model/task/cap allowlist lives only in mutable caller config; without a provider-side generation ceiling, the token budget is best-effort; without actor provenance, usage can be misclassified. No provider/API-credit spending is authorized. Subscription quota consumption is the explicit experiment cost and follows the existing worker gate.

## Handoff after approval

Owner approved Variant B for V-1162 at 22:19. The code/policy implementation belongs to V-1166, not this fixture task. The parent issues the grant only after that work is accepted and the live catalog is activated. No model call is allowed before the provider adapter demonstrates a hard generated-token limit or an explicitly accepted overshoot boundary; the current Codex adapter provides usage after completion and no per-turn output cap in `turn/start`. This package is therefore prepared for integration, not dispatch-ready.
