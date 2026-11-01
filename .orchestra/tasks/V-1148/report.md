# V-1148 — исследование позднего завершения Codex compaction

Дата: 2026-10-31. Только исследование переданной частичной копии. Рабочий код,
существующие тесты и конфигурация не изменены. Провайдеры, native session histories,
пользовательские данные и защищённые журналы не вызывались и не читались.
Реальные сессии не прерывались, не сжимались и не перезапускались; детей не запускал.

## Уровень доказательств и идентичность

- **S — исходники:** вывод из предоставленного кода, без подтверждения живым процессом.
- **P — локальный синтетический прогон:** семь сценариев на неизменённых AST-телах
  выбранных методов `backend_codex.py`, с искусственным состоянием и транспортом в памяти.
  Это не импорт приложения, не штатный JSONL harness и не интеграционный тест.
- **T — тест прочитан:** существующий тест задаёт контракт, но здесь не выполнен.
- **U — не проверено:** недостающий код/фронтенд, реальный app-server и рабочие данные.

**Точный HEAD недоступен:** в предоставленной копии нет `.git` и метаданных HEAD.
Приписывать ей ревизию родителя нельзя. Назначенная платформой ветка результата:
`task-V-1148/research-codex-compact` (из задания, локально не подтверждается).
Коммит выполняет платформа после завершения; `git commit/push/clone` не запускались.
Хеши всех девяти предоставленных Python-файлов сохранены в `source-identity.txt`.
SHA256 исследованного `app/backend_codex.py`:
`ef96690394c582881f9420408b56f6903d999bc7e68d4f4032e8f0338d3cf232`.

Runner найден: provisioned **uv 0.11.28**, default `.venv`, CPython 3.12.3.
Штатный импорт `app.backend_codex` блокируется отсутствующим
`app.runtime_process_group`. Также нет `app/__init__.py`, `backend_jsonrpc.py`,
`events.py`, `runtime_history.py`, `usage_contract.py`, `session_state.py`, `db.py`
и полного runner `scripts/run_tests.py`. `import app` создаёт namespace package,
`app.__file__ is None`; абсолютный путь его `__path__`:
`/home/<runtime-user-redacted>/orchestra-ws/<runtime-host-redacted>/hub-4cbfb6e327fb4c1b/app`.
Импортированного штатного `app/__init__.py` здесь нет. Недостающие модули и схему БД
не создавал. Исторический статус тестов в коммитах по этой копии неизвестен.

## Фактическая семантика заданной последовательности

**S + P:** локальный deadline и удалённый исход — разные поля одного объекта.
В заданной синтетической последовательности ACK в 0.007 s и S=`turn/started`
в 0.045 s ещё не означают успех. В 120 s вызывающий получает `TimeoutError`,
`outcome=timeout`, `remote_outcome=unknown`, `stage=completion notification`.
После C=`item/completed(contextCompaction)` в 120.159 s и
T=`turn/completed(status=completed)` в 120.169 s диагностика становится:

```json
{"outcome":"timeout","remote_outcome":"completed","late":true,"compacted":true,"terminal_status":"completed","stage":"completion notification","stages_seconds":{"ack":0.007,"started":0.045,"compacted":120.159,"terminal":120.169}}
```

Это совместимо с успешным удалённым завершением после истечения ожидания клиента.
Старая ошибка не заменяется успешным ответом. `stage` сохраняет **стадию выхода
вызывающего** (`caller_stage`), а не текущее состояние сервера. Начальная копия
`exception.compact_diagnostics` тоже остаётся `remote_outcome=unknown` и `late=false`.
Свежая `backend.compact_diagnostics` читает изменившийся объект; поздний переход
пишется Python logger-ом `Codex compact state ...`.

В P реальные ожидания ограничены 0.02 s, а диагностические часы искусственно
выставлены в значения задания. Это проверка переходов и формирования полей,
**не замер 120 секунд и не наблюдение сервера**. Вывод целиком: `synthetic-output.txt`.

## Пути и контракты

В колонке evidence имена тестов без пути относятся к
`tests/test_codex_compact_state.py`. S/T/P/U имеют определения выше.

| path/trigger | awaited contract | timeout/cancellation behavior | late terminal behavior | context update source | queue release | frontend-visible status | evidence symbol+test |
|---|---|---|---|---|---|---|---|
| Ручной HTTP compact: `app/routes/sessions.py:1811`, `AgentSession.compact:3433` → `_compact_codex_context:3205` | Сессионный permit резервирует `_compacting`; запрещён RUNNING; создаётся задача `backend.compact_context`, ожидается её результат. Native thread сохраняется, generic summary/новая сессия для Codex не выполняются. | Исключение backend превращается в `{ok:false, mode:native, error, compact_diagnostics, before_pct, thread_id}`; ошибка журнала `native Codex compact failed: ...`. `CancelledError` логируется с диагностикой и пробрасывается. Этот HTTP route сам дополнительного deadline не устанавливает. | Сессионная coroutine уже завершена. Поздний backend T её не возобновляет и HTTP-ответ не исправляет. | Только при успешном возврате backend: `context_tokens=last.totalTokens`, `max_tokens=modelContextWindow`; обновляет `_last_context`, процент, `known`, persist. Если usage отсутствует, процент/токены сбрасывает в 0 и `known=false`. При timeout/ошибке ветка обновления не выполняется. | `finally`: `_compacting=false`; при pending запускает `_flush_pending`, иначе при IDLE планирует hibernate; будит durable deliveries. Снятие сессионного барьера не ждёт позднего T. | Лог начала/ошибки либо `compact done (native Codex)`. Поле session status само native-компактирование в RUNNING не переводит. Фактический toast/индикатор браузера U. | S: `_compaction_permit`, `_run_compaction_start`, `_compact_codex_context`; T: `test_session_compact_path_and_hibernate`, `test_session_unknown_usage_does_not_reuse_precompact_percentage`. |
| Backend native request: `app/backend_codex.py:1142`, `thread/compact/start` | Один общий бюджет **120 s** на ACK и S/C/T: acknowledged + started + compaction evidence + terminal completed. Принимает C форм `item/completed(contextCompaction)`, `context/compacted`, `thread/compacted`; C/T могут приходить до ACK и в обратном порядке после S. | Timeout фиксирует `outcome=timeout`, cancellation — `cancelled`; сохраняет caller_stage. `finally` ставит waiting=false, отменяет незавершённый локальный request/future, снимает `_compact_future`. Если terminal отсутствует, `_compact_operation` остаётся. Этот путь не отправляет `turn/interrupt`, не отключает transport и не перезапускает сессию. | Reader продолжает редуцировать собственные уведомления. После выхода вызывающего любой соответствующий terminal фиксирует remote status, late=true и освобождает op, сохраняя outcome. Успешный late C/T не меняет отменённый future и не идёт в пользовательскую очередь. | `_record_token_usage:1476` принимает валидный `last.totalTokens` и окно в backend cache. Само C/T не содержит гарантии нового размера контекста. `compact_context` не подменяет usage старым `_runtime_context`. | Пока waiting=true backend `send` отказывает. После timeout/cancel waiting=false и обычный `send` разрешён локально; повторный **compact** запрещён, пока op остаётся unresolved. | Python diagnostics обновляются; поздняя успешная пара поглощается reader-ом, нового `AgentEvent("status", "codex context compacted")` для неё нет. | S: `_CompactOperation:106`, `_finish_compact_if_ready:1602`, `_complete_compaction_from_notification:1504`; P: caller_timeout/late_success; T: `test_success_forms_and_order`, `test_timeout_cancel_retains_owner_and_reconciles`, `test_one_deadline_includes_ack_and_completion`. |
| Автоматическая компактация Orchestra после хода/таймера: `TurnManager.schedule_context_compaction:748`, `AgentSession._fire_precompact_timer:789`, `_auto_compact:4030` | Critical: validated context ≥ threshold, обычно 95%; при известном CLI threshold — min(95, ceil(CLI/window ×100)−1). Учитывает auto_compact_enabled. Critical запускает `_auto_compact(delay_seconds=0)`; обычный Codex precompact policy — native, delay 25 min, floor по умолчанию 30%. При fire проверяет idle/waiting, известность context, backend и разрешённое окно. | В итоге вызывает тот же `self.compact()` с тем же backend deadline 120 s. `_auto_compact` перед вызовом проверяет generation/manual interrupt. Он не анализирует `{ok:false}`; таймер сохраняет весь `compact_result` и пишет строку `precompact timer compacted` даже при отрицательном результате. | Тот же detached backend owner, что у ручного пути; отдельного auto-reconciliation сессионной coroutine здесь нет. | `_last_context` после ordinary turn через `_cost.update_context_from_turn` (модуль cost не передан); deferred/unknown context может запросить API refresh. Immediate native compact success обновляет context по строке выше. | Общий `finally` `_compact_codex_context`. Generic правило >90% для workers явно исключает Codex; overflow guard в `send` ограничен Claude. | Логи `critical auto-compact triggered`, timer fired/result. Имя строки `compacted` не является проверкой `compact_result.ok`. UI rendering U. | S: `session_turns.py:50,468–497,748–776`, `session.py:621–645,747–867,1444–1470,4030`; T: в двух переданных файлах отдельного late-success теста через timer/critical scheduler нет. |
| Native automatic compaction **внутри пользовательского хода**, `CodexBackend.events:919`, `_item_started:1924`, `_item_completed:2099` | Не вызывает Orchestra `thread/compact/start`, `_CompactOperation` для неё не создаётся. `item/started(contextCompaction)` и C — события того же активного user turn; после C возможны дальнейшие output/tool события до пользовательского T. | Deadline `CODEX_COMPACT_TIMEOUT_SECONDS=120` к этому пути не применяется. 30 s тишины в `events()` при active turn дают `thinking_stream` waiting и продолжение ожидания, без завершения user turn. В просмотренном listener нет общего 120 s compact timeout. Другие внешние watchdog-ы U. | C отображается как status, но само не завершает `events`; только соответствующий `turn/completed`/process exit. Следовательно несколько минут native compaction с последующим продолжением user turn этому коду не противоречат; длительность здесь не измерена. | tokenUsage → shared `_last_call_usage`; при пользовательском T `_turn_completed` берёт last-call **input_tokens**, окно, иначе `_runtime_context` fallback; session turn-end направляет результат в cost/context слой. Native histories при исследовании не читались. | User turn удерживает RUNNING до своего T; post-turn idle actions выполняются после него. Поведение steer/внешних очередей определяется обычным ходом, не ручным compact finally. | `codex compacting context`, `codex context compacted`, при тишине waiting; далее обычный ответ. Реальный браузер U. | S: `events:919–999`, `_convert_notification:1684`, `_item_started`, `_item_completed`, `_turn_completed:2160`; T: `test_ordinary_user_turn_and_auto_compaction_are_supported`; P: ordinary_native_compaction_routing проверяет только маршрутизацию C/продолжения, не event conversion и не длительность. |
| Обычный send/queued delivery при unresolved старом compact: `backend.send:862`, `_route_notification:1618`, `session._flush_pending:2939` | `send` допускает waiting=false owner; новый `turn/start` ACK сообщает user turn ID. Ранние уведомления буферизуются в `_starting_user_turn` и разбираются после ACK. | Неуспех старого caller не создаёт пользовательский terminal. Новый компакт до освобождения старого owner запрещён. Реальное принятие нового `turn/start` ещё выполняющимся провайдером U. | Старые S/C/T обрабатываются отдельно; не завершают чужой listener и не должны выдавать старое C за C нового хода. Native user C при этом остаётся видимым. | Usage содержит отдельную тонкость shared cache, описанную ниже. Ownership хода и ownership статистики — разные проверки. | Session finally вызывает flush; flush спустя 0.3 s проверяет `_compacting`/RUNNING, admission/stop generation; очищает pending перед send, при исключении возвращает сообщения, ставит IDLE и освобождает lock. `compact_pending` не является flush-барьером. | Новый пользовательский turn может стать RUNNING и закончиться IDLE; поздний T старого компакта статус не должен уронить в IDLE. | S: `send:862–913`, `_complete_compaction_from_notification:1536–1546`, `_lifecycle_belongs_to_turn:1109`; T: `test_ordinary_send_recovers_while_unresolved_with_early_events`, `test_session_actual_send_and_listener_proceed_after_compact_timeout`, `test_session_queued_delivery_reaches_actual_listener_after_timeout`. |
| Hibernate / manual interrupt unresolved compaction: `session_hibernate.py:74`, `backend.interrupt:1127`, `session.interrupt:3113` | Hibernate требует IDLE, отсутствие pending и отсутствие `_compacting` **и** `backend.compact_pending`. Interrupt выбирает active user turn, иначе op.turn_id, и ждёт ACK до 5 s. | Автоматического interrupt при compact timeout нет. Отдельный ручной interrupt без известного turn не может отправить запрос; отсутствие ACK не ведёт к disconnect только из-за unresolved compact. Для обычного running turn сохраняется manual-stop fallback disconnect. | Late terminal снимает backend compact_pending; после него повторная проверка hibernate может пройти. Сам reducer не вызывает schedule/retry hibernate; ранее назначенный auto timer может уже закончиться отказом. | Hibernate/interrupt не являются источником postcompact usage. | Manual interrupt увеличивает stop generation, влияя на стартеры. Late compact T не будит новые session tasks напрямую. | При неизвестном исходе лог `interrupt requested; native compact outcome is unresolved`. Точный автоматический повтор hibernate после late T не подтверждён. | S: `_compact_codex_context.finally`, `_release_compact`, `SessionHibernate.hibernate_now`; T: `test_session_compact_path_and_hibernate`, `test_session_interrupt_does_not_disconnect_unknown_compact`, `test_unresolved_compact_preserves_manual_interrupt_of_ordinary_running_turn`. |
| Terminal failure / transport close / RPC reject / старые уведомления | `failed`, `interrupted`, unsupported T и non-retry error не удовлетворяют контракту успеха. RPC rejection отдельно означает request rejected. EOF будит и ACK-, и lifecycle-waiter до ожидания process wait. | Definitive ошибка при живом caller даёт failed/rejected, не искусственный timeout. Nonterminal fatal error будит caller, но owner без T остаётся unresolved. Transport close снимает owner и помечает `transport_closed`, если terminal ещё не был известен. | Late failed/interrupted/unsupported T тоже late=true и освобождает owner, outcome остаётся timeout/cancelled. Late EOF не доказывает успешное выполнение. `remote_outcome=completed` сам по себе без C не доказывает compaction. | Явно foreign thread/turn и retired turns отфильтровываются до обновления usage. Legacy без ID принимается только в совместимом exclusive lifecycle; при active user turn unscoped C/error/usage неоднозначны и поглощаются. | Retry компакта возможен после terminal/rejection/transport release; старые turn/item identities не должны завершать retry. Новый transport generation ограждает старого reader. | Terminal rejection/error может оставить failure response; поздняя remote диагностика не переписывает его. | S: `_fail_compact_transport:1231`, `_read_stdout:1292`, reducer; P: late_failed_terminal, late_transport_close, completed_without_compaction_evidence; T: `test_terminal_failure_never_ok_or_timeout`, `test_rpc_rejection_is_not_unresolved`, `test_transport_failure_wakes_every_stage_without_waiting_process`, `test_old_reader_cannot_fail_or_route_into_new_generation`, `test_preack_completed_lifecycle_transport_failure_wakes_ack_waiter`. |

## Статистика контекста и границы восстановления

1. **S:** успех компактации и известность нового context size независимы. Backend
   ждёт protocol evidence, не снижения процентов. В успешном immediate пути берёт
   `last.totalTokens`; stale runtime snapshot явно не используется для результата
   compact. Это закрепляют T `test_old_main_queue_and_stale_runtime_snapshot_are_not_evidence`
   и `test_session_unknown_usage_does_not_reuse_precompact_percentage`.
2. **S:** поздний C/T проходит только через backend reducer. Он не вызывает
   `_compact_codex_context` повторно, session persist, handoff build,
   `_cost.update_context_from_turn` или отдельный UI success event. Поэтому
   `_last_context` может продолжать показывать до-компактный процент после late success.
   `get_context` (`session.py:4994`, route `sessions.py:823`) возвращает cache.
3. **S:** следующий пользовательский T формирует usage через `_turn_completed` и
   session turn-end. В `send` сбрасывается `_last_call_usage`, поэтому свежая usage
   нового хода является обычным источником восстановления. Если её нет, есть
   fallback `_runtime_context` в исходниках; мы его не вызывали. Сессионный
   `_refresh_context_from_api` защищён backend/generation, ждёт до 5 s и требует
   `hasattr(backend, 'context_usage')`. Самого метода `context_usage` в переданном
   классе CodexBackend нет, его базовый transport отсутствует. Утверждать, что
   API polling обязательно исправит context после late success, по этой копии нельзя.
4. **S + P:** валидная tagged usage старого компакта **до его late T** может обновить
   `_compact_context_tokens`, `_last_call_usage`, `_thread_usage_total`, окно.
   **После** release turn внесён в retired set, и tagged usage того же turn
   отбрасывается до `_record_token_usage`. Unscoped usage может идти по другому
   пути. Комментарий `Include usage delivered immediately after C/T in the same batch`
   не отменяет retired-ID фильтр; варианты с explicit turn ID и без него различаются.
5. **S + P, ограниченный результат:** при одновременно active user turn matching
   tagged usage detached compact всё ещё вызывает `_record_token_usage`. Probe
   показал shared last-call input `9000 → 1000`, при сохранении user-turn ownership.
   `_turn_completed` читает этот общий cache. Итоговый пользовательский turn usage
   зависит от последующего порядка уведомлений; session end-to-end не выполнен,
   а значит неверную статистику реального пользователя этим опытом не установили.

## Как различаются timeout, late success и failure

- ACK доказывает только ответ на request. S доказывает начало lifecycle. C
  доказывает compaction notification; для контракта caller также нужен completed T.
- `outcome=timeout` или текст `native Codex compact failed` — свидетельство
  отрицательного результата **локального ожидания**. В отсутствие T удалённый исход
  остаётся unknown, а не failed. `stage` и `stages_seconds` указывают границу ожидания.
- Для заданной последовательности matching S + C + completed T вместе с
  `remote_outcome=completed`, `late=true`, `compacted=true` отличают позднее
  завершение от отсутствия compaction evidence. `outcome` при этом ожидаемо timeout.
- `remote_outcome=completed` без `compacted=true` недостаточен: reducer освобождает
  op по любому T; существует T `test_completed_terminal_without_compaction_allows_safe_retry`.
  После выхода caller late T-before-C уже освобождает и retire-ит turn; последующий
  tagged C не добавит compaction evidence. Даже полный S/C/T без ACK оставляет caller timeout на стадии request acknowledgement
  (T `test_no_ack_despite_completed_protocol_still_times_out`).
- Matching `failed`/`interrupted`/unsupported T, RPC rejection, nonretry error и
  transport loss имеют разные поля. EOF сообщает потерю transport и не устанавливает,
  что удалённый сервер не успел/успел выполнить сжатие. `late=true` означает позднее
  разрешение ownership, само по себе не означает success.
- Сниженный context%, прежний context%, наличие heartbeat или очереди сообщений
  не заменяют matching protocol evidence. Размер после сжатия без свежей usage U.
- `ignored` фиксирует invalid JSON, foreign thread/turn, legacy unscoped и ambiguous
  overlap. Диагностика не содержит raw native ID, тела ошибок или пути; причинную
  связь конкретных живых событий устанавливает родитель по своим локальным данным.

## Что действительно покрывают переданные регрессии

Все перечисленные T здесь **прочитаны, а не пройдены**. Штатная collection остановлена.

| Тест/набор | Что проверяет | Граница доказательства |
|---|---|---|
| `test_timeout_cancel_retains_owner_and_reconciles:275` | timeout/cancel × ACK/completion/terminal stages; owner остаётся; retry compact запрещён; late C/T снимают owner, late=true, C/T не попадают в общий queue; duplicate старого turn не завершает новый compact. | После late C/T прямо не утверждает сохранённый outcome и `remote_outcome=completed`; проверяет их до late. Поля после late дополнительно проверены только P. |
| `test_session_compact_path_and_hibernate:473` | Immediate success/failed/timeout/cancel через настоящие session permit/finally; expected context before/after, durable wake; unresolved блокирует hibernate, после late T ручная повторная hibernate успешна. | Persistence, handoff, scheduler и disconnect замоканы; после late T context не сравнивается; автоматический повтор hibernate не проверяется. |
| `test_ordinary_send_recovers_while_unresolved_with_early_events:415` | Старое C/T до/после ACK нового user turn; user native compact и output не теряются; один user terminal. | Fake app-server; нет поздней tokenUsage overlap и действительной задержки в минуты. |
| `test_session_actual_send_and_listener_proceed_after_compact_timeout:673`, `test_session_queued_delivery_reaches_actual_listener_after_timeout:792` | Настоящий session send/listener/flush, user RUNNING не завершается старым T, user вывод доходит, pending пустеет; old compact success не изобретается. | DB/UI broker изолированы; admission отдельно не проверяется; позднего обновления context нет. |
| `test_success_forms_and_order:174`, legacy/foreign/duplicate/retired/old-generation tests | Формы C, ACK ordering, C/T order, isolation по thread/turn/item/generation; отрицательные и разрешающие плечи. | Синтетический transport. Из этого не следует конкретная форма уведомлений установленной версии реального app-server. |
| `test_ordinary_user_turn_and_auto_compaction_are_supported:405` | C обычного user turn видим, completed T даёт успешный turn_end. | Не отправляет item/started, resumed output и не моделирует compaction дольше 120 s/30 s heartbeat. |
| `test_one_deadline_includes_ack_and_completion:706` | ACK через 0.12 s при общем бюджете 0.2 s не даёт нового полного бюджета completion. | Короткое wall-clock ожидание, не пользовательский многоминутный замер. |
| `test_native_compact_drains_terminal_before_returning:1013` в `test_backend_codex.py` | C недостаточно, ожидает T; compact usage 33124/258400, очередь пуста, native session ID тот же. | Fake request + настоящий reader, не session/UI; late success после caller timeout не проверяет. |
| `test_native_compact_missing_terminal_times_out_and_detaches:1101` в `test_backend_codex.py` | После C без T timeout; в teardown EOF снимает owner, queue пуста. | Название `detaches` не доказывает снятие owner самим timeout: assertion выполняется **после EOF**. |
| Transport failure и pre-ACK EOF/rejection tests (`:311`, `:840`, `:880`) | Failure должен разбудить caller даже при отсутствующем ACK/задержанном process.wait, не замаскироваться таймаутом/успехом. | Прочитан контракт; реальное EOF/recovery не вызывались. |

**Существенные непокрытые в переданных тестах сочетания (не рекомендации):**
полный HTTP/UI путь с late success и неизменностью первоначального response snapshot;
late success через critical auto/timer; context/session persist после late T;
tagged usage после release; late compact usage при active user turn и её влияние
на итоговый user usage; multi-minute native compact с heartbeat и resumed output;
реальный ответ app-server на новый turn/start при незавершённом старом compact;
автоматический hibernate retry после уже отказавшего timer.
Наличие покрытия этих случаев в остальных, не переданных тестах неизвестно.

## Выполненные проверки и verbatim-артефакты

Точные команды со всеми export/redirect приведены в `commands.md`; stdout/stderr
сохранены без редакции отдельными файлами рядом с отчётом:

| Артефакт | Команда/результат |
|---|---|
| `offline-tests.txt` | provisioned uv; `uv run --frozen python -m pytest tests/test_codex_compact_state.py tests/test_backend_codex.py -q`; **2 errors during collection**, `ModuleNotFoundError: No module named 'app.runtime_process_group'`, `PYTEST_EXIT=2`. Ни один test body не выполнен. Другим интерпретатором не заменял. |
| `synthetic-initial-failure.txt` | Первый вспомогательный AST probe: `PROBE_EXIT=1`, AssertionError на преждевременном ACK observer. Ошибка самого исследовательского harness; transport callback сработал раньше, чем caller обработал ACK. Исправлен только observer в новом task-файле: сигнал после `_finish_compact_if_ready`, когда acknowledged уже установлен. |
| `synthetic-six-scenarios.txt` | Повтор после исправления observer: 6 сценариев, PASS, `PROBE_EXIT=0`. |
| `synthetic-output.txt` | После добавления отдельного overlap-usage сценария: **7 сценариев, PASS**, `PROBE_EXIT=0`, wall 0.126 s. Fake diagnostic timestamps; не real duration. |
| `source-identity.txt` | Namespace import identity, отсутствие `.git`/нужных файлов, SHA256 и AST parse всех 9 переданных исходных/test Python-файлов, `PARSE_OK=9`. |
| `validation-output.txt` | Финальная сверка: `SOURCE_HASHES_UNCHANGED=9`, синтаксис task Python и таблица PASS, распространённых secret shapes не найдено, `VALIDATION_EXIT=0`. |
| `validation-initial-failure.txt` | Первый validator получил AssertionError из-за захвата следующей таблицы при проверке колонок; исправлен только диапазон task validator. Исходники и доказательные проверки не менялись. |

Полный набор `scripts/run_tests.py`, штатные regression bodies, HTTP/БД/SSE/browser,
живой Codex и настоящее восстановление контекста не выполнены. AST probe не
подменяет этих проверок. Продакшен-код и исходные acceptance/regression tests не
исправлялись. Данные о конкретной живой сессии и общий вердикт остаются у родителя.

Publication note: parent replaced runtime identity/path literals in this report and four stdout derivatives. Original bytes and hashes remain private under V-1148; source, probes and numeric evidence are unchanged. Public stdout copies are labelled publication derivatives, not verbatim originals.
