# #374 — reasoning effort для Orchestra research/full-cycle

## Question

- **Context:** Orchestra выбирает pipeline и role при создании сессии, сохраняет `effort` в состоянии сессии и запускает Codex CLI через собственный backend.
- **Change under test:** действующая policy, дающая research/full-cycle `high` или `xhigh`, и утверждение, что верхний effort оправдан классом работы.
- **Baseline:** `medium` — документированный баланс качества и задержки GPT-5.6 и default при отсутствии явной настройки.
- **Outcome:** прослеживаемая цепочка `pipeline/role/task → session.effort → backend argv/config → Codex turn` без неоднозначного fallback; для выбора effort — прирост качества на одинаковом acceptance oracle, отдельно от wall time, tool calls, tokens/cache и quota delta.

## Hypotheses considered

### H1 — высокая ступень является действующей task-aware policy

`high`/`xhigh` доезжает до Codex потому, что Orchestra сознательно классифицирует research/full-cycle как трудную открытую работу, а измеренный прирост качества на таком классе оправдывает дополнительную задержку и расход.

**Falsifier:** effort определяется только ролью/сохранённой строкой, не учитывает task class или фазу, либо имеющиеся одинаковые оракулы не показывают прироста качества против `medium`.

### H2 — наблюдаемая высокая ступень частично является legacy/stale состоянием

Текущая policy отличается от исторической, а старые сессии продолжают нести сохранённый `high`/`xhigh`; backend лишь явно передаёт это значение CLI, поэтому runtime behavior ошибочно принимают за актуальное решение policy.

**Falsifier:** восстановление/продолжение сессии заново резолвит effort из текущего pipeline, либо сохранённый `session.effort` не участвует в argv нового Codex turn.

### H3 — backend или Codex runtime переопределяет effort

Даже при правильном `session.effort` фактический turn может получить другое значение из глобального/project config, resume metadata или собственного default CLI.

**Falsifier:** явный `-c model_reasoning_effort=...` строится из `session.effort` и имеет документированный приоритет над defaults; Codex rollout подтверждает тот же observable turn request.

## Findings

### Короткий ответ

Orchestra не назначает effort по задаче или фазе. На текущем commit
`2abaed4e7fba4b1b8429eda7a85435e81d238b7c` все пять ролей несут одну карту:
`gpt-5.6-sol → xhigh`, `gpt-5.6-luna → high`, `claude-opus-5[1m] → high`,
`default → high` [1]. Research/full-cycle обычно получает Sol по текстовой policy model routing,
поэтому получает `xhigh`; тот же Sol на роли `worker`, `orchestrator` или `reducer` получает ровно
тот же `xhigh` [1][2]. Сам `resolve_effort` — **model-aware и role-invariant**, а не direct
task-aware. Полная цепочка всё же косвенно task-sensitive: task class влияет на выбор модели,
после чего модель определяет effort.

Фактическая доставка исправна: resolved effort сохраняется в `sessions.effort`, проходит через
`BackendBuildContext`, становится одновременно startup override
`-c model_reasoning_effort="…"` и полем `effort` в `turn/start`; rollout живой сессии #374
подтвердил `payload.effort='xhigh'` [3][4][M4]. Наблюдаемое `high/xhigh` поэтому реально, но сам
факт доставки не доказывает правильность policy.

Доказательства качества слабее механики. Наш #199 на двух закрытых Sol-задачах не увидел смены
вердикта при `medium→xhigh`, но увидел до `2.04×` цены и `42→73 s`; внешний свип из #208 показывает
монотонные `+1.76/+1.68` пункта индекса на `medium→high→xhigh`, одновременно `1.474×` цены и
`82.2→135.8→183.0 s` на ступеньках [5][7][M5]. Для настоящего многоходового research/full-cycle
свипа нет: #204 и #208 называют эту дыру прямо [6][7]. Следовательно, `high`/`xhigh` сейчас —
обратимая policy-гипотеза по модели; Orchestra-specific оправдание `xhigh` остаётся **UNCERTAIN**.

### 1. Фактическая цепочка `pipeline/role/task → Codex turn`

| Звено | Что происходит сейчас | Доказательство | Confidence |
|---|---|---|---|
| Task → role/model | `spawn_worker` принимает `model`, `role`, `task_id`, но не принимает `effort`. Текстовая policy требует Luna для CLOSED, Sol для research/review/architecture/benchmarks. `task_id` только переносится в session API [2]. | `pipelines/default/prompts/modules/model-routing.md:2-20`; `app/mcp_stdio.py:893-970` | **CONFIRMED** — текущий код и собранный prompt-owner |
| Pipeline/role/model → effort | `manager.create_session` отдельно резолвит task identity, затем вызывает `resolve_effort(raw_effort, model, backend)`; порядок ключей: exact model → runtime → `default` [1][2]. Во всех ролях карта одинакова. | `app/manager.py:724-751`; `app/pipeline.py:524-539`; M1 | **CONFIRMED** — код + исполненный резолвер |
| effort → session state | При новом spawn результат передаётся в `AgentSession`; `_to_db_dict` сохраняет его в `sessions.effort`. Восстановление сначала читает сохранённую строку БД [2][3]. | `app/manager.py:742-752,1279-1308,1642-1663`; `app/session.py:4520-4534` | **CONFIRMED** |
| stored mismatch → current policy | Перед новым idle turn `_apply_manifest_effort()` перечитывает manifest. При расхождении сначала disconnect, затем меняет и сохраняет effort; native `session_id` остаётся для resume. Running turn не трогается; legacy без pipeline/role остаётся на БД [3]. | `app/session.py:1205,1419-1452`; 26 focused tests PASS [M2] | **CONFIRMED** |
| session → backend | `_make_backend` кладёт `self.effort` в `BackendBuildContext`; Codex factory передаёт `reasoning_effort=context.effort or 'high'`; конструктор оставляет допустимое значение, неизвестное молча заменяет на `high` [3][4]. | `app/session.py:799-833`; `app/runtime_registry.py:246-263`; `app/backend_codex.py:762-790` | **CONFIRMED** |
| backend → argv/config | App-server запускается с `-c model_reasoning_effort="<effort>"`. В приватный managed `config.toml` из базового home переносятся только `project_doc_max_bytes`, `model_context_window`, `model_auto_compact_token_limit`; глобальный effort не переносится [4]. | `app/backend_codex.py:349-355,708-723,2229-2245,2328-2390` | **CONFIRMED** |
| backend → turn | Каждый новый `turn/start` явно получает `model` и `effort`; steer текущего turn effort не меняет [4]. | `app/backend_codex.py:1096-1134` | **CONFIRMED** |
| Observable Codex turn request | В 15:23Z живая строка #374 была `full-cycle / gpt-5.6-sol / xhigh / default`. Оба процесса app-server имели sanitized argv `model_reasoning_effort="xhigh"`; line 8 Codex rollout native thread содержал `payload.model='gpt-5.6-sol'`, `payload.effort='xhigh'` и `collaboration_mode.settings.reasoning_effort='xhigh'` [M4]. | DB + `/proc` + `/home/kesha/.codex/sessions/...jsonl` | **CONFIRMED request agreement** — артефакт пишет Codex CLI после `turn/start`; он не является независимой provider-side аттестацией фактически использованного compute |

Механическая матрица текущего резолвера [M1]:

| role | Opus 5 | GPT-5.6 Sol | GPT-5.6 Luna |
|---|---|---|---|
| orchestrator | high | xhigh | high |
| sub-orchestrator | high | xhigh | high |
| worker | high | xhigh | high |
| full-cycle | high | xhigh | high |
| reducer | high | xhigh | high |

Следствие: сам effort resolver сегодня не различает role/task class. Role и task class влияют на
prompt/workflow и косвенно — через выбор модели; затем модель определяет ступень. Прямой
контрпример direct task-aware resolver: закрытый `worker` на Sol тоже получает `xhigh`, а
`full-cycle` на Luna получает `high` [M1][M2].

### 2. Policy, legacy/stored sessions и runtime behavior — три разных слоя

#### Policy

Текущая карта появилась в #214: отдельный scalar роли заменили exact-model mapping и затем по
прямому решению подняли orchestrator/sub-orchestrator с `medium` до той же карты [8]. Основания,
записанные в manifest:

- Opus `high`: внешний #208 показывал крупнейший шаг composite на `medium→high`, а выше отдача
  замедлялась;
- Sol `xhigh`: во внешней лестнице #208 не было перегиба до `max`;
- Luna `high`: #204 счёл `high` коленом AA-LCR;
- прочее `high`: не измеренный default [1].

Это policy by model. Она не проверяет, является ли конкретный Sol-turn закрытой правкой, research,
review или многочасовой сессией. Последнее предложение комментария manifest — «ступень честно
окупается» — сильнее данных: свип имеет одну точку на конфигурацию, не публикует CI для разностей и
не воспроизводит Orchestra workload [7].

#### Legacy/stored sessions

Read-only срез живой БД `2026-08-23T15:38:33Z` [M3]:

```text
snapshot nonarchived= 73 resolved= 73 legacy= 0 errors= 0
stored_mismatch= 7 stored_match= 66
4 full-cycle gpt-5.6-luna xhigh high idle
1 orchestrator claude-opus-5[1m] medium high idle
1 worker gpt-5.6-luna xhigh high idle
1 worker gpt-5.6-sol high xhigh idle
```

Все семь mismatch были `idle`; их последние provider turns лежали между 09.08 и 17.08. Это
**stored-policy mismatches, согласующиеся со stale pre-policy state**, но без per-row provenance
manifest revision нельзя подтвердить историческую причину каждой строки. Они не опровергают
hot-reload: update выполняется не по времени и не фоном, а на границе **следующего** turn. Архив
содержит ещё больше старых `xhigh/high`, но архивная строка описывает историческое состояние, не
будущий Codex turn. Настоящих legacy rows без role/pipeline в этом срезе нет; ветка кода и тест для
них существуют [3][M2].

#### Runtime behavior

Runtime не выбирает direct task-aware effort. Он:

1. принимает уже resolved строку;
2. на неизвестном значении fallback'ит в `high`;
3. запускает app-server с тем же override;
4. повторяет effort в каждом `turn/start`;
5. после manifest change пересоздаёт idle backend и resumes тот же native thread [3][4].

Официальная Configuration Reference подтверждает, что явный model/reasoning `--config` override
имеет приоритет над defaults нового thread, а `model_reasoning_effort` — Responses API настройка
[O2]. Внешний контракт, локальный argv и observable turn request в Codex rollout согласуются;
provider-side использованный reasoning compute отдельно не аттестован.

### 3. Что уже измерено про качество и цену effort

#### Наш #199: одинаковый закрытый oracle, Sol `medium` против `xhigh`

Критерии были заморожены до прогонов; оба effort прошли одинаковый behavioral oracle. Ниже числа
пересчитаны из `docs/tasks/199/runs_summary.json`, не из описательной фразы [5][M5].

| case | effort | quality | wall s | tools | input | cached | output | reasoning | reconstructed $ | quota delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| T1 diagnosis | medium | PASS | 42.0 | 5 | 111,673 | 98,816 | 1,004 | 343 | 0.143813 | не снимался по ячейке |
| T1 diagnosis | xhigh | PASS | 73.0 | 4 | 205,789 | 177,152 | 2,065 | 1,285 | 0.293711 | не снимался по ячейке |
| T3 code+hidden grader | medium | PASS | 50.8 | 5 | 132,252 | 110,848 | 1,768 | 251 | 0.215484 | не снимался по ячейке |
| T3 code+hidden grader | xhigh | PASS | 54.3 | 4 | 149,824 | 124,416 | 1,797 | 310 | 0.243158 | не снимался по ячейке |

T1: `2.04×` reconstructed cost, `1.74×` wall, одинаковый вердикт. T3: `1.13×` cost,
`1.07×` wall, одинаковый hidden grader. `N=1` на ячейку и задачи короткие; вывод узкий:
`xhigh` не оправдан **этими закрытыми кейсами**, но это не тест research/full-cycle [5].

У Luna те же T1/T3 прошли на `medium` и `high`; cost ratio получился `1.10×` и `0.79×` — знак
разошёлся, что при `N=1` является наблюдаемым шумом, а не эффектом [5].

#### Внешний #208: одинаковый AA harness, Sol ladder

| effort | intelligence index | wall/task s | cost/task $ | tools | tokens/cache | quota delta |
|---|---:|---:|---:|---|---|---|
| medium | 55.572905 | 82.179 | 0.371671 | не опубликовано | не опубликовано | не опубликовано |
| high | 57.331721 | 135.811 | 0.547730 | не опубликовано | не опубликовано | не опубликовано |
| xhigh | 59.009036 | 183.046 | 0.807181 | не опубликовано | не опубликовано | не опубликовано |

Шаги: `medium→high +1.758816` при `1.4737×` cost; `high→xhigh +1.677315` при `1.4737×` cost
[M5]. Это контр-доказательство тезису «верх всегда бесполезен», но не подтверждение текущего
global Sol mapping: смесь AA включает GPQA/HLE/SciCode/Terminal-Bench/τ-bench, имеет одну точку на
конфигурацию, без доверительных интервалов для разностей и без Orchestra tool loop [7].

#208 Q3 дал Luna(high) и Sol(high) одинаковые `5/6` на реальной research+implementation задаче,
при `48 vs 34` tools и `4,988,324 vs 2,615,195` input tokens; это сильное свидетельство про
**model routing**, но не про effort — обе ячейки были `high`, поэтому в effort-вердикт оно не
включается [7].

#### Отсутствующий различитель

#204 не нашёл effort sweep на BrowseComp/GAIA/FRAMES/DeepResearch Bench и ни одного многочасового
agentic sweep; #208 подготовил red/green fixture, но Q1 не запускал [6][7]. В репозитории сохранились
commit/22-test oracle и описание, но поиск нашёл ноль exact prompt/replay bundle для L1 [M6].
Новый provider-backed `N=1` пришлось бы сформулировать заново; он не был бы replay прежней
предрегистрации и не установил бы устойчивость. Поэтому в #374 provider run не делался.

### 4. Доказательная матрица «класс задачи → effort»

Это не предлагаемая правка config, а граница того, что факты уже позволяют утверждать.

| Класс задачи / наблюдаемый признак | Текущая Orchestra route | Доказательно допустимый effort сейчас | Статус | Фальсификатор |
|---|---|---|---|---|
| Закрытая правка: file+line, immutable test/AC, один короткий chain | Luna → `high`; если вручную Sol → `xhigh` | `medium` — официальный baseline; `high` только после повторяемого выигрыша на том же oracle; в #199 пользы `xhigh` не наблюдалось | **UNCERTAIN / no observed benefit in this sample** — два Sol-case и два Luna-case, `N=1` | ≥3 парных hard closed cases, где `medium` теряет acceptance/требует escalation, а `high` проходит при приемлемых wall/tools/tokens/quota |
| Большой контекст, явное извлечение по маркерам | Luna → `high` | `medium` решил конкретную fixture; comparative effort effect не измерен | **CONFIRMED: medium passed this NIAH fixture; comparison UNMEASURED** — #199: 9/9 PASS на 164K | Замороженный cross-reference corpus показывает значимое падение medium и восстановление high |
| Короткий/средний research или review с механическим oracle | Sol → `xhigh` | `medium` как baseline; `high` допустим как проверяемая гипотеза; `xhigh` пока не подтверждён нашей нагрузкой | **UNCERTAIN** — AA указывает вверх, #199 не про этот класс | Blind paired medium/high/xhigh на одном frozen prompt+repo+oracle; xhigh повышает acceptance/evidence completeness сверх high |
| Открытая архитектура/каузальный research без deterministic oracle | Sol → `xhigh` | `high` — только как risk policy; `xhigh` оправдан лишь независимой оценкой меньшего rework/ошибок против high | **UNCERTAIN** — effort sweep на таком классе отсутствует | Слепой human acceptance/rework cohort показывает, что high не хуже xhigh или xhigh порождает больше scope/review rounds → xhigh снят |
| Многочасовой full-cycle: десятки turns, compact/resume, ветвление, ошибки self-conditioning | Sol → `xhigh` | `high` как консервативная рабочая точка; `xhigh` — экспериментальная ступень, пока нет long-horizon eval | **UNCERTAIN, ключевой пробел** [6][7] | Frozen long-chain task: одинаковый initial state/prompt/oracle, fresh thread per effort; xhigh должен повысить final acceptance сверх high, а не только reasoning tokens/wall |
| Legacy/ad-hoc session без resolvable pipeline/role | сохранённый DB effort | Не классифицируется: это состояние, не policy | **CONFIRMED** | Следующий turn такой сессии заново резолвит manifest — текущий код/тест говорят обратное |

Сквозной критерий из актуальной документации OpenAI: GPT-5.6 default — `medium`; `high` или
`xhigh` следует использовать, когда **representative measurement** показывает прирост качества;
`max` резервируется для самых трудных quality-first workload [O1]. Цена ошибки не отменяет
измерения: она может поднять допустимый budget/latency, но не превращает отсутствие gain в gain.

### 5. Как исследовать ключевой пробел без p-hacking

Один frozen task across three efforts не закроет policy-вопрос: это лишь mechanism/pilot case.
Минимальный пригодный протокол такого пилота:

1. Заморозить commit fixture, точный prompt (hash + дословный текст), model, CLI version,
   system prompt/config и один заранее существующий hidden acceptance oracle. Проверить oracle
   `RED` на base и `GREEN` на known-good; exact prompt/replay должен быть tracked artifact.
2. Одна задача, три fresh native threads: `medium`, `high`, `xhigh`; provider calls строго
   последовательно. Порядок ступеней предрегистрировать; лучше повторить balanced order, если
   бюджет допускает, иначе результат навсегда exploratory.
3. До старта записать pass/fail и stop rule. После раскрытия первой ячейки oracle не менять.
4. Считать **раздельно**, не сводить в один «cost»: final oracle/acceptance; monotonic wall;
   tool calls; input/cached/cache-write/output/reasoning tokens; reconstructed dollar; provider
   quota before/after. Quota delta принимать только в эксклюзивном окне без foreign turns; иначе
   писать `not attributable`, как показал #208 (`+2 п.п.` общего счётчика при ≈`0.37 п.п.` своего
   расхода) [7].
5. Пилот считается сигналом только если `xhigh` улучшил качество сверх `high`; меньше tools или
   быстрее wall при том же провале не является победой. Один run не доказывает устойчивость и не
   меняет global policy.

Policy-validating study требует нескольких representative task classes, повторов или balanced
orders внутри каждого класса и независимой blind оценки acceptance/rework. Только он может
подтвердить global `Sol→xhigh`; одна frozen task остаётся exploratory независимо от чистоты oracle.

## Counter-evidence

- **Против «верх бесполезен»:** AA ladder монотонно растёт до xhigh/max у Sol [7][M5]. Поэтому
  #199 не переносится с закрытых коротких кейсов на все задачи.
- **Против «xhigh уже доказан для Orchestra research»:** #204 не нашёл research/long-horizon
  effort sweep; #208 Q1 не был запущен [6][7]. Официальная документация требует measured gain,
  а не ярлык «research» [O1].
- **Против «больше reasoning безопаснее»:** #176 наблюдал, что два xhigh full-cycle дали больше
  всего review rounds и бумаги; причинность confounded размером задач, поэтому это warning, не
  доказательство вреда [9].
- **Против «строка БД равна current policy»:** семь живых idle rows не совпали с manifest, а
  archived rows сохраняют исторические значения [M3].
- **Против «argv достаточно»:** промежуточный флаг мог бы не дойти до turn; именно поэтому #374
  проверил Codex rollout `turn_context`, где observable request совпал [M4]. Это всё ещё не
  provider-side аттестация использованного reasoning compute.
- **Открытая несовместимость:** локальный `CODEX_REASONING_EFFORTS` допускает `max`, API guide
  GPT-5.6 тоже допускает `max`, но текущая Codex Configuration Reference перечисляет для
  `model_reasoning_effort` только до `xhigh` [4][O1][O2]. Manifest `max` не использует; его работа
  через Orchestra **UNCERTAIN** и в этой задаче не проверялась.

## Affected files, risks, edge cases

- Research-only: код и конфигурация не менялись.
- Если позже делать direct task-aware effort, текущий `spawn_worker`/REST schema не имеют параметра effort;
  единственные production call sites `resolve_effort` — spawn и hot reload [2][3].
- Одинаковая карта скопирована в пяти ролях manifest: изменение одной роли создаст настоящее
  role-aware различие; изменение model key во всех ролях останется model-aware policy [1].
- Изменение manifest доезжает только на следующем idle turn; текущий RUNNING не прерывается.
  Поэтому DB snapshot сразу после edit смешивает old и new без runtime defect [3][M3].
- `context.effort or 'high'` означает, что отсутствие mapping не возвращает официальный Codex
  default `medium`, а локально превращается в `high` [4]. Это legacy runtime default Orchestra,
  не default GPT-5.6.
- Нельзя выводить quota effect из API-equivalent dollars или общего percentage delta, когда в
  пуле есть другие turns [5][7].

## Sources

### Current code / local artifacts (прочитаны 23.08.2026)

1. `pipelines/default/pipeline.yaml:17-41,57,73,84-115` — одинаковая model→effort карта всех
   ролей и смысл full-cycle.
2. `pipelines/default/prompts/modules/model-routing.md:2-20`; `app/mcp_stdio.py:893-970`;
   `app/manager.py:724-751`; `app/pipeline.py:524-539` — task→model policy и spawn resolver.
3. `app/manager.py:1279-1308,1642-1663`; `app/session.py:799-833,1205,1419-1452,4520-4534` —
   persistence, restore, hot reload, BackendBuildContext.
4. `app/runtime_registry.py:246-263`; `app/backend_codex.py:349-355,708-723,762-790,
   1035-1134,2229-2245,2328-2440` — Codex factory, argv/config, app-server `turn/start`.
5. `docs/tasks/199/research.md`, `prereg.md`, `runs_summary.json` — наш frozen-oracle effort slice.
6. `docs/tasks/204/research.md`, `aa-index-by-effort.json` — effort synthesis и явные пробелы.
7. `docs/tasks/208/research.md`, `prereg.md`, `aa-cost-per-task.json` — Sol ladder, Q3 и
   незапущенный long-chain Q1.
8. `docs/tasks/214/report.md` — происхождение model map и hot reload policy.
9. `docs/tasks/176/research.md:354-375` — confounded correlation xhigh с review/paper volume.
10. `docs/tasks/374/codex-review-research.md` — два раунда targeted Sol falsification review.

### Measurements in #374

- **M1:** current resolver script: 5 roles × 3 models → во всех строках Opus high / Sol xhigh /
  Luna high.
- **M2:** `/home/kesha/orchestra/.venv/bin/python -m pytest -q <5 effort nodes>` →
  `26 passed in 15.55s` (после исправления трёх ошибочных class node ids; первая попытка была
  collection error и доказательством не считается).
- **M3:** read-only SQLite + current `resolve_effort`: `73` non-archived, `66` match, `7` idle
  mismatch, `0` legacy/unresolved.
- **M4:** live session row + sanitized `/proc` + native rollout
  `/home/kesha/.codex/sessions/2026/08/23/rollout-2026-08-23T17-23-13-01a02f37-fd0a-79f0-8cb9-9f7ecc562bab.jsonl:8`
  → `model=gpt-5.6-sol`, `effort=xhigh` в БД, argv и `turn_context`.
- **M5:** mechanical parse of `runs_summary.json`, `aa-index-by-effort.json`,
  `aa-cost-per-task.json`; raw values reproduced in §3.
- **M6:** `rg -n '90af8a74|quota_runway_baseline|L1|22 failed|22 passed|codex exec' docs/tasks/208
  docs/tasks/204 docs/tasks/199` → only fixture/oracle description; exact L1 prompt/replay not found.

### Official OpenAI documentation (opened 23.08.2026; evidence tier 2, primary)

- **O1:** [Using GPT-5.6 / reasoning effort](https://developers.openai.com/api/docs/guides/latest-model)
  — `medium` balanced/default; `high`/`xhigh` only with measured quality gain; `max` for hardest
  quality-first workloads.
- **O2:** [Codex Configuration Reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  — `model_reasoning_effort` values and priority of explicit model/reasoning config override.

## Confidence summary

- **CONFIRMED:** фактическая цепочка до observable Codex turn request; resolver model-aware и
  role-invariant, полная цепочка косвенно task-sensitive через model routing; hot reload semantics;
  семь текущих idle stored-policy mismatches, согласующихся со stale state без per-row provenance.
- **OBSERVED, узкая выборка:** #199 не показал выгоды xhigh на двух closed Sol cases; #199 NIAH
  fixture прошла на medium, comparative effort effect не измерен.
- **OBSERVED in published AA ladder; general direction UNCERTAIN:** у Sol больше effort совпало с
  более высоким composite и большими wall/cost в одной точке на конфигурацию.
- **UNCERTAIN:** `xhigh` улучшает настоящую Orchestra research/full-cycle работу; прямого
  representative long-horizon benchmark нет.
- **REFUTED:** «research/full-cycle получает high/xhigh потому, что task class напрямую входит в
  effort resolver»; «любая сохранённая строка БД описывает current policy».

## Adversarial review outcome

- Route: targeted Sol, выбран по `codex-debate` для causal/statistical research без strong
  deterministic oracle. Author и reviewer — одна модель/runtime (`gpt-5.6-sol`/Codex), поэтому
  это fresh adversarial thread, но не cross-model independence.
- Round 1: `Needs revision; no blocking findings`. Reviewer подтвердил арифметику, но нашёл семь
  переобобщений: direct resolver vs end-to-end task sensitivity; недоказанная история DB mismatch;
  request vs provider compute; три завышенных confidence label; pilot vs policy study.
- Все семь проверены и приняты; artifact изменён. Round 2 — последний разрешённый для prose:
  `APPROVED`, `All seven prior findings are FIXED`, `No new material blockers` [10].
- Verdict evidence проверено нормализацией по правилу skill: обе reviewer quotes присутствуют в
  `research.md`; second-round quote — «Один frozen task across three efforts не закроет
  policy-вопрос: это лишь mechanism/pilot case.»

## Review gate inputs

- Changed artifact / consumer: только `docs/tasks/374/research.md`; consumers — постановщик и
  оркестратор, код/runtime не меняются.
- Author metadata: live `sessions` row — `gpt-5.6-sol`, runtime `codex`, effort `xhigh` [M4].
- Exact AC: end-to-end chain до observable Codex turn request; policy/stored/runtime разделены; #199/#204/
  #208 переиспользованы без повторного provider burn; матрица task class→effort содержит
  фальсификатор каждой строки; quality/wall/tools/tokens/cache/quota не смешаны.
- Named checks: focused effort suite — `26 passed in 15.55s` [M2]; current resolver matrix [M1];
  DB/current-policy reconciliation [M3]; live rollout end effect [M4]. Для причинного вывода
  deterministic oracle слабый — representative long-horizon experiment отсутствует, поэтому
  выбран targeted Sol falsification review, а не skip/Luna.
