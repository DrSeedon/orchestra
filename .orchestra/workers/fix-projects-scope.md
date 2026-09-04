# fix-projects-scope

- **В worktree воркера НЕТ `.venv`.** `.venv/bin/python -m pytest` из задания падает
  `no such file or directory`. Рабочий интерпретатор — в корне чекаута:
  `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest -q tests/…`, запускать
  из своего worktree (cwd), не переходя в главный чекаут.
- **Готовая защита от записи в боевую `data/orchestra.db` уже есть — не писать свою.**
  Фикстура `portfolio_db` в `tests/test_project_roadmap_backend_425.py` подменяет
  `db.DB_PATH` на tmp, перехватывает `sqlite3.connect` и печатает инвариант
  `production sessions invariant: before=N after=N`. `tests` — пакет, поэтому
  `from tests.test_project_roadmap_backend_425 import portfolio_db, _save_session`
  работает и импортирует только фикстуру, а не чужие тесты.
- **Правку `app.js` можно проверить на НАСТОЯЩЕМ дашборде тестом, а не браузером руками:**
  `tests/test_frontend.py` поднимает реальную страницу через фикстуру `dashboard_page`
  (настоящий шаблон, ассеты, вкладки). Синтетический Playwright-харнесс
  (`tests/test_project_roadmap_frontend_425.py`) грузит скрипты вручную и реального DOM
  не даёт — там нет `#orch-picker` и подобных узлов, поэтому код, читающий страницу,
  на нём зеленеет вакуумно.
- **`record_review_outcome` требует `receipt_id`, которого НЕТ ни в артефакте ревью, ни в
  ответе `codex_review`.** Брать из боевой БД (read-only, чтение безопасно):
  `sqlite3 -readonly data/orchestra.db "SELECT receipt_id,status,job_id FROM review_receipts
  WHERE worker_name='<моё имя>' ORDER BY requested_at DESC LIMIT 3;"` — сверять `job_id` с id
  фонового джоба ревью. Строка `task-run:*` в той же выборке — не ревью, не путать.
- **Заглушки `api` в этих тестах сверяют путь ДОСЛОВНО (`path === '/api/...'`).**
  Добавил query-параметр к существующему запросу → сперва
  `rg -n "'/api/<endpoint>'" tests/`, иначе запрос молча уходит в настоящий API и падает
  не там, где сломал. Чинить префиксом (`path.startsWith('/api/x?')`), а не подгонкой
  строки под новый URL.
