# Architecture Review: Orchestra

Дата: 2026-04-30

Область чтения: все Python-файлы в `app/` и шаблон `app/templates/dashboard.html`.

## Короткий вывод

Проект сейчас содержит две разные модели запуска агентов:

1. `Worker` напрямую создает `ClaudeSDKClient` и ведет worker-сессию.
2. `Orchestrator` тоже создает `ClaudeSDKClient`, но затем просит эту сессию spawn'ить background Agent через Agent tool.

Это нарушает Pit of Success: у проекта два способа создать worker, два lifecycle loop'а, два способа хранить session id, две реализации worktree setup и две модели событий. Минимальная архитектура должна иметь один способ: `AgentSession` как единственная обертка над `ClaudeSDKClient`; `AgentManager` хранит и запускает такие сессии; worktree-подготовка вынесена в маленькую явную функцию.

## Дублирование `worker.py` и `orchestrator.py`

### Повторяется работа с SDK

`app/worker.py`:

- импортирует `ClaudeSDKClient`, `ClaudeAgentOptions`, `AssistantMessage`, `ResultMessage`, `TextBlock`, `ToolUseBlock`, `PermissionResultAllow` (`worker.py:12-20`);
- создает `ClaudeAgentOptions` (`worker.py:113-120`);
- прокидывает `system_prompt` и `resume` (`worker.py:121-124`);
- создает и подключает `ClaudeSDKClient` (`worker.py:126-127`);
- читает `receive_messages()` и разбирает `AssistantMessage`, `TextBlock`, `ToolUseBlock`, `ResultMessage` (`worker.py:134-153`);
- делает `disconnect()` (`worker.py:199-203`);
- имеет `_auto_approve()` (`worker.py:216-218`).

`app/orchestrator.py`:

- импортирует тот же SDK-набор (`orchestrator.py:8-16`);
- создает `ClaudeAgentOptions` (`orchestrator.py:65-73`);
- прокидывает `resume` (`orchestrator.py:74-75`);
- создает и подключает `ClaudeSDKClient` (`orchestrator.py:77-78`);
- читает `receive_messages()` и разбирает `AssistantMessage`, `TextBlock`, `ToolUseBlock`, `ResultMessage` (`orchestrator.py:158-188`);
- делает `disconnect()` (`orchestrator.py:202-207`);
- имеет `_auto_approve()` (`orchestrator.py:210-213`).

Это должен быть один класс. Разница между worker и orchestrator не в SDK lifecycle, а в конфигурации: `name`, `role`, `cwd`, `model`, `system_prompt`, `permission_mode`, `max_turns`, обработчик сообщений.

### Повторяется worktree setup

`Worker._setup_worktree()` создает `worktrees/<name>`, ветку `feat/<name>`, удаляет старый worktree, вызывает `git worktree add`, потом копирует файлы (`worker.py:70-101`).

`Orchestrator.spawn_worker()` делает то же вручную (`orchestrator.py:101-126`).

Различия случайные:

- `Worker` копирует `CLAUDE.md`, `.mcp.json`, `.env`, `.worktreeinclude` (`worker.py:96`);
- `Orchestrator` копирует только `CLAUDE.md`, `.mcp.json`, `.env` (`orchestrator.py:121`);
- оба игнорируют ошибки `git worktree remove`;
- оба при ошибке первого `git worktree add` пробуют другой вариант без проверки результата (`worker.py:84-88`, `orchestrator.py:114-116`).

Для Pit of Success это надо вынести в одну функцию `create_worktree(repo_path, name) -> Worktree`, которая использует `subprocess.run(..., check=True, text=True, capture_output=True)` и падает явно с stderr.

### Повторяется загрузка `worker.md`

- `app/manager.py:12-22`;
- `app/orchestrator.py:30-36`.

При этом `Orchestrator._worker_md` загружается, но не используется (`orchestrator.py:45`). Это dead code.

## Целевая архитектура

Минимальные сущности:

```text
app/
  agent_session.py   # единственный ClaudeSDKClient lifecycle
  manager.py         # registry AgentSession by name
  workspace.py       # create/remove worktree, copy project files
  db.py              # persistence: sessions/logs only
  main.py            # HTTP API
  templates/dashboard.html
```

### `AgentSession`

Один класс для orchestrator и worker:

```python
@dataclass
class AgentSession:
    name: str
    role: Literal["orchestrator", "worker"]
    cwd: str
    model: str
    prompt: str = ""
    system_prompt: str = ""
    permission_mode: str = "default"
    max_turns: int = 50
    status: AgentStatus = AgentStatus.PENDING
    session_id: str | None = None
    cost_usd: float = 0.0
    logs: list[AgentLog] = field(default_factory=list)

    async def start(self, message: str | None = None) -> None: ...
    async def send(self, message: str) -> None: ...
    async def listen(self) -> None: ...
    async def interrupt(self) -> None: ...
    async def stop(self, final_status: AgentStatus = AgentStatus.STOPPED) -> None: ...
```

Правила:

- `AgentSession` единственный владеет `ClaudeSDKClient`.
- `start()` только подключает SDK и запускает listen loop.
- `send()` только вызывает `client.query()`.
- `listen()` единственный разбирает SDK messages.
- `ResultMessage` обновляет `session_id`, `cost_usd`, статус.
- Любая ошибка переводит сессию в `ERROR`, логируется и пробрасывается там, где это важно.
- Никаких `_expected_results`: один запрос -> один listen loop, либо явная очередь сообщений.

### `AgentManager`

`AgentManager` не должен знать детали SDK. Он только:

- держит `sessions: dict[str, AgentSession]`;
- создает orchestrator session;
- создает worker session;
- вызывает `send/interrupt/stop/remove`;
- сохраняет состояние через `db.py`.

Один публичный spawn:

```python
async def spawn_agent(
    name: str,
    role: Literal["orchestrator", "worker"],
    task: str,
    repo_path: str,
    model: str,
    use_worktree: bool,
) -> AgentSession
```

Для worker `use_worktree=True`, для orchestrator `use_worktree=False`.

### Worktree

Отдельный модуль без SDK:

```python
PROJECT_FILES = ("CLAUDE.md", ".mcp.json", ".env", ".worktreeinclude")

def create_worktree(repo_path: Path, name: str) -> Worktree:
    branch = f"feat/{name}"
    path = ROOT / "worktrees" / name
    run(["git", "worktree", "remove", str(path), "--force"], check=False)
    run(["git", "worktree", "add", str(path), "-b", branch], check=True)
    copy_project_files(repo_path, path)
    return Worktree(path=path, branch=branch)
```

Если нужна поддержка существующей ветки, она должна быть явной опцией, а не скрытым fallback'ом после ошибки.

## Что удалить или упростить

### 1. Удалить второй способ spawn'а workers

Сейчас есть:

- прямой spawn: `POST /api/workers/spawn` -> `manager.spawn()` -> `Worker.spawn()` (`main.py:60-68`);
- orchestrator spawn: `POST /api/orchestrator/spawn` -> `orchestrator.spawn_worker()` -> prompt с просьбой вызвать Agent tool (`main.py:131-141`, `orchestrator.py:128-145`).

Нужен один способ. Для минимального проекта лучше оставить прямой spawn SDK-сессий через `AgentManager`. Тогда `Orchestrator` становится обычной `AgentSession` для чата/планирования, а не отдельным менеджером worker'ов.

Если принципиально нужен Claude Agent tool, тогда наоборот надо удалить прямой `Worker`-spawn. Но смешивать оба пути нельзя.

### 2. Удалить `Worker` и `Orchestrator` как отдельные SDK wrappers

`Worker` и `Orchestrator` должны схлопнуться в `AgentSession`. Различия уйдут в конфиг:

```python
ORCHESTRATOR = AgentConfig(
    role="orchestrator",
    model="claude-opus-4-6[1m]",
    max_turns=200,
    permission_mode="bypassPermissions",
)

WORKER = AgentConfig(
    role="worker",
    model="claude-sonnet-4-6",
    max_turns=50,
    permission_mode="default",
)
```

### 3. Убрать dead code

- `AgentDefinition`, `SystemMessage`, `RateLimitEvent` импортируются, но не используются (`orchestrator.py:18`, `orchestrator.py:22-23`).
- `json` импортируется, но не используется (`db.py:4`).
- `db_get_worker`, `get_worker_logs`, `delete_worker` импортируются в `manager.py`, но не используются (`manager.py:8`).
- `Orchestrator._listen_task` объявлен, но не используется (`orchestrator.py:43`).
- `Orchestrator._worker_md` загружается, но не используется (`orchestrator.py:45`).
- `WorkerStatus.DONE` есть, но `Worker` никогда не ставит статус `DONE`; после `ResultMessage` он становится `IDLE` (`worker.py:32`, `worker.py:149-152`).
- `context_pct` хранится и отдается, но нигде не обновляется (`worker.py:58`, `worker.py:228`, `db.py:32`).
- `chatHistory` объявлен в dashboard, но не используется (`dashboard.html:121`).
- `api_callback()` выглядит как внешний callback endpoint, но dashboard и SDK-flow используют `add_callback()` напрямую; если внешнего клиента нет, endpoint лишний (`main.py:102-107`).
- `api_workers/spawn` и `api_orchestrator/spawn` не вызываются из dashboard (`dashboard.html`), значит UI уже не покрывает часть API.

### 4. Упростить статусы

Сейчас: `PENDING`, `SPAWNING`, `WORKING`, `IDLE`, `DONE`, `ERROR`, `KILLED`.

Минимально:

```text
starting -> running -> idle -> stopped
                 \-> error
```

`killed` можно заменить на `stopped`, если нет отдельной бизнес-логики для killed. `done` стоит либо реально использовать, либо удалить. В текущем интерактивном SDK-подходе `idle` лучше, чем `done`.

### 5. Fail loud вместо скрытых `False` и `pass`

Сейчас ошибки часто превращаются в молчание:

- `inject()` возвращает `False`, если worker не найден или статус неподходящий (`worker.py:160-186`, `manager.py:45-49`);
- `interrupt()` и `kill()` глотают ошибки disconnect/interrupt (`worker.py:188-203`);
- dashboard ловит ошибки пустым `catch {}` (`dashboard.html:199`, `dashboard.html:290`, `dashboard.html:371`);
- worktree fallback не проверяет результат второго `git worktree add` (`worker.py:84-88`, `orchestrator.py:114-116`).

Для Pit of Success:

- API должен возвращать 404, 409 или 500, а не `{ok: false}`;
- subprocess должен падать с stderr;
- frontend должен показывать ошибку хотя бы в toast/notification area;
- `disconnect()` можно логировать как warning, но не молча.

## Dashboard HTML/JS

Dashboard делает слишком много для одного HTML-файла: чат, workers list, notifications, sidebar, logs polling, status polling, rendering, API error handling. Это можно упростить без фреймворка.

### Что оставить

Минимальный dashboard:

- header со статусом orchestrator;
- одна таблица/список sessions;
- выбранная session справа;
- logs выбранной session;
- одно поле `send message`;
- кнопки `start`, `stop`, `remove`.

### Что убрать

- Отдельную вкладку notifications. Это те же events/logs, только в другой таблице (`dashboard.html:79-80`, `dashboard.html:346-361`).
- `chatHistory` (`dashboard.html:121`).
- Отдельный polling `pollOrchestratorResponse()` на 120 итераций (`dashboard.html:178-202`). Нужен один общий polling `/api/events?since=<id>` или `/api/sessions`.
- Дублирующий polling: сейчас есть `pollOrchestratorResponse()` и общий `setInterval()` (`dashboard.html:178-202`, `dashboard.html:317-372`).
- `system_prompt` в ответе `/api/workers/{name}`, если UI его не показывает (`main.py:51-57`).
- Inline `onclick` в HTML. Для маленького файла терпимо, но проще поддерживать один `addEventListener` блок внизу.
- CDN Tailwind в dev-dashboard можно оставить, но это не HTMX, хотя `CLAUDE.md` говорит "FastAPI + HTMX dashboard". Либо добавить HTMX и убрать ручной rendering, либо исправить описание.

### Главный баг dashboard

`selectWorker('${escapeHtml(w.name)}')` вставляет escaped HTML внутрь JS string (`dashboard.html:331`). `escapeHtml()` не экранирует кавычки для JavaScript context. Имя worker с `'` ломает onclick. Лучше не генерировать inline JS, а создавать элементы через DOM и класть имя в `dataset.name`.

### Минимальный frontend flow

```text
setInterval(refresh, 2000)
refresh:
  GET /api/sessions
  render list
  if selected: render selected details/logs

send:
  POST /api/sessions/{name}/messages

start worker:
  POST /api/sessions
```

Один polling loop, один источник состояния, один renderer.

## Предлагаемый минимальный API

```text
GET    /api/sessions
POST   /api/sessions
GET    /api/sessions/{name}
POST   /api/sessions/{name}/messages
POST   /api/sessions/{name}/interrupt
DELETE /api/sessions/{name}
GET    /api/stats
```

Удалить:

- `/api/workers/spawn` как отдельную сущность;
- `/api/orchestrator/spawn`;
- `/api/orchestrator/send`;
- `/api/orchestrator/start`;
- `/api/orchestrator/status`;
- `/api/callbacks`;
- `/api/callbacks/read`;
- `/api/workers/{name}/callback`, если нет внешнего протокола.

Если нужен orchestrator как постоянный агент, он просто session с именем `orchestrator`:

```text
POST /api/sessions
{
  "name": "orchestrator",
  "role": "orchestrator",
  "repo_path": "/mnt/data/Projects/Python/Parsing",
  "use_worktree": false
}
```

## Упрощение persistence

Таблицы должны называться по новой модели:

```sql
sessions(name, role, task, repo_path, branch, model, status, cwd, session_id, cost_usd, created_at, finished_at)
logs(id, session_name, ts, type, content)
```

`callbacks` можно удалить. `TaskNotificationMessage`, assistant text, tool use и errors должны быть обычными `logs` с типом `event`, `text`, `tool`, `error`, `status`.

## Порядок рефакторинга

1. Добавить `AgentSession` и перенести туда SDK lifecycle из `Worker`/`Orchestrator`.
2. Добавить `workspace.py` и перенести туда worktree/copy logic.
3. Переписать `WorkerManager` в `AgentManager`, оставив старые endpoint'ы временно только если нужно руками сравнить поведение.
4. Удалить `worker.py` и `orchestrator.py` как отдельные классы.
5. Схлопнуть API до `/api/sessions`.
6. Упростить dashboard до одного polling loop и одного списка sessions.
7. Удалить `callbacks` и заменить их session logs/events.

Такой порядок сохраняет работоспособность на каждом шаге, но финальная цель должна быть без обратной совместимости: один класс сессии, один spawn path, один event stream.

## Итоговая рекомендация

Самое важное решение: выбрать один механизм spawn'а. Для текущего кода проще и надежнее сделать каждый worker прямой `ClaudeSDKClient` сессией через `AgentSession`, а orchestrator сделать такой же сессией с другим prompt/model/cwd. Тогда исчезают `Worker`, `Orchestrator`, callbacks как отдельная шина, дублированный worktree setup и большая часть специальных endpoint'ов.

Минимальный код выполняющий функцию: `AgentSession` + `AgentManager` + `create_worktree()` + SQLite logs + простой dashboard поверх `/api/sessions`.
