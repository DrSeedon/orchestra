# #422 — автоматическая работа и бесплатная полоса Harness

Дата среза: 2026-08-30. Фаза: research only. Ничего не запускалось по расписанию,
агенты и background jobs не создавались, живая конфигурация не менялась.

## Вопрос

- **Контекст:** Orchestra умеет хранить фоновые задания, будить существующие сессии и запускать
  собственный OpenRouter Harness, но вся полезная работа сейчас начинается вручную.
- **Change under test:** периодически или событийно вызывать полезную работу, а разведку,
  сортировку и черновики отдавать точным `:free`-маршрутам.
- **Baseline:** один ручной вход создания агента, ноль harness-сессий, ноль полезной
  периодической работы; три активных recurring job — инфраструктурные сторожа [U1].
- **Измеримый исход:** для каждого класса работы известны trigger/read/write/limit/error-cost;
  существующая проводка отделена от отсутствующей; способность free-полосы определяется
  frozen replay по закрытым тикетам, а не мнением о моделях.

## Гипотезы и фальсификаторы

1. **H1:** `bg_jobs` уже достаточно для расписания и пробуждения, но не для автоматического
   создания агента и не для безопасного принятия его изменений.
   - Фальсификатор: в `bg_jobs` нет cron/run/wake, либо cron сам создаёт новую session.
2. **H2:** текущий `self-improvement` работает как реактивный сборщик предложений, но не как
   периодический cross-session улучшатель.
   - Фальсификатор: в модуле есть обход истории/cron, либо большинство предложений остаётся
     без triage и ни одно не попадает в durable rules.
3. **H3:** Harness как runtime проведён до обычного spawn path, а ноль сессий объясняется
   незавершённой операционной активацией, не отсутствием backend-кода.
   - Фальсификатор: runtime/factory/registry отсутствуют, `model=<exact :free>` не проходит
     общий resolver, либо session create обходит HarnessBackend.
4. **H4 (конкурирующая):** бесплатные модели тянут только демонстрационные задачи, поэтому
   долю реальной работы нельзя выводить из наличия tools или одного удачного дня.
   - Фальсификатор: blinded replay на репрезентативной frozen-выборке закрывает AC с тем же
     oracle discipline, что принятая историческая реализация.

## Короткий ответ

1. **Механизм расписания уже есть.** `timer`, `file`, `command`, `ssh`, `run`, `cron` и
   `cron_command` валидируются и сохраняются; `cron` будит существующую session, а
   `cron_command` сначала запускает 30-секундную shell-команду и будит только по regex [S1][S2].
   Автоспавна нет: recurring job адресуется immutable `target_session_id`; единственная точка
   создания агента остаётся `POST /api/sessions` [U1][S1]. **CONFIRMED — primary code.**
2. **Candidate-only граница сейчас принуждается только для canonical KB links.** #417
   запрещает LLM записывать proposed link как current fact без approved receipt [S6]. Но scheduler
   будит агента с его обычными правами, а текущий `self-improvement` прямо разрешает orchestrator
   самостоятельно писать project `CLAUDE.md` [S3]. Поэтому общий безопасный потолок
   «read-only evidence/candidate» — это **вариант будущей capability policy**, а не свойство
   работающей системы. **CONFIRMED — validator + противоречащий ему по другой поверхности
   role-specific prompt.**
3. **`self-improvement` частично работает.** За августовский срез в Orchestra найдено 53
   реальных `user_message` с `📝 RULE:`; после сведения одного refinement и одного relay —
   51 proposal event. Для 34/51 (66.7%) найден post-proposal commit в истории `CLAUDE.md`
   с тем же правилом. После выката trigger-test explicit triage дал 8 TAKE / 9 REJECT /
   2 REPHRASE (ещё 4 сообщения без явного verdict), против старого baseline 42 TAKE / 1 REJECT
   [M1][M2][S3]. Это рабочий reactive capture и заметно менее резиновый фильтр, но не
   автоматический аналитик истории и не доказательство качества принятых правил.
   **CONFIRMED для сдвига verdict mix; UNCERTAIN для качества фильтра — ground truth нет,
   cohorts не joinятся, n=19 verdicts после изменения.**
4. **Отдельный per-task `self-analysis` уже пробовали и сняли.** Восемь retro, 283 строки,
   ноль рабочих чтений; три retro независимо нашли одну проблему, но агрегатора не было,
   поэтому promotion не случился. Skill удалён 25.07 коммитом `cff55c40`; cross-session
   Mechanism B не был реализован [S4]. **CONFIRMED — git history + measured consumers.**
5. **Harness проведён, но live activation сейчас закрыта тремя воротами:** cached catalog
   отсутствует; две статические free-модели имеют `agents=false/dashboard=false`; в environment
   живого сервиса нет `OPENROUTER_API_KEY`/`OPENROUTER_KEY` [M3]. При этом runtime, factory,
   resolver, agent-visibility gate и backend connect существуют [S5]. Значит, ноль сессий —
   не «backend невозможно спавнить», а «маршрут не активирован и без ключа connect упадёт».
   **CONFIRMED — primary code + read-only live state.**
6. **Долю работы free-полосы пока не знает никто.** Старый Ox-день доказывает capability
   (858 tool calls, 0 tool errors), но три отчёта разошлись с артефактами; frozen matrix
   также показала model/provider drift [S7]. Нужен отдельный preregistered replay, описанный
   ниже. **UNCERTAIN — прямого репрезентативного замера нет.**

## Часть A — что реально может запускаться само

### A1. Что уже умеет `app/bg_jobs.py`

| тип | что делает сейчас | persistence / wake | жёсткие границы |
|---|---|---|---|
| `timer` | agent-facing путь один раз ждёт delay и будит target; внутренний `action=wake_subscription_limited` уходит в отдельный runner | хранится в SQLite; после restart восстанавливается только пока row не expired | `delay_seconds` сверху не ограничен; stored lifetime clamp = 8 суток, поэтому timer >8 суток может дожить только без restart [S1] |
| `file` | `tail -F`, regex по строкам | одно совпадение → одно terminal wake | no-expiry допустим; вывод обрезается до последних 3000 символов [S1] |
| `command` | shell-команда каждые ≥5 с, regex по объединённому stdout/stderr | одно совпадение → wake, затем terminal | одна проверка ≤30 с; no-expiry допустим [S1] |
| `ssh` | поток удалённой команды, regex | одно совпадение → wake | BatchMode, connect timeout 10 с; no-expiry допустим [S1] |
| `run` | одна локальная/SSH shell-команда | target будится на exit 0, nonzero exit, timeout и validation failure; generic exception только ставит `failed` без wake | ≤24 ч; после service restart **не возобновляется**, помечается interrupted и target уведомляется [S1] |
| `cron` | 5-field UTC cron, на каждом fire отправляет сообщение target session | recurring, SQLite; missed fires во время downtime пропускаются | no-expiry допустим; это wake, не spawn [S1][S2] |
| `cron_command` | на cron запускает shell-команду, будит только если regex совпал | recurring; fire count/last fired сохраняются | команда ≤30 с; non-match не будит; no backfill [S1][S2] |

Общие ограничения: `create()` делает неатомарный admission check `active < 50`; это не hard cap —
конкурентные create могут пройти одновременно, а внутренний `replace_key` обходит check. Job хранит immutable
`target_session_id` и отказывается будить нового владельца старого имени; обычный MCP `bg_create`
не выставляет внутренний `replace_key`, поэтому дедупликацию recurring jobs нельзя считать
гарантированной на agent-facing API [S1][S2]. Scheduler доставляет сообщение обычному агенту
с его обычными правами — он не превращает небезопасную запись в безопасную.

### A2. Инвентаризация классов полезной автоматической работы

В таблице перечислены **варианты**, не решения о внедрении. «Пишет» означает предлагаемый
безопасный потолок конкретного класса, а не текущий enforcement: обычный разбуженный orchestrator
сегодня технически способен записать больше. Capability/role для auto-work пришлось бы ограничить
отдельно и обсудить с пользователем.

| класс работы | trigger (что запускает) | кто исполняет | что читает | что пишет | чем ограничен | цена ошибки |
|---|---|---|---|---|---|---|
| Самоулучшение: rule/skill candidates из истории | weekly cron **или** ≥N новых task reports/retros после watermark | существующий harness-agent, разбуженный `cron`; extractor до него может быть deterministic | новые logs, task reports, reviews, tests, текущие prompts/skills/rules | candidate report с evidence и предлагаемым diff; не canonical | только события после watermark; 1–3 candidates/run; trigger-test, dedup, counterexample; human promotion | ложное общее правило меняет весь fleet; prompt bloat; skill без consumer превращается в ритуал |
| Разбор bug reports | новый record (event/poll) или hourly `cron_command` по счётчику inbox | deterministic detector → harness/обычный orchestrator для смыслового triage | private bug record, названные code/log locations | triage table / draft task; исходный record не удаляет | никакой auto-close/delete; exact exception/repro/evidence; dedupe по record id | потеря реального инцидента, ложная срочность, раскрытие приватного record |
| Разбор мёртвых задач | weekly cron; age threshold — только сигнал | harness analyst | canonical task state, session status, last activity, linked commits/artifacts | candidate list: keep/clarify/cancel с доказательством | без `task_update`; «нет live worker» + «нет fresh artifact» оба обязательны; пользователь решает | автоотмена живой работы, потеря контекста, вмешательство в приоритеты пользователя |
| Сверка документации с кодом | nightly cron или post-merge event (такого hook сейчас нет) | `cron_command` для anchors; agent только на mismatch | docs commands/paths/symbols и production code/config | drift report / candidate patch | commands read-only; exact owners; prompt/docs edits proposal-only | неверная документация может сломать всех агентов; auto-fix закрепит ложный owner |
| Дежурная проверка красных тестов | scheduled low-load window; cron будит session, которая запускает one-shot `run` | deterministic test runner; agent классифицирует только сохранённый log | pinned commit, named suite, env manifest | immutable log + failure set; код не чинит | isolated DB/credentials, no live probes, per-test timeout, no `-x`, base/branch symmetry | тест загрязняет prod, тратит внешнюю квоту, греет машину, flaky red создаёт ложную работу |
| Сборка digest | daily/weekly cron | deterministic selectors + free model summarizer | git since watermark, task transitions, bug/task queues, failed jobs | dated digest candidate | ссылки на каждый пункт; отдельные «новое / без изменения / требует решения»; max items | важное выпадет из summary или шум будет выдан за приоритет |
| KB freshness / rejected-road audit | weekly `cron_command` на validator + agent только при debt | repository script, затем harness | `docs/kb`, linked task evidence, current symbols | validation report / candidate recheck | canonical fact/link не мутируется; withdrawn history не удаляется | ложное «устарело» перепишет current truth; тихий duplicate owner |
| Backlog sorting и task enrichment | event после **явно одобренного** intake либо daily draft pass | free model | новые tasks, user-stated priorities, existing owners | labels/summary/AC draft в candidate artifact | не меняет status/priority/assignee, не спавнит; нет standing approval | агент сам создаёт пользователю работу и сжигает очередь на лишнее |
| Разведка / черновик для уже одобренной задачи | task approval event; такого event→agent hook сейчас нет | harness worker | task text, repo, разрешённые public sources | task-local research draft / source table | approved task id; read-only tools; facts require opened source; final verdict у paid/human lane | уверенный, но нерелевантный research; poisoned retrieval; утечка private context внешней модели |
| Dependency/security watch | weekly catalog/advisory poll | deterministic scanner → agent summarizer | lockfiles, official advisories | candidate incident/task | no auto-upgrade, no secret upload, primary sources only | supply-chain regression или ложная security тревога |
| Инфраструктурные сторожа | timer/file/command/ssh/cron по наблюдаемому симптому | deterministic job; существующий agent только получает alert | health/status/output | alert + last output | это единственный реально используемый recurring class: 3 active, все infrastructure [U1] | missed wake либо alert storm; полезную продуктовую работу не выполняет |

### A3. Общая граница безопасности

Существующий scheduler уже годится для **detect → wake** и короткого
**check → match → wake**. Для полной цепи **schedule → fresh agent → canonical write → accept**
не хватает не одного «cron-флага», а четырёх отдельных owners:

1. lifecycle fresh/persistent agent (сейчас job только будит существующий `session_id`);
2. task/user approval boundary (новая задача сама по себе не разрешение работать);
3. candidate→approval→canonical receipt для shared rules/knowledge;
4. independent acceptance и rollback rehearsal, причём rollback не стирает уже случившиеся
   решения других агентов.

Из этих четырёх только link receipt #417 принуждается validator-ом. Общего read-only режима для
cron-awakened agent нет; без отдельного limited role/tool allowlist scheduler является транспортом,
не safety boundary.

## Часть B — самоулучшение

### B1. Что текущий модуль делает и чего не делает

`self-improvement.md` реагирует на явную коррекцию, требует один `📝 RULE`, запускает
trigger-test, выбирает personal/project/global target и требует `RULE TRIAGE` [S3]. Он:

- **работает как capture:** предложения реально возникают и часть попадает в Git;
- **работает как более строгий filter после #147:** post-change REJECT+REPHRASE = 11/19
  explicit verdicts, тогда как старый baseline отклонял 1/43;
- **не смотрит историю:** нет watermark, aggregation, recurrence, skill detection или cron;
- **не измеряет outcome правила:** попадание строки в `CLAUDE.md` не доказывает снижение
  повторных ошибок;
- **не является безопасностью сам по себе:** orchestrator всё равно может ошибочно TAKE,
  а prompt не блокирует canonical write кодом.

#### Повторённый месячный замер

Окно: `2026-08-01T00:00:00Z` — `2026-08-30T11:50:34Z`, scope строго
`/mnt/data/Projects/Python/orchestra`.

- SQL corpus: `logs.type='user_message' AND instr(content,'📝 RULE:')>0` → **53 rows**.
- Manual normalization: `401045/401315` — одно предложение + refinement;
  `406590/407497` — proposal + relay в summary → **51 proposal events**.
- Frozen полный ledger всех 51 groups, включая 17 `NONE`, лежит в
  `docs/tasks/422/rule-audit.tsv`; это owner результата normalization, а не сокращённый список
  только удачных promotions [M4].
- Git audit: для **34/51** найден более поздний `main:CLAUDE.md` commit с тем же trigger/action;
  17 не имеют traceable CLAUDE promotion. Это консервативный semantic match: merged/paraphrased
  правила засчитывались только при узнаваемом trigger и action, простое совпадение слов — нет.
- Trace ledger (log id → commit):
  `373872→fd050bfc`, `383141→958ec363`, `383436→d74f0005`,
  `387961→33776de9`, `391836→fef05578`, `392081→49ccc8f7`,
  `393952→2167e166`, `396315→c934150e`, `399471+400068→6d312339`,
  `401045/401315→e146bf57`, `403044→d6453d09`,
  `403391+403464→d296b853`, `403808→e9492aec`, `406686→252da4ad`,
  `407314→0cb7fe01`, `409090→52e71500`, `409537→994aae1c`,
  `410987+412184+412315→4549d041`, `420007+420144→534478ae`,
  `422445+422475→402bf88e`, `423576→c3407372`, `424843→b58cbe6c`,
  `456888→e95b0b8f`, `457378→7238df7d`, `511458→9a656413`,
  `539784→30a36cc3`, `540032→f556a51a`, `540774→6da6822d` [M1][M2].
- Все explicit triage за месяц: **29 TAKE / 9 REJECT / 2 REPHRASE / 7 OTHER**.
  После commit `dee33644` (trigger-test, 04.08 08:26 UTC):
  **8 TAKE / 9 REJECT / 2 REPHRASE / 4 OTHER** [M1].

Proposal и triage cohorts **не соединяются по stable proposal id**: 51 — нормализованные RULE
events, 47 — сообщения с `RULE TRIAGE`, post-change 23 = 19 explicit verdicts + 4 OTHER.
Поэтому эти числа измеряют отдельно capture/promotion throughput и verdict mix; полнота
«каждое предложение получило triage» остаётся неизвестной, а не выводится вычитанием.

Интерпретация: модуль **не пустой** — capture→Git канал существует. Но 34 promotions —
throughput, не precision; без backtest «правило снизило повтор» нельзя назвать их 34 улучшениями.
Снижение TAKE-rate после #147 согласуется с тем, что trigger-test фильтрует, но маленький и
нерандомизированный post-period не доказывает причинность или рост correctness. Distribution
shift **CONFIRMED**, filter quality **UNCERTAIN**.

### B2. Уже отвергнутый вариант: per-task retro без потребителя

В июле `self-analysis` делал signal-anchored retro перед DONE. Аудит нашёл 8 файлов / 283 строки /
0 рабочих чтений; три retro независимо предложили ограничивать Codex-review, но каждый видел
только одну задачу и оставил предложение `logged, not promoted`. Реально дошедшее в тот день
правило пришло из живой коррекции через `self-improvement`, а retro повторило его постфактум.
25.07 skill и обязательный `retro.md`-step удалены [S4].

Это не опровергает cross-session pattern pass. Оно опровергает более дешёвую формулу
«писать ещё один retro после каждой задачи — значит самообучаться».

### B3. Как history-agent отличает правило, skill и шум

Ниже candidate pipeline, а не утверждённая архитектура.

1. **Инкрементальный вход:** только события после durable watermark; whole-history scan нужен
   для первого bootstrap и редких re-audit, иначе цена растёт с каждой неделей.
2. **Таблица сигналов, не свободная рефлексия:**
   `event/task/scope → correction|failed oracle|retry≥3|review blocker|report↔artifact mismatch →
   observed cost → exact evidence`.
3. **Root cause отдельно от remedy:** одна и та же symptom может иметь разные причины; кандидат
   без end-to-end trace остаётся `UNCERTAIN`.
4. **Дедуп с current owners:** literal anchors по `CLAUDE.md`, prompts, skills, `docs/kb`; наличие
   похожего owner переводит candidate в `duplicate/extend`, а не создаёт вторую копию.
5. **Развилка типа:**
   - **rule candidate** — один устойчивый `When X → do Y`, который меняет workflow и проходит
     trigger-test хотя бы на одном контрпроекте;
   - **skill candidate** — повторяющийся многошаговый workflow с ≥3 шага/ресурса/шаблона,
     который без skill каждый раз требует заново собирать процедуру; должен быть назван consumer
     и delivery check;
   - **tool candidate** — только когда эквивалент без tool действительно длинный/кодовый;
     короткий `rg`/read не оправдывает новый interface;
   - **task/domain finding** — остаётся в task/KB, не маскируется под правило.
6. **Falsification card:** проект, где trigger невозможен; валидная альтернатива; риск слишком
   широкого применения; evidence count; что измерит пользу после promotion.
7. **Выход:** candidate + предлагаемая цель + exact diff + rollback/revert command; promotion
   выполняет другой gate/человек.

Порог recurrence — отдельная ценовая ручка. Текущий модуль разрешает один яркий измеренный случай;
старый cross-session дизайн предлагал ≥3 повторения. Первый быстрее ловит дорогие аварии, второй
снижает overfit, но пропускает редкие тяжёлые случаи. Это развилка, не установленная истина.

### B4. Конфликт #417: кто имеет право писать

Current contract однозначен для canonical links: LLM пишет `candidate-link` только в task artifact;
canonical `связи:` требует approved plan/ticket receipt, exact source fact key, relation и target.
Validator отклоняет candidate в `docs/kb` [S6]. По тому же blast-radius принципу history-agent
может автоматически писать **наблюдение и кандидат**, но не объявлять shared rule/fact текущей истиной.

Фактические LLM rounds, wall time и байты для трёх вариантов **не измерены**. Сравнимые
structural lower bounds ниже не выдаются за стоимость в деньгах.

| вариант | durable writes до решения | обязательные решения/ходы | rollback exposure | выигрыш и неизмеренная цена | совместимость с #417 и current policy |
|---|---:|---|---|---|---|
| Отдельный candidate-файл | 1 candidate artifact | ≥1 human triage; model rounds unmeasured | canonical consumers не видят candidate | минимальный blast radius; backlog size, triage minutes и storage bytes unmeasured | совместим с #417; для общего auto-work нужен limited role, которого сейчас нет |
| Пишет patch/ветку и требует approval | candidate + worktree/patch | ≥1 review/approval, затем merge; rebase может добавить ход | consumers не видят patch до merge, но stale branch/merge debt остаются | exact diff ускоряет review; worktree bytes, model rounds, wall time и approval minutes unmeasured | совместим, если receipt предшествует canonical merge; project `CLAUDE.md` current orchestrator policy и так разрешает self-write, поэтому этот gate надо вводить явно |
| Пишет сразу с автооткатом | canonical edit + evaluator/receipt | минимум apply + evaluate; при reject ещё rollback | exposure window >0; rollback не отменяет downstream turns/решения | fastest feedback; максимальный fleet radius, spent turns и recovery time unmeasured | несовместим для canonical links; для prompts/rules потребует отдельного решения пользователя и isolated experimental consumer |

### B5. Что оставлено задаче #421

`docs/tasks/421/` не читался. Сравнение Prime `/refine` и Hermes curator не повторялось.
Когда #421 завершится, сюда можно присоединить только его проверенные mechanism/cost rows;
ни один вывод #422 от них не зависит.

## Часть C — Harness как рабочая полоса

### C1. Проводка и нынешний blocker

Полный кодовый путь существует:

`spawn_worker(model)` → `POST /api/sessions` → `manager.create_session` →
`resolve_model` + `ensure_spawn_allowed` → `backend_for_model` → `AgentSession._make_backend` →
registered runtime `harness` → `_harness_factory` → `HarnessBackend.connect` → `AgentLoop` [S5].

Что уже есть:

- builtin runtime `harness` зарегистрирован с per-turn stream, steering, reconnect и model retarget [S5];
- cached catalog регистрирует каждый exact `:free` text→text route с tools [S5];
- `validate_harness_model_spec` и последний guard перед POST блокируют unsuffixed/paid routes [S5];
- normal session lifecycle создаёт worktree/task/prompt так же, как для других workers [S5];
- subscription quota gate возвращает Harness `not_applicable`, то есть Claude/Codex pool не расходуется [S5].

Чего не хватает в живом контуре на 30.08:

1. `kv.model_catalog_cache` отсутствует;
2. обе static fallbacks выключены: `agents=false`, `dashboard=false`;
3. в environment MainPID сервиса нет OpenRouter key;
4. live canary и replay качества не проводились [M3].

Поэтому сейчас `model='z-ai/glm-5.2:free'` резолвится, но agent spawn остановится на
visibility gate; если включить флаг без ключа, `HarnessBackend.connect()` упадёт до первого хода.
Это **операционные blockers**, а не missing runtime implementation.

### C2. Живые `:free` routes 30.08.2026

Официальный `GET https://openrouter.ai/api/v1/models` вернул **18 exact `:free` IDs**;
17 соответствуют текущему Harness predicate (text input + text output + `tools`).
`nvidia/nemotron-3.5-content-safety:free` не рекламирует tools и потому не eligible [W1][S5].

Eligible:

1. `inclusionai/ling-3.0-flash-fin:free`
2. `dots-studio/dots-3-note-preview:free`
3. `liquid/lfm-2.5-2.6b:free`
4. `nvidia/nemotron-3.5-lightning:free`
5. `thinkingmachines/inkling-small:free`
6. `poolside/laguna-s-2.1:free`
7. `thinkingmachines/inkling:free`
8. `poolside/laguna-xs-2.1:free`
9. `cohere/north-mini-code:free`
10. `z-ai/glm-5.2:free`
11. `nvidia/nemotron-3-ultra-550b-a55b:free`
12. `minimax/minimax-m3:free`
13. `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
14. `google/gemma-4-26b-a4b-it:free`
15. `google/gemma-4-31b-it:free`
16. `minimax/minimax-m2.7:free`
17. `nvidia/nemotron-3-super-120b-a12b:free`

Exact free, но не Harness-eligible: `nvidia/nemotron-3.5-content-safety:free` (tools=false).

Каталог изменчив: список должен замораживаться в evidence непосредственно перед будущим replay.
OpenRouter docs подтверждают account-global free limits и различие platform vs upstream 429;
существующая KB фиксирует для оплаченного tier 20/min и 1000/day [W2][S7].

### C3. Протокол замера доли работы — отдельная задача после approval

#### Population и выборка

- Scope: только project `/mnt/data/Projects/Python/orchestra`; последние 60 дней закрытых задач.
- Включение: существует **до-implementation frozen oracle commit** или delivery check + exact AC;
  известен принятый implementation commit и его зелёный output.
- Исключение: solution commit физически достижим из стартового clone; внешняя запись нужна для AC;
  oracle зависит от живой subscription/quota/production DB.
- **N=30 tickets**, по 6 из пяти mutually exclusive strata. Классификатор применяется сверху
  вниз, первое совпадение побеждает:
  1. shared-runtime/auth/persistence/destructive/high-risk boundary;
  2. research, если принятым deliverable была Phase-1 truth/rubric, а не code behavior;
  3. docs/drift/delivery, если consumer читает текст и production behavior не менялось;
  4. closed leaf code fix для оставшегося behavioral code;
  5. extraction/sorting/digest для оставшихся read-only transformations.
- Внутри strata — deterministic random sample с опубликованным seed. Реальную долю работы считать
  не простым средним, а stratum success × доля strata во всей eligible population.

N=30 — screening, не точная оценка: шесть наблюдений на stratum дают широкие интервалы.
Он не оценивает весь каталог и не обещает отвергнуть произвольную малую долю успеха; он проверяет
заранее заданный production-candidate roster по decision rule ниже.

#### Arms и бюджет

1. **До первого model response** exact route roster замораживается механически: из текущих
   text+tools candidates исключаются routes, не прошедшие transport-only canary; survivors
   ранжируются `sha256("422-route-roster:" + route_id)`, первые три образуют roster. Canary
   не содержит benchmark task и не позволяет выбирать по качеству ответа.
2. Перед full run — pilot 3 tickets × frozen 3 routes; первым идёт route с худшим прежним
   external evidence, а если его нет — первый hash-ranked route. Pilot проверяет measurement path,
   не меняет roster, strata, thresholds или AC.
3. Каждый из 30 tickets получает **две** free-route attempts по balanced random rotation;
   один route не определяет судьбу всей полосы.
4. Budget считается в **HTTP attempts**, не logical rounds. Current client может сделать до
   трёх attempts/round [S8], поэтому его retry policy для eval должен быть `0`; иначе global
   counter останавливает matrix до следующего request и outcome становится `budget_incomplete`.
   Max full run = `30 × 2 × 12 = 720 attempts`; pilot cap снижен до
   `3 × 3 × 8 = 72`; всего 792. Два false-premise cases входят в шесть tickets high-risk
   stratum и уже учтены двумя route attempts; oracle/leakage/no-op/isolation controller controls
   model calls не требуют. Hard stop = 900 attempts.
5. До freeze живой `GET /api/v1/key` обязан подтвердить tier/лимит используемого key.
   Если daily cap <900, cap/routes/sample меняются **до** первого response; после старта не меняются.
   Provider-429 — availability outcome, не capability failure; eval retries disabled.

#### Blindness

- Каждый run начинается из внешнего `git clone --no-local` на RED commit; remotes и credential
  helpers удаляются до старта, tool subprocess network deny проверяется positive/negative probe.
- Controller, который общается с OpenRouter, живёт вне tool sandbox. Tool environment не содержит
  `INTERNAL_TOKEN`, OpenRouter key, `.env`, user config или production service env; MCP servers = `{}`.
  Allowlist: repo-local read/grep/glob/write/edit/bash; bash запускается под disposable uid/cgroup,
  без network и вне production mounts. SQLite/app tests получают отдельный temp DB path; отсутствие
  изоляции = preflight failure до model call.
- До и после run `git cat-file -e <solution_sha>` обязан вернуть non-zero; post-run audit также
  проверяет отсутствие remotes, новых alternates и solution object/reachability.
- Agent получает original task text, immutable Test/AC и named files — не report, solution diff,
  reviewer finding после реализации или commit message решения. Output проходит secret-shape
  redaction scan до экспорта из sandbox.
- Oracle paths после run побайтно сравниваются с RED commit.

#### Success

Ticket success только если одновременно:

1. exact named command green;
2. каждый AC имеет artifact/command evidence;
3. oracle/test/config/fixtures не изменены и не ослаблены;
4. diff в scope, clean commit существует;
5. prose-output проходит blind rubric двумя независимыми graders либо deterministic delivery check;
6. isolation receipts зелёные; failed run физически не мог достать production/external side effect,
   а не просто заявил, что его не было.

Дополнительные метрики: request rounds, tool calls, wall time, context bytes, upstream/platform 429,
WIP/STOP, manual acceptance minutes, report↔artifact mismatch. «Почти сделал» отдельно от success.

Lane capacity можно посчитать двумя способами, оба надо показать:

- **single-route success:** среднее качество конкретного route;
- **best-of-two lane success:** ticket закрыт хотя бы одним из двух независимо назначенных routes,
  с учётом удвоенного request budget.

Main estimand = direct-standardized **best-of-two success этого frozen three-route roster** по
историческим весам пяти strata. Это не оценка всех 17 routes. Для каждой stratum показывается
Wilson 90% interval; total interval — stratified bootstrap с frozen seed.

Decision rule, frozen до ответов:

- `promising`: weighted best-of-two ≥50%, lower 90% bound ≥35%, safety failures = 0;
- `not broad-lane ready`: weighted best-of-two ≤20% **или** safety failures ≥1;
- иначе `inconclusive` и никакой deployment verdict из N=30 не делается.

#### Controls

1. **Oracle positive:** принятый historical implementation commit обязан быть green.
2. **Oracle negative:** исходный RED commit без изменений обязан падать на missing behavior, не на import/collection.
3. **Leakage negative:** solution SHA недостижим; нарушение исключает run целиком.
4. **False-premise control:** 2 из 6 tickets high-risk stratum содержат проверяемо
   ложную/невыполнимую предпосылку и уже входят в N=30/matrix budget;
   корректный outcome — `WIP/STOP` с доказательством. Сочинённый patch считается safety failure,
   даже если он что-то коммитит.
5. **No-op grader control:** пустая ветка не может получить success; иначе rubric/oracle дырявы.
6. **Isolation controls:** tool-side `curl`/DNS к публичному адресу и чтение production DB/key
   обязаны fail; repo-local read/write и controller→OpenRouter обязаны succeed. Одинаковый отказ
   в обоих плечах означает сломанный sandbox, не безопасность.

Pass/fail, strata, routes, seed и request cap замораживаются **до** первого model response.

## Counter-evidence и ограничения

- 34/51 promotions не означают 34 полезных улучшения; outcome повторных ошибок не измерялся.
- Post-trigger triage n=19, задачи и orchestrators менялись вместе с prompt, причинность не изолирована.
- Старый self-analysis failure может быть failure of consumer wiring, а не reflection quality: сами retro
  были содержательными. Поэтому отвергнут per-task file-as-endpoint, не cross-session aggregator [S4].
- Ox evidence доказывает, что Harness способен работать, но endpoint/model drift за сутки менял результат
  от 858 tool calls до 6 пустых ответов; сегодняшний route name не является вечной capability [S7].
- Live key absence измерена по environment текущего MainPID; добавление key/flags/catalog — отдельное
  изменение конфигурации, в этой фазе не выполнялось.
- Replay budget 792/900 предполагает eval-specific retry=0; текущий production client до трёх
  attempts/round и без изменения превысил бы лимит. Изменение eval harness — часть отдельной задачи,
  не скрытая возможность текущего запуска.
- #421 может принести prior art по `/refine`/curator; его отсутствие не закрывает внутренние факты #422.

## Review outcome

- Route: Luna (`gpt-5.6-luna`), 2/2 allowed prose rounds.
- Round 1: two blocking findings — overclaimed candidate-only boundary and unsafe replay isolation;
  both verified against code/prompts and fixed. Wrapper falsely labeled the completed review blind;
  full output was recovered into `docs/tasks/422/review-research-luna.md`.
- Round 2 verdict: **“Correct, no blocking findings.”** It explicitly marked scheduler semantics,
  ledger, branch pricing, retry budget, blindness and estimand/thresholds **FIXED**.
- Five remaining non-blocking calibration suggestions were applied after Round 2; a third review is
  forbidden by the prose ceiling. No reviewer finding remains silently ignored.

## Confidence по несущим выводам

| вывод | confidence | причина / tier |
|---|---|---|
| `bg_jobs` умеет recurring cron и wake, но не spawn | **CONFIRMED** | Tier 2 primary code + user-measured single spawn seam |
| candidate-only потолок | **CONFIRMED** только для canonical links; **REFUTED** как current общий rule | project `CLAUDE.md` self-write разрешён orchestrator prompt; cron сохраняет обычные права |
| self-improvement работает частично | **CONFIRMED** capture/promotion и verdict-mix shift; **UNCERTAIN** filter quality | direct DB/git measurement; no joined ground truth, post-change n=19 |
| per-task retro alone уже отвергнут | **CONFIRMED** | git deletion + 8/283/0 consumer audit |
| Harness backend технически проведён | **CONFIRMED** | runtime/factory/manager/backend primary code |
| live harness сейчас не может сделать первый ход | **CONFIRMED** | flags disabled + key absent; spawn/connect gates primary code |
| доля реальной работы free-моделей | **UNCERTAIN** | representative blinded replay ещё не проводился |

## Affected files, риски и края будущей работы

Research не меняет production. Если пользователь выберет архитектуру, затронуты могут быть:

- `app/bg_jobs.py`, `app/routes/bg.py`, `app/mcp_stdio.py` — scheduler/event/receipt surface;
- `app/model_catalog.py`, `app/models.py`, `app/runtime_registry.py`, `app/backend_harness.py` —
  Harness activation/admission;
- `pipelines/default/prompts/modules/self-improvement.md` или новый on-demand skill — только после
  live mechanism proof и обсуждения архитектуры;
- task/candidate storage — owner должен быть выбран до записи, чтобы не создать второй truth.

Края: timezone и skipped cron fires; target session killed/renamed; duplicate schedules; prompt/context
bloat; private logs в external model input; false task closure; production-test side effects; provider 429;
model disappearance; candidate backlog без consumer; rollback после уже совершённого downstream action.

## Источники и измерения

- **[U1] Tier 1, supplied measurement:** вход пользователя #422 — single spawn seam; turn/session/job totals;
  harness=0; три active recurring infrastructure jobs.
- **[S1] Tier 2, primary code:** `app/bg_jobs.py:34-40,73-140,356-455,488-529,564-607,717-825,920-1025`.
- **[S2] Tier 2, primary code:** `app/mcp_stdio.py:2858-2914` — agent-facing job types, UTC/no-backfill/no-expiry contract.
- **[S3] Tier 2, primary prompt:** `pipelines/default/prompts/modules/self-improvement.md:4-63`.
- **[S4] Tier 1+2 internal measurement/history:** `docs/tasks/fullcycle-audit/research.md:115-153,382-406`;
  deletion commit `cff55c40`; former `self-analysis` skill read via `git show cff55c40^:...`.
- **[S5] Tier 2, primary code:** `app/models.py:124-153,368-488`; `app/model_catalog.py:45-76,119-218`;
  `app/runtime_registry.py:317-389`; `app/manager.py:644-675,780-910`; `app/session.py:822-869`;
  `app/backend_harness.py:160-215`; `app/harness/llm.py:164-184`; `app/quota_gate.py:278-299,410-455`.
- **[S6] Tier 2, executable contract:** `pipelines/default/prompts/modules/research-method.md:145-169`;
  `scripts/check_kb_contract.py:148-169,341-343`; `docs/tasks/417/plan.md:107-113`.
- **[S7] Tier 1 internal measurements:** `docs/kb/openrouter-quotas.md`,
  `docs/kb/ox-alpha-harness-verdict.md`, `docs/kb/harness-tools.md`.
- **[S8] Tier 2, primary code:** `app/harness/llm.py:206-254` — до трёх provider attempts на logical request.
- **[M1] Tier 1, live read-only SQLite:** `data/orchestra.db` query on 2026-08-30, window/scope above;
  raw RULE rows 53; normalized proposals 51; post-#147 triage 8/9/2/4.
- **[M2] Tier 1, Git audit:** `git log main --since 2026-08-01 --until 2026-08-31 -p -- CLAUDE.md`
  plus per-proposal trigger/action match; 34 traceable promotions, ledger included in §B1.
- **[M4] Tier 1, frozen normalization artifact:** `docs/tasks/422/rule-audit.tsv` — все 51 groups,
  source log ids, literal anchor и promotion commit/`NONE`; `sha256=c5852c198f1bafa20c0bf20f3946d4cfb80389396d7241021c24cd3016fb7689`,
  mechanical count `groups=51 promoted=34 none=17`.
- **[M3] Tier 1, live read-only state:** `kv.model_catalog_cache` absent; `kv.model_flags` has both
  static routes false/false; `/proc/<MainPID>/environ` contains neither OpenRouter key name.
- **[W1] Tier 2, primary live API opened 2026-08-30:** https://openrouter.ai/api/v1/models —
  frozen normalized response `docs/tasks/422/openrouter-free-catalog.tsv`, retrieved
  `2026-08-30T12:28:29Z`, SHA-256 `d2f8132fa8b62bf70b108041f97da48cbd65f1886feeed0376fd3914095f766e`;
  18 exact free rows, 17 with text I/O + tools.
- **[W2] Tier 2, primary docs opened 2026-08-30:** https://openrouter.ai/docs/api_reference/limits —
  account-global free rate limits and platform/upstream 429 distinction.
- **[R1] Reviewer artifact:** `docs/tasks/422/review-research-luna.md` — two Luna rounds,
  final verdict `Correct, no blocking findings`, plus wrapper recovery note.
