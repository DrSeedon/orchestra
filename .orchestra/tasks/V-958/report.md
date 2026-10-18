# V-958 — Orchestra тратит одноразовый refresh-токен Claude CLI

## Причина (код)
В `app/routes/system.py` два пути опроса лимитов Anthropic при `PermissionError` (401) читали `refreshToken` из `~/.claude/.credentials.json` и вызывали `_refresh_oauth_token`: `_get_usage_data` (кешируемый `/api/usage`, принудительные обновления квот) и `_collect_usage_snapshot` (снимок usage каждые 5 минут). Функция делала POST на `platform.claude.com/v1/oauth/token`, возвращала только `access_token`; новый `refresh_token` из ответа выбрасывался. Refresh-токен одноразовый (по issue-ссылкам оркестратора), поэтому записанный в файл CLI токен после нашего обмена недействителен, и следующее собственное обновление CLI заканчивалось разлогином. Подтверждено чтением кода; сам эффект на ноутбуке владельца я не воспроизводил и логи ноутбука не видел.

## Исправление
- `_refresh_oauth_token` удалена (больше нигде не вызывается), `_read_oauth_credentials` возвращает `(accessToken, rateLimitTier)` — refresh-токен не читается вообще. Файл учётных данных Orchestra не пишет и раньше, и теперь.
- 401 → «лимиты Anthropic временно недоступны»: `_get_usage_data` отдаёт последний кеш и поле `anthropic_error` = `ANTHROPIC_TOKEN_STALE_REASON`; при `required_provider="anthropic"` ошибка «fresh Anthropic usage is unavailable» теперь содержит причину; снимок usage помечает провайдера `unavailable` с этой причиной.
- Журнал: стоячее состояние пишет `logger.warning` один раз (`_warn_once`), дальше `debug`; первый успешный опрос очищает причину и заново взводит предупреждение.

## Другие провайдеры (одной строкой)
Grok: `_read_grok_token` читает токен и `_fetch_grok_usage` только ходит с ним, обмена refresh-токена нет; `backend_grok` общий `auth.json` подключает симлинком, чтобы обновления оставались у самого CLI. Codex: usage берётся запуском самого `codex app-server`, обновление токена — внутри CLI, у Orchestra обмена нет. `rg` по `app/` на `grant_type|refresh_token|oauth/token|refreshToken` других обменов не находит. Править их не нужно.

## Проверка
- Новый `tests/test_v958_no_refresh_exchange.py` (4 теста): файл с refresh-токеном и tripwire на любой `httpx.AsyncClient.post` — оба пути (`_get_usage_data`, `_collect_usage_snapshot`) при 401 не делают POST и не меняют файл; `/api/usage`-путь отдаёт кеш с причиной и предупреждает один раз; снимок называет причину; восстановление очищает причину; `_refresh_oauth_token` отсутствует, refresh-токен не читается.
- Мутации (`mutation.log`): возврат обмена на пути `/api/usage` краснит 2 теста, на пути снимка — 1.
- Обновлены существующие тесты под двойной возврат `_read_oauth_credentials` (test_usage_snapshot, test_usage_readiness, test_codex_usage); тест «401 без пригодного refresh» больше не подменяет удалённую функцию.
- `tests.log`: test_v958_no_refresh_exchange, test_usage_snapshot, test_usage_readiness, test_codex_usage, test_turn_usage, test_frontend, test_quota_map_api — 204 passed, 1 skipped. Перезапись трекаемого скриншота V-874 тестами откатил.
- Рестарт Orchestra нужен (Python, `app/routes/system.py`). На ноутбуке владельца нужен тот же код; уже слетевший логин Orchestra не чинит — войти в Claude Code заново.
