# #174 — Самопереключение рантайма и перенос контекста между моделями

Дата исследования: 2026-08-11. Фаза: **только research/experiment**. Продакшен-код и живые сессии не изменялись.

Сырые протоколы независимых срезов:

- [`handoff/research.md`](handoff/research.md) — control flow смены модели и точный замер потерь на read-only backup живой SQLite;
- [`transcripts/research.md`](transcripts/research.md) — форматы Claude/Codex/Grok и изолированные resume-эксперименты (добавляется после завершения стенда).

## Вопрос

**Контекст.** Orchestra уже умеет менять Claude/Codex/Grok между ходами: сбрасывает нативный `session_id`, кладёт `runtime_handoff`, а при следующем сообщении добавляет его как `<prior-conversation>` (`app/session.py:955-1008,2056-2158`).

**Проверяемое изменение.** Нужен ли и возможен ли тул, которым агент сам заказывает смену собственного рантайма, сам пишет сводку, а сервер безопасно завершает старый ход и продолжает на новой модели. Отдельно проверяется более сильная идея: перенести не сводку, а настоящую историю, синтезировав нативный transcript целевого CLI.

**Baseline.** Текущий внешний вызов `change_worker_model` у idle-сессии и машинный handoff из последних 120 логов либо `last_summary` до 4 000 знаков.

**Критерии ответа.** Реальный self-call должен либо безопасно сменить рантайм после доставки tool result, либо доказуемо отказать без мутации; поддельная история должна быть принята установленным CLI в изолированном home и позволить новой сессии семантически вспомнить маркер; потери текущего handoff считаются тем же алгоритмом, что в проде.

## Гипотезы и фальсификаторы

1. **H1: текущий синхронный API не может гарантировать безопасное самопереключение внутри хода**, потому что handler должен отключить тот же backend, который ещё ждёт ответ тула. Фальсификатор: self-call меняет рантайм и старый агент получает успешный tool result до disconnect, без гонки с финализаторами хода.
2. **H2: отложенное переключение безопасно реализуемо как durable state machine**, если сервер сначала сохраняет намерение и отвечает старому агенту, а применяет его только после terminal `turn_end`. Фальсификатор: нет terminal точки до очередного сообщения либо crash/restart оставляет неоднозначность «switch уже применён?»/«continuation уже доставлен?» и сервер может повторить side effect.
3. **H3: агентская сводка полезнее машинной, но не может быть единственным источником**, потому что агент может не вызвать тул, превысить лимит или исказить состояние. Фальсификатор: сервер способен надёжно проверить смысловую полноту/истинность произвольного текста без исходных логов.
4. **H4: настоящий transcript можно переносить между всеми рантаймами.** Фальсификатор: целевой CLI отвергает поддельную сессию либо форматы содержат непреобразуемое provider-specific состояние.
5. **H5: лимиты 120 строк/32k и исключение tool rows сегодня теряют существенный контекст.** Фальсификатор: на длинной реальной сессии сохраняется хотя бы половина смысловых сообщений и достаточно доказательств, чтобы не повторять tool calls.

## Вывод

Немедленное самопереключение **не поддерживается и не должно делаться синхронным**: живой self-call получает 409 до любого disconnect, а после удаления guard синхронная ветка не сможет гарантировать доставку результата тула; teardown некоторых backend почти наверняка прервёт этот транспорт. Ближайшая безопасная схема — **deferred state machine**: агент последним tool call сохраняет target+сводку и завершает ход; сервер применяет switch только после terminal event. Автоматический wake требует отдельной durable delivery phase; при неоднозначном crash generic backend нельзя молча ретраить.

Предпосылка «`change_worker_model` доступен только оркестратору» на текущем стенде **REFUTED**: тул был в реестре full-cycle worker и принял self-call; ограничителем оказался только RUNNING guard. Это означает, что будущий self-contract должен проверять identity на сервере и не принимать произвольный `name` от модели.

«Настоящая история» не является общим переносимым объектом. Claude и Codex имеют разные нативные журналы и поддерживаемые resume-seams; даже когда целевой CLI принимает синтетическую observable history, она не переносит зашифрованное reasoning, provider events и полную семантику tool protocol. Поэтому устойчивый продуктовый контракт — provider-neutral handoff, а нативный transcript import можно рассматривать только как отдельный version-pinned adapter, не как источник истины.

Текущий fallback слабее, чем выглядит: он выбирает последние 120 **всех** логов до фильтрации, выкидывает tools/results и может начать с ответа без вопроса. На выбранной длинной живой сессии сохранилось 24/1 284 смысловых строк (1,87%) и 15 163/1 760 169 знаков (0,86%); фактическая эстафета `Orchestra-orchestrator` вообще использовала старый `last_summary` 3 337 знаков и не включила 14 более новых смысловых записей/6 580 знаков и 65 tool/result записей/251 149 знаков.

## 1. Самопереключение

### Что работает сейчас

`change_worker_model` технически присутствует и у full-access worker, принимает произвольное имя и синхронно вызывает `/api/sessions/{name}/change-model` (`app/mcp_stdio.py:449-490,1215-1223`). То есть ограничение «только оркестратору» сейчас является ожидаемым workflow, а не проверкой caller role на границе тула.

Для self-call с другой моделью путь такой:

1. route находит загруженную сессию и ждёт `found.change_model()` (`app/routes/sessions.py:606-621`);
2. `change_model()` берёт `_lifecycle_lock`;
3. `_change_model_locked()` сначала проверяет same-model, затем при `status == RUNNING` возвращает `cannot change model while running` (`app/session.py:2095-2106`);
4. route переводит отказ в HTTP 409, старый backend получает ошибку и продолжает ход.

Изолированная `AgentSession` с `RUNNING` и mock backend вернула этот отказ, сохранила `model=claude-sonnet-5[1m]`, `runtime=claude`, не вызвала `disconnect` ни разу и отпустила lifecycle lock. Неизменённые focused tests дали `3 passed in 8.31s`; команда и полный вывод сохранены в [`handoff/research.md`](handoff/research.md#empirical-statuslock-probe). Живой self-call данного воркера также вернул `http_4xx: cannot change model while running`; модель осталась `gpt-5.6-sol`.

**CONFIRMED — tier 1 (два прямых эксперимента) + tier 2 (код):** агент может вызвать собственный control tool, но текущая смена внутри активного хода невозможна; она fail-safe отклоняется без отложенного действия.

### Почему нельзя просто убрать RUNNING guard

Успешная ветка смены строит handoff, логирует смену и **до HTTP-ответа** ждёт `_disconnect_backend()`, затем сбрасывает `session_id`, меняет backend/model и persist-ит состояние (`app/session.py:2108-2158`). Disconnect каждого backend завершает исполняющий substrate: Claude SDK client, Codex app-server/turn, Grok ACP process либо OpenCode daemon (`app/backend_claude.py:320-326`, `app/backend_codex.py:691-725`, `app/backend_grok.py:502-529`, `app/backend_opencode.py:610-638`). При self-call это тот же процесс, который ждёт MCP result.

Одновременно listener/finalizer активного хода умеет делать `RUNNING → IDLE`, flush pending queue и hibernate (`app/session.py:1212-1236,1358-1491`). Lifecycle lock сериализует отдельные мутации, но не создаёт приоритет «сначала switch, потом pending send» и не доказывает доставку tool result перед kill.

**CONFIRMED — tier 2 (полный code path); риск не проверялся разрушительным опытом:** синхронный forced self-switch не гарантирует доставку ответа и создаёт гонки финализации. На живом агенте такой эксперимент намеренно не проводился, поэтому неизбежность конкретного обрыва не заявляется.

### Безопасная схема

Предлагаемый контракт — `request_runtime_switch(target_model, handoff)` вместо немедленного `change_model` для self-case. У каждой заявки есть `switch_id`, source turn generation и durable phase:

1. **`requested`.** Внутри `RUNNING` сервер валидирует self identity/target и одной записью сохраняет request+handoff. Тул отвечает «принято; заверши ход»; disconnect/mutation в handler нет.
2. **Eligibility.** Switch разрешён только после terminal event именно source generation, при отсутствии активного backend turn/listener и при `status == IDLE`. `WAITING` сам по себе **не разрешает** switch: активные bg jobs должны закончиться; их completion/user messages ставятся в очередь за control intent. Как только bg count равен нулю, switch имеет приоритет перед обычным `_flush_pending()`.
3. **`switched`.** Смена model/runtime, архив old native id, reset session id, сохранение handoff и переход phase выполняются одной durable транзакцией. Recovery из `requested` применяет её один раз при eligibility; recovery из `switched` **не повторяет** disconnect/switch.
4. **Continuation claim.** Сервер выбирает payload: первый queued user/bg message с handoff либо, если очередь пуста, синтетический `runtime switch completed; continue`. **Для обеих веток** до `backend.send` одна транзакция ставит phase `continuation_inflight` и помечает durable queue/synthetic record как `claimed_by=switch_id`; обычный `_flush_pending()` обязан игнорировать claimed record. Затем выполняется ровно один `backend.send`.
5. После успешного принятия `backend.send` phase **`continuation_submitted`**, clearing handoff и ack/delete claimed record фиксируются одной транзакцией. `submitted` не означает завершение нового хода или model acknowledgement. Crash/exception в `continuation_inflight` оставляет результат принятия неоднозначным: claimed record не возвращается в обычный flush, сервер **не ретраит автоматически**, сохраняет handoff и переводит session в operator-visible `recovery_required`; новые сообщения остаются queued. Явное решение выбирает `assume_submitted` (не переигрывать claimed payload) либо `retry_claimed` (осознанно принять риск дубля). Это единая at-most-once default-граница для queued и synthetic continuation, а не ложное exactly-once обещание.
6. Второй request получает явный conflict, пока первый не `continuation_submitted`/cancelled. На startup каждая phase имеет единственное действие выше; `switch_id` дедуплицирует durable queue/control records.

Точка после `TurnManager.finish_turn_status()` существует: код уже persist-ит `IDLE/WAITING`, публикует завершение и запускает `after_turn_idle_actions` (`app/session_turns.py:455-499`). Phase 2 должна встроить control intent **до** auto-report/ordinary flush. Текущий `BackendLike.send` не имеет общего idempotency receipt; поэтому полностью автономное exactly-once продолжение без fail-loud uncertain state исследованием не подтверждено.

**LIKELY — design inference поверх tier 2 code trace:** state machine устраняет self-disconnect до tool-result delivery и определяет crash recovery без двойного wake. Она ещё не реализована и не имеет end-to-end доказательства; гарантия намеренно at-most-once на границе continuation.

Без нового кода ближайший рабочий workflow: воркер отправляет сводку оркестратору и завершает ход; оркестратор меняет уже idle-воркера и посылает сводку новым сообщением. Для корневого оркестратора нужен внешний инициатор (пользователь/сервер), поэтому это не полное самопереключение.

## 2. Сводка от самого агента

### Контракт

Агент лучше машины знает, какие решения load-bearing, но сервер лучше знает идентификаторы и свежие события. Поэтому handoff должен быть гибридным.

**Server-authored metadata** (не доверять модели): source/target runtime+model; session id/name; scope/cwd/branch; task id; turn generation; timestamp.

**Agent-authored payload**, предпочтительно как типизированные поля, а не свободный эссе-текст:

- `objective`: текущая задача и критерий готовности;
- `completed`: что уже сделано, с проверяемыми результатами;
- `decisions`: принятые решения и краткая причина;
- `current_state`: где остановился агент;
- `next_action`: один конкретный следующий шаг;
- `blockers_questions`: блокеры и незакрытые вопросы;
- `constraints`: запреты, разрешения, gate, что нельзя повторять;
- `artifacts`: пути файлов, commit SHA, dirty files, test/evidence paths;
- `side_effects`: уже совершённые внешние действия, чтобы новая модель их не переиграла.

После payload сервер добавляет ограниченный **recent machine tail**, включающий более новые user/assistant события после точки сводки и выборочные tool outcomes/side effects. Это страхует забытую деталь и гонку «сводка написана, затем в ходе произошло ещё событие».

### Отказ и мусор

Можно формально проверить schema, обязательные непустые поля, размер и соответствие target, но нельзя надёжно определить, истинно ли утверждение «tests passed» или не забыл ли агент критический blocker. Поэтому смысловой quality score не должен решать судьбу истории.

Правило fallback:

1. **schema-valid** агентская сводка → metadata + сводка + machine tail;
2. нет сводки, timeout, schema/size invalid → metadata + улучшенный machine tail;
3. switch был запрошен, но handoff не удалось построить/сохранить → fail loud и **не переключать**, вместо тихой потери контекста.

`schema-valid` означает только корректную форму/размер. Правдоподобный, но ложный payload не блокирует switch; machine tail снижает ущерб и даёт проверяемые anchors, но не валидирует утверждения агента.

Текущий `last_summary` не годится как единственный fallback: при runtime change любой непустой `last_summary` полностью обходит `_build_runtime_handoff()` и режется `_bounded_summary(..., 4000)` (`app/session.py:2115-2119`, `_LAST_SUMMARY_MAX_CHARS=4000` в `app/session.py:182,268-275`). Нужен recent tail **после** summary, а не выбор одного из двух источников.

**LIKELY — design inference; контр-доказательство учтено:** гибрид уменьшает blast radius плохой сводки, но сам текст модели остаётся недоверенным и может содержать ошибку.

## 3. Настоящая история: что физически хранится и можно ли подделать

### Claude Code / Agent SDK 0.2.114

Установленный Claude Code: `2.1.197`; `claude -r <session>` официально возобновляет по id/name [1]. Реальный transcript `Orchestra-orchestrator` лежал в `~/.claude/projects/-home-kesha-orchestra/<session-id>.jsonl`: 51 валидная JSONL-строка/267 026 bytes в точке замера. Верхние типы: `assistant=22`, `user=13`, `ai-title=5`, `queue-operation=4`, `last-prompt=4`, `attachment=3`; внутри сообщений были `tool_use=11`, `tool_result=11`, `thinking=8`, `text=3`. У 37 дочерних UUID-событий не было ни одной отсутствующей `parentUuid`; это граф событий, а не простой массив chat messages.

Agent SDK `SessionStore` официально вызывает `load(session_id)` до запуска subprocess и материализует возвращённые JSON objects как временный JSONL; `append()` получает новые записи [2][3]. Но установленный `types.py` определяет `SessionStoreEntry` как внутренний discriminated union, а документация требует pass-through совместимых записей. Seam поддерживаемый, provider-neutral schema — нет.

На свежем `CLAUDE_CONFIG_DIR` под `/tmp` Claude принял минимальный target-native transcript из **одной** `type=user` JSONL-записи, возобновил заданный UUID и в следующем ходе дословно вспомнил маркер. Raw Codex rollout, просто переименованный в Claude project JSONL, завершился `No conversation found ...`, exit 1. Тот же однострочный transcript был возвращён custom `SessionStore.load()` SDK 0.2.114: SDK материализовал временный JSONL, Claude вспомнил маркер, а store получил шесть appended native entries; SDK затем удалил temp materialization. Полная запись и sanitized команды/вывод — [`transcripts/research.md`](transcripts/research.md#claude-sdk-02114-sessionstore).

**CONFIRMED — tier 1 isolated direct+SDK experiments + tier 2 official docs/source:** Claude принимает синтетическую историю и имеет поддерживаемый storage seam, но для синтеза всё равно надо генерировать его собственные version-specific entry types. Raw foreign JSONL не переносится.

### Codex CLI / app-server 0.146.0

Установленный `codex-cli 0.146.0` хранит rollouts в `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Собственный rollout этого исследования содержал 209 валидных строк/около 890 KiB в точке замера: `response_item=146`, `event_msg=60`, по одному `session_meta`, `world_state`, `turn_context`. Среди payload были `reasoning=47`, `custom_tool_call=45`, `custom_tool_call_output=44`, `token_count=44`, `message=10`; у 47 reasoning items было `encrypted_content`.

Официальный app-server умеет `thread/resume` тремя способами: `history`, `path` или persisted `thread_id`; приоритет `history > path > id` [4][5]. Но current protocol помечает `history` как experimental и «FOR CODEX CLOUD - DO NOT USE» [5]. Официальные тесты сами создают fake rollout в изолированном `CODEX_HOME`, значит disk forgery технически предусмотрена тестовым harness, но не объявлена стабильным публичным импортным API [6].

Три изолированных опыта на установленной 0.146.0 дали положительный marker recall:

1. Двухстрочный forged rollout (`session_meta` + user `response_item`) в отдельном `CODEX_HOME` был принят `codex exec resume`; следующий turn вернул маркер. Raw Claude JSONL как Codex rollout был разобран как пустой и отвергнут.
2. `thread/resume.history` без capability ответил exact `-32600: thread/resume.history requires experimentalApi capability`; с `initialize.capabilities.experimentalApi=true` принял два `ResponseItem`, создал rollout и вспомнил маркер.
3. `thread/resume.path` без capability дал аналогичный `-32600`; с capability принял forged rollout по произвольному absolute `/tmp/.../forged.jsonl` и вспомнил маркер.

У `history` важная семантика: переданный request `threadId` игнорируется, app-server возвращает **новый** id. Текущий `CodexBackend.connect()` считает любое отличие returned id от requested ошибкой (`app/backend_codex.py:408-421`), поэтому этот seam нельзя подставить в обычную resume-ветку без отдельного import→new-native-id перехода. `path` вернул id из metadata forged rollout. Дословные JSON-RPC request/response и второй свежий acceptance run — [`transcripts/research.md`](transcripts/research.md#literal-acceptance-appendix).

**CONFIRMED — tier 1 isolated CLI/app-server experiments + tier 2 protocol source:** Codex 0.146.0 принимает target-native forged rollout, experimental `history` и experimental `path`; raw Claude JSONL не принимает. `history` — самый чистый измеренный seam для observable messages, но его cloud-only/unstable warning и новый thread id не позволяют считать его стабильным drop-in API.

### Grok CLI

На текущем host Grok binary и `data/grok-home` отсутствуют, поэтому современный live import/resume не проверен. Предыдущее изолированное исследование Orchestra #95 на Grok `0.2.112` измерило store `~/.grok/sessions/<url-encoded-cwd>/<sessionId>/` с `events.jsonl`, `updates.jsonl`, `chat_history.jsonl`, `system_prompt.txt`, `summary.json`, `rewind_points.jsonl`; `session/load` после смерти процесса вспомнил контрольный маркер при том же `(cwd, sessionId)`.

Текущая xAI документация заявляет `grok import [targets...] — Import sessions from Claude Code` [7]. Однако current open-source код даёт контр-доказательство: `claude_import.rs` импортирует Claude **settings** в TOML [9]; foreign session picker формирует prompt `/resume-claude <native-id>` [10], а loader создаёт новую Grok session и отправляет этот slash-command [11]. Код bundled skill, который обрабатывает команду, в просмотренном репозитории не найден; прямого доказательства переписывания Claude JSONL в Grok native store нет.

**CONFIRMED только для 0.2.112 — tier 1 прежний локальный experiment:** нативный Grok store привязан к cwd+id и resume работает. **UNCERTAIN для current import — конфликт tier 2 official docs/source и нет binary:** `/resume-claude` может читать/суммаризовать foreign transcript, но это не доказанный перенос настоящего native history.

### Итог по переносимости

Физически синтезировать **часть наблюдаемой беседы** в целевом формате возможно там, где установленная версия принимает custom store/history/path. Но это не «настоящая история» в сильном смысле:

- Codex `encrypted_content` нельзя осмысленно сгенерировать из Claude thinking;
- Claude UUID/parent graph, Codex `ResponseItem`/turn context и Grok events различаются;
- tool ids, MCP call/result schema, approval state, token counters и provider events не имеют взаимно-однозначного отображения;
- импорт необрезанных tool results увеличивает риск вынести секреты и повторить уже совершённый side effect;
- undocumented disk schema меняется вместе с CLI, тогда как поддерживаемый handoff остаётся обычным user-visible контекстом.

**REFUTED — tier 1 format comparison:** raw/native файлы не взаимозаменяемы, и не найден/не поддерживается единый converter, который создаёт исполнимую нативную историю каждого target runtime без потери provider-specific semantics. Это не доказывает логическую невозможность archival container, способного хранить opaque события как вложения. **LIKELY:** узкие lossy adapters observable user/assistant/tool history возможны, но должны быть version-pinned, протестированы каждым CLI и использоваться только как ускоритель поверх обязательного provider-neutral handoff.

## 4. Что теряется сегодня

### Точный алгоритм

`_build_runtime_handoff()` flush-ит pending log writes, затем `get_logs(id, limit=120)`. SQL сначала выбирает последние 120 строк **всех типов**, только после этого builder оставляет `user_message/text`, исключает platform note, режет каждую запись до первых 6 000 знаков и идёт newest→oldest под бюджет 32 000 block chars (`app/db.py:1101-1118`, `app/session.py:2056-2093`).

Если очередной старый block не помещается, код при `remaining > 200` добавляет `block[-remaining:]`: суффикс может начинаться без `User:`/`Assistant:`, посреди строки/слова. Финальный `"\n\n".join()` не входит в counter, поэтому реальный предел может превышать 32 000 на `2 × (число блоков - 1)`.

### Замер длинной живой сессии

Предварительно зафиксированный selector выбрал из online backup с 91 sessions/54 914 logs сессию с максимальным объёмом eligible `user_message+text` среди имеющих ≥120 логов: `seedon-orchestrator`, 7 251 log row. Использовался `sqlite3.Connection.backup()` из URI `mode=ro`; ни live DB, ни сессия не менялись.

| Этап | Строки | Смысловые знаки | Потеря на этапе |
|---|---:|---:|---:|
| Вся eligible user/assistant history | 1 284 | 1 760 169 | — |
| После newest-120 и type filter | 24 | 24 830 | 1 260 строк / 1 735 339 знаков |
| После per-row 6 000 | 24 | 15 163 | ещё 9 667 знаков одной user row |
| После 32k formatter | 24 full, 0 partial | 15 163 | 0 |
| Финальный handoff с labels/separators | 24 | 15 433 total | +270 framing |

Итого retained: **1,87% строк и 0,86% смысловых знаков; потеря 99,14%**. В newest-120 было `tool=38`, `tool_result=38`, `status=20`, `text=16`, `user_message=8`: 76/120 (63,33%) window заняли tools, которые затем целиком выбросились.

В полной выбранной сессии исключены 4 646 tool/tool_result rows/10 463 792 знака; только в newest-120 — 76 rows/196 335 знаков, то есть 12,95 объёма сохранённой смысловой payload. Среди пропавшего были сырые records для утверждений «all 9 ads» и два результата по 20 000 знаков; без них новый runtime может сохранить вывод, но не проверить его и не сделать альтернативную группировку без повторного внешнего запроса. Конкретные log ids и обезличенные фрагменты — в [`handoff/research.md`](handoff/research.md#omitted-toolsresults-and-concrete-impact).

Ни одна из 91 live sessions не вошла в partial-suffix branch 32k: максимум недавней capped semantic payload был 21 907 знаков. Поэтому утверждение «сегодня режет по-живому на 32k» **REFUTED на текущем snapshot**. Реальная per-row обрезка была: шесть сессий имели записи >6 000; у выбранной строки отрезано 9 667 знаков. Кроме того, newest-120 граница реально оставила assistant answer, а непосредственно предшествующий user question оказался строкой 121 и не попал в handoff.

**CONFIRMED — tier 1 exact production-algorithm measurement:** активный ограничитель сейчас 120 all-type rows, затем 6k per-row; 32k — латентный, но не наблюдавшийся на snapshot риск.

### Что реально получил `Orchestra-orchestrator` при эстафете Codex → Opus

В логе этой сессии `codex context compacted` — id 54 866, `2026-08-11T05:25:14Z`; model change — id 54 957, `2026-08-11T07:13:04Z`. `last_summary` имеет 3 337 знаков; по коду runtime change при непустом summary использует именно его и не вызывает builder. Между compact и switch накопились:

- 14 eligible user/text rows / 6 580 знаков;
- 65 tool/tool_result rows / 251 149 знаков.

Они не вошли в `last_summary`. После switch первое «Ну как» вызвало шесть tool calls и шесть results/15 119 знаков до ответа за 50 секунд; среди вызовов были повторные `list_agents`, git/task/status checks. Это совместимо с восстановлением утраченного свежего состояния, но причинная связь **LIKELY, не доказана**: пользовательский вопрос сам требовал актуального status lookup.

**CONFIRMED — tier 1 log/DB measurement + tier 2 branch code:** фактическая эстафета несла 3 337 знаков старого summary, а не свежий 120-row fallback. **LIKELY:** часть первых повторных reads была ценой такого handoff.

## Рекомендация для Phase 2

Минимальный один путь решения:

1. Добавить self-only deferred request, не расширять семантику синхронного `change_worker_model`.
2. Сохранять state machine `requested → switched → continuation_inflight → continuation_submitted`; применять switch только после terminal source generation, `IDLE`, отсутствия active turn/bg jobs и до flush обычной queue. Перед **любым** первым send (queued или synthetic) атомарно claim-ить durable record по `switch_id`; uncertain `continuation_inflight` не авторетраить и не возвращать в обычный flush.
3. Передавать typed agent summary + server metadata + bounded recent machine tail; отсутствие/invalid summary автоматически означает machine tail, а не потерю.
4. Считать logs по semantic turns, а не по 120 сырым rows; не обрывать turn boundary. Включать не raw tool dumps, а компактные tool outcomes: имя, успешность, изменённый объект/файл, side effect и ссылку на log id.
5. Не строить общий cross-provider transcript converter. Если после отдельного product gate нужен target-native import, делать version-pinned adapter только для подтверждённого supported seam и всегда сохранять provider-neutral handoff как fallback.

## Counter-evidence и ограничения

- Текущий механизм уже работает на реальной эстафете; исследование не утверждает, что новая модель получает ноль контекста. Оно измеряет неполноту и stale tail.
- Same-model self-call проходит как no-op до RUNNING guard; значит запрет относится к реальному model change, не ко всем вызовам.
- 32k suffix-cut доказан кодом, но не воспроизведён ни на одной из 91 текущих сессий; его нельзя выдавать за текущий инцидент.
- Installed Codex 0.146.0 действительно принял `history/path`, но только после opt-in `experimentalApi`; generated schema прямо предупреждает `UNSTABLE` и `FOR CODEX CLOUD - DO NOT USE`.
- xAI docs говорят «Import sessions», current source показывает settings import и `/resume-claude` prompt. Без Grok binary/skill implementation нельзя выбрать одну трактовку как доказанную.
- Синтетическая история улучшила recall маркера на Claude и Codex и всё равно может быть семантически неполной: marker recall — критерий приёма CLI, не proof для tools, images, reasoning, compaction, subagents или длинной истории.
- Generic backend API не даёт exactly-once receipt для continuation. Предложенная at-most-once граница предотвращает автоматический дубль, но после crash в `continuation_inflight` требует явного восстановления; бесшовный wake во всех авариях не обещается.

## Codex second opinion

Первый review-round не смог прочитать workspace из-за `bwrap: loopback: Failed RTM_NEWADDR`; это записано как infrastructure failure, не verdict. Повторный review получил target и raw evidence embedded-текстом и нашёл blocking crash-window между switch и continuation, затем тот же window в queued-message ветке. После введения общей state machine, `claimed_by=switch_id`, at-most-once default recovery, явного `WAITING` predicate и сужения двух overclaims финальный verdict: **Approved for Phase 1 research; blocking findings отсутствуют**. Полная исходная критика и два раунда разрешения сохранены в [`codex-review-research.md`](codex-review-research.md).

## Затрагиваемые файлы и риски будущей реализации

Research не менял код. Если Phase 2 будет одобрена, ожидаемые точки:

- `app/session.py` — lifecycle, durable pending switch application, handoff composition;
- `app/session_turns.py` — строгий post-terminal ordering;
- `app/mcp_stdio.py` — новый self-request contract/caller identity;
- `app/routes/sessions.py` — API validation/conflict semantics;
- `app/db.py` и schema/migration — durable pending intent, если не помещать его в существующую session row;
- backend-specific adapters — только если отдельно одобрен нативный import;
- focused tests для delivery-before-disconnect, restart recovery, pending queue ordering, bad summary fallback и one-shot clearing.

Blocking-риски: потеря handoff при clearing до успешного send; двойной wake/replay side effect; switch между terminal event и pending flush; restart с наполовину применённой сменой; секреты в raw tool results; caller может переключить чужого worker, если self-only identity не валидируется сервером.

## Источники

Evidence tiers: tier 1 — выполненный experiment/measurement; tier 2 — первичный код/официальная документация; tier 3+ не использовались для load-bearing выводов.

1. [Claude Code CLI reference: `--resume`](https://code.claude.com/docs/en/cli-usage) — tier 2, открыто 2026-08-11.
2. [Claude Agent SDK: Custom session storage](https://code.claude.com/docs/en/agent-sdk/session-storage) — tier 2, открыто 2026-08-11.
3. [Claude Agent SDK Python `client.py`](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/client.py) + установленный `types.py/client.py` 0.2.114 — tier 2.
4. [OpenAI Codex app-server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) — tier 2.
5. [Codex `ThreadResumeParams` protocol source](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/thread.rs) — tier 2.
6. [Codex app-server fake rollout test helper](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/common/rollout.rs) — tier 2.
7. [xAI Grok CLI reference](https://docs.x.ai/build/cli/reference) — tier 2.
8. [xAI Grok Build overview](https://docs.x.ai/build/overview) — tier 2.
9. [xAI Grok Build `claude_import.rs`](https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-shell/src/claude_import.rs) — tier 2 counter-evidence.
10. [xAI Grok Build `foreign_sessions.rs`](https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-pager/src/app/foreign_sessions.rs) — tier 2 counter-evidence.
11. [xAI Grok Build `dispatch/session/load.rs`](https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-pager/src/app/dispatch/session/load.rs) — tier 2 counter-evidence.
12. Local code at commit `47949781c9595ecf6fd1dc8f8c88f4d1665b5873`, live SQLite online backup and installed CLI/session files; reproducible commands are in the two raw research artifacts — tiers 1–2.
