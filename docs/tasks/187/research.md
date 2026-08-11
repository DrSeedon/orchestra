# #187 — Квота-осознанная маршрутизация рантаймов

**Сейчас разрыв прямой: статический блок `<model-routing>` требует от агента защищать исчерпывающийся недельный пул, но ни `GET /api/usage`, ни `usage_snapshots`, ни свежий `current_quota_observation` в его prompt в момент выбора не попадают; при этом `spawn_worker` требует, чтобы сам агент уже назвал конкретную модель. Закрыть разрыв нужно одним механизмом: серверным quota-router, который на каждом безопасном старте нового хода получает проверяемый класс работы, сам читает свежую телеметрию и атомарно выбирает рантайм. Модель не должна выбирать модель, а prompt/tool/message-инъекции квоты для маршрутизации не нужны.** [S1–S9][M1]

## Вопрос

- **Контекст:** Orchestra запускает persistent orchestrators, workers и cross-review на Claude/Codex; недельные подписочные пулы конечны и имеют разные окна/сбросы.
- **Изменение под проверкой:** перенести выбор рантайма из ручного решения оркестратора в один детерминированный серверный механизм по актуальной квоте, классу работы и provenance предыдущей фазы.
- **Baseline:** агент выбирает точный model id по статическому prompt; сервер затем только разрешает либо запрещает выбранный weekly bucket.
- **Измеримый исход:** одинаковые `(task class, author/implementation runtime, fresh quota observation)` всегда дают один и тот же model decision; обычная работа сжигает Codex до явной normal/reserve границы, резерв открывается только по проверяемому признаку; исчерпание пула не теряет входное сообщение или worktree и не вызывает тихого ожидания.

## Гипотезы и фальсификаторы

1. **H1:** агенту велено учитывать квоты, но актуальная телеметрия не доставляется в момент выбора, поэтому инструкция не может работать детерминированно. **Фальсификатор:** каждый путь выбора модели уже автоматически получает свежие `usage_snapshots`/`GET /api/usage` либо сервер уже сам выбирает модель по этим данным.
2. **H2:** один серверный маршрутизатор по структурированному классу задачи лучше prompt-инъекции или quota-tool, потому что устраняет устаревание и модельное решение. **Фальсификатор:** сервер не имеет достаточного сигнала для выбора либо task class невозможно выразить проверяемым полем.
3. **H3:** Codex имеет стабильное календарное недельное окно, поэтому router может заранее планировать расход по одному `resets_at`. **Фальсификатор:** utilization реально падает до нуля вне календарной границы либо `resets_at` переносится без календарного правила.
4. **H4:** доказанный специальный случай для Claude — независимость постановки/ревью от runtime реализации, а не общее превосходство Opus над Sol. **Фальсификатор:** исторические замеры показывают устойчивое превосходство Claude на конкретном проверяемом классе либо не подтверждают вред однорантаймовой петли.
5. **H5:** текущий runtime handoff достаточен для бесшовного автоматического failover. **Фальсификатор:** production-алгоритм или живой замер показывает потерю существенной части semantic/tool history либо переключение невозможно в активном ходе.

## Метод и заранее зафиксированные критерии

### Трассировка кода

Проверены не только строки prompt, но полный путь `GET /api/usage` → normalization/cache → `usage_snapshots` → dashboard/admission/wake → prompt assembly → `spawn_worker`/new-turn start/model change. Отдельно проверены fallback и bypass: orchestrator, running steering, pending flush, Codex review, terminal limit и cross-runtime handoff. [S1–S10][M1]

### Измерение окон Codex

- Источник — консистентная копия живой SQLite, снятая только через `sqlite3.Connection.backup`; production DB не менялась. [M2]
- Для `codex.primary` и `codex_spark.primary`: число наблюдений, `window_minutes`, диапазон, уникальные `resets_at`, переходы utilization вниз и расхождение одновременных состояний.
- Тезис «недельный лимит сбрасывается каждый день» считается подтверждённым только при ≥2 фактических падениях utilization к нулю в разные **последовательные** календарные дни. Смена одного прогнозного `resets_at` без падения utilization не считается сбросом.
- Spark считается отдельным бакетом, если он одновременно присутствует с primary и хотя бы в одном снимке расход/reset отличаются.
- Для признака emergency посчитано фактическое использование текущего `tm_tasks.priority=0`: часто используемый признак не может защищать редкий резерв. [M4]

## Findings

### F1. Телеметрия существует, но до решения агента не доезжает

`GET /api/usage` получает и нормализует Claude, Codex и отдельный Spark; `current_quota_observation()` отдаёт provider windows с per-provider `observed_at`, при необходимости обновляя нужное семейство под lock и timeout. Фоновый сборщик раз в 300 секунд пишет нормализованный `provider_usage` в `usage_snapshots`; dashboard и analytics читают API/history. Это полноценный серверный источник текущего состояния и истории. [S6][S7]

Но `build_system_prompt()` собирает только статические pipeline layers/modules. `ROLE_SYSTEM_PROMPT()` добавляет статические rules, role catalog, workers и перечень доступных моделей; `available_models_block()` содержит id/runtime/context, не utilization. Поиск всех вызовов `current_quota_observation`/`current_provider_usage` нашёл quota gate, wake/readiness и UI, но не prompt builder/manager model selection. [S1–S4][M1]

`spawn_worker` отклоняет пустой `model` дословно: `model is required; choose it by the <model-routing> block in your prompt`, после чего manager создаёт ровно указанную модель. История Git подтверждает, что `cf47269` добавил quota-runway **в prompt**, а `18cdd87` отдельно сделал model обязательным; серверного selector вместе с ними не появилось. [S5][S20][M1]

Текущий #168 gate решает другую задачу: для уже выбранной модели он разрешает weekly `<95%`, блокирует `>=95%`, а missing/malformed/stale telemetry трактует как unknown/fail-closed. Он перечисляет доступные alternatives, но не выбирает и не переключает на них. `AgentSession.send()` применяет gate только к idle/waiting non-orchestrator worker; running steering и все orchestrators обходят его. Spawn preflight также проверяет уже выбранный model. [S8][S9][S12][S19]

**Вывод: H1 CONFIRMED — tier 2 полный code trace + git history.** Вероятный корень из постановки подтверждён: инструкция знает, **что** учитывать, но агент не знает текущие числа, а сервер не принимает решение за него.

### F2. Один owner решения — серверный router, не четыре способа сообщить квоту модели

| Вариант | Актуальность | Цена/контекст | Кто в итоге выбирает | Вердикт |
|---|---|---|---|---|
| Инъекция при spawn | Верна только в момент spawn; persistent session живёт дольше 5-минутного snapshot | Без отдельного tool call, но добавляет state в prompt | Модель | Отклонить |
| Отдельный quota tool | Можно получить fresh state | Ещё один model round-trip; прошлый замер — медиана ≈$0.13 за tool call, и контекст перечитывается снова | Модель может не вызвать/неверно интерпретировать | Отклонить [S13] |
| Автоврезка в каждое сообщение | Свежесть достижима | Шумит каждым prompt, дублирует серверное состояние, требует интерпретации | Модель | Отклонить |
| Серверное решение | Можно использовать тот же `current_quota_observation` непосредственно перед side effect | Ноль model round-trip; решение тестируется как pure policy | Сервер | **Выбрать** |

Единственный контракт должен принимать не точный model id, а валидируемый `task_class` плюс автоматически доказуемый provenance (`requesting_runtime`, `spec_author_runtime`, `implementation_runtime`, continuation id). Известный workflow ставит class сам. Для persistent free-text entrypoint без trusted metadata сервер не угадывает смысл: применяется один фиксированный class `orchestrator_free_text`; неизвестный/недопустимый class отклоняется loud до side effect. Это сознательно может не распознать редкий 1M case, но не возвращает скрытое решение модели. Router в одном месте:

1. получает свежие наблюдения **обоих** candidate families под per-bucket admission lock; unknown/stale candidate считается недоступным, но не заражает свежий доступный alternative;
2. применяет class eligibility, cross-runtime constraint, измеренные Claude thresholds #186 и отдельную явно маркированную Codex policy;
3. возвращает точный model и структурированный reason (`observed_at`, utilization/state каждого кандидата, reserve authorization, decision rule);
4. только затем создаёт worktree/backend или начинает idle turn.

Обычный агент не должен иметь parallel exact-model override: иначе остаются два owner одной задачи. Административная ручная смена может существовать как control plane, но не как нормальный task-routing path. [S5][S8][S9]

Router нужен на трёх фактических границах одного и того же решения: planned spawn до side effects; начало любого нового idle/waiting turn, включая orchestrators; review launch. Running steering не является новым ходом и не переключается. `codex_review` сейчас отдельный обход: он жёстко объявлен как `gpt-5.6-sol`, проверяет только Codex quota и не имеет Claude fallback; общий review entrypoint должен пользоваться тем же router. [S5][S9]

Чтобы quota balancing не превращался в постоянную потерю native context, внутри одного `logical_work_id` действует stickiness: уже выбранный runtime сохраняется, пока он eligible; `reserve_only` разрешает закончить эту continuation, а смена происходит только при блокировке/terminal limit или на границе новой phase/task. Это design inference из измеренной цены handoff, не существующее поведение. [S17]

**Вывод: H2 CONFIRMED как архитектурное решение — tier 2 code trace + tier 1 cost measurement.** Семантика остаётся у workflow как малый enum класса работы; выбор provider/model и трактовка квот модели не делегируются.

### F3. Кто принимает решение и как выглядит детерминированная политика

Сервер, а не spawning agent, должен подставлять runtime. Это уменьшает свободу оркестратора намеренно: при одинаковых inputs решение воспроизводимо, а stale/unknown telemetry нельзя «объяснить» оптимистично. Agent сообщает только содержание работы в структурированной форме; известные workflow сами проставляют класс (`spec`, `implementation`, `review`, `empirical/mechanical`, строго ограниченный `spark_leaf`). [S1][S5]

Предлагаемый порядок constraints, один и тот же для spawn/new turn/review:

1. **Eligibility:** Spark допустим только для уже определённого leaf-контракта; 1M-context requirement исключает Sol с измеренным effective 258K; unavailable/stale provider исключается fail-closed. [S1][S4]
2. **Quota state:** Claude использует состояния #186; Codex-first burning использует явную 90/95 user policy, потому что #186 запретил перенос Claude-чисел. Reserve-only открывается только по проверяемому признаку; затем fallback в другой доступный runtime.
3. **Independence с явной деградацией:** сначала выбирается eligible runtime, отличный от runtime реализации. Если такого runtime нет, но тот же runtime quota-eligible, user requirement «когда Codex закончится — все на Opus» разрешает same-runtime phase с обязательным `degraded_review_independence` audit/warning. Только отсутствие любого quota-eligible runtime ведёт в blocked queue. Provenance берётся из session/task metadata, не из заявления агента. [S15]
4. **Stable tie-break:** если constraints оставили несколько моделей, применяется один manifest ordering, а не «реши сам».

Router сначала отличает continuation того же logical work от нового задания. Для continuation stickiness сильнее Codex-first rebalance; для новой работы Codex-first снова применяется. Иначе каждый неожиданный reset будет мигрировать живой multi-turn task туда-обратно и ухудшать именно сохранность, которую должна дать бесшовность. [S17]

Текущая строка «Orchestrators — always Opus» не подтверждена эксплуатационным сравнением: #175 измерил эпоху Sol-оркестратора — 47/47 успешных ходов, 6 задач, 8/8 успешных merge, 0 printed-tool-call failures — и не нашёл измеримой причины предпочесть Opus. Поэтому orchestrator exemption нельзя оставлять скрытым override quota-router; orchestrator меняется только на безопасной границе между ходами. Free-text такого orchestrator получает фиксированный `orchestrator_free_text`, пока trusted workflow не создаст более узкую phase/task. [S14]

**Вывод: CONFIRMED для owner/inputs, LIKELY для окончательного enum.** Owner следует прямо из требуемого детерминизма и текущих seams; точные имена классов — предмет Phase 2, но они не должны кодировать model id.

### F4. Политика жжения Codex и реальное поведение окон

Read-only backup содержит **8 805** snapshots за `2026-07-05T05:19:58.635440+00:00` → `2026-08-11T09:51:04.862326+00:00`. Codex/Spark присутствуют в **2 320** одновременных снимках за 03–11 августа; оба окна имеют `window_minutes=10080`. [M2]

У `codex.primary` utilization был 0–100%, но обнаружены ровно три падения:

| До → после (UTC) | Utilization | Старый → новый `resets_at` |
|---|---:|---|
| 08-08 05:50 → 05:55 | 100 → 0 | 08-08 05:53:45 → 08-15 05:55:40 |
| 08-08 20:31 → 20:36 | 26 → 0 | 08-15 06:41:36 → 08-15 20:36:35 |
| 08-10 23:55 → 08-11 00:00 | 87 → 0 | 08-16 07:16:05 → 08-18 00:00:25 |

Сводка парсера над backup (raw output):

```text
snapshots {'n': 8805, 'first': '2026-07-05T05:19:58.635440+00:00', 'last': '2026-08-11T09:51:04.862326+00:00'}
codex_samples 2320 2026-08-03T07:02:20.948252+00:00 2026-08-11T09:51:04.862326+00:00
codex_util_minmax 0.0 100.0 unique_reset_at 154 reset_at_changes 597
paired_states equal=134 divergent=2186 total=2320
spark_minmax 0.0 1.0 spark_down=1
```

Это **не** ежедневный календарный reset по заранее заданному критерию: два падения случились в один день, следующее — спустя более двух суток. Одновременно это подтверждает наблюдение пользователя в более узкой форме: Codex действительно несколько раз неожиданно освобождался до прогнозной даты. История содержит 154 уникальных `resets_at` и 597 изменений строки reset; при 0% forecast двигался вместе со snapshot, поэтому `resets_at` нельзя считать стабильным календарным якорем. Причина трёх падений из snapshots не устанавливается. [M2]

Официальный Codex app-server отдельно возвращает `rateLimitResetCredits` и имеет mutating метод `account/rateLimitResetCredit/consume`; после consume документация требует заново прочитать rate limits. Живой `/api/usage` в 10:01 UTC показал `plan_type=prolite`, `codex.primary=22%`, reset `2026-08-18T00:28:28Z`, **1 reset credit**, Spark 0%. Код Orchestra читает count, но вызова consume в репозитории нет. Следовательно, earned reset — правдоподобный competing mechanism, но утверждать, что именно он вызвал исторические drops, нельзя. Автоматически тратить credit обычным router также нельзя: это отдельный редкий актив, для которого нет одобренной политики. [S6][S11][M2][M3]

API не сообщает дату продления самой подписки: observed `primary.resets_at=2026-08-18` относится к quota window и не подтверждает предположение о billing reset 20-го числа. [S6][S11][M3]

Spark независим: в тех же 2 320 снимках его state `(utilization,resets_at)` отличался от Codex в **2 186**, совпал в 134; utilization был 0–1%, с одним собственным падением 1→0. Значит свободный Spark не означает свободный Sol и не отменяет его узкое class eligibility. [M2]

Практическое следствие: router реагирует на свежую utilization/state, а не предсказывает «ежедневный reset». После неожиданного drop normal Codex автоматически снова открывается на **следующей безопасной границе нового хода**, без человеческой команды. `resets_at` годится для видимого ETA/wake, но каждое пробуждение обязано перепроверить fresh state.

#### Численные состояния: Claude — измерение #186, Codex — явная policy пользователя

#186 вывел Claude runway в **рабочих часах**, а не по одному проценту:

```text
rate      = (7d_now - 7d_at_week_start) / elapsed_work_hours
runway    = (100 - 7d_now) / rate
remaining = work_hours_until Tuesday 07:00 UTC
D         = remaining - runway
```

Рабочее время в измерении — 06:00–20:00 МСК. Для Claude: `preferred` при **D ≤ 14**; `reserve_only` при **D > 14**; `unavailable` при **7d ≥95%** или остатке `<0.3 pp`. Порог 14 — один рабочий день, а в backtest #186 полоса 14…55 была пуста. Стоимость Claude turn: median **0.05 pp**, p90 **0.27 pp**, max **1.06 pp**; поэтому p90 guard округлён до 0.3 pp. При текущем hard gate 95% условие `<0.3 pp` математически им поглощено, но фиксирует запрет ждать literal 100%, если hard gate когда-либо меняется. [M5]

Claude 7d reset доказан как календарный: 6/6 сбросов во вторник 07:00 UTC за 38 суток; `resets_at` отсутствовал в 381/8 804 snapshots (4,3%), поэтому `remaining` считается от календаря. Claude 5h, наоборот, якорится первым запросом после предыдущего закрытия и восстанавливается только по `resets_at`. Недельный пул оплачивает лишь 7,8 полностью выжженных 5h-окон из ~33,6 в неделе (`r=0.128`), поэтому 5h не является routing-runway: actual 5h limit временно закрывает Claude до своего `resets_at`, а «почти полный 5h» сам по себе не переключает модель. Ex-ante признак тяжёлого хода в #177 не найден. [M5]

Числа Claude **не переносимы** на `codex.primary`: у Codex нет доказанного календарного anchor; цена Codex turn не измерена в pp и token counters несовместимы с Claude; Spark — второй независимый bucket. Для data-derived Codex cutoff #186 требует 2–3 недели Codex outcomes; у #187 есть лишь восемь суток snapshots. [S14][M2][M5]

Но система должна действовать сейчас, а пользователь прямо задал резерв 5–10%. Поэтому временная Codex policy не маскируется под измерение:

- `normal`: utilization **<90%** → вся eligible обычная работа Codex-first;
- `reserve_only`: **90% ≤ utilization <95%** → только `reserve_authorized`;
- `unavailable`: **≥95%**, terminal provider limit либо unknown/stale observation → новый/idle ход идёт на Claude;
- неожиданный drop ниже 90% снова открывает normal Codex на следующей безопасной границе.

Это единственный численный выбор, который одновременно исполняет дословный пользовательский коридор 90–95 и не выдаёт Claude measurement за Codex measurement. После достаточной Codex истории policy должна пройти тот же pre-registered backtest, а не бесшумно менять числа.

`90/95` — best-effort reserve, не строгая транзакционная гарантия: provider не даёт операции «зарезервировать pp», Codex cost/turn ещё не измерен, а внешний расход может измениться между observation и start. Per-bucket lock + forced fresh read сериализует локальный `refresh → decide → admit` и устраняет одновременное чтение одного cache несколькими spawn, но один уже допущенный turn всё равно может пересечь 90 или 95. До Codex pp/turn measurement router не вводит выдуманную capacity reservation и в UI/audit не пишет «5% гарантированно сохранены».

Проверяемый emergency-признак нельзя строить на текущем `priority=0`: live backup содержит **82** таких задачи (67 done, 9 in progress, 6 new), включая обычные research tasks; активны 15. Он съест редкий резерв как обычную очередь. `reserve_authorized` — серверный predicate только для: (a) continuation уже начатого logical work; (b) обязательной capability/independence phase, которую второй runtime выполнить не может; (c) отдельного human-authenticated emergency action. Agent, свободный текст и обычный task priority сами его не повышают. [M4]

**Вывод: H3 REFUTED — tier 1 measurement.** Codex окно недельной длины, но его reset не наблюдается как стабильная календарная неделя. Политика Codex-first подтверждена как реактивная state machine; Claude thresholds импортированы из #186, а Codex 90/95 явно маркированы как временная пользовательская policy, не эмпирический cutoff.

### F5. «Специализированные задачи Claude» — что доказано, а что нет

Прямых исторических свидетельств общего превосходства Opus над Sol не найдено. #178 нашёл обратные operational observations: Sol дважды опроверг неверные гипотезы живыми данными и имел 0 printed tool calls против 9 у Opus; #175 не обнаружил измеримой причины предпочитать Opus для orchestrator; `sol-vs-opus` связывает объём результата прежде всего с формулировкой задания. [S13][S14][S16]

Доказанный normal-assurance routing rule другой: #176 измерил однорантаймовую петлю, где Sol написал постановку, реализовал и отревьюил её. Итог — 364 мёртвые строки из 843 добавленных (43,2%) и три круга переделок. Это не доказывает, что Sol слабее; это доказывает отсутствие независимой проверки. Поэтому при наличии двух quota-eligible runtimes:

- runtime постановки ≠ runtime реализации;
- runtime ревью ≠ runtime реализации;
- если implementation=Codex, spec/review идут на Claude;
- если implementation=Claude, spec/review идут на Codex.

[S15]

Технически проверяемый отдельный Claude case — необходимый context > effective 258K Codex при доступном `claude-opus-5[1m]`. Признаки «ambiguity/dialogue/creative/vision» в #178 имеют лишь LIKELY confidence и не должны быть жёстким quota override без нового A/B. Spark не годится для финального review: ранее он пропустил реальный double-count, который поймал Sol. [S1][S4][S13]

Если Codex полностью закончился и вся работа переходит на Opus, работоспособность сохраняется, но cross-runtime independence для Claude implementation физически отсутствует. Router явно ослабляет только independence constraint после доказанного отсутствия второго eligible runtime, допускает Opus и пишет `degraded_review_independence`; quota/capability constraints не ослабляются. Тихо подменять независимое review self-review нельзя.

**Вывод: H4 CONFIRMED — tier 1 prior measurements для independence, REFUTED как тезис «Claude в целом лучше».** Claude — не престижный default, а один из двух runtime в проверяемом разделении ролей и fallback при исчерпании Codex.

### F6. Бесшовный переход: что сохраняется и что ломается сейчас

Running turn переключать нельзя: `change_model()` возвращает `cannot change model while running`; cross-runtime switch disconnect-ит backend, сбрасывает native `session_id` и переносит только `runtime_handoff`. Официальные Codex docs при этом говорят, что уже активный turn при достижении лимита может закончиться subject to fair use. Следовательно, нормальный failover не прерывает живой Sol turn: решение ставится на post-turn/next-turn boundary. [S9][S11]

Если provider всё же отдаёт terminal `usageLimitExceeded`/`sessionBudgetExceeded`, Codex backend классифицирует событие как `rate_limit`; текущая система завершает ход и планирует wake, но не выбирает другой runtime. Нельзя слепо повторить исходный prompt на Opus: до terminal error могли произойти внешние side effects, а общего idempotency receipt нет. Безопасное действие — сохранить server-owned failover intent, дождаться idle/finalization, переключить runtime и продолжить из durable work/handoff без автоматического replay исходного сообщения. [S10][S17]

Сам worktree, незакоммиченные файлы, Orchestra logs и task metadata сменой runtime не удаляются. Но нативная сессия обнуляется. Текущий fallback `_build_runtime_handoff()` берёт последние 120 **всех** log rows, затем оставляет только user/text, режет row до 6 000 и общий payload примерно до 32K; при наличии `last_summary` switch вместо этого использует максимум 4K старой summary. [S9][S17]

#174 измерил production-алгоритм на live backup: для выбранной длинной сессии handoff сохранил 24 из 1 284 semantic rows (**1,87%**) и 15 163 из 1 735 339 semantic chars (**0,86%**); tool/results исключены. В реальном switch с `last_summary` ушло 3 337 старых знаков, а 14 новых semantic rows и 65 tool/result rows после summary не вошли. Поэтому на текущем коде можно сохранить рабочее дерево и дать **видимую lossy handoff**, но нельзя обещать бесшовную передачу знания. [S17]

#174 research вывел необходимость post-turn control intent, но его текущий plan намеренно **не** реализует self-switch/deferred state machine: человек инициирует idle switch. План #174 переносит DB history в native Claude/Codex import там, где canary проходит, и оставляет видимый summary fallback. Поэтому #187 не ждёт его: automatic failover intent остаётся ответственностью #187; до merge действует текущий lossy summary/handoff, после merge тот же quota decision переиспользует улучшенный history transport. Отдельный второй router не нужен. [S17][S18]

**Вывод: H5 REFUTED — tier 1 live measurement + tier 2 code.** Безопасен автоматический **выбор момента** (после активного turn); lossless перенос текущим summary не подтверждён.

### F7. Когда кончилось всё: один fail-loud outcome

Чтобы blocked case не стал вторым delivery path, **каждый новый idle logical input** сначала проходит один durable ingress; при available quota тот же request может доставить его немедленно. Контракт at-most-once:

1. У входа есть стабильный `delivery_id`, созданный **до** retry: TG выводит его из `(chat_id,message_id)`, HTTP/MCP caller передаёт и сохраняет UUID. Запрос без id отклоняется до enqueue; server-issued id в потерянном ответе не защищает повтор caller-а.
2. DB имеет unique `(scope,target,delivery_id)`. Повтор enqueue возвращает существующий row/status, не создаёт вторую работу.
3. Worker/wake/manual retry получает row единственным compare-and-swap `queued → claimed(attempt_id, lease)`. Просроченный `claimed` можно вернуть в queue только если dispatch ещё не начался; concurrent claim проигрывает без backend call.
4. Непосредственно **до** `backend.send` транзакционно сохраняется `dispatching`. После подтверждённого submit сохраняется `submitted` (и native turn/thread id, если runtime его даёт), затем listener завершает `completed/failed`.
5. Crash/timeout в `dispatching` — неизбежно неоднозначное состояние между SQLite и внешним backend. Оно становится `delivery_unknown`, громко эскалируется и **никогда автоматически не replay-ится**. Только доказанный pre-submit failure возвращает row в `queued`; `submitted/completed/delivery_unknown` повторно не отправляются.
6. Если router не нашёл eligible provider до dispatch, row остаётся `queued`, вызывающий сразу получает `all_runtimes_unavailable` с возрастом observation/reset ETA, а сервер ставит один wake. Wake повторяет claim/router, не создаёт новый row.

Это очередь **с громким статусом**, а не обещание exactly-once, которого нельзя дать без provider idempotency receipt. Она выбирает at-most-once side effects и видимую ручную развязку ambiguous state вместо возможного дубля. Текущий idle `AgentSession.send()` сначала проверяет quota и только после admission пишет `user_message`, поэтому ordinary blocked send сейчас не durable; только `_flush_pending` отдельно удерживает сообщения, пришедшие во время running turn. Значит «просто вернуть существующий 409» не удовлетворяет сохранности входа. [S9][S12][S17]

#186 наблюдал unavailable Claude telemetry в 381/8 804 snapshots, включая 191 последовательный snapshot 10 августа. Router не подставляет last-known utilization: неизвестный provider исключается, а если alternatives тоже недоступны, включается именно loud queue outcome выше. [M5]

Terminal limit после `submitted` — другой state того же logical work: сохраняется новый continuation intent со ссылкой на исходный `delivery_id`, но исходный row/prompt автоматически не переигрывается. Stop/model-control остаются доступны независимо от quota; retry storm запрещён. [S10][S17]

**Вывод: CONFIRMED как требуемая политика fail loud; implementation отсутствует.** Она одновременно не теряет новую работу и не выдаёт waiting за running/delivered.

## Итоговая state machine

| Событие | Решение сервера | Что видит агент/пользователь |
|---|---|---|
| Spawn/new idle turn, Codex `normal`, class eligible | Codex/Sol (Spark только strict leaf) | model reason в audit log; quota в prompt не нужна |
| Codex `reserve_only`, обычная работа | Claude, если eligible/available | автоматический fallback |
| Codex `reserve_only`, `reserve_authorized` | Codex | audit с provenance authorization |
| Codex blocked, Claude available | Claude | автоматический fallback; при отсутствии независимого runtime явный degraded audit |
| Неожиданный Codex reset/drop | Codex снова доступен со следующего new-turn decision | без команды человека |
| Running Sol turn | Не прерывать и не switch | ход заканчивается на текущем runtime |
| Terminal limit внутри turn | durable failover intent, switch после finalize, без blind replay | явный degraded/lossy handoff до #174 |
| Все eligible pools unavailable/unknown | deduped `queued` row + loud status + one wake | `all_runtimes_unavailable`, не тишина |
| Crash/timeout после `dispatching`, до persisted submit ack | `delivery_unknown`, no auto-replay | громкая ручная развязка; дубль side effect не допускается |

## Counter-evidence и ограничения

1. **Prompt injection дешевле в реализации.** Она может дать агенту снимок без нового tool call. Но persistent prompt стареет, а модель всё равно остаётся owner решения; фальсификатор H2 не выполнен.
2. **Сервер не понимает свободный текст задачи.** Поэтому он не угадывает семантику: workflow передаёт малый валидируемый class, а entrypoint без него получает один фиксированный `orchestrator_free_text`. Цена — редкий special case может начать ход как general; это честнее скрытого LLM-classifier.
3. **Три Codex drops — малая история и причина неизвестна.** Вывод ограничен: refuted только стабильный daily/calendar reset; не доказаны ни общий закон reset credit, ни будущая частота.
4. **#175 — всего 47 Codex turns.** Он опровергает заявление о найденной необходимости Opus, но не доказывает равенство моделей на всех задачах.
5. **#176 смешивает runtime и workflow.** Это именно основание для independence rule, а не доказательство, что Claude review всегда качественнее.
6. **Все-на-Opus fallback конфликтует с cross-runtime review.** Conflict разрешён в самом router: independence — сначала обязательная preference, затем единственная явно ослабляемая constraint с `degraded_review_independence`; quota/capability не ослабляются.
7. **Текущий handoff сохраняет disk state, не cognition.** До #174 бесшовность можно обещать только для worktree/log persistence, не для полного reasoning/tool context.
8. **Claude thresholds нельзя переносить на Codex.** Поэтому D≤14/D>14 и 0.3 pp применяются только к Claude. Codex 90/95 — явная политика пользователя до отдельного 2–3-недельного backtest, не результат #186.
9. **Строгий Codex reserve сейчас недоказуем.** Admission lock закрывает local race, но provider не резервирует pp и cost следующего Codex turn неизвестен; один turn или внешний consumer может пересечь границу. UI обязан называть 90/95 best-effort policy до measurement.
10. **SQLite + provider send не дают exactly-once.** Stable delivery id/unique row/CAS убирают retry и concurrency duplicates; crash в `dispatching` намеренно платит доступностью (`delivery_unknown`) ради запрета blind replay.

## Confidence по главным выводам

| Вывод | Confidence | Основание |
|---|---|---|
| Live quota не попадает в agent model decision | **CONFIRMED** | tier 2 полный code/call-site trace + git history |
| Один server-side router — нужный owner | **CONFIRMED** | tier 2 seams + tier 1 round-trip cost; альтернативы оставляют model owner |
| Claude state: D≤14 / D>14 / unavailable | **CONFIRMED для измеренного периода** | #186: 38 суток, 8 804 snapshots, backtest с пустой полосой 14…55 |
| Codex cutoff 90/95 data-derived | **REFUTED** | всего 8 суток; нет календарного anchor и pp/turn measurement; это user policy |
| Codex не имеет наблюдаемого daily calendar reset | **CONFIRMED (refutation)** | tier 1: 3 drops, не удовлетворившие pre-registered criterion |
| Spark — отдельный quota bucket | **CONFIRMED** | tier 1: 2 320 paired samples, 2 186 divergent states |
| Priority 0 не защищает emergency reserve | **CONFIRMED** | tier 1: 82 critical rows, 15 active |
| Codex 90/95 строго сохраняет 5% | **UNCERTAIN / не гарантировано** | нет pp/turn measurement или provider reservation; local admissions можно лишь сериализовать |
| Общее превосходство Opus над Sol | **REFUTED как найденный факт** | #175/#178 не нашли доказательства; это не proof равенства |
| Cross-runtime spec/review снижает amplification risk | **LIKELY/strong** | один подробный measured incident #176; нет controlled A/B |
| Текущий runtime handoff бесшовен | **REFUTED** | tier 1 live measurement #174 + tier 2 code |
| Router может безопасно replay terminal turn | **REFUTED** | нет idempotency receipt; side effects могли состояться |
| Durable ingress предотвращает auto-duplicate | **LIKELY design inference** | stable id + unique row + CAS; ambiguous dispatch fail-stops в `delivery_unknown`, implementation ещё нет |

## Codex second opinion

Первый зрячий раунд заблокировал research: первоначальная очередь не имела stable id, atomic claim и определённого исхода после ambiguous backend submit, поэтому могла повторить side effect. Он также нашёл неявное противоречие independence/all-Opus, local admission race и отсутствующий class для free-text. Первоначальный dissent сохранён дословно в review artifact. [S21]

После правки контракт получил один durable ingress, stable `delivery_id`, unique row, CAS states и fail-stopped `delivery_unknown`; independence — явный relaxation order; local admission сериализован с честным best-effort reserve; free-text имеет fixed server class. Второй и последний prose round: Blocking — `None`, Suggestion — `None`, verdict — **APPROVED**. Sighted proof — дословная цитата строки 194 обновлённого research, которой не было в review prompt. [S21]

## Affected files для возможной Phase 2

Это карта, не разрешение писать код.

- `app/quota_gate.py` — единственный owner pure quota/task-class routing decision вместо gate только уже выбранного model.
- `app/routes/system.py` — coherent fresh observation обоих candidate families; reset credits остаются telemetry, не auto-consume.
- `app/mcp_stdio.py` — `spawn_worker` принимает task class вместо обязательного model; `codex_review` заменяется/оборачивается runtime-neutral review entrypoint.
- `app/manager.py` — router до worktree/backend side effects; сохранение decision provenance.
- `app/session.py`, `app/session_turns.py` — router на любой idle new-turn boundary, включая orchestrators; post-turn failover intent; durable blocked delivery; не трогать running turn.
- `app/backend_codex.py`, `app/limit_wake.py` — terminal limit → единый failover/wake outcome без retry/replay.
- `app/routes/sessions.py`, TG/HTTP/MCP callers — stable `delivery_id`, structured loud status и administrative override отдельно от normal routing.
- `app/db.py` — unique delivery identity и `queued/claimed/dispatching/submitted/delivery_unknown/completed` state; migration только после проверки существующих inbox/jobs/schema.
- `tests/test_quota_gate.py`, `tests/test_session.py`, `tests/test_mcp_stdio.py`, `tests/test_usage_readiness.py`, focused restart/failover tests — один decision contract на всех входах.
- `pipelines/default/prompts/base.md` — после server authority убрать ложное ожидание, что агент сам знает live quota; model-routing prompt не должен быть вторым owner.

Главные edge cases: два provider refresh разного возраста; reset между decision и backend start; один unmeasured turn пересекает 90/95; внешний consumer меняет quota; root orchestrator self-switch; enqueue response потерян и caller retry; lease истёк; crash до/после `dispatching`; terminal error после side effect; Spark ошибочно принят за Sol; reset credit неожиданно меняет window; #174 ещё не merged; cross-runtime reviewer отсутствует при all-Opus fallback.

## Sources

### Код и текущие контракты — tier 2, primary

- **[S1]** `pipelines/default/prompts/base.md:77-87`; `pipelines/default/prompts/modules/orchestration.md:166-167` — статическая model-routing инструкция.
- **[S2]** `app/pipeline.py:427-470` — сборка system prompt из pipeline layers/modules.
- **[S3]** `app/manager.py:301-330,472-655` — prompt assembly, session creation, planned initial quota preflight.
- **[S4]** `app/models.py:49-136,641-663`; `app/backend_codex.py:26-35` — model/runtime/context metadata; effective Sol context 258400.
- **[S5]** `app/mcp_stdio.py:546,711-750,2035-2125` — обязательный exact model при spawn; Codex-only review и quota refusal.
- **[S6]** `app/routes/system.py:478-521,934-1015,1080-1124` — Codex normalization, `/api/usage`, fresh observation, snapshot collector.
- **[S7]** `app/db.py:230-252,1030-1118` — `usage_snapshots` и history persistence/read.
- **[S8]** `app/quota_gate.py:16-48,210-355` — weekly 95, stale fail-closed, alternatives without selection.
- **[S9]** `app/session.py:813-850,900-1024,2056-2158`; `app/manager.py:633-636` — new-turn seam, orchestrator/running bypass, current handoff/model switch.
- **[S10]** `app/backend_codex.py` (`usageLimitExceeded`, `sessionBudgetExceeded`); `app/session_turns.py` after-turn finalization; `app/limit_wake.py` — terminal limit/wake path.
- **[S11]** OpenAI Codex official manual, current fetch 2026-08-11: <https://developers.openai.com/codex/codex-manual.md> — active turns at usage limit; app-server `account/rateLimits/read`, multi-bucket response and earned reset credits/consume.
- **[S19]** `tests/test_quota_gate.py`, `tests/test_session.py`, `tests/test_usage_readiness.py` — executable current gate/bypass/freshness contract.
- **[S20]** Git commits `cf47269`, `18cdd87`, `8369737` — prompt quota policy, required spawn model, #168 weekly gate.
- **[S21]** `docs/tasks/187/codex-review-research.md` — два раунда adversarial review; first-round BLOCKED preserved, second-round APPROVED с проверенной дословной цитатой target.

### Предшествующие исследования — tier 1 measurements recorded in-repo

- **[S12]** `docs/tasks/168/research.md` — централизованный weekly admission gate и все входы.
- **[S13]** `docs/tasks/178/research.md` — ≈$0.13/tool call, cold start $0.31–0.62, отсутствие найденного Opus>Sol evidence.
- **[S14]** `docs/tasks/175/research.md` — Sol-era orchestrator: 47 turns/6 tasks и ограничения сравнения.
- **[S15]** `docs/tasks/176/research.md` — однорантаймовая петля spec/review/implementation и 364 dead lines.
- **[S16]** `docs/tasks/sol-vs-opus-2026-07-30.md` — влияние scope формулировки и measured runtime behavior.
- **[S17]** `docs/tasks/174/research.md`, `docs/tasks/174/handoff/research.md` — runtime switch/handoff measurements.
- **[S18]** `docs/tasks/174/plan.md` — ещё не merged human-initiated idle switch с DB→native history import; self-switch/deferred state machine явно вне scope, поэтому это не источник текущего behavior.

### Измерения этой задачи — tier 1

- **[M1]** `rg` call-site trace + `git log -S` по `current_quota_observation`, `model is required`, `protect whichever weekly pool`; 2026-08-11.
- **[M2]** `sqlite3.Connection.backup` live `/home/kesha/orchestra/data/orchestra.db` → временная read-only копия; Python JSON parse `usage_snapshots`; 8 805 total / 2 320 Codex paired samples; 2026-08-11. Копия не коммитится.
- **[M3]** authenticated read-only `GET /api/usage`, 2026-08-11 10:01 UTC: Claude 5h 37%/7d 6%; Codex 22%, reset credit 1; Spark 0%.
- **[M4]** та же backup, `tm_tasks GROUP BY priority,status`: priority 0 = 67 done + 9 in progress + 6 new.
- **[M5]** `docs/tasks/186/research.md`, секция «Ответ на вопросы #187 (quota-routing)» — Claude D/runway thresholds, 5h/7d semantics, turn pp distribution, NULL behavior и явный запрет переносить числа на Codex.
