# #247 — план: честная маршрутизация моделей и доставка prompt-правок

## Цель и граница

Исправление должно убрать из prompt ложный registry dump, перенести решение о фактической
исполняемости модели в server-side admission и не создать новую ложь в виде «live catalog =
policy». Отдельно нужно вернуть под управление текущего prompt восемь spawn-capable legacy
сессий с `prompt_overlay IS NULL` и сделать последующие module-правки наблюдаемо горячими.

Не входят в эту фазу:

- удаление моделей из `app.models.MODELS`, `/api/models`, UI, aliases или legacy validation;
- добавление Grok 4.6 либо новой route-роли: live discovery сам по себе не даёт разрешение;
- `payment prose`: экспозиция осталась `UNCERTAIN`, поэтому оснований менять его нет;
- examples из `background-jobs`, task-management duplicate, code-quality/phase rewrites и
  прочие P1/P2 аудита — им нужен отдельный behavioral eval;
- provider/API-turn probes, performance/latency/token benchmarks;
- изменение live DB, restart/deploy или включение staged policy без отдельного разрешённого окна.

## Инварианты решения

1. Model registry отвечает «что код умеет распознать», route policy — «что разрешено выбрать»,
   runtime readiness — «может ли выбранное стартовать сейчас». Эти сущности не подменяют друг
   друга и не генерируются одна из другой.
2. Проверка planned spawn проходит **до** `create_worktree`, конструирования/publish
   `AgentSession` и записи session row. Отказ не оставляет ни worktree, ни мёртвую сессию.
3. `model_policy_override_reason` может обойти только route/balance policy, как сегодня. Он не
   превращает отсутствующие credentials/catalog и подтверждённо исчерпанную quota в готовность.
4. Ни readiness, ни ошибки не читают и не логируют содержимое auth/token stores. Используются
   только CLI status/catalog contracts и факт готовности managed home.
5. Full prompt override (`prompt_overlay IS NULL`) остаётся authority boundary: автоматическая
   эвристика не переписывает его. Legacy rows переводятся в componentized mode только по
   заранее одобренному списку `session id + sha256`, в остановленном окне и с backup.
6. Safety/authorization/lifecycle rules и role/module ownership не ослабляются.

## Разрешённый конфликт: формула research против #227

В `research.md` доступность была записана как однородное пересечение всех входов. Это неверно
для quota telemetry и противоречит уже проверенному поведению #227. Направление отказа задаёт
семантика **неизвестности конкретного входа**, а не один общий оператор:

```text
allowlist ∩ credential_ready ∩ catalog_ready ∩ (quota != blocked)
```

- credentials и runtime catalog — fail-closed: отсутствующая credential, неответивший runtime
  либо отсутствие точного model id в живой выдаче означают, что работа сейчас невозможна;
- quota — fail-open при `unknown`, fail-closed только при `blocked`: stale cache, 12-секундный
  timeout либо ошибка telemetry не доказывают исчерпание лимита.

Четвёртый член намеренно слабее первых трёх. Иначе первый сбой telemetry остановит весь контур.
Но fail-open обязан быть громким: каждый `unknown`/exception пишет `ERROR` с runtime/model/reason.
Тесты #227 на warm normal, stale+failed refresh, missing telemetry, slow→timeout и exception
остаются регрессиями; подтверждённые 95% по-прежнему блокируют.

Для runtime без list-model contract отсутствие каталога не маскируется словом `unknown`:
capability явно объявляет `catalog_mode=not_applicable`. На текущем host это Claude: для него
нулевой-turn preflight может доказать auth readiness (`claude auth status`) и принадлежность id
к явному allowlist/registry, но не live membership конкретной модели. Считать это live catalog
нельзя; жечь отдельный subscription turn на каждый spawn план не предлагает. Codex и Grok имеют
catalog contract, поэтому там timeout/parse error/missing id закрывают spawn. Необъявленный hook
у нового runtime — ошибка регистрации, а не неявный `not_applicable`.

## Архитектура

### Один coordinator admission

Новый `app/spawn_readiness.py` получает `pipeline`, `role`, exact `model`, runtime, override и
**уже разрешённый** `profile`/credential context, возвращает структурированный decision trace и
либо разрешает spawn, либо поднимает одну диагностируемую ошибку. Он вызывается после обеих
веток наследования profile (`explicit` и auto-found parent), но до side effects, и последовательно
выполняет:

1. static route admission из `WorkerModelPolicy`: `always_allowed ∪ quota_guarded.model`;
2. credential probe runtime;
3. exact catalog membership, когда runtime объявил live catalog;
4. текущий balance gate для quota-guarded Opus и общий `get_worker_admission(model)`.

Текущая `_enforce_worker_model_policy()` не остаётся вторым owner: её allowlist/balance logic
переезжает в coordinator без изменения порогов, latch и loud fail-open #227. Planned session
creation вызывает coordinator один раз на общем pre-side-effect seam. Credential/catalog
применяются и к planned orchestrator-role spawn; worker allowlist — только к `kind=worker`, как
сейчас. Root restore и уже существующие session resume этим gate не переопределяются.

Claude credential context разрешается одним общим helper, который используют и preflight, и
`_claude_factory`: непустой profile читается через `profiles.config_dir`, пустой сохраняет
текущий contract наследования `CLAUDE_CONFIG_DIR`/process env. Поэтому status-команда получает
ровно тот `CLAUDE_CONFIG_DIR`, который затем получит backend; отдельная «похожая» логика путей в
readiness не заводится.

### Runtime contracts

`RuntimeDefinition` получает обязательное явное описание readiness вместо ветвления по строке
runtime в manager:

| Runtime | credential_ready | catalog_ready | Failure semantics |
|---|---|---|---|
| Claude | bounded `claude auth status` в resolved `CLAUDE_CONFIG_DIR` выбранного/унаследованного profile | explicit `not_applicable`; exact id всё равно обязан быть в registry + allowlist | profile-specific status failure/timeout closes; отсутствие live list остаётся задокументированной границей |
| Codex | bounded `codex login status` | bounded `codex debug models`, exact slug membership | command/JSON/missing id closes |
| Grok | существующий user-auth existence check, затем тот же managed `GROK_HOME`, что получит backend | bounded `grok models`, exact id membership | missing auth/command/parse/missing id closes before worktree |
| OpenCode/custom | должен явно объявить probes или `catalog_mode=not_applicable` | route отсутствует сейчас | unknown runtime/hook и отсутствующий binary закрывают spawn |

Все subprocess probes запускаются без shell, с общим bounded timeout и bounded stderr. Auth body,
полный catalog и environment в логи не попадают. Tests подменяют subprocess; ни один тест не
запускает provider turn и не читает реальный auth store.

Подготовка Grok home имеет один owner — существующий helper в `app/backend_grok.py`, вызываемый и
preflight, и backend. Поскольку helper создаёт config и заменяет auth symlink в общем managed
home, вся операция защищается module-level lock; запись config остаётся atomic. Параллельные
preflight/backend calls должны получить один целый config и правильный symlink либо одну явную
ошибку, но никогда промежуточное состояние. Это допустимый bounded readiness side effect; session,
worktree и DB row до успешного результата всё равно не создаются.

### Prompt surface

`ROLE_SYSTEM_PROMPT()` перестаёт добавлять `available_models_block()`. `MODELS` остаётся runtime/UI
registry. Единственный model-choice owner для агента — `modules/model-routing.md`; tool schema
`spawn_worker` продолжает направлять к нему без второй копии id.

Контрактный тест выводит разрешённые exact ids из **активного** `WorkerModelPolicy` и требует,
чтобы каждый был назван в `<model-routing>` ровно один раз у orchestrator, sub-orchestrator и
full-cycle. У worker/reducer нет ни routing module, ни старого `Available models` dump. Denied и
unrouted registry ids не становятся choice только потому, что существуют в `MODELS`.

### Hot delivery и legacy rows

`prompt_template_hash(pipeline, role)` хеширует фактическую static assembly
`build_system_prompt(pipeline, role)`, включая manifest module list, module order и bodies.
Перед новым входящим ходом componentized session сравнивает hash **до** `_prompt_injected` gate:
изменение взводит reinjection, current prompt пересобирается один раз, следующий неизменившийся
ход ничего повторно не получает. Full override не перевооружается template hash.

Для legacy rows добавляется offline CLI `scripts/normalize_prompt_overlays.py`:

1. `snapshot` пишет только id/name/role/status/`prompt_overlay is NULL`/sha256 prompt, без prompt
   body; первая rollout-группа — восемь active spawn-capable rows из среза #247;
2. человек явно утверждает exact manifest; terminal 9 и любые custom/неоднозначные rows не входят;
3. `apply` сначала через `sqlite3.Connection.backup` создаёт recoverable backup, затем выполняет
   `BEGIN IMMEDIATE → повторное чтение active NULL set → сверку id/hash/status → UPDATE → COMMIT`;
4. добавление, исчезновение либо drift любой строки приводит к explicit `ROLLBACK` и **нулю**
   записей; успешная транзакция ставит `prompt_overlay=''` только exact approved rows.
   `system_prompt` не переписывается: после старта штатный `_load_from_db` собирает current base +
   пустой overlay + fresh memory.

CLI нельзя запускать на live service: in-memory session state перезапишет/проигнорирует DB и
сломает атомарность. Это rollout-команда для остановленного окна, не автоматическая миграция.

## Tickets

### T1 — Server-side spawn readiness до side effects

- Files: `app/spawn_readiness.py` (new), `app/runtime_registry.py`, `app/backend_grok.py`,
  `app/manager.py`, `tests/test_spawn_readiness.py` (new), `tests/test_manager.py`,
  `tests/test_runtime_registry.py`, `tests/test_backend_grok.py`, существующие #227 gate tests.
- AC:
  - coordinator реализует дословно
    `allowlist ∩ credential_ready ∩ catalog_ready ∩ (quota != blocked)` и отдаёт раздельные
    reason/state по четырём входам;
  - missing credential, command timeout/parse error и missing exact id дают отказ до вызовов
    `create_worktree`, `AgentSession`, `save_session`; после real `create_session` DB row и path
    отсутствуют;
  - Codex/Grok live catalog не расширяет allowlist внутренними/новыми slug;
  - runtime с explicit `catalog_mode=not_applicable` проходит только credential + registry +
    route checks; отсутствующий declaration fail-loud;
  - explicit Claude profile и profile, унаследованный от явно указанного либо auto-found parent,
    проверяются с тем же `CLAUDE_CONFIG_DIR`, что получает `_claude_factory`; global auth не может
    замаскировать неготовый selected profile;
  - два одновременных Grok preflight/backend prepare не оставляют broken config/auth symlink;
    missing auth по-прежнему отказывает до session/worktree/DB;
  - quota `unknown` и exception разрешают spawn и дают `ERROR`; `blocked` запрещает; все пять
    #227 состояний и 95%-control остаются зелёными;
  - override обходит route/balance policy, но не credentials/catalog/confirmed quota block;
  - probes bounded, no-shell, не печатают auth/catalog body и не делают provider turn.
- blocked-by: none

### T2 — Удалить ложный dump, оставить один исполнимый model-choice owner

- Files: `app/manager.py`, `app/models.py`, `pipelines/default/prompts/modules/model-routing.md`
  (только если exact-id contract обнаружит реальный пробел), `tests/test_backend_routing.py`,
  `tests/test_default_pipeline.py`, `tests/test_manager.py`, `tests/test_mcp_stdio.py`.
- AC:
  - `Available models for spawn_worker(model=...)` и все строки auto dump отсутствуют во всех
    пяти собранных role prompts; `MODELS`, `/api/models` и backend validation не изменены;
  - spawn-capable роли получают полный routing module ровно один раз, terminal roles — ни одного;
  - каждый positive model id активной worker policy есть в routing owner ровно один раз и
    `spawn_worker` schema указывает к `<model-routing>`, не дублируя ids;
  - удаление одного positive id из module, возврат auto dump или утечка module в worker ломают
    отдельные regressions.
- blocked-by: T1

### T3 — Module-aware hot refresh и безопасная нормализация legacy prompt state

- Files: `app/prompting.py`, `app/session.py`, `app/manager.py`,
  `scripts/normalize_prompt_overlays.py` (new), `tests/test_hot_apply.py`,
  `tests/test_manager.py`, `tests/test_normalize_prompt_overlays.py` (new).
- AC:
  - изменение только module body/list/order меняет template hash и на следующем ходе
    componentized session получает один свежий prompt; повторный ход без изменения не reinject;
  - base/role change сохраняют тот же контракт; custom overlay, ownership и fresh
    `<worker-memory>` присутствуют ровно по одному разу;
  - full override (`NULL`) не меняется и не пересобирается от template hash;
  - snapshot не содержит prompt body/token data; apply на temp SQLite создаёт backup и меняет
    только exact approved ids; `BEGIN IMMEDIATE` охватывает fresh reread, compare и update;
    hash/status/set drift между snapshot и apply даёт explicit rollback и zero writes;
  - после load нормализованная row получает current prompt без старого catalog, а неутверждённая
    `NULL` row остаётся byte-for-byte authority-preserved;
  - live `data/orchestra.db` не изменяется в тестах/Phase 3 без rollout authorization.
- blocked-by: T2

### T4 — Координированная activation и доказательство доставки

- Files: `pipelines/default/pipeline.yaml` (снять staging-комментарий только в остановленном
  окне), `docs/tasks/247/report.md`; live DB/backup — вне git и только по отдельной authorization.
- AC:
  - перед окном fresh snapshot всё ещё даёт ровно утверждённый набор legacy spawn-capable
    rows; любое расхождение останавливает rollout;
  - последовательность: закрыть ingress → остановить Orchestra → DB backup → approved legacy
    normalization → активировать уже типизированный `worker_model_policy` → старт;
  - после старта pipeline loader видит non-NULL policy, componentized/approved manager prompts
    не содержат old catalog и содержат один current routing module;
  - тестовый denied/unrouted model отклоняется до side effects; credential/catalog probe failure
    и quota blocked/unknown проверяются на fixture/mocked runtime, не разрушительным live spawn;
  - rollback описан и проверен на копии: вернуть DB backup + закомментировать policy + один
    authorized restart. Без явного restart-window T4 не выполняется и задача честно остаётся
    «implemented, rollout pending», а не выдаётся за deployed.
- blocked-by: T1, T2, T3

## Проверка и независимые мутации

Targeted/regression suites в worktree:

```bash
uv run python -m pytest -q \
  tests/test_spawn_readiness.py tests/test_runtime_registry.py \
  tests/test_backend_grok.py tests/test_backend_routing.py \
  tests/test_default_pipeline.py tests/test_hot_apply.py \
  tests/test_manager.py tests/test_mcp_stdio.py tests/test_pipeline.py
```

Перед каждой мутацией — новый `cp F F.bak`, мутация и `mv F.bak F` в одной команде с проверкой
маркера после возврата. Минимальный набор независимых mutants:

1. route gate всегда возвращает allow;
2. credential failure игнорируется;
3. catalog membership не проверяется;
4. preflight переносится после `create_worktree`;
5. `quota unknown` снова блокирует либо его `ERROR` удаляется;
6. confirmed `blocked` разрешается;
7. auto model dump возвращается в `ROLE_SYSTEM_PROMPT`;
8. один positive id исчезает из routing module;
9. template hash снова не включает modules;
10. normalizer принимает changed hash либо переписывает неутверждённый `NULL` override.

Каждая мутация обязана покрасить предназначенный ей тест; составная мутация «routing id исчез из
module, но строка вернулась через общий dump» обязана также краснеть — иначе negative prompt test
проверяет наличие текста где угодно, а не единственного owner.

## Доставка и цена отката

| Изменение | До разрешённого restart | После restart без legacy normalization | После T4 |
|---|---|---|---|
| Python admission / удаление auto dump | не действует: код сервера в памяти | действует для новых и componentized rows | действует для всех approved spawn-capable rows |
| module/base edit после T3 | старый Python не re-arm | следующий входящий ход componentized session | то же для normalized rows; full overrides намеренно не меняются |
| staged worker policy | остаётся закомментированной | всё ещё не активна | активна; последующие value-only edits hot через loader |
| terminal 9 legacy `NULL` rows | без изменений | без изменений | без изменений: вне первой группы и исходного route-дефекта |

Rollback T1–T3 — обычный revert + authorized restart. Rollback T4 требует именно сохранённый DB
backup: обратное `'' → NULL` без старого full blob не восстанавливает прежний authority state.
