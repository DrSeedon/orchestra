# feat-runtime-switch

- В worktree Orchestra `VIRTUAL_ENV` указывает на `/home/kesha/orchestra/.venv`; для точечных прогонов использовать `uv run --active ...`, иначе uv создаёт лишнюю `.venv` внутри worktree.
- Перед формулировкой `Codex approved` открыть `codex-review-*.md` и проверить содержательный `Verdict`; exit 0/background completion при `bwrap`/read failure означает «вердикта нет», даже если job формально успешна.
- Merge фикса `app/mcp_stdio.py` в `main` не обновляет уже запущенный MCP subprocess этого long-lived worker: перед повторной проверкой исправленного тула нужен reconnect, иначе он продолжит исполнять pre-merge код своей ветки.
- Для внешнего review и handoff указывать immutable commit SHA, а не имя рабочей ветки: Orchestra может перенести persistent worker на `adhoc-*`, после чего diff по прежней `task-*` ветке станет пустым.
- Ошибки чужого протокола не типизировать по substring свободного `message`: сперва проверить `code`/`data`/parameter field на реальном response; структурного discriminator нет → fail-loud без догадочного fallback.
