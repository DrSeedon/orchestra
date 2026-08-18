# feat-quota-front — личная память

## Схема quota_controller_* сверяется ДОСЛОВНЫМ текстом CREATE
`_quota_controller_schema_complete` (`app/db.py`) сравнивает `sqlite_master.sql` с эталоном,
собранным в памяти, после нормализации только пробелов и регистра. Отсюда два следствия,
на которые я потратил время в #318:
- `ALTER TABLE ... RENAME TO` не годится для миграции: SQLite перепишет сохранённый текст на
  `CREATE TABLE "имя" (...)` без `IF NOT EXISTS`, и страж потом падает `incompatible quota
  controller object`. Мигрировать надо так: прочитать строки → `DROP TABLE` → создать ТЕМ ЖЕ
  оператором, что и путь создания (общая константа `_QUOTA_POLICY_TABLE_SQL`) → вставить строки.
- Страж РУГАЕТСЯ (raise), а не возвращает False, поэтому миграцию надо звать ДО него — и в
  `_ensure_quota_controller_schema`, и в `quota_controller_connection`.

## Sync-Playwright травит async-тесты: чинится ОБЛАСТЬЮ фикстуры, не порядком файлов
Сессионная фикстура `playwright` в pytest-playwright держит запущенный event loop до конца
СЕССИИ, и любой последующий `@pytest.mark.asyncio` падает `RuntimeError: Runner.run() cannot be
called from a running event loop`. Починено в `tests/conftest.py`: цепочка `playwright` →
`browser_type` → `launch_browser` → `browser` переопределена с модульной областью, файл закрывает
свою сессию за собой (замер #318: широкий прогон 48 failed + 24 errors → 3 failed / 0 errors,
`test_frontend.py` 82 errors → 0).

**Урок дороже самого факта:** моё первое лечение было «называй файл так, чтобы сортировался рядом,
и гоняй отдельным прогоном» — его отбил тест-гейт, потому что отдельный прогон делает ЧЕЛОВЕК, а
гейт собирает мапнутые тесты в один процесс. Лечение, которое держится на договорённости о способе
запуска, в автоматике не исполняется вовсе. Проверять такой фикс надо ровно тем прогоном, который
упал, а не «у меня локально зелено».

Диагностика загрязнения петли — тест на три строки:
`print(asyncio.events._get_running_loop())` до и после подозреваемого файла.

## Фронт этого проекта проверяется подменой файлов на живом :8888
`page.route("**/static/js/analytics.js*", → fulfill(path=<мой worktree>))` плюс то же для
`style.css`; логин берётся из `.env` (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`), форма — поля
`username`/`password`. Факт применения — `page.evaluate("typeof <новый символ>")`, а не скриншот.
Живые данные при этом идут от СТАРОГО питона (правка Python доедет только рестартом), поэтому так
проверяется именно деградация нового JS на старом бэкенде. Чтобы увидеть панель на настоящих
числах без рестарта: `curl /api/usage` с `INTERNAL_TOKEN` → `system._provider_usage_snapshot(...)`
→ `build_quota_map()` офлайн на временной БД → отдать payload в браузерный harness.

## Harness модалки аналитики
`tests/test_usage_analytics_frontend.py::_page` строит DOM-скелет и подключает мои
`app/static/js/*` и `style.css` из worktree; `window.api` там — одна заглушка на все URL.
Если нужен разный ответ по URL, переопределять `window.api` СВОИМ `page.evaluate` после `_page`.
