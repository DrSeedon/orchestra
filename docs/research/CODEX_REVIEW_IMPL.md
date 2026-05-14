## Tests

`uv run pytest` не дошел до тестов: сначала `uv` пытался писать cache в read-only `/home/maxim/.cache/uv`, затем с `UV_CACHE_DIR=/tmp/uv-cache` уперся в запрет сети при скачивании `anyio`.

Fallback `python -m pytest` на системном Python 3.13 собрал 84 теста, но пошли массовые ошибки/фейлы и прогон завис на `tests/test_session.py`; я остановил его. Точечные подтверждения:
- `python -m pytest tests/test_db.py::TestSaveAndGetSession::test_round_trip -q` падает: `sqlite3.ProgrammingError: You did not supply a value for binding parameter :context_pct`.
- `python -m pytest tests/test_manager.py::TestCreateSession::test_returns_session -q` падает: тесты патчат удаленный `AgentSession._make_client`.
- `python -m pytest tests/test_session.py -q` зависает после первого теста из-за устаревшего мокинга старого session API.

## Summary

ClaudeBackend в основном сохраняет старое поведение `session.py`: SDK options, auto-approve, ResultMessage accounting, subagent events и reconnect перенесены без заметной потери критичной логики. CodexBackend покрывает базовый happy path и synthetic `turn_end` при смерти процесса, но есть пробелы вокруг ошибок JSONL/turn loop и практической доставки MCP-конфига. DB-миграция добавляет колонку корректно для существующих строк, но `save_session()` теперь не backward-compatible с dict'ами старой формы и прямо валит текущие тесты. Явных import cycles не нашел: backend-и импортируются лениво из `session.py`, обратные импорты только локальные.

## Findings

blocking: `app/db.py:94` — `save_session()` безусловно требует `context_pct`, `context_tokens`, `progress_pct`, `progress_status`, `backend_type` в переданном dict. Старые callers/tests, которые сохраняют session dict старой формы, теперь падают до SQL (`ProgrammingError` на `:context_pct`). Это легко чинится нормализацией defaults внутри `save_session()` перед `execute`: добавить значения по умолчанию для новых колонок, если ключи отсутствуют.

blocking: `app/session.py:184` — `_codex_turn_loop()` ловит любое исключение из `self._backend.events()`, логирует его, но не переводит сессию из `RUNNING` в `IDLE`; при наличии очереди `finally` вызывает `send()`, который из-за `status == RUNNING` снова кладет сообщение в очередь. Итог: один неожиданный parser/subprocess bug в Codex event stream может навсегда оставить worker running и заблокировать очередь. Минимальный фикс: в `except Exception` или `finally` выставлять `IDLE`/persist, если turn_end не был обработан, и только после этого drain pending queue.

suggestion: `app/manager.py:105` — Codex MCP config пишется в `<worktree>/.codex/config.toml`, но `codex exec --help` для 0.124.0 говорит про загрузку `$CODEX_HOME/config.toml`, а smoke test с битым `.codex/config.toml` под `-C <worktree>` не показал попытки его распарсить. `CodexBackend` также не выставляет `CODEX_HOME` и не передает `mcp_servers...` через `-c`, поэтому Codex workers, скорее всего, стартуют без Orchestra MCP и не смогут нормально `send_message`/`list_agents`. Нужно либо подтвердить правильный project config path для Codex 0.124.0, либо передавать MCP явно через `-c`, либо запускать с per-worker `CODEX_HOME`.

suggestion: `app/backend_codex.py:85` — backend игнорирует top-level Codex JSONL events типа `{"type":"error","message":"..."}`. Я локально видел такие события от Codex 0.124.0 при websocket/retry failure; сейчас они не попадают в logs, а `_handle_turn_end()` еще и не выводит `stderr_tail`, так что resume/network/auth ошибки будут плохо диагностируемы. Добавить ветку `elif etype == "error": yield AgentEvent("error", data.get("message", ""))`; можно также логировать `stderr_tail` при `ok=False`.

question: `app/backend_codex.py:53` — resume запускается как `codex exec resume --json <thread_id> <message>` без `cwd=self.cwd` на subprocess. План говорит, что `-C`/sandbox наследуются, и CLI действительно не принимает `-C` на resume, но стоит acceptance-тестом проверить, что resumed Codex turn реально остается в worktree, а не в cwd процесса Orchestra. Если нет, единственный безопасный рычаг тут — `create_subprocess_exec(..., cwd=self.cwd)`.

## Verdict

needs fixes
