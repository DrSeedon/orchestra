# #455 — выполняется ли ambient-требование «упрости» на собственных мержах

Дата среза: 2026-09-03. Фаза: 1, только ресёрч и измерения; production/prompts не менялись.

## Прямой ответ

**Формулировка `200 lines where 50 suffice → rewrite` не доказана как работающий контроль и в
текущем виде не может им быть.** Она реально доставляется воркерам, но не задаёт наблюдаемого
предиката. В 39 обычных prompt-bearing мержах AST-граф нашёл 741 добавленную строку (4.867%),
которая до замороженного `main` осталась недостижима из tracked production roots. Все 741 строки,
однако, достигаются из обычных или замороженных task-local acceptance-тестов: это не бесхозный текст,
а tested dormant/admin seams, преимущественно большой #315. Поэтому назвать все 741 строки
«мусором, который можно удалить» нельзя. [M1][M4]

Гипотеза «модели структурно не умеют упрощать» опровергнута контр-примерами. Когда цель была
конкретной, модели удаляли и консолидировали: #309 удалил 1,735 строк Python; #338 удалил ровно
12 строк недостижимого JS за один Luna-turn и прошёл точечный оракул `3 passed in 0.27s`; #167
свёл четыре копии обработки ошибки к одному владельцу. Отличие не в магической модели, а в задании:
названный символ/владелец, замороженный consumer path и механический pass/fail. [M5][M6]

Причинный вывод слабее структурного: contrast 4.867 п.п. между обычными и explicit-simplify мержами
меньше собственного медианного split-half шума метрики 4.997 п.п. (p95 11.550 п.п.). Следовательно,
по этой выборке нельзя утверждать ни «ambient-фраза улучшает код», ни «explicit-просьба статистически
улучшает долю недостижимого». Законный итог из постановки — **как общий gate требование
неоперационально; как эвристика оно не доказано и не опровергнуто причинно. Работает проверяемая
конкретизация, а не слово “упрости”.** [M2]

## Вопрос и гипотезы

### Step 0

- Контекст: успешные worker/full-cycle merges репозитория Orchestra.
- Изменение под проверкой: ambient-блок `code-quality` с минимумом кода, запретом спекулятивных
  абстракций и фразой `200 lines where 50 suffice → rewrite`.
- Baseline: prompt-bearing задачи без явной просьбы сократить структуру; counter-arm — задачи с
  дословной просьбой удалить/консолидировать/упростить.
- Измеримый исход: production AST reachability добавленных определений, exact AST clones, рост
  многократно правившихся файлов, наличие исполняемого merge/acceptance gate.

### Step 1

| Гипотеза | Фальсификатор | Результат |
|---|---|---|
| H1. Ambient-требование само удерживает мерджи простыми | Стабильные production-unreachable clusters или exact clones проходят мерж без simplify-oracle | **REFUTED как абсолютное требование; causal average effect UNCERTAIN** |
| H2. Модель не умеет сокращать даже по прямой просьбе | Explicit-задачи сохраняют/добавляют тот же дефект и не дают сокращения выше шума | **REFUTED контр-примерами #309/#338/#167** |
| H3. Проблема — модели обычно не поручали проверяемое упрощение | Есть общий автоматический oracle, который связывает фразу из prompt с каждым merge | **CONFIRMED: общего oracle нет; одна точечная проверка #338 есть** |
| H4. Статическая метрика сама даёт честный verdict «лишнее» | Legal negative control или ручная проверка показывает обязательный повтор/динамический вход | **REFUTED для clone→waste; reachability остаётся conservative candidate metric** |

## Метод и корпус

Протокол был записан до полного прогона в `protocol.md`. Источник — read-only
`data/orchestra.db` и Git objects; приложение не импортировалось. Граница БД:
148 `merge_operations.state='SUCCEEDED'` до `2026-09-03T08:44:44.926475+00:00`; после удаления
двух duplicate target rows осталось 146 unique single-parent targets. Exact prompt
anchor присутствует в сохранённом `sessions.system_prompt` 139/146 (95.21%) раз. Структурный census —
42 из них, изменившие ≥10 строк `app/**/*.py`: 39 ambient и 3 explicit. [M1]

Граф парсил все tracked `app/**/*.py` и `scripts/**/*.py`. Каждый module body, decorated definition
и dunder — root; Name/Attribute, function-object reference, literal string dispatch и import alias —
edge. Это over-approximation: она скорее пропустит мёртвое, чем объявит живое мёртвым. Non-literal
`getattr` проверен отдельно. Added candidates сверялись повторно на frozen `main`; ставший достижимым
или исчезнувший symbol записывался `resolved_later`, а не остаточным. [M3][M4]

Пилот действительно изменил метод, а не ответ. Первая версия не разрешала function-local
`ImportFrom.asname` и ложно назвала весь `portfolio_watchdog` мёртвым, хотя `app/main.py` импортирует
`ensure_task as ensure_portfolio_watchdog` и вызывает alias. Результат удалён, alias-edge добавлен,
controls/full run/noise/comparison повторены с нуля. [M7]

## Findings

### F1 — prompt доставлен, но общий simplify-gate отсутствует

**CONFIRMED — tier 1, сохранённые session prompts + текущий код гейтов.**

- 139 из 146 сопоставимых успешных merge targets получили exact anchor; все 42 строки structural
  cohort получили его. Проблема не объясняется недоставкой prompt. [M1]
- `tests/test_default_pipeline.py::test_code_quality_has_one_owner_and_reaches_both_working_roles`
  проверяет доставку всего модуля worker/full-cycle и отсутствие копий, но не качество результата.
- `app/diff_budget.py` считает только insertions и отказывает после 2,000; он не смотрит AST
  reachability, clones или sufficiency и разрешает любой diff в пределах потолка. [M8]
- В 148 successful merge receipts 16 содержали acceptance command. Ровно одна команда совпала с
  `dead-code|unreachable|simplif` — task-specific #338. Поэтому исходная абсолютная фраза «проверок
  нет ни одной» **REFUTED**: одна есть; общего default simplify-check — ноль. [M6]

### F2 — 4.867% ambient additions остаются production-unreachable, но это tested dormant code

**CONFIRMED как статическая production reachability — tier 1; UNCERTAIN как “мусор”.**

- Ambient: 15,225 Python additions, 803 deletions; 1,178 additions сразу попали в unreachable
  definitions, 437 позже стали достижимы/исчезли, 741 осталась unreachable на frozen `main`:
  **4.867% additions**. Explicit: 475 additions, 1,834 deletions, 0 persistent candidate lines. [M1]
- 741 lines относятся к 31 stable definition в восьми merges. Крупнейшие seams: #358 cutover
  341 lines; #352 session archive/recovery 272; #436 review-receipt create/get 56; #342 promotion
  wrappers 27; #335 schema helpers 25. Полный список и входящие graph edges — `candidate-audit.md`.
- #315 сам документировал seam как административный и отложенный: `migration_api → cutover_api`,
  «There is no startup caller», canonical owner switch `NOT EXECUTED`. То есть граф совпал с
  задокументированным runtime-state, а не придумал отсутствие входа. [M9]
- После добавления как roots реальных pytest tests/fixtures/framework hooks из `tests/` и всех
  task-local `*/acceptance/*.py` все 31 definition стали достижимы. **Ноль из 741 строк недостижимы
  одновременно из production и tracked tests.** Это контр-свидетельство против ярлыка «бесхозный
  мусор» и объясняет, почему обычный test gate их не удаляет. [M4]

### F3 — computed `getattr` не скрывает вход в найденные clusters

**CONFIRMED для frozen snapshot — tier 1, AST sites + receiver inspection.**

15 unresolved sites распались на data access, а не dispatch к кандидатам: `usage[k]`-подобное поле
(1), `RagMemory.<method>` (2; candidate methods этого класса нет), runtime manifest field (1),
prepared handoff fields (1), `_TgDeliveryState` counters derived from `traffic_class` (10). Literal
names и конечные literal sets уже являлись edges. Ни один receiver не может владеть одним из 31
candidate definitions. [M3][M4]

### F4 — own noise запрещает причинное сравнение explicit против ambient

**CONFIRMED — tier 1, preregistered 1,000 split-halves.**

Три одинаковых current-snapshot прогона дали один SHA-256 — instrument noise 0. На 39 ambient rows
median absolute split-half difference для persistent-dead rate = **4.997 п.п.**, p95 =
**11.550 п.п.** Наблюдаемый ambient 4.867% против explicit 0% даёт contrast **4.867 п.п.**, то есть
ниже медианного собственного шума. По заранее записанному правилу это **no measured contrast**. [M2][M3]

Причина видна в данных: несколько больших #315 seams концентрируют почти весь candidate volume,
а explicit arm содержит всего три merges. Увеличивать уверенность пересказом процентов нельзя.

### F5 — exact-clone rate измерим, harmful-duplication rate нет

**CONFIRMED для exact candidates; REFUTED как автоматический verdict “лишнее”.**

- Negative control: 11 реальных copies трёхстрочного transaction cleanup в `app/tm.py` найдены;
  equivalent three-statement scratch copies дали 0 clone groups. Four-statement positive control
  дал ровно 1. [M3]
- Во всех 42 merges появилось шесть exact four-statement-window hashes, затрагивающих 15 unique
  added lines: **0.0955% от 15,700 additions**. Ambient = 13/15,225 (0.0854%), explicit = 2/475
  (0.4211%). Explicit arm формально хуже. [M1][M2]
- Ручное чтение показало смесь: DB snapshot и in-memory session обязаны получить одни поля (#293);
  poisoned/normal transport branches очищают одни поля при разных preconditions (#319); typed stores
  повторяют atomic temporary-file pattern с разными contracts (#342). Это кандидаты на named helper,
  а не доказательство removable duplication. [M4]

Clone contrast 0.336 п.п. превышает median noise 0.081 п.п., но идёт против ожидаемого направления и
опирается на semantic false positives. Значит метрика различает exact AST форму, но не законный повтор.

### F6 — модели упрощают, когда задача называет объект и oracle

**CONFIRMED как existence proof — tier 1; не population estimate.**

| Case | Explicit instruction | Result | Recorded model turns before merge |
|---|---|---|---:|
| #309 / `9f946a6017` | удалить named unused features с deletion oracles | app Python `+17/-1735`, persistent-dead additions 0 | 7 Luna session turns (task binding появился поздно) |
| #338 / `b09118919b` | удалить только `deleteOrchestrator`, сохранить live delete UX и computed-dispatch guard | JS `+0/-12`; `3 passed in 0.27s` | 1 Luna turn |
| #167 / `4b862eb6e1` | один error-text owner вместо четырёх copies в задаче на три сбоя | app Python `+101/-64`; persistent-dead additions 0 | 1 task-linked Opus turn |
| #349 / `7717ef880d` | убрать generated Markdown, оставить один agent knowledge API | app Python `+357/-35`; `26 passed, 1 deselected`; persistent-dead additions 0 | 3 Sol turns |

Четыре cases охватывают Opus, Luna и Sol. Они опровергают универсальный тезис из #439 «LLM просто
не может упростить», но не доказывают, что любая модель найдёт упрощение без названного target. [M5][M6]

### F7 — repeatedly edited files растут, но рост не равен bloat

**CONFIRMED как LOC trajectory; UNCERTAIN как качество.**

В main-ancestry части cohort за 20.08–03.09 шесть Python files были затронуты ≥5 включёнными merges:

| File | Touches | First→last LOC | Change |
|---|---:|---:|---:|
| `app/mcp_stdio.py` | 12 | 2,654→3,933 | +1,279 (+48.2%) |
| `app/main.py` | 7 | 466→572 | +106 (+22.7%) |
| `app/routes/sessions.py` | 7 | 1,818→2,683 | +865 (+47.6%) |
| `app/tm.py` | 6 | 1,179→2,540 | +1,361 (+115.4%) |
| `app/manager.py` | 5 | 2,438→2,782 | +344 (+14.1%) |
| `app/session.py` | 5 | 4,824→5,303 | +479 (+9.9%) |

Explicit merges дали внутри учтённых deltas `tm.py -496 net`, `routes/sessions.py -27`, `main.py -26`,
но series всё равно выросли из-за новых функций и промежуточных merges. LOC trajectory показывает
давление на монолиты; без reachability/behavior evidence он не отделяет capability growth от bloat. [M2]

## Проверяемая замена и цена в model turns

| Вариант | Что проверяет | Дополнительная цена | Вердикт |
|---|---|---:|---|
| Оставить только `упрости` в prompt | Ничего механически наблюдаемого | 0 turns | не gate; текущий статус |
| Task-specific absence oracle как #338 | Названный symbol отсутствует во всех production/static/registry dispatch arms, live consumer остаётся | **0 extra merge turns**: команда выполняется существующим acceptance runner; в Phase 2 всё равно пишется RED | **рекомендуется для удаления** |
| Task-local AST root predicate | У named cluster нет production-root path; computed `getattr` и decorators вынесены в явный список | 0 turns на зелёном server-side run; **+1 model continuation** при non-zero candidates для проверки receivers/contracts | рекомендуется как candidate gate, не auto-delete |
| Global exact-clone threshold | Повтор AST формы | 0 turns server-side, но каждый false positive требует ≥1 adjudication turn | не принимать как blocking gate |
| Отдельное model review «упрости» | Семантическое второе мнение | ≥1 auxiliary reviewer turn/session | полезно точечно, не deterministic oracle |

Надёжная формула для следующего ticket: **не “сделай проще”, а “после изменения symbol X не имеет
пути от production roots R; computed dispatch set D перечислен; consumer Y остаётся зелёным; command Z
возвращает 0”.** Для duplication — замораживать exact known seam/hash и поведенческий consumer, а не
вводить repository-wide clone budget.

## Контр-свидетельства и ограничения

1. Explicit arm n=3; contrast ниже собственного шума. Нельзя оценить средний causal effect prompt.
2. 741 production-unreachable line покрыты acceptance tests и в #315 были явно спроектированы как
   manual cutover/recovery seams. Это может быть осознанная deferred capability, а не removable waste.
3. Static graph over-approximates Name/Attribute reachability, но не моделирует произвольный внешний
   Python consumer, reflection in untracked config или framework override. Поэтому verdict ограничен
   tracked production roots frozen snapshot.
4. Exact AST clone equality пропускает переименованные/слегка изменённые copies и ловит необходимую
   state synchronization. Доля 0.0955% — lower bound формы, не доля плохого кода.
5. File growth windows начинаются в разные дни и включают промежуточные main commits вне measured
   merge rows; они показывают фактическое first→last состояние, но не атрибутируют каждую строку агенту.
6. Claim Карпатия из #439 — внешний existence claim о microGPT, а не измерение Orchestra. Наши explicit
   counterexamples опровергают его универсализацию, но не опыт автора на его конкретном корпусе. [S1]

## Affected files, risks, edge cases for a possible Phase 2

- Prompt owner: `.orchestra/pipelines/default/prompts/modules/code-quality.md`.
- Delivery-only test: `tests/test_default_pipeline.py`.
- Existing gates: `app/diff_budget.py`, `app/merge_operations.py`, `app/acceptance.py`,
  `app/workspace.py`.
- Reusable measured pattern: task-specific acceptance under `.orchestra/tasks/<id>/acceptance/` with
  production-root + dynamic-dispatch + surviving-consumer arms.
- Main risk: a global dead/clone gate would block framework callbacks, administrative entrypoints,
  intentional tombstones and multi-store state synchronization. Scope must be named per ticket.
- No prompt/code change is justified before the user chooses whether ambient prose stays advisory or
  future plans must translate it into named structural AC.

## Review decision inputs

- Changed files/consumers: research artifacts under `.orchestra/tasks/455/`; later one new KB topic;
  no production consumer.
- Author metadata: session DB row = `codex`, `gpt-5.6-sol`, `full-cycle`, effort `xhigh`.
- AC: answer all four mandatory method constraints, preserve all legal outcomes, no prompt or
  implementation edit.
- Named checks: `controls.json` has negative/positive/instrument pass; `per-merge.stderr` is empty;
  `noise.json` precedes `comparison.json`; KB contract check runs after KB write.
- Route: causal/statistical prose would prefer Sol, but an auxiliary Sol run is not authorized;
  one fresh Luna falsification pass is used under `codex-debate`.

### Review outcome

Luna timed out after 10 minutes and produced no findings/final verdict. The recovered interim message
mechanically confirmed `741/15225 = 4.867%`, `15/15700 = 0.0955%`, and `39+3=42`, then continued
checking graph premises until termination. Because reviewer agent messages existed, the prose round is
spent; because there was no blocker or dispute, an unchanged retry is not permitted by `codex-debate`.
Artifact: `review-research.md`. **Review verdict: none.**

## Sources

- [M1, tier 1 measurement] `evidence/structural-cohort.json`, `cohort-labels.json`,
  `evidence/per-merge-summary.json` — frozen merge corpus, task labels, AST/clone attribution.
- [M2, tier 1 measurement] `evidence/noise.json`, `evidence/comparison.json` — preregistered
  split-half noise, group rates, file trajectories.
- [M3, tier 1 measurement] `evidence/controls.json` — real/synthetic negative control, positive control,
  three-run determinism and computed-getattr sites.
- [M4, tier 1 measurement + source inspection] `candidate-audit.md`,
  `evidence/current-reachability-summary.json` — corrected graph, incoming edges, complete tracked test
  roots and manual clone reading; discarded full-output hashes are retained separately.
- [M5, tier 1 measurement] `evidence/explicit-cases.json`, Git diffs `9f946a6017`, `b09118919b`,
  `4b862eb6e1`, `7717ef880d` — exact changes and historical runtime/model turns.
- [M6, tier 1 measurement/source] `evidence/acceptance-gate-summary.json`,
  `.orchestra/tasks/332/acceptance/test_t1_delete_orchestrator_dead_code.py` — the one existing
  simplification-specific merge oracle and its `3 passed in 0.27s` receipt.
- [M7, tier 1 falsifying control] `evidence/invalidated-run.json`, `protocol.md` — import-alias false
  positive and full rerun decision.
- [M8, primary source] `evidence/gate-audit.txt`, `app/diff_budget.py`,
  `tests/test_default_pipeline.py` — current merge gates and delivery-only prompt assertion.
- [M9, primary source] `.orchestra/tasks/315/report.md:102-104,225-238` and
  `.orchestra/tasks/315/plan.md` — dormant manual cutover was an explicit designed state.
- [S1, supplied transcript extraction] `.orchestra/tasks/439/claims.md:38` — Karpathy quote used only
  as the hypothesis anchor, not as evidence about Orchestra.
