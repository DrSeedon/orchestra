# #432 — план парного замера context scout

Статус: Phase 2. Research approved. Реализация и Luna-прогоны ещё не начинались.

## Outcome

Собрать изолированный локальный controller и провести frozen A/B на 12 реальных задачах:

- **A = полная API-equivalent USD цена main;**
- **B = полная API-equivalent USD цена scout + main;**
- обе стороны решают один и тот же historical task в одном snapshot и проходят один и тот же
  controller-only hidden oracle;
- timeout/429/transport — `availability_failure`, локальный дефект стенда — `harness_failure`,
  completed модель с красным oracle — `model_failure`; только completed+green = `success`.

Итог должен ответить «сколько стоит весь пакет scout+handoff», не «на сколько подешевел main,
если забыть цену scout».

## Architecture chosen for discussion

### Model runtime

Использовать subscription Codex CLI, не `app/harness/`: существующий HarnessBackend принимает
только OpenRouter `:free`, а постановщик зафиксировал **Luna**. Controller запускает только:

```text
codex exec --model gpt-5.6-luna --ephemeral --ignore-user-config --ignore-rules --json ...
```

Main получает workspace-write внутри ephemeral historical checkout; scout — read-only. Controller
создаёт private `CODEX_HOME` вне workspace, передаёт auth только процессу Codex, запускает CLI во
внешнем `bwrap` mount namespace с единственным model workspace и задаёт
`shell_environment_policy.inherit=none`; `OPENAI_*`, `INTERNAL_TOKEN`, proxy/auth env в model shell
не наследуются. Внутренний Codex sandbox обязан запретить generated shell чтение private
`CODEX_HOME`/host paths. Сам текст/mount intent не доказательство: отдельная **первая Luna canary
session** требует успешной CLI-аутентификации и одновременно `DENY` для auth file, env-secret,
absolute oracle path, `../` traversal и `git cat-file <result>`. Любой доступ → STOP до benchmark.

### One currency and accounting owner

Каждый `codex exec --json` role session даёт ровно один terminal cumulative
`turn.completed.usage`. Controller пишет **одну** локальную `turn_usage` row на role session и
считает только этот terminal total; intermediate round usage в cost не суммируется. Provider
timeout/429/transport с нулём terminal events → `availability_failure`; process с
`provider_status=completed`/exit 0, но нулём terminal events → `harness_failure`; два terminal
events → `harness_failure + cost_unaccounted`. API-equivalent USD считает production owner
`app/backend_codex.py::_codex_cost`, model ровно `gpt-5.6-luna`. Frozen revision =
`ea27c8c444bdab441d4ffc3ad87172c62d7ea3a6c0b6eacd1f935f27cdfcdba3`, SHA-256 от исходника
`_codex_cost` + canonical JSON Luna prices `{input:0.2,cached:0.02,write:0.25,output:1.2}`.
Каждая A/B role row и `final.json` обязаны иметь этот digest; иной digest → STOP/re-approval.

- `cost_A = SUM(main.cost_usd)`;
- `cost_B = SUM(scout.cost_usd) + SUM(main.cost_usd)`;
- usage до терминального отказа, если она есть, остаётся в сумме;
- `cost_unaccounted`/missing usage → `INCOMPLETE`, не ноль.

Это виртуальный API-equivalent USD dashboard, не фактическое списание подписки; одна шкала нужна
для сравнения плеч.

### Who judges success

Судья — deterministic privileged controller после остановки model process, не Luna и не сходство
diff с историческим. Для каждого episode T1 замораживает:

- controller-only oracle files + SHA-256;
- exact named command;
- baseline snapshot RED с первой строкой `missing behavior` (не import/collection error);
- historical result commit GREEN;
- один `oracle_id`, передаваемый A и B.

Model checkout oracle не содержит. После model exit controller копирует result tree в отдельный
judge checkout, накладывает oracle и запускает command. Успех: provider completed **AND** oracle
RC=0. Explicit oracle assertion/nonzero = `model_failure`; judge/controller timeout =
`harness_failure`. Все остальные исходы остаются в своей корзине.

### Failure taxonomy

| Класс | Правило |
|---|---|
| `success` | Provider завершил turn, hidden oracle RC=0 |
| `model_failure` | Provider завершил turn, hidden oracle завершился explicit assertion/nonzero |
| `availability_failure` | Provider timeout/429/transport оборвал call до terminal completion |
| `harness_failure` | Completed/exit-0 JSONL без terminal, duplicate terminal, clone/sandbox/controller fault или hidden judge timeout |

Один retry разрешён только при одновременно `provider_started=0` и нуле usage rows. После
provider start retry запрещён. Все availability attempts считаются отдельно по arm/role.

### Run shape and price ceiling

Frozen execution count:

- A0/A0 noise: 6 episodes × 2 = 12 main sessions;
- main A/B: 12 episodes × 2 repetitions = 24 A main + 24 B scout + 24 B main = 72 sessions;
- cold-history control: 3 × (A main + B scout + B main) = 9 sessions;
- zero-retrieval #409 control: A main + B scout + B main = 3 sessions.

Итого benchmark/control максимум **96 Luna CLI sessions** плюс **1 Luna sandbox/auth canary**,
всего 97. Canary cost отчётна отдельно и не входит в A/B denominator. Внутри session может быть
несколько model/tool rounds, но cost берётся один раз из terminal cumulative usage. Порядок main
corpus counterbalanced: 6 `ABAB`, 6 `BABA`. Long run запускается только server-side
`bg_create(type="run")`, не обычным blocking shell.

## Files

Новые:

- `scripts/recon429/oracle_controller_432.py` — DB backup, snapshot/oracle/judge controller,
  sandbox canary, frozen manifest.
- `scripts/recon429/run_inline_432.py` — arm A, Codex JSONL parser, local usage/failure ledger.
- `scripts/recon429/run_scout_432.py` — arm B, scout bundle cap, main handoff, полная сумма B.
- `scripts/recon429/analyze_432.py` — A/A noise, ABAB/BABA scheduler/analysis, quality/failure gates.
- `scripts/recon429/.gitignore` — только `run-*/` и private raw payload.
- `docs/tasks/432/oracles/manifest.json` и controller-only oracle files.
- `docs/tasks/432/results/final.json` — агрегаты без raw prompt/transcript.
- `docs/tasks/432/report.md` — численный ответ, confidence, controls и граница применимости.

Существующие:

- `docs/tasks/432/acceptance/test_experiment_432.py` — immutable tests from RED commit
  `db30b40d`; после одобрения плана не менять. Старые `da7d6934`/`c36e22c6`/`fe587b86` исключены:
  первый — до review ради currency revision; второй — после проверенных Luna blockers ради
  terminal-cumulative accounting, exact digest, auth canary и serialized bundle evidence.
- `docs/tasks/432/plan.md`, plan-review artifact.

Read-only dependencies:

- `docs/tasks/432/corpus.tsv`;
- `app/backend_codex.py::_codex_cost` / `CODEX_TOKEN_PRICES`;
- `/home/kesha/orchestra/data/orchestra.db` только как source `sqlite3.Connection.backup`.

## Explicit non-scope

- Не менять `app/harness/`, `app/backend_harness.py`, production runtime, model registry или RAG.
- Не включать vector/semantic arm; `RAG_ENABLED=false` остаётся.
- Не писать в `/home/kesha/orchestra/data/orchestra.db`; никакого `app.db.init_db()` до установки
  абсолютного `ORCHESTRA_DB_PATH` на backup.
- Не коммитить raw transcript, model JSONL, auth, prompt, customer data или run DB.
- Не запускать Sol/review Sol; дополнительный Sol не авторизован. Plan review — один Luna pass.
- Не менять corpus, denominator 24, bundle cap 262,144 bytes, failure taxonomy или oracle после
  первого treatment output. Ложный oracle → STOP и новая санкция, не «починить по результату».

## Tickets

### T1 — Controller-only oracle для всех 12 episodes

- Files: `scripts/recon429/oracle_controller_432.py`, `scripts/recon429/.gitignore`,
  `docs/tasks/432/oracles/manifest.json`, `docs/tasks/432/oracles/**`
- Test: `docs/tasks/432/acceptance/test_experiment_432.py::test_t1_controller_keeps_oracle_outside_model_and_freezes_red_green` — committed RED in `db30b40d`
- RED: `AssertionError: missing behavior T1: controller-only oracle CLI does not exist`
- AC: `/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/432/acceptance/test_experiment_432.py::test_t1_controller_keeps_oracle_outside_model_and_freezes_red_green` is green; manifest has all 12 exact commands/hashes, baseline missing-behavior RED and result GREEN; canary authenticates CLI but reports auth-file/env-secret/absolute/traversal `DENY`, workspace-only mount, result commit invisible, judge after model exit, judge timeout=`harness_failure`; production `sessions` before=after.
- blocked-by: none

### T2 — Inline arm A с полной main-ценой и честным provider failure

- Files: `scripts/recon429/run_inline_432.py`; may import controller helpers from T1
- Test: `docs/tasks/432/acceptance/test_experiment_432.py::test_t2_inline_arm_records_full_main_cost_and_separates_provider_failure` — committed RED in `db30b40d`
- RED: `AssertionError: missing behavior T2: inline Luna arm runner does not exist`
- AC: `/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/432/acceptance/test_experiment_432.py::test_t2_inline_arm_records_full_main_cost_and_separates_provider_failure` is green; multi-round fixture produces one terminal cumulative role row (intermediate usage not double-counted), prices to exactly `$0.000337`, and pins revision `ea27c8c…cdba3`; A total equals main; provider timeout+zero terminal is only `availability_failure`; completed+zero terminal and duplicate terminal are `harness_failure`, duplicate cost is unaccounted, neither retries; local `turn_usage` contains all four rows.
- blocked-by: T1

### T3 — Scout arm B: capped bundle, same oracle, scout+main cost

- Files: `scripts/recon429/run_scout_432.py`; may import T1/T2 ledger/cost helpers
- Test: `docs/tasks/432/acceptance/test_experiment_432.py::test_t3_scout_arm_sums_scout_and_main_under_the_same_oracle` — committed RED in `db30b40d`
- RED: `AssertionError: missing behavior T3: scout+main Luna arm runner does not exist`
- AC: `/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/432/acceptance/test_experiment_432.py::test_t3_scout_arm_sums_scout_and_main_under_the_same_oracle` is green; both roles are Luna and pin revision `ea27c8c…cdba3`; runner canonical-serializes the actual bundle, measures its file bytes ≤262,144, hashes it, and main handoff records the same hash; B uses the same `oracle_id`; fixture costs scout `$0.000184` + main `$0.000337` = B `$0.000521`, with two local usage rows.
- blocked-by: T1, T2

### T4 — Counterbalanced analyzer, A/A noise and non-promoted failures

- Files: `scripts/recon429/analyze_432.py`
- Test: `docs/tasks/432/acceptance/test_experiment_432.py::test_t4_analysis_keeps_24_pairs_counterbalances_order_and_never_promotes_failures` — committed RED in `db30b40d`
- RED: `AssertionError: missing behavior T4: paired experiment analyzer does not exist`
- AC: `/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/432/acceptance/test_experiment_432.py::test_t4_analysis_keeps_24_pairs_counterbalances_order_and_never_promotes_failures` is green; denominator remains 24; order counts 12/12 slots for ABAB/BABA; A/B total costs are 24.0/19.2 in fixture; zero/zero main-cache noise = 0; net cache descriptive; injected provider timeout counts only `availability_failure`; injected judge timeout counts only `harness_failure`; neither increments `model_failure`.
- blocked-by: T2, T3

### T5 — Live Luna A/B и итог «на сколько»

- Files: `docs/tasks/432/results/final.json`, `docs/tasks/432/report.md`; private raw run data only under ignored `scripts/recon429/run-*/`
- Test: `docs/tasks/432/acceptance/test_experiment_432.py::test_t5_live_luna_result_has_full_arm_cost_same_judge_and_isolated_db` — committed RED in `db30b40d`
- RED: `AssertionError: missing behavior T5: live Luna A/B result has not been delivered`
- AC: `/home/kesha/orchestra/.venv/bin/python -m pytest -q docs/tasks/432/acceptance/test_experiment_432.py::test_t5_live_luna_result_has_full_arm_cost_same_judge_and_isolated_db` is green; `final.json` has 24 pairs, one model (`gpt-5.6-luna`) and exact revision `ea27c8c…cdba3` on every role/pair, same oracle/command per A/B, A=main and B=scout+main, three separate failure buckets, production sessions unchanged, no raw prompt/transcript; report states full prices, paired/weighted deltas, quality, availability, A/A noise, negative controls and no-class boundary.
- blocked-by: T1, T2, T3, T4

## Phase 3 execution order

1. Run T1 RED; implement only controller/oracles; run T1 GREEN. Any one of 12 oracles already
   green, collection-broken or not hidden → STOP, do not silently shrink corpus.
2. Run/implement T2, then T3, then T4, always exact RED before edit and exact GREEN after.
3. Run all T1–T4 tests together; mutate each load-bearing seam once: oracle visibility, A cost,
   B sum, failure bucket/denominator. Restore+`touch`; GREEN repeat.
4. Run T5 RED. First Luna call is the separately-accounted auth/sandbox canary; before it:
   live sessions count, DB backup and exact model/price revision. Canary failure → STOP; no
   benchmark/control model run.
5. Start the 96-session benchmark/control maximum sequence in one durable background job. No post-provider retry;
   resume only from manifest-defined unstarted slot after controller crash.
6. Analyze once from frozen raw ledger. Write `final.json`/`report.md`; run T5 GREEN and all five
   acceptance tests. Raw private directory stays ignored and is not committed.

## Breaking/migration/rollback

- Production changes: none. SQLite migration: none; experiment adds tables only to backup DB.
- Rollback before live run: delete only explicit `scripts/recon429/run-<uuid>/`; committed oracle
  and scripts remain auditable.
- A live run is append-only by slot. Never overwrite a completed slot; a controller restart reads
  manifest and continues only `NOT_STARTED`. Provider-started ambiguous slot makes experiment
  `INCOMPLETE` rather than rerunning and double-spending.

## Plan review inputs

- Changed files/consumers: plan + immutable acceptance test; future consumers listed above.
- Author metadata: `gpt-5.6-sol`, runtime `codex`.
- Exact AC: five named pytest node ids in RED commit `db30b40d` plus task requirements 1–3 from
  approval message.
- Actual RED: all five commands exit 1 on distinct missing-behavior assertions; no import or
  collection error.
- Review route: one Luna plan pass. Sol would be technically stronger for a causal harness, but an
  additional Sol run is explicitly not authorized; it will not be started.
