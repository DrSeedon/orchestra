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

## Round 2

### Tests

`python -m pytest tests/test_db.py -q` теперь проходит: `29 passed`.

Полный fallback-прогон `timeout 20 python -m pytest -q` все еще не зеленый: до timeout видны ошибки в `tests/test_api.py` и падения в `tests/test_manager.py`/`tests/test_session.py`. Часть этого ожидаемо из-за устаревших тестов, которые все еще патчат удаленный `AgentSession._make_client`; например `tests/test_manager.py::TestCreateSession::test_returns_session` падает на `AttributeError: AgentSession does not have the attribute '_make_client'`.

### Fix Status

FIXED: `app/db.py:91` — defaults в `save_session()` добавлены, старый dict больше не падает на новых bind-параметрах. Подтверждено `tests/test_db.py`.

FIXED: `app/session.py:205` — Codex turn loop теперь переводит сессию в `IDLE` после exception/no-turn_end, так что исходный stuck-`RUNNING` сценарий закрыт.

FIXED: `app/backend_codex.py:176` — top-level `{"type":"error"}` теперь мапится в `AgentEvent("error", ...)`.

FIXED: `app/session.py:84` + `app/backend_codex.py:64` — MCP config теперь передается через `-c` overrides на первом Codex turn. Это закрывает риск, что `<worktree>/.codex/config.toml` не будет загружен Codex CLI.

FIXED: `app/backend_codex.py:67` — `create_subprocess_exec(..., cwd=self.cwd)` добавлен, resume запускается из правильной директории процесса.

### New Findings

blocking: `app/session.py:211` — `CancelledError` в `_codex_turn_loop()` делает `return`, но `finally` все равно выполняется: `app/session.py:220` переводит session в `IDLE`, а `app/session.py:223` начинает drain queued messages. Поэтому `stop()`/`remove()`/`change_model()` через `_disconnect_backend()` отменяют listener на `app/session.py:511`, но при наличии `_pending_messages` cancelled Codex loop может тут же запустить следующий queued turn вместо остановки. Это ломает семантику stop/remove и может привести к неожиданным file edits после команды остановки. Минимальный фикс: в `_codex_turn_loop()` завести `cancelled = False`; в `except asyncio.CancelledError` выставлять `cancelled = True`; в `finally` не drain-ить `_pending_messages`, если `cancelled` или если идет shutdown/disconnect.

suggestion: `app/session.py:92` — `_build_codex_mcp_args()` использует ручные TOML-строки для `command` и env values (`"...{v}..."`), в отличие от уже более надежного `json.dumps()` в `manager.py`. Для обычных Linux paths это, скорее всего, работает, но кавычка/backslash/newline в scope/path/env сломают `-c`. Лучше использовать `json.dumps()` для всех TOML string values, как уже сделано для args.

### Verdict

needs fixes
