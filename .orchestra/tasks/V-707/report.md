# V-707 — точная телеметрия лимитов Claude и Codex

## Наблюдение на текущих версиях

Живые образцы записаны без токенов и идентификаторов аккаунта: [Claude CLI event](claude-rate-limit-event.sample.json) и [Codex app-server response](codex-rate-limits.sample.json). Вызовы сделаны 05.10.2026: Claude Code CLI 2.1.284 с установленным `claude-agent-sdk` 0.2.114; Codex CLI 0.156.1 через `app-server` и `account/rateLimits/read`.

Claude CLI прислал событие `rate_limit_event` со статусом `allowed_warning`, `rateLimitType: seven_day`, `utilization: 0.83`, `resetsAt`, `isUsingOverage: false`, `surpassedThreshold: 0.75` и `unifiedWindows`. В `unifiedWindows` сейчас есть `five_hour` (`utilization: 0.11`, `resetsAt`) и `seven_day` (`utilization: 0.83`, `resetsAt`). Это доли окна, а не проценты; текущий SDK `RateLimitInfo` также типизирует `utilization` как float от 0 до 1 и предоставляет `raw`. В живом событии нет отдельных модельных окон. Отдельные поля `seven_day_opus`/`seven_day_sonnet` из типа SDK поддерживаются преобразованием, если CLI начнёт их присылать.

Codex `account/rateLimits/read` сегодня вернул `rateLimits` и `rateLimitsByLimitId` с записью `codex`; окна содержат `usedPercent: 25` на 300 минут и `usedPercent: 14` на 10080 минут, обе величины в этом ответе целые. `credits.balance` пришёл строкой `"0"`, `hasCredits: false`, `unlimited: false`. Также ответ содержит `rateLimitResetCredits.availableCount: 2` и два объекта кредитов. В этом живом ответе не было отдельного модельного окна; нормализатор сохраняет все идентификаторы лимитов из `rateLimitsByLimitId`, например будущий `codex_bengalfox`, если он есть в ответе. Десятичный `usedPercent` поддерживается без округления, хотя фактический текущий ответ целочисленный.

## Хранение и потребители

Claude `RateLimitEvent` теперь передаёт полный `RateLimitInfo.raw` в `provider_limit` и обновляет актуальный usage-кеш. Значения из `unifiedWindows` преобразуются из доли в процент умножением на 100 без округления; окно, reset time и исходный raw event остаются доступными. Если событие пришло между REST-опросами, `/api/usage`, quota gate и следующий снимок используют его свежие данные. Исходное событие записывается журналом с временем; регулярный `usage_snapshots.provider_usage` сохраняет точные окна, reset time и raw payload.

Codex нормализация сохраняет `usedPercent` как число без округления, а полный ответ `account/rateLimits/read` кладёт в `raw_payload`. История `usage_snapshots.provider_usage` содержит все окна с `window_minutes` и `resets_at` плюс полный ответ, включая кредиты и дополнительные `rateLimitsByLimitId`. `/api/usage` получает нормализованные точные значения, а гейт уже использует числовые значения напрямую.

`turn_usage.quota_five_hour_pct`, `quota_seven_day_pct` и `quota_primary_pct` уже имеют тип SQLite `REAL`; вставка сохраняет переданные float без преобразования в int. Для новых лимитных payload достаточно уже существующего `usage_snapshots.provider_usage` JSON и журнала событий. Схема БД не менялась, миграция не требуется.

## Проверка и ограничения

Живые вызовы были только чтением текущих rate-limit данных через Claude CLI и Codex app-server. Сырые payload записаны в JSON-файлы выше. В Codex-ответе фактические проценты оказались целыми, поэтому десятичный Codex путь покрыт тестовой фикстурой, а не живым значением. Отдельных модельных окон текущие два живых ответа не содержали.

Проверки: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_rate_limit_capture_441.py tests/test_rate_limit_exact_v707.py tests/test_usage_readiness.py tests/test_turn_usage.py tests/test_codex_usage.py tests/test_usage_snapshot.py -q` → **47 passed**. Проверены SQLite round-trip дробей и raw payload для `usage_snapshots`, а также дробь в `turn_usage`. `git diff --check` прошёл. Импортированный модуль приложения: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-ratelimit/app/__init__.py`. Образцы прошли проверку на bearer/access/refresh token, email и account ID паттерны.

Python-изменения вступят в силу после рестарта владельцем; Orchestra не перезапускалась.
