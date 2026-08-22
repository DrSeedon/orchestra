# #368 — План: счётчик запросов OpenRouter (1000/сутки, 20/мин) в полосу лимитов

Research: docs/tasks/368/research.md (гибрид: локальный счёт + /activity). Красные тесты: коммит 976a43a7, `uv run python -m pytest tests/test_openrouter_counter.py` → 10 failed (ImportError отсутствующих модулей = отсутствующее поведение; T4 — AssertionError на анкор).

## Что строим

Гибрид из research.md:
1. **Локальный счёт** каждой HTTP-попытки к POST /chat/completions (включая ретраи, 429/5xx, транспортные ошибки — требование оркестратора: «считать то же, что тратит квоту», консервативно в большую сторону).
2. **Сверка за вчера** через `GET /api/v1/activity` (management key): `delta = provider - local` как ЧИСЛО в API-ответе; расхождение не списывается молча на «другие машины» — рядом публикуется разбивка локальных попыток по статусам (2xx vs отклонённые), чтобы отделить «чужой расход» от «провайдер не считает отклонённые».
3. **Полоса** в дашборде: сутки n/1000 + минутное окно m/20; недоступность источника — явная подпись, никогда не ноль.

## Контракт счётчика (verbatim, не менять при имплементации)

```python
# app/openrouter_counter.py — единица = одна HTTP-попытка
record_attempt_start(ts: float | None = None) -> int | None   # INSERT, id строки
record_attempt_status(attempt_id: int | None, status: int | None) -> None
today_count() -> int                      # строки с UTC-полуночи
minute_count(window_sec: int = 60) -> int # скользящее окно
local_day_count(day: str) -> int          # 'YYYY-MM-DD' UTC
status_breakdown(day: str) -> dict[str, int]   # {"200": n, "429": n, "none": n}
today_utc() -> str
day_of(ts: float) -> str
healthy() -> bool
```

Хук в llm.py: `stream()` перед каждой `_one_attempt` зовёт `record_attempt_start()`; `_one_attempt(body, headers, attempt_id)` после проверки `resp.status_code` зовёт `record_attempt_status`. Все вызовы счётчика обёрнуты try/except → сбой счётчика НЕ рвёт стрим, но гасит `healthy()` (видимо в API, не тихо).

Таблица (app/db.py, init_db + миграция):
```sql
CREATE TABLE IF NOT EXISTS openrouter_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,          -- unix UTC
  day TEXT NOT NULL,         -- 'YYYY-MM-DD' UTC, денормализация для быстрых дневных сумм
  status INTEGER             -- NULL = ответ не получен (транспортная ошибка)
);
CREATE INDEX IF NOT EXISTS idx_or_attempts_ts ON openrouter_attempts(ts);
CREATE INDEX IF NOT EXISTS idx_or_attempts_day ON openrouter_attempts(day);
```
Чистка: при `record_attempt_start` раз в ~100 записей DELETE ts < now - 31*86400.

```python
# app/openrouter_activity.py — провайдерская правда за завершённые сутки
reconcile(day: str, provider_requests: int, local_count: int,
          local_by_status: dict[str, int]) -> dict
# → {"day", "provider_requests", "local_requests", "delta", "local_by_status"}
#   delta = provider - local БЕЗ clamp (отрицательный тоже честное число)
fetch_day_sync(day: str) -> dict
# → {"available": True, "requests": n, ...} | {"available": False, "reason": str}
#   нет OPENROUTER_MANAGEMENT_KEY → available False, reason про key, БЕЗ сети
#   day >= сегодня UTC → available False, reason "...completed UTC days", БЕЗ сети (F9)
#   сеть: GET /api/v1/activity?date=<day>, Bearer management key; сумма requests по строкам
_http_get_json(url, key) -> tuple[int, dict]   # шов для тестов
```

Ветка /api/usage (system.py):
```python
_get_openrouter_usage() -> dict
# доступно: {"available": True, "source": "local", "daily": {"count", "limit": 1000},
#            "minute": {"count", "limit": 20, "window_sec": 60},
#            "reconciliation": <reconcile-дикт | None>, "healthy": bool}
# счётчик сломан: {"available": False, "reason": ...} — НЕ ноль (тест T3)
```
Кеш: суточное число меняется каждым запросом — читать счётчик напрямую (локальный SQLite, дёшево); reconciliation — свой TTL-кеш 1ч + failure-TTL по образцу #197. В `_get_usage_data` добавить `"openrouter": _get_openrouter_usage()`. Квотный гейт НЕ трогаем.

Фронт (usage.js, `renderUsageBar`): новый compact-provider-блок `data-usage-compact-provider="openrouter"` по образцу grok: заголовок «OpenRouter», мини-бар `daily.count/1000` c `_usageColor`, рядом `m/20` минутного окна, countdown до UTC-полуночи; reconciliation в тултипе ⓘ; `available: False` → явное «нет данных» (существующий паттерн `showUnavailable`). Ноль в начале суток честный (счётчик реально пуст), но тултип помечает источник «локальный счёт».

## Чего НЕ делаем

- app/quota_gate.py — не трогаем (harness там сознательно not_applicable: счётчик для глаз, не блокировка).
- app/static/js/app.js — не трогаем (конфликт с #366/#369; наш участок — usage.js).
- limits_card.py (/limits PNG) — вне скоупа задачи; расширение отдельной задачей, если юзер захочет.
- app.js-каталог #366 и бабблы #369 — не пересекаемся.

## Устойчивость к harness-tools (#368-смежное: батчинг тулов)

Батчинг режет число HTTP-вызовов на ход → счётчик считает вызовы, а не ходы, поэтому остаётся правдивым автоматически: полоса просто начнёт ползти медленнее. Ничего менять не нужно; лимиты провайдера те же.

## Review status плана

- **Модельного ревью НЕТ и не будет: отменено юзером 22.08 («никаких ревью им нельзя») — Codex 100%, Claude 96%, встроенный review тратит квоту OpenRouter, которую считаем.** Ни на плане, ни на реализации ревью не проводится; проверку делает оркестратор. План защищает себя красными тестами: каждый тикет называет команду, которая на сломанной реализации падает с конкретной строкой (прогоны зафиксированы до реализации, коммит 976a43a7).
- Самопроверка критичных пунктов (вместо оборванного ревью, с доказательствами):
  1. Покрытие HTTP-путей хуком: запись идёт В НАЧАЛЕ каждой итерации цикла попыток stream() → ретраи после _RetryableStatus, транспортные ошибки и mid-stream сбои уже посчитаны; статус дописывается когда известен, иначе NULL. Контракт теста T1 это фиксирует.
  2. Новый ключ `openrouter` в ответе /api/usage никого не ломает: `_provider_usage_snapshot(anthropic, codex, grok)` читает позиционные аргументы (system.py:593); фронт читает только `_usageData.anthropic/codex/grok/subscription_cost/voice_cost_usd` (usage.js); `limits_card.collect` берёт только anthropic/codex через .get (limits_card.py:127-128) — PNG-карточка не затронута.
  3. Изоляция тестов от прод-БД: autouse `_isolate_production_db` (tests/conftest.py:51-66) + guard на sqlite3.connect — новые тесты пишут в tmp_path.

### T5 — Ретрай минутной стены OpenRouter: потолок ожидания и различение двух 429

Проверка «что уже есть» (llm.py:176-208, чтение 22.08 — файл правит harness-tools, не трогаю):
- **Есть:** экспоненциальная задержка с джиттером — `_retry_delay`: `BACKOFF_BASE * 2**attempt + uniform(0, 0.5)`; рост строгий (max предыдущего окна 2.0 < min следующего 3.0), одинаковый интервал у параллельных воркеров исключён конструкцией.
- **Есть:** приоритет `Retry-After` над формулой — `_parse_retry_after` → `_RetryableStatus.retry_after`, проверяется первым.
- **Есть (T1):** каждая попытка ретрая считается счётчиком — запись идёт в начале итерации цикла независимо от логики задержек; test_t1 это фиксирует.
- **Нет:** потолка ожидания. MAX_RETRIES=3 ограничивает ЧИСЛО попыток, но не время: платформенный 429 по СУТОЧНОМУ лимиту может прийти с Retry-After на часы — сейчас ход молча зависнет на этот срок.
- **Нет:** различения платформенного 429 (есть X-RateLimit-* — наша минутная стена, ждать осмысленно) и upstream-429 («temporarily rate-limited upstream», Retry-After:5 — «занято»; research #368 F6). Сейчас оба идут одним путём _RetryableStatus.

- Files: app/harness/llm.py (только; территория harness-tools)
- Test: tests/test_openrouter_retry.py::test_t5_* (новый файл, оракул ниже)
- AC:
  1. Фейковый транспорт отдаёт подряд N×429 затем 200; monkeypatch на asyncio.sleep пишет фактические задержки: внутри одного запуска последовательность строго растёт, между двумя запусками различается (джиттер живой).
  2. Retry-After ≤ потолка соблюдается дословно (задержка == значению заголовка, не формуле).
  3. Retry-After > потолка ИЛИ суммарный бюджет исчерпан → RuntimeError с текстом, называющим лимит ожидания («упёрлись в потолок ожидания Ns»), не тишина и не вечный сон.
  4. Платформенный и upstream 429 обрабатываются РАЗНЫМИ ветками (различение наблюдаемо в тесте: разные задержки/бюджеты для ответов с X-RateLimit-* и без).
  5. Счётчик: после сценария «3 ретрая + успех» openrouter_counter.today_count() == числу HTTP-попыток — ретраи не потеряны.
- blocked-by: none (от T1-T4 не зависит; счётчик уже существует)

### Реализация T5 — кто делает

По согласованию с оркестратором: кандидат — harness-tools (владелец файла, там же его батчинг);
мой вклад — только пункт AC 5 (счётчик) и приёмка результата. Ждём решения.

## Зелёный на сломанной реализации (матрица «код есть, ведёт себя неверно»)

Красные прогоны до реализации отвечают на «исполняется ли тест»; ниже — по тикету —
может ли тест ОСТАТЬСЯ зелёным на неверном коде, и что это вскрывает.

- **T1.** Сквозная проверка двух независимых наблюдений: `len(calls)` считает вызовы HTTP-мок,
  `today_count()` читает БД — двойной учёт/недоучёт попыток ломает равенство. Мутация «считай
  только 2xx» (фильтр в трёх запросах счётчика) — красная, замерено: grep-маркер 0→3→0.
  **Остаточная дыра:** дрейф таймзоны. day_of() одна для записи и чтения — если её сломать в
  локальную таймзону, тест не заметит (обе стороны согласованы); ловится только код-ревью
  (`timezone.utc` дословно) и завтрашняя сверка с /activity за сегодня (провайдерская дата
  сдвинется относительно локальной). Принято: риск мал, внешний арбитр существует.
- **T2.** Первый reconcile-тест (92/85→7) НЕ различает clamp≥0 — поэтому существует второй с
  отрицательной дельтой; вместе пара убивает и арифметику, и clamp. fetch-тесты отсекают сеть
  моком-«бомбой»: любая реализация, дёрнувшая сеть на «сегодня», падает. **Остаточная дыра:**
  локальная дата вместо UTC в сравнении с «сегодня» расходится только у полуночи; тот же
  внешний арбитр (сверка), плюс `_today()` использует timezone.utc дословно.
- **T3.** Найден РЕАЛЬНЫМ прогоном: сиды без статусов (NULL) переживали мутанта «в ветке usage
  считать только status=200» — NULL читался как успех. Усилены сида (200 + 429 явно),
  повторная мутация (отдельный SQL с фильтром status=200 внутри `_get_openrouter_usage`) —
  красная, откат чистый. Мутация «ноль вместо available:false» — красная (grep 0→1→0).
- **T4.** Delivery-чек по природе не смотрит поведение рендера: он доказывает доставку текста
  потребителю (anchor в usage.js, грузимом dashboard.html). Сломанная математика полосы или
  пропавший branch «нет данных» им НЕ ловятся — это заявленное ограничение тикета, остаточная
  проверка AC вручную на дашборде (перечислена в AC).

## Требование апрува №2 — сбой счётчика не роняет стрим

Проба: monkeypatch `record_attempt_start`/`record_attempt_status` на RuntimeError → стрим с
фейковым транспортом доходит до `final`. Первый прогон вскрыл дыру: статус-хук внутри
`_one_attempt` был без страховки — исправлено (963738b1): оба хука обёрнуты, сбой гасит
`mark_unhealthy()` → `healthy()` ложный → `/api/usage` отдаёт available:false.

## Tickets

### T1 — Счётчик: модуль + таблица + хук в llm.py
- Files: app/openrouter_counter.py (новый), app/harness/llm.py (+~8 строк), app/db.py (таблица+миграция)
- Test: tests/test_openrouter_counter.py::test_t1_counts_every_attempt_including_retry_and_failures + test_t1_utc_day_rollover_and_persistence + test_t1_survives_restart_rows_not_memory — RED в 976a43a7
  - красная строка: `ImportError: cannot import name 'openrouter_counter' from 'app'`
- AC: `uv run python -m pytest tests/test_openrouter_counter.py -k t1` green; ретрай после 429 считается как отдельная попытка со своим статусом; сутки/минуты считаются по UTC из SQLite; сбой счётчика не рвёт стрим (ручная проба: уронить БД → стрим продолжает).
- blocked-by: none

### T2 — Сверка с /activity: модуль reconcile + fetch с деградацией
- Files: app/openrouter_activity.py (новый)
- Test: tests/test_openrouter_counter.py::test_t2_* (4 шт) — RED в 976a43a7
  - красная строка: `ModuleNotFoundError: No module named 'app.openrouter_activity'`
- AC: `uv run python -m pytest tests/test_openrouter_counter.py -k t2` green; delta без clamp; сегодня и отсутствие ключа отсекаются ДО сети; живая проба с реальным ключом (Phase 3, вручную): `fetch_day_sync('2026-08-21')` → available True, requests=92.
- blocked-by: none

### T3 — Ветка openrouter в /api/usage
- Files: app/routes/system.py (_get_openrouter_usage + строка в _get_usage_data)
- Test: tests/test_openrouter_counter.py::test_t3_usage_payload_counts_and_limits + test_t3_usage_payload_never_fakes_zero_when_broken — RED в 976a43a7
  - красная строка: `ImportError: cannot import name 'openrouter_counter' from 'app'` (T3-ассерты оракулят после T1)
- AC: `uv run python -m pytest tests/test_openrouter_counter.py -k t3` green; `GET /api/usage` содержит `openrouter.daily.count/limit`, `minute`, `reconciliation`; сломанный счётчик → available False без нулей; существующие тесты usage (tests/test_codex_usage.py, test_usage_readiness.py) не краснеют.
- blocked-by: T1, T2

### T4 — Полоса OpenRouter в usage.js
- Files: app/static/js/usage.js (renderUsageBar + тултип ⓘ)
- Test: tests/test_openrouter_counter.py::test_t4_usage_bar_has_openrouter_group (delivery-чек: анкор `data-usage-compact-provider="openrouter"` в usage.js, который грузится из dashboard.html) — RED в 976a43a7
  - красная строка: `AssertionError: usage.js must render an OpenRouter provider group in renderUsageBar()`
- AC: тест green; вручную в дашборде: блок «OpenRouter» с n/1000 и m/20, countdown до UTC-полуночи, при available False — «нет данных», reconciliation виден в тултипе ⓘ; полосы Claude/Codex/Spark не изменились.
- blocked-by: T3

## Риски

- Ретраи внутри stream() спят BACKOFF_BASE — тест T1 ускоряется monkeypatch; в проде ничего не меняем.
- `_get_openrouter_usage` вызывается на каждый /api/usage (опрос 2 мин) — локальный SQLite COUNT по индексу, копейки; reconciliation под TTL.
- Параллельные #366/#369 не трогаем их файлы; мерж через check_conflict.
- Management key в .env основного чекаута; в тестовой среде его нет — путь T2 деградирует, тесты это и фиксируют.
