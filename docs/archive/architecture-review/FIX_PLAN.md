# Fix Plan — ответ на Codex Architecture Review

## Контекст для Codex

Все workaround'ы вызваны SDK багами (claude-agent-sdk issue #425, #701, #889).
SDK — единственный способ получить Claude Code agent loop программно.
Альтернативы (Codex CLI, subprocess wrapping) имеют те же классы проблем.
Цель — сделать workaround'ы **maintainable и observable**, не убрать их.

---

## Blocking Issue 1: send_to_worker не доставляет сообщение

**Codex says**: semantic break, врёт оркестратору.

**Мой ответ**: согласен на 100%. Log-only — это emergency hack.

**План фикса**: Worker Inbox
- Новая таблица `inbox(id, session_id, sender, message, delivered, created_at)`
- `send_to_worker` → пишет в inbox (мгновенно, не блокирует MCP)
- Worker prompt → "перед каждым ответом проверь inbox: `curl GET /api/sessions/{name}/inbox`"
- Новый API endpoint `GET /api/sessions/{name}/inbox` — возвращает непрочитанные
- `POST /api/sessions/{name}/inbox/{id}/ack` — mark delivered
- **Почему не session.send()**: SDK session.send() запускает turn/connect в том же event loop → блокирует MCP control path оркестратора (SDK bug #425)

## Blocking Issue 2: Spawn/Kill без tracking

**Codex says**: fire-and-forget, ошибки теряются.

**Мой ответ**: согласен. Нужен job tracking.

**План фикса**: Job Registry
- Новая таблица `jobs(id, type, name, status, error, created_at, finished_at)`
- `spawn_worker` → создаёт job "spawning" → enqueue → supervisor обновляет "running"/"done"/"failed"
- `kill_worker` → создаёт job "killing" → background task → обновляет status
- MCP tool `list_jobs` — оркестратор видит статус spawn/kill
- **Почему async**: SDK MCP handler должен вернуть result мгновенно, иначе control protocol deadlock (Codex сам это подтвердил в mcp-hang-debug review)

## Blocking Issue 3: Нет timeout'ов на SDK turns

**Codex says**: `_run_turn` может висеть вечно.

**Мой ответ**: согласен.

**План фикса**:
```python
TURN_TIMEOUT = 300  # 5 минут
await asyncio.wait_for(self._listen_loop(), timeout=TURN_TIMEOUT)
# except asyncio.TimeoutError → interrupt + ERROR status
```
- При timeout → `session.interrupt()` → если не помогло → `_cleanup_client()` → ERROR
- **Почему 300с**: Sonnet turn с MCP = 30-60с. 300с = 5x safety margin

## Blocking Issue 4: bypassPermissions

**Codex says**: hack, убрали permission layer.

**Мой ответ**: частично согласен. bypassPermissions — единственный workaround для SDK bug (can_use_tool закрывает stdin). НО можно добавить app-level safety:

**План фикса**: App-level permission policy
- Убрать копирование `.env` в worktrees (workspace.py)
- Worker system prompt: "НИКОГДА не выполняй rm -rf, git push --force, pip install"
- Orchestrator cwd = project root — ок для dev tool, НЕ ок для production
- **Почему не can_use_tool**: SDK issue — can_use_tool callback forces streaming control channel mode, which closes stdin after first ResultMessage, making second query() impossible. Это подтверждённый баг, без PR fix'а.

## Blocking Issue 5: HTTP callback hardcoded

**Codex says**: hardcoded localhost:8888, no auth.

**Мой ответ**: согласен.

**План фикса**:
- `ORCHESTRA_URL` env var, default `http://127.0.0.1:8888`
- Worker prompt template: `{orchestra_url}` вместо hardcoded
- Auth: `X-Worker-Token: {worker_token}` header — генерируется при spawn, проверяется в API
- **Почему prompt template**: worker запускается как отдельный CLI process, не может получить config программно. Prompt — единственный канал конфигурации.

## Blocking Issue 6: Тесты висят

**Codex says**: lifecycle тесты timeout'ятся.

**Мой ответ**: тесты проходят в нашем окружении (107 green за 2с). Codex не смог запустить из-за sandbox (no network → uv fails, worktrees collected by pytest).

**План фикса**:
- `pyproject.toml`: `[tool.pytest.ini_options] testpaths = ["tests"]` — exclude worktrees
- Убедиться что `uv run pytest` работает offline (deps already installed)

## Blocking Issue 7: _log/_persist fire-and-forget

**Codex says**: DB ошибки теряются.

**Мой ответ**: согласен, но low priority для dev tool.

**План фикса**:
- `_persist()` — оставить fire-and-forget (write-through cache, DB = backup)
- `_log()` — оставить fire-and-forget (потеря лога не критична)
- Добавить periodic DB health check: если write fail 3x подряд → WARNING в session status
- **Почему не await**: sync DB write в event loop блокирует SDK MCP control path (подтверждено тестами — sync _log вызывал 3+ MCP call hang)

## Blocking Issue 8: find_worker без scope

**Codex says**: может убить чужого воркера.

**Мой ответ**: согласен, easy fix.

**План фикса**:
- `find_worker(name, scope)` — добавить scope parameter
- MCP tools передают scope из orchestrator session
- **Риск без фикса**: в multi-repo setup оркестратор может случайно kill/send чужому воркеру

---

## Приоритет

1. **Issue 8**: scope в find_worker — 5 минут, zero risk
2. **Issue 6**: pytest config — 2 минуты
3. **Issue 1**: Worker Inbox — 1-2 часа, critical
4. **Issue 2**: Job Registry — 1-2 часа, important
5. **Issue 3**: Turn timeout — 30 минут
6. **Issue 5**: HTTP callback config — 30 минут
7. **Issue 4**: App-level permissions — 1 час
8. **Issue 7**: DB health check — 30 минут
