# feat-runtime-switch

- В worktree Orchestra канонический тестовый Python — локальный `.venv/bin/python` 3.12; корневой `/home/kesha/orchestra/.venv` всё ещё 3.11. Перед `uv run --active` проверять `VIRTUAL_ENV`/`python -V`, иначе можно незаметно взять несовместимый shared env.
- Перед формулировкой `Codex approved` открыть `codex-review-*.md` и проверить содержательный `Verdict`; exit 0/background completion при `bwrap`/read failure означает «вердикта нет», даже если job формально успешна.
- Merge фикса `app/mcp_stdio.py` в `main` не обновляет уже запущенный MCP subprocess этого long-lived worker: перед повторной проверкой исправленного тула нужен reconnect, иначе он продолжит исполнять pre-merge код своей ветки.
- Для внешнего review и handoff указывать immutable commit SHA, а не имя рабочей ветки: Orchestra может перенести persistent worker на `adhoc-*`, после чего diff по прежней `task-*` ветке станет пустым.
- Ошибки чужого протокола не типизировать по substring свободного `message`: сперва проверить `code`/`data`/parameter field на реальном response; структурного discriminator нет → fail-loud без догадочного fallback.
- Semantic resume-canary хранит маркер только в СТАРОМ ходе: не повторять его в текущем system/developer prompt, иначе точный recall — ложноположительный.
- Оракул границы полномочий обязан провести враждебные данные через реальный источник и публичный auth/action seam; отсутствие строки в вручную собранном безопасном объекте — вакуумная проверка.
- `bg_create(type="run")` исполняет команду через `/bin/sh`: bash-only `<(...)` падает до тестов. Для frozen-файла использовать POSIX `git show ref:path | cmp - file` либо явно оборачивать весь job в `bash -lc`.
