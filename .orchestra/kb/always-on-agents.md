# Always-On Agents — 5 базовых примитивов ядра Orchestra (16.11.2026)

Реализация архитектурного паттерна Anthropic «Building always-on agents» (спящий агент с 0 токенов простоя, пробуждаемый через durable таблицы и планировщик):

1. **Нативные таймеры (`app/timers.py`, `/api/timers`, MCP `set_timer` / `list_timers` / `cancel_timer`):**
   - `follow_up`: разовый будильник (`delay_seconds` или `due_at`) с опциональным автогашением (`cancel_on_sender`, `cancel_on_scope`) через триггеры SQLite при приходе ответа раньше срока.
   - `schedule`: регулярное расписание (`interval_seconds >= 10` или 5-польный `cron_expr` с `ZoneInfo` и защитой от catch-up шторма после простоя).
   - Срабатывание атомарно обновляет строку `timers`, пишет идемпотентное событие в `mailbox` и будит сессию через коалесцирующий `wake_recipient`.

2. **Event Inbox (`app/mailbox.py`, `app/message_deliveries.py`, `/api/inbox/events`):**
   - Поддержка `idempotency_key` (`UNIQUE(recipient, scope, idempotency_key)` для непустых ключей).
   - Структурированный батчинг пачек `<event-inbox count="N">` и single-flight пробуждение на адрес `(recipient, scope)` вместо серии конкурирующих ранов.
   - Устранён дедлок `WAITING_NEXT_TURN` (`TODO.md:58`): новый `QUEUED`/`PREPARING` вход позади `WAITING_NEXT_TURN` на `IDLE`/`WAITING` сессии немедленно восстанавливает недостающие `mailbox`-копии, снимает `Stop`-удержание и доставляет очередь без ожидания 120 с.

3. **Формализованный Outbox (`app/outbox.py`, `/api/outbox`, MCP `outbox_enqueue` / `outbox_list`):**
   - Каналы `dashboard`, `telegram`, `webhook` (только публичный HTTPS с пиннингом DNS и `Idempotency-Key`, без редиректов и прокси окружения).
   - Контроль темпа (`min_interval_seconds` на адресата), тихие часы (`quiet_start_hour..quiet_end_hour`, `urgent=True` проходит сразу), ретраи с экспоненциальным backoff и реестр уже сказанного `outbox_said_ledger` (`dedupe_key` и SHA-256 нормализованного текста).

4. **Deferred Approvals (`app/approvals.py`, `/api/approvals`, MCP `request_approval` / `list_approvals` / `cancel_approval`):**
   - Сохранение карточки подтверждения без удержания живого процесса модели; решение оператора (`POST /api/approvals/{id}/resolve`, защищено от самоодобрения агентом `403`) атомарно переводит карточку и будит сессию событием в `mailbox` с сохранённым `payload` и `context_note`.

5. **Фоновый Dreaming (`app/dreaming.py`, `/api/dreaming`):**
   - Бесплатная детерминированная курация памяти в простое (`0` LLM-вызовов): архивирует переросшие `<scope>/.orchestra/workers/*.md` в `<scope>/.orchestra/workers/archive/`, сжимает живой файл в бюджет `WORKER_MEMORY_L1_BUDGET_CHARS` с актуальными `tm_tasks` пойнтерами и ведёт компактный дайджест завершённых длинных сессий (`>= 12` ходов).
