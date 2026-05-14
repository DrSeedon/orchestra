## Tests
`pytest -q`: 22 passed, 23 failed, 39 errors.

Основные падения: API/manager/session тесты не могут замокать `app.session.AgentSession` (`AttributeError: module 'app' has no attribute 'session'` / `ModuleNotFoundError` / import errors), DB-тесты падают в `app/db.py:91` из-за фикстур без `context_pct`, `context_tokens`, `progress_pct`, `progress_status`. Это не "tests not applicable": Python-тесты есть, но текущий baseline красный.

## Summary
План в целом попадает в правильный уровень абстракции: `AgentBackend` маленький, `AgentEvent` плоский, а вынос Claude SDK из `session.py` оправдан. Ссылки на строки `app/session.py` в таблицах плана в основном точные: импорты действительно на `app/session.py:10`, `_auto_approve` на `app/session.py:45`, `_persistent_listen` на `app/session.py:174`, disconnect на `app/session.py:500`. Главная слабость плана не в абстракции, а в семантике выполнения Codex: inline subprocess-per-turn меняет контракт `send()` с "быстро поставить turn" на "ждать завершения turn", а текущий API/MCP слой к этому не готов. Еще не закрыты failure paths: смерть Codex-процесса, resume failures, stderr, параллельные send/interrupt и сохранение backend identity.

## Findings
blocking: Codex `send()` по плану блокирует до конца turn (`docs/research/codex-backend-plan.md:486`, `docs/research/codex-backend-plan.md:500`), но текущий HTTP API синхронно ждет `manager.send()` в `app/main.py:323`-`app/main.py:335`, а MCP stdio ждет HTTP-ответ с дефолтным timeout 30 секунд в `app/mcp_stdio.py:27`-`app/mcp_stdio.py:40` и `app/mcp_stdio.py:63`-`app/mcp_stdio.py:70`. Для длинного Codex turn `send_message` из MCP начнет таймаутиться, `/api/sessions/{name}/send` будет висеть до конца работы агента, а `_spawn_worker_loop` будет держать очередь до завершения первого задания (`app/manager.py:137`-`app/manager.py:143`). Нужно сохранить внешний контракт: `send()` должен быстро стартовать turn и возвращать управление, а Codex event consumption должен идти в task с per-session lock/queue; иначе multi-turn коммуникация через Orchestra будет ненадежной.

blocking: В CodexBackend failure path оставляет сессию в подвешенном состоянии. План обрабатывает `turn.failed` только как `AgentEvent("error")` (`docs/research/codex-backend-plan.md:295`-`docs/research/codex-backend-plan.md:297`), а `_handle_event` на `error` только пишет лог (`docs/research/codex-backend-plan.md:426`-`docs/research/codex-backend-plan.md:427`); `status = IDLE` выставляется только на `turn_end` (`docs/research/codex-backend-plan.md:437`-`docs/research/codex-backend-plan.md:456`). Если `codex exec` умер без `turn.completed`, вернул non-zero, оборвал JSONL или написал ошибку в stderr, `events()` просто делает `wait()` и обнуляет `_proc` (`docs/research/codex-backend-plan.md:299`-`docs/research/codex-backend-plan.md:300`), а session останется `running`. Нужен обязательный terminal event для любого завершения процесса: `turn_end` с failed status или отдельный `turn_error`, плюс чтение stderr, returncode и сброс `_turn_start`/`status`/persist.

suggestion: В плане есть `backend_type` в dataclass (`docs/research/codex-backend-plan.md:355`-`docs/research/codex-backend-plan.md:360`) и migration (`docs/research/codex-backend-plan.md:554`-`docs/research/codex-backend-plan.md:562`), но не показано протягивание поля через `AgentSession._to_db_dict()` (`app/session.py:532`-`app/session.py:545`), `save_session()` insert/update (`app/db.py:91`-`app/db.py:115`), `_load_from_db()` (`app/manager.py:281`-`app/manager.py:297`) и `to_dict()` (`app/session.py:550`-`app/session.py:560`). Если это забыть, после рестарта Codex-сессия с `gpt-*` может восстановиться как Claude по default `backend_type="claude"` и попытаться открыть Claude SDK с GPT-моделью. Минимальный фикс: хранить `backend_type`, но при загрузке валидировать `backend_type == backend_for_model(model)` или явно чинить/логировать mismatch.

suggestion: Inference backend-from-model-name удобен для MVP, но текущий `change_model()` разрешает смену модели без учета смены backend (`app/session.py:488`-`app/session.py:498`), а план говорит "Model change = new backend" (`docs/research/codex-backend-plan.md:653`) без правила миграции контекста. Смена `claude-* -> gpt-*` или `gpt-* -> claude-*` с тем же `session_id` сломает resume, потому что Claude `session_id` и Codex `thread_id` не взаимозаменяемы (`app/session.py:119`-`app/session.py:124`, `docs/research/codex-backend-plan.md:188`-`docs/research/codex-backend-plan.md:189`). Нужно либо запретить cross-backend model change, либо делать compact-summary + `session_id = None` + новый backend.

suggestion: `AgentEvent` достаточен как MVP-форма, но текущий набор типов теряет важный terminal/status контекст. У Claude `ResultMessage` содержит `stop_reason` и `num_turns` (`app/session.py:234`-`app/session.py:241`), а Codex failure/interrupt/nonzero returncode потребуют отличать normal end, failed end и interrupted end. Сейчас `turn_end` metadata не включает `stop_reason`/`success`/`returncode`, а `error` не завершает turn (`docs/research/codex-backend-plan.md:23`-`docs/research/codex-backend-plan.md:33`, `docs/research/codex-backend-plan.md:284`-`docs/research/codex-backend-plan.md:293`). Добавьте в terminal event `ok`, `stop_reason`, `returncode`, `stderr_tail`; это не усложняет модель, но закрывает dashboard, auto-report и recovery.

suggestion: План говорит `app/tools.py` без изменений (`docs/research/codex-backend-plan.md:579`), но это верно только если Claude orchestrator всегда использует новый stdio MCP. Сейчас `app/tools.py` все еще импортирует `claude_agent_sdk` (`app/tools.py:7`) и описывает модели только Claude в schema `spawn_worker` (`app/tools.py:37`-`app/tools.py:43`). Если Claude orchestrator продолжит получать in-process SDK MCP tools из `app/tools.py`, он не узнает про `gpt-5.*` модели и часть старых tool paths содержит уже подозрительный код (`_manager.archived`/`archive_by_id` в `app/tools.py:83`-`app/tools.py:96`, `app/tools.py:140`-`app/tools.py:144`, которых нет в `SessionManager`). Либо удалить/отключить этот путь, либо обновить schema и проверить, какой MCP сервер реально подключается к orchestrator.

suggestion: Global `~/.codex/config.toml` для Orchestra MCP недостаточно для корректной идентичности worker-а. Текущий per-session Claude MCP config задает `ORCHESTRA_SCOPE`, `ORCHESTRA_ROLE`, `WORKER_NAME` в `app/manager.py:105`-`app/manager.py:113`, а `mcp_stdio.py` использует их для `send_message`, `list_agents`, `update_progress`, `send_file` (`app/mcp_stdio.py:19`-`app/mcp_stdio.py:22`, `app/mcp_stdio.py:63`-`app/mcp_stdio.py:70`, `app/mcp_stdio.py:191`-`app/mcp_stdio.py:199`). Один global config не может одновременно дать разным Codex workers разные `WORKER_NAME` и `ORCHESTRA_SCOPE`. Нужен per-worktree/per-process MCP env или другой способ передавать identity; иначе сообщения будут приходить от `worker`/неверного scope и auto-report/progress начнут путаться.

suggestion: Команда resume в плане теряет часть параметров первого запуска: для нового thread передаются `-m`, sandbox flags и `-C self.cwd` (`docs/research/codex-backend-plan.md:190`-`docs/research/codex-backend-plan.md:198`), а для resume только `exec resume --json <thread_id> message` (`docs/research/codex-backend-plan.md:188`-`docs/research/codex-backend-plan.md:189`). Если Codex CLI не восстанавливает cwd/sandbox/model из thread metadata гарантированно, turn может выполниться не в worktree или с другим sandbox behavior. Для session reliability лучше явно проверить CLI semantics и, если поддерживается, передавать `-C`, sandbox и model и на resume; если не поддерживается, это должно быть acceptance test из фазы 2.

question: План заявляет `--dangerously-bypass-approvals-and-sandbox` вместе с `--sandbox workspace-write` (`docs/research/codex-backend-plan.md:191`-`docs/research/codex-backend-plan.md:194`). Что реально побеждает в codex CLI v0.124.0? Если bypass отключает sandbox, Codex worker получает права шире worktree, что расходится с текущей моделью "каждый worker в git worktree" (`app/manager.py:185`-`app/manager.py:192`) и может повредить файлы вне scope. Для MVP я бы выбрал один режим и проверил destructive write outside worktree тестом.

thought: Строковые ссылки в плане по `app/session.py` в основном актуальны, но список "What stays" недооценивает связность heartbeat/listener с `_client`: `_heartbeat_loop` напрямую проверяет `_client` и перезапускает `_persistent_listen()` (`app/session.py:347`-`app/session.py:380`), а `compact()` напрямую создает Claude client и читает SDK messages (`app/session.py:394`-`app/session.py:461`). Это не блокер для плана, но фазу 1 надо считать не механическим extract: сначала добиться Claude parity на `AgentEvent`, потом добавлять Codex.

## Verdict
needs fixes.

## Round 2

### Status по прошлым findings

1. **STILL BROKEN** — non-blocking `send()` исправлен концептуально в Round 1 (`docs/research/codex-backend-plan.md:661`-`docs/research/codex-backend-plan.md:694`), но полный план все еще содержит старый inline вариант (`docs/research/codex-backend-plan.md:486`-`docs/research/codex-backend-plan.md:500`) и "Codex `send()` blocks" в non-goals (`docs/research/codex-backend-plan.md:650`). Плюс новый sketch запускает `_event_loop` до `backend.send()`, поэтому для Codex listener может увидеть `_proc is None`, выйти, а затем `send()` создаст subprocess без читателя.

2. **FIXED** — synthetic `turn_end` при смерти процесса теперь описан: `ok=False`, `returncode`, `stderr_tail`, `stop_reason` (`docs/research/codex-backend-plan.md:701`-`docs/research/codex-backend-plan.md:732`). Это закрывает зависание `RUNNING`, если `_handle_turn_end` действительно выполняет общий idle/persist path.

3. **FIXED** — `backend_type` теперь явно протянут через DB/session/API и валидируется на load (`docs/research/codex-backend-plan.md:734`-`docs/research/codex-backend-plan.md:742`).

4. **FIXED** — cross-backend model change заблокирован (`docs/research/codex-backend-plan.md:744`-`docs/research/codex-backend-plan.md:752`).

5. **FIXED** — terminal metadata расширен `ok`, `stop_reason`, `returncode`, `num_turns`/Codex returncode (`docs/research/codex-backend-plan.md:754`-`docs/research/codex-backend-plan.md:758`).

6. **STILL BROKEN** — Round 1 говорит обновить `app/tools.py` schema (`docs/research/codex-backend-plan.md:760`-`docs/research/codex-backend-plan.md:765`), но таблица файлов все еще говорит `app/tools.py` **NO CHANGE** (`docs/research/codex-backend-plan.md:579`). Также план не решает старые dead paths в `app/tools.py` (`_manager.archived`, `archive_by_id`), хотя признает, что orchestrators все еще используют in-process SDK tools.

7. **FIXED** — global MCP config заменен на per-worktree `.codex/config.toml` с `WORKER_NAME` и `ORCHESTRA_SCOPE` (`docs/research/codex-backend-plan.md:767`-`docs/research/codex-backend-plan.md:789`).

8. **FIXED** — resume ограничения задокументированы, acceptance test добавлен в план (`docs/research/codex-backend-plan.md:791`-`docs/research/codex-backend-plan.md:797`).

9. **STILL BROKEN** — Round 1 говорит убрать `--dangerously-bypass-approvals-and-sandbox` (`docs/research/codex-backend-plan.md:799`-`docs/research/codex-backend-plan.md:804`), но основной CodexBackend sketch все еще содержит этот флаг (`docs/research/codex-backend-plan.md:191`-`docs/research/codex-backend-plan.md:194`). Это опасное противоречие: реализация по верхнему sketch даст `danger-full-access`.

10. **FIXED** — `compact()` теперь явно должен идти через backend abstraction, а не raw Claude SDK (`docs/research/codex-backend-plan.md:805`-`docs/research/codex-backend-plan.md:818`).

### New bugs introduced

blocking: Новый non-blocking design для Codex имеет race на старте listener-а. `_ensure_backend()` из старого sketch создает `_event_loop` сразу после `connect()` (`docs/research/codex-backend-plan.md:380`-`docs/research/codex-backend-plan.md:388`), а Round 1 `send()` только потом вызывает `backend.send()` (`docs/research/codex-backend-plan.md:668`-`docs/research/codex-backend-plan.md:672`). Для Codex `connect()` no-op, `_proc` еще нет, значит `events()` может сразу вернуть управление по старой логике (`docs/research/codex-backend-plan.md:207`-`docs/research/codex-backend-plan.md:209`), `_event_loop` завершится, и stdout subprocess никто не прочитает. Фикс: для Codex стартовать listener после successful `backend.send()` на каждый turn, либо сделать `events()` ожидающим condition/queue появления процесса.

blocking: Не описана защита от второго `send()` во время активного Codex turn. Текущий API допускает `manager.send()` без проверки `RUNNING` (`app/main.py:323`-`app/main.py:335`, `app/manager.py:210`-`app/manager.py:214`), а Round 1 не добавил per-session queue/lock. Повторный `send()` может перезаписать `CodexBackend._proc` или запустить два `codex exec` на один thread. Для Codex нужно явно: если `RUNNING`, класть message в очередь или возвращать 409; mid-turn injection не поддерживается.

suggestion: `_got_turn_completed` должен сбрасываться в начале каждого Codex `send()`. Round 1 говорит, что flag есть, но в sketch показан только check после process exit (`docs/research/codex-backend-plan.md:709`-`docs/research/codex-backend-plan.md:720`). Если первый turn завершился успешно и поставил `_got_turn_completed=True`, следующий crashed turn не получит synthetic failed `turn_end`.

suggestion: Чтение stderr после завершения stdout может подвесить процесс, если stderr pipe заполнится. Round 1 читает stderr только после `await self._proc.wait()` (`docs/research/codex-backend-plan.md:706`-`docs/research/codex-backend-plan.md:707`). Без concurrent stderr drain subprocess может заблокироваться на записи stderr и никогда не закрыть stdout. Минимально: отдельная task для stderr tail или `stderr=STDOUT` с маркировкой.

suggestion: `assert backend_type == backend_for_model(model)` плохой механизм load validation (`docs/research/codex-backend-plan.md:741`). `assert` отключается `python -O` и при mismatch может убить `auto_resume_all()` вместо мягкой коррекции/лога. Нужен обычный `if mismatch: log + repair or skip session`.

suggestion: `.codex/config.toml` генерируется через f-string без TOML escaping (`docs/research/codex-backend-plan.md:772`-`docs/research/codex-backend-plan.md:786`). Путь/scope с кавычкой или backslash сломает config. Для MVP достаточно экранировать через `json.dumps(value)` для TOML basic strings или писать маленький helper.

suggestion: `.codex/config.toml` создается внутри worktree (`docs/research/codex-backend-plan.md:768`-`docs/research/codex-backend-plan.md:789`), но план не добавляет его в `.git/info/exclude` и не описывает cleanup. Worker может случайно закоммитить локальный Orchestra config в свою ветку. Добавьте exclude сразу после создания файла.

### Round 2 Verdict

needs fixes.
