# #247 — аудит системных промптов: модели и мёртвый текст

Дата среза: 2026-08-13. Исследование read-only относительно активных prompt/code; изменены
только артефакты `docs/tasks/247/` и личная память. БД снята через
`sqlite3.Connection.backup`, не `cp`.

## Вопрос и критерий

**Контекст.** Оркестратор получает статический `<model-routing>` и автоматически добавленный
блок `Available models for spawn_worker(model=...)`. Роли дополнительно собираются из `base.md`,
role body и manifest modules.

**Проверяемое изменение.** Сократить видимый модельный каталог до реально исполнимых маршрутов и
убрать только те prompt-фрагменты, ненужность которых подтверждается кодом или наблюдаемым
поведением.

**Baseline.** Текущий собранный prompt и текущий runtime/model registry.

**Решающий исход.** Для модели «доступна» означает не просто зарегистрированный id, а одновременно:

1. runtime сейчас сообщает или принимает модель;
2. креды/runtime готовы;
3. route policy разрешает этот класс работы;
4. отказ обнаруживается **до** создания session/worktree.

Для prompt-фрагмента «мёртвый» означает одно из трёх: он описывает отсутствующую affordance;
дословно/семантически повторяется у того же consumer; либо имеет ноль наблюдаемых срабатываний
при достаточной экспозиции и остаётся доступен из tool schema. Один ноль без экспозиции не приговор.

## Гипотезы и фальсификаторы

| Гипотеза | Что доказало бы её неверной | Вердикт |
|---|---|---|
| H1. 12 строк — честный список доступных `spawn_worker` моделей | registered id проходит prompt, но runtime/preflight не готов; либо live runtime показывает модель, которой нет в блоке | **REFUTED** |
| H2. Ошибка только в нескольких протухших строках manifest | владелец блока находится вне manifest; доступность зависит от живого runtime/config | **REFUTED** |
| H3. Большая часть prompt — мёртвый текст | реальные tool/phase markers показывают массовые срабатывания; exact duplicate scan мал | **REFUTED** |
| H4. Есть точечные мёртвые/дублированные куски | ноль lifetime use + ноль данных; same-run duplicate; schema уже несёт тот же контракт | **CONFIRMED** |
| H5. Любая prompt-правка сейчас доезжает сама | активные session blobs остаются на старом routing после рестарта/пересборки | **REFUTED** |

## 1. Владелец модельного списка найден не там, где предполагала задача

`pipeline.yaml` **не собирает** 12 строк. Источник — hardcoded `MODELS` в
`app/models.py:43-55`; `available_models_block():641-654` без фильтра проходит по всему словарю.
`ROLE_SYSTEM_PROMPT():371-401` добавляет результат каждому `kind=orchestrator` на строке 394.
Манифест владеет ролями, modules и staged model policy, но не этим каталогом [S1].

Размер блока — **1 426 B / 13 строк**. Он попадает в orchestrator и sub-orchestrator; шесть
активных таких сессий хранят **8 556 B** одинакового каталога. Это не значимая денежная экономия
само по себе; проблема — ложная развилка.

`MODELS` одновременно обслуживает `/api/models`, request validation, aliases, backend routing и
dashboard (`app/routes/system.py:353-380`, `app/routes/sessions.py:140-146`). Поэтому удалять
строки из `MODELS` ради prompt нельзя: это сломает не только рекламу, но и runtime/UI/legacy use.

**CONFIRMED** — прямой code path, tier 2 (наш source).

## 2. Фактическая матрица 12 строк

### Метод и граница данных

- Provider probes: минимальный один ход с `Reply exactly MODEL_OK. Do not call tools.` через
  текущие subscription CLI. Claude: `claude -p ... --model <id> --max-turns 1`; Codex:
  `codex exec ... -m <id> --json`. Это доказывает provider-callability, но не полный Orchestra
  spawn lifecycle.
- Grok: один реальный `spawn_worker(model="grok-4.5")`; повтор запрещён, дальнейший end-to-end
  4.6/4.5 меряет #251.
- Usage: `turn_usage.model`, а не имя агента и не mutable `sessions.model`. Срез от
  `2026-07-30T00:00:00Z`; сама `turn_usage` существует только с 03.08
  (`min=2026-08-03T06:33:39Z`, 3 001 строка на срезе), поэтому это **10 дней наблюдения внутри
  запрошенного 14-дневного окна**, а не полные две недели.
- Дополнительный контроль: все 199 `spawn_worker` tool calls в 14-дневных `logs` распарсены по
  JSON-аргументу `model`; имена воркеров не использовались.

| Строка в prompt | Provider/runtime сейчас | `turn_usage` turns / sessions | `spawn_worker` calls | Route policy | Вывод для prompt |
|---|---:|---:|---:|---|---|
| `claude-fable-5[1m]` | direct probe **OK** | 0 / 0 | 0 | `Fable — do not use`; server deny staged, но не активен | скрыть: callable ≠ разрешена |
| `claude-opus-5[1m]` | **OK** | 2 270 / 101 | 97 | special complex / fallback | оставить в actionable routing |
| `claude-sonnet-5[1m]` | **OK** | 26 / 1 | 0 | маршрута нет | убрать из agent catalog; registry оставить |
| `claude-haiku-4-5` | **OK** | 2 / 1 | 1 | маршрута нет | убрать из default choices; registry оставить |
| `gpt-5.3-codex-spark` | **OK** | 0 / 0 | 0 | узкий отдельный pool | оставить: ноль use не опровергает явный маршрут |
| `gpt-5.6-sol` | **OK** | 653 / 73 | 56 | complex/open | оставить |
| `gpt-5.6-terra` | **OK** | 1 / 1 | 3 | `Terra — do not use`; server deny staged, но не активен | скрыть: prompt запрещает, server пока нет |
| `gpt-5.6-luna` | **OK** | 49 / 38 | 41 | default/closed | оставить |
| `gpt-5.5` | **OK** | 0 / 0 | 0 | маршрута нет | убрать из agent catalog; registry оставить |
| `gpt-5.4` | **OK** | 0 / 0 | 0 | маршрута нет | убрать из agent catalog; registry оставить |
| `gpt-5.4-mini` | **OK** | 0 / 0 | 0 | маршрута нет | убрать из agent catalog; registry оставить |
| `grok-4.5` | см. хронологию ниже | 0 / 0 | 1 (failed) | маршрута нет | не рекламировать без readiness + policy |

`spawn_worker` распределён так: Opus 97, Sol 56, Luna 41, Terra 3, Haiku 1, Grok 1.
**199/199** вызовов передали точный id; ни один не использовал aliases, ради которых каталог
расходует заметную часть своих 1 426 B. Контрольный `sessions` срез не содержит сохранённых 5.5,
5.4, 5.4-mini, Fable, Sonnet или Spark session rows; единственный Grok row — архивированный
no-start probe #247.

**CONFIRMED для измеренных counts/callability** — tier 1 (прямые команды + live DB backup).
**LIKELY для рекомендации скрыть** — route policy измерена по коду/prompt, но будущий оператор
может назначить новой модели явную роль.

### Grok: каталог ошибается в обе стороны

Хронология разделяет состояние, а не склеивает его:

1. В 08:37 CEST реальный `spawn_worker(model="grok-4.5")` **сначала создал session/worktree**, а
   первичная доставка затем упала дословно:
   `Grok credentials not found at /home/kesha/.grok/auth.json. Run grok login first.`
   Сессия осталась idle, 0 turns, и была архивирована оркестратором. В этот момент prompt уже
   утверждал `grok-4.5` как “Available”.
2. К 08:53 появился regular `~/.grok/auth.json` mode 600 (содержимое не читалось).
3. `grok models` затем показывал то 4.5, то 4.6+4.5. По прямому сообщению исполнителя #251 это
   **не provider flap**, а конфаунд аудита: временный общий `[features] remote_fetch=false`
   отключал online catalog и оставлял статический fallback 4.5. После удаления только ключа тот
   же `/usr/bin/grok` 1.0.3 снова показал default 4.6 и available 4.6+4.5. Этот разбор не
   воспроизведён внутри #247 и пока не закреплён завершённым артефактом #251 [S9].
4. В `MODELS` есть 4.5 и нет 4.6. Значит prompt одновременно способен рекламировать неготовую
   модель и скрывать модель из live catalog. End-to-end Orchestra spawn 4.6 остаётся за #251;
   CLI catalog не выдаётся за доказательство spawn.

Причина late failure видна в коде: общий admission считает Grok `not_applicable`/available без
проверки кред (`quota_gate.py:138-150,288-293`; вызов `manager.py:815-836`). Worktree готовится
на `manager.py:886-930`, session публикуется на `:971-980`; `ensure_grok_home()` проверяет
`~/.grok/auth.json` только при backend connect из `_build_env()`
(`backend_grok.py:100-114,1009-1020`). MCP уже после публикации посылает первый task
(`mcp_stdio.py:831-855`) и только там получает ошибку [S4].

**CONFIRMED** для credential failure и late-failure path — tier 1 spawn + tier 2 code path.
**LIKELY** для `remote_fetch=false` как причины 4.5-only — точное свидетельство исполнителя #251,
но не воспроизводимый артефакт этого исследования.

### Проверка идеи «всегда брать live runtime catalog» по четырём runtime

| Runtime | Живой discovery на этом host | Сравнение со статикой | Следствие |
|---|---|---|---|
| Claude | `claude --help` не даёт list-model command; четыре точных id прошли direct probe | 4/4 текущих static id callable | нужен exact readiness/probe на spawn, live list из CLI взять неоткуда |
| Codex | `codex debug models` вернул 9 slugs | все 7 registry id есть; дополнительно `gpt-5.6-sol-wm`, `codex-auto-review` | live catalog нужен как readiness input, но не как разрешение: внутренние variants нельзя автоматически рекламировать |
| Grok | `grok models` динамический и зависит от remote catalog/config | live 4.6+4.5 против static только 4.5 | live catalog обязателен для readiness; static fallback нельзя называть availability |
| OpenCode | бинарник `opencode` отсутствует; в текущем `MODELS` нет opencode rows | активного маршрута нет | не требует prompt route сейчас; будущий proxy model проходит свой runtime preflight |

Итак, правильный механизм не «заменить один статический список другим». Исполнимое множество:

`routing allowlist ∩ live runtime catalog/probe ∩ credential readiness ∩ quota admission`.

Для prompt минимальный вариант ещё проще: **вообще убрать автоматический 12-line registry dump**.
`<model-routing>` уже называет только осмысленные id, а server-side preflight обязан отказать до
side effects, если runtime/credential сейчас не готов. `/api/models` сейчас также построен из
`MODELS`, поэтому переиспользовать его как readiness нельзя.

## 3. Что в активных prompts реально используется

### Размеры текущей сборки

| Role | static bytes / lines | Modules, отличающие роль |
|---|---:|---|
| orchestrator | 48 639 / 665 | routing, orchestration, lifecycle, bg, task management |
| sub-orchestrator | 47 937 / 649 | те же manager modules |
| worker | 24 171 / 365 | git, report, memory/self-improvement |
| full-cycle | 51 574 / 712 | routing, research method, lifecycle |
| reducer | 8 790 / 100 | отдельный минимальный body |

Distinct active prompt sources: **85 357 B / 16 files** (base + roles + modules; skills не
включены). Это static size, не денежная стоимость: #178 уже показал, что prompt bytes не драйвер
расхода.

### 14-дневные наблюдения не подтверждают «всё мёртвое»

35 146 tool events были распарсены полностью, включая старые строки, где `tool_name` пуст и имя
лежит в префиксе `content`. Массово используются: `send_message` 2 374, `merge_worker` 609,
`search_memory` 479, `task_update` 351, `task_create` 336, `list_agents` 277,
`codex_review` 256, `worker_wip` 220, `spawn_worker` 199, `kill_worker` 166,
`bg_create` 161. В сообщениях: `RESEARCH DONE` 196, `PLAN READY` 77,
`Memory: updated` 366, `Memory: none` 176, `RULE TRIAGE` 236, pre-mortem marker 71.

Это не доказывает причинность prompt → action, но опровергает тезис «модули не используются
вообще» для research gates, memory, task flow, lifecycle и background jobs.

**CONFIRMED для counts; UNCERTAIN для causal effect** — tier 1 observation без A/B.

## 4. Подтверждённые мёртвые, повторные и протухшие куски

### 4.1 Автоматический model catalog — P0 dead decision surface

- 7 из 12 строк не имеют текущей agent route роли (Fable, Sonnet, Haiku, Terra, 5.5, 5.4,
  5.4-mini); две прямо запрещены соседним routing block.
- 199/199 spawn calls используют exact ids; aliases из dump не использованы.
- Registry membership не проверяет creds/readiness и уже дал dead Grok session.
- Соседний `spawn_worker` tool description уже говорит, что id намеренно не дублируются и
  `<model-routing>` — owner. Автоматический dump нарушает этот контракт.

**Вердикт: удалить dump из agent prompt целиком, не удаляя модели из registry. CONFIRMED.**

### 4.2 Payment prose — ноль использования, но экспозиция не доказана

`payment_receive` и `payment_status` описаны и в `orchestration.md:78-80`, и в
`task-management.md:6-12`. В 14-дневном окне — 0/0 calls; во **всей** БД — 0/0 calls,
`tm_payments=0`, `tm_payment_allocations=0`. При этом task tools живы: create 336, update 351,
get 65, list 23 в 14-дневном окне.

Это основание рассматривать две payment строки как кандидата на удаление из обязательного prompt:
сами tools и schemas сохраняют discoverability для явной финансовой задачи. Но частые task calls
не доказывают, что в истории вообще были задачи, где платёж был уместен; пустые таблицы скорее
подтверждают отсутствие финансовых событий, чем достаточную экспозицию правила. Не основание
удалять код или объявлять текст доказанно мёртвым.

**UNCERTAIN candidate for conditional removal** — tier 1 lifetime zero + empty domain tables,
но релевантная выборка финансовых задач не установлена.

### 4.3 Background-jobs module не мёртв целиком, но его catalog prose протух

Manager roles получают и 571 B summary в `base.md:28-34`, и 1 778 B module. Tool schema уже
перечисляет типы/параметры. Module перечисляет `timer,file,command,ssh,run,cron`, но пропускает
существующий и использованный `cron_command` (7 calls у manager roles; 2 у worker).

Из 161 `bg_create` calls **111** сделали worker/full-cycle, которые module не читают; manager
roles с module — 50. Значит подробный type catalog не нужен для самой affordance. Однако правило
качества message нельзя назвать мёртвым: у manager roles median message length 376.5 chars,
и лишь 3/50 calls имели пустой message (все `run`, где message опционален).

**Вердикт:** протухший enum-каталог — подтверждённый кандидат на удаление или генерацию из schema.
Examples содержат сценарии, которых в schema нет: их ненужность для manager behavior не доказана
и требует A/B. Manager-specific message/turn-ending semantics оставить. **CONFIRMED stale enum;
UNCERTAIN examples; REFUTED, что весь module мёртв.**

### 4.4 Task management — живой workflow, но два owner одной схемы

Orchestrator получает одновременно 640 B task/payment summary в `orchestration.md:78-88` и
1 829 B `task-management.md`. Calls доказывают, что workflow жив; удалить module целиком нельзя.
Правка должна оставить один owner для signatures/status transition/task numbering, а в
`orchestration` — только ссылку/неочевидное manager decision.

**CONFIRMED semantic duplicate, REFUTED dead module.**

### 4.5 Дословные повторы малы

Exact cross-layer scan текущей assembly нашёл лишь:

- 61 B heading Background jobs у orchestrator/sub;
- 68 B `ALWAYS commit before reporting DONE` одновременно в `worker.md:12` и
  `git-workflow.md:23` у одного worker prompt.

Worker/full-cycle имеют три дословно одинаковых code-quality paragraphs: 267 + 249 + 358 =
**874 B**. Но роли взаимоисключающие, поэтому это maintenance duplicate, а не same-run tax.
То же относится к acceptance-test rule в обеих ролях. Лучший будущий owner — shared worker
module, но это P2 без измеренного behavior failure.

Предыдущий #172 также отмечал Phase 1 summary (сейчас 1 875 B) против полного research-method
(8 770 B). Counts `RESEARCH DONE=196` и gates не позволяют назвать ни один слой мёртвым;
сворачивать только отдельным behavioral A/B, не массовой переписью.

### 4.6 Нулевые forbidden-tool counts не являются доказательством мёртвого правила

За 14 дней: built-in `SendMessage`, `AskUserQuestion`, `Monitor`, `run_in_background`, `Task` —
0; `Agent` — 2 calls у Claude worker/full-cycle. Код даёт `AskUserQuestion/Monitor` permission
deny всем, а `Task/Agent` полностью убирает только у orchestrator
(`backend_claude.py:57-65,154-160,418-427`). Worker реально сохраняет Agent affordance.

Поэтому:

- правила Ask/Monitor объясняют safe alternative поверх enforcement — не удалять только из-за 0;
- общий запрет Agent не описывает одинаковую schema reality для всех ролей, но два worker calls
  доказывают, что tool там существует; это enforcement/ownership вопрос, не dead text;
- reducer — положительный контроль: код физически оставляет ему только 4 MCP tools
  (`mcp_stdio.py:68-73,277-298`), и его prompt не компенсирует лишние tools запретами.

### 4.7 `open_fan=0` пока не находка

Во всей БД `open_fan` calls = 0, но правило смержено только 13.08 в 07:10 CEST. На текущем live
срезе текст доехал лишь в **4 из 26** активных spawn-capable sessions; у всех пяти orchestrator и
sub-orchestrator его в сохранённом blob нет. Экспозиции недостаточно: удаление по нулю было бы
ошибкой измерения.

**UNCERTAIN, не кандидат на удаление сейчас.**

## 5. Доставка правок: исходная посылка уже протухла

`docs/tasks/220/research.md` верно описывал старый код («только memory hot»), но #220 затем
реализовал `SessionManager.assemble_prompt()` и rebuild на reinjection
(`docs/tasks/220/report.md`, current `manager.py:1638-1670`, `session.py:1049-1099`). Сервис
запущен 13.08 06:57 CEST, то есть код #220 уже в памяти.

Но «всё доедет само» всё равно неверно:

1. Rebuild выполняется только когда `_prompt_injected == False`; сам file change не взводит этот
   флаг. Его взводят compact/model-change/fresh-session пути. `prompt_template_hash()` лишь
   сравнивается внутри уже открытого reinjection path.
2. Hash в `prompting.py:174+` строится через старый `role_prompt_file()`. Role files сейчас
   frontmatter-free, поэтому manifest modules не входят в этот helper; module-only change сам по
   себе не даёт надёжного trigger.
3. `prompt_overlay is None` означает legacy/full replacement с неизвестной границей. Такой blob
   намеренно сохраняется byte-for-byte и **не пересобирается даже при restart**
   (`manager.py:1652-1667`).

Live DB после рестарта подтверждает не теорию, а эффект:

- active sessions: 41; `prompt_overlay IS NULL`: **17**;
- spawn-capable: 26; legacy/full unknown: **8**;
- новый `Luna is the DEFAULT` routing имеют 18/26, старый routing — 8/26;
- все 6 manager sessions всё ещё имеют 12-line model catalog;
- `open_fan` имеет 4/26 spawn-capable prompts.

### Матрица применения будущих правок

| Изменение | Доедет без restart? | После restart? |
|---|---|---|
| `docs/workers/*.md` | на следующем уже взведённом reinjection | да |
| role/base/module для componentized session (`prompt_overlay != NULL`) | только на следующем reinjection; file save сам его не гарантирует | да, `_load_from_db` rebuild |
| role/base/module для `prompt_overlay IS NULL` | нет | **нет**, full prompt сохраняется |
| `app/models.py`, `available_models_block`, Grok preflight code | нет | да для новых/componentized; legacy blob всё ещё требует миграции/замены |
| `pipeline.yaml` values при уже известной schema | loader читает по mtime/size, но prompt blob — по правилам выше | да |
| staged `worker_model_policy` #227 | нет: поле ещё закомментировано | требует разрешённый restart + activation; затем меняется горячо |

**CONFIRMED** — tier 2 code + tier 1 live DB. Посылку «только memory hot» надо снять; вместо неё
фиксировать три разных класса: componentized reinjection, legacy override, Python runtime.

## 6. Приоритет точечных правок после approval

### P0 — убрать ложный catalog и сделать failure ранним

1. Перестать добавлять `available_models_block()` в agent prompt. Оставить `<model-routing>`
   единственным owner выбора; registry/UI не урезать.
2. До создания session/worktree проверить runtime readiness. Для Grok минимум: auth file + live
   catalog содержит requested id; ошибка возвращается до publish. Для Codex использовать live
   debug catalog/probe; для Claude — exact model probe/readiness, потому что list command нет.
3. Не разрешать любой live-discovered slug автоматически: пересечение с explicit routing policy,
   иначе в choices попадут `codex-auto-review` и `gpt-5.6-sol-wm`.
4. У #227 отдельно активировать staged server policy в разрешённое restart-window; сейчас
   `worker_model_policy` закомментирован, поэтому Fable/Terra держатся только на послушании prompt.

**Эффект:** ложная модель не создаёт мёртвую session; оркестратор видит только решение, которое
может исполнить. **Риск:** live catalog может быть временно недоступен; fail loud с точной причиной,
не fallback к слову “available”.

### P1 — устранить same-run semantic owners по одному

5. `background-jobs.md`: удалить или генерировать из schema только протухший type catalog;
   examples и manager-specific contract трогать лишь после A/B.
6. Task management: оставить одну копию tool signatures/status transitions; payment prose
   переносить из always-on prompt только после проверки экспозиции либо как обратимый pilot,
   tool schemas оставить.
7. Исправить delivery observability: hash/reinjection должен учитывать manifest + modules;
   legacy `prompt_overlay=NULL` требует явной миграции/маркировки, иначе новый prompt нельзя
   честно назвать развернутым.

### P2 — не трогать без behavior eval

8. Общий worker code-quality module вместо 874 B maintenance duplicate.
9. Phase 1 summary ↔ research-method: свернуть одну смысловую группу и сравнить реальные
   RESEARCH DONE completeness/gate adherence. Не giant rewrite.
10. Forbidden-tool prose: сначала решить schema by role/runtime; prompt не должен быть единственным
    способом компенсировать 37-tools-for-everyone.

## Контрдоказательства и ограничения

- 11 direct probes показывают, что большинство «старых» id технически callable. Поэтому вывод
  **не** «удалить модели из кода», а «не выдавать technical registry за route availability».
- Spark имеет 0 turns, но явную узкую роль и отдельный pool; zero-use не делает его мёртвым.
- Tool/rule count не доказывает причинность. Нулевой forbidden-tool count совместим и с хорошим
  правилом, и с отсутствующей affordance; поэтому такие строки не удалялись по счётчику.
- `turn_usage` покрывает только 10 из 14 дней. `logs` покрывает полный период, но usage table нет.
- Grok login и catalog изменились во время аудита; хронология сохранена. #251 end-to-end 4.6 ещё
  не выдаётся за завершённый факт; объяснение `remote_fetch=false` пока основано на свидетельстве
  исполнителя #251, а не на завершённом артефакте.
- Live DB хранит assembled blobs, но не показывает, какую часть модель фактически удержала после
  native compact; finding про delivery ограничен записанным server state.

## Источники и воспроизводимость

- **[S1], tier 2 (наш source):** `app/models.py:43-55,611-654`,
  `app/manager.py:371-401,561-636,815-836,1638-1670`,
  `app/routes/system.py:353-380`, `app/routes/sessions.py:140-146`.
- **[S2], tier 2:** `pipelines/default/pipeline.yaml:4-19`,
  `pipelines/default/prompts/modules/model-routing.md:1-17`.
- **[S3], tier 1:** read-only backup `/home/kesha/orchestra/data/orchestra.db` →
  `/tmp/orchestra247-current.db`; cutoff `2026-07-30T00:00:00Z`; joins use
  `logs.session_id = sessions.id` and `turn_usage.session_id = sessions.id`.
- **[S4], tier 1 + tier 2:** реальный Grok spawn #247; `app/quota_gate.py:138-150,272-330`,
  `app/manager.py:815-836,886-930,971-980`, `app/backend_grok.py:100-114,1009-1020`,
  `app/mcp_stdio.py:831-855`.
- **[S5], tier 1:** direct provider commands, `codex debug models`, `grok models`,
  `claude --help`, `command -v opencode`; все выполнены 13.08.2026 на текущем host.
- **[S6], tier 2 + tier 1:** `docs/tasks/220/{research.md,report.md}` + current source + live
  `sessions.system_prompt/prompt_overlay/template_hash`.
- **[S7], tier 2:** все 16 активных files под `pipelines/default/prompts/{base.md,roles,modules}`;
  current assembly через `build_system_prompt("default", role)`.
- **[S8], tier 2:** `docs/tasks/172/research.md`, `docs/tasks/118/audit.md`; прошлые находки
  перепроверены на текущих файлах, а не перенесены по старым line numbers.
- **[S9], tier 4:** сообщение `bench-grok` по #251 от 13.08.2026 о постановке и снятии общего
  `~/.grok/config.toml [features] remote_fetch=false`; завершённого `docs/tasks/251/` на момент
  среза нет, поэтому свидетельство не повышено до воспроизводимого измерения.
