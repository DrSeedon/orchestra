## Root Cause

Зависает не сам `list_workers`. Он вообще не успевает вызваться.

Root cause: `spawn_worker` делает fire-and-forget через `asyncio.create_task(_do_spawn())`, но `_do_spawn()` немедленно начинает тяжёлую работу в том же event loop, где SDK `Query` читает stdout Claude CLI и роутит `control_request`. В результате первый MCP handler уже вернул Python-результат, но до стабильной отправки `control_response` обратно в CLI event loop успевает заняться worker spawn: `git worktree add`, sync DB writes, старт нового `ClaudeSDKClient`, worker turn. Следующий MCP call (`list_workers`) приходит в тот же CLI turn, но SDK read loop не доходит до его `control_request`, поэтому `list_workers()` не логируется и CLI ждёт MCP response бесконечно.

Это не сценарий "модель не ответила". `cost_usd = $0.00` как раз ожидаем: Claude API не вызывается, потому что Claude CLI стоит на локальном tool execution и ждёт control response от Python SDK.

Критичная часть SDK:

```python
# claude_agent_sdk/_internal/query.py
async for message in self.transport.read_messages():
    ...
    elif msg_type == "control_request":
        self._spawn_control_request_handler(request)
        continue
    ...
    await self._message_send.send(message)
```

Один read task одновременно:

- читает stdout CLI;
- роутит `control_request` к MCP handlers;
- кладёт обычные SDK messages в bounded stream.

Если этот task не получает CPU или застревает на backpressure/синхронной работе вокруг turn, новые `control_request` не будут обработаны. Именно поэтому handler `list_workers` не вызывается.

## Evidence

`app/tools.py:34-49`:

```python
async def _do_spawn():
    session = await _manager.create_session(...)
    await session.send(task)

asyncio.create_task(_do_spawn())
return {"content": ...}
```

Это выглядит как быстрый ответ, но task запускается на том же loop и может стартовать до того, как `Query._handle_control_request()` допишет `control_response` в stdin CLI.

`app/manager.py:95-114`:

```python
if use_worktree and repo_path:
    wt = create_worktree(repo_path, name, scope)
...
await session.start()
self.sessions[session.id] = session
```

`create_worktree()` вызывается прямо из async path.

`app/workspace.py:42-50`:

```python
result = subprocess.run(["git", "worktree", "add", ...])
...
result = subprocess.run(["git", "worktree", "add", ...])
```

Это sync subprocess в event loop. Пока он выполняется, SDK read loop не читает stdout orchestrator CLI.

`claude_agent_sdk/_internal/query.py:264-270` роутит `control_request`; `query.py:298-299` делает blocking send в bounded memory stream. Значит control traffic и regular messages завязаны на один read loop.

`claude_agent_sdk/client.py:254-256` показывает, что `ClaudeSDKClient.connect()` сразу стартует `Query` и делает initialize. Запуск worker session внутри `_do_spawn()` создаёт ещё один active SDK client/read loop в том же process/event loop, пока orchestrator turn ещё не завершён.

Фактический trace из `data/orchestra.db` подтверждает reentrancy:

```text
18:38:59  Exp tool        mcp__orchestra__spawn_worker
18:39:17  Exp user_msg    [from:pp] PING1
18:39:24  Exp tool_result Worker 'pp' spawning in background...
18:39:35  Exp tool        mcp__orchestra__list_workers: {}
```

Worker успел стартовать и отправить `PING1` до того, как orchestrator получил `tool_result` для `spawn_worker`. Это невозможно при реально изолированном "background after response"; значит `_do_spawn()` выполнялся в критическом окне MCP response path.

После `18:39:35` нет `tool_result` и нет признака входа в `list_workers()`. Это совпадает с зависанием до MCP handler, а не внутри handler.

## Fix (конкретный код)

Нужно убрать тяжёлый spawn из MCP handler/control path. Tool должен только поставить job в очередь и быстро вернуть id/status. Worker startup должен идти в отдельном supervisor task, а sync worktree операции должны уходить в thread.

Минимальный фикс по смыслу:

```python
# app/manager.py
import asyncio

class SessionManager:
    def __init__(self):
        self.sessions = {}
        self.archived = {}
        self._load_locks = {}
        self._spawn_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._spawn_task: asyncio.Task | None = None
        set_manager(self)

    def start_background_tasks(self) -> None:
        if not self._spawn_task or self._spawn_task.done():
            self._spawn_task = asyncio.create_task(self._spawn_worker_loop())

    async def enqueue_worker_spawn(self, **job) -> str:
        job_id = str(uuid.uuid4())
        await self._spawn_queue.put({"job_id": job_id, **job})
        return job_id

    async def _spawn_worker_loop(self) -> None:
        while True:
            job = await self._spawn_queue.get()
            try:
                # Let the MCP control_response for spawn_worker flush before
                # starting worker CLI initialization in the same event loop.
                await asyncio.sleep(0.25)
                session = await self.create_session(
                    name=job["name"],
                    scope=job["scope"],
                    cwd=job["repo_path"],
                    model=job["model"],
                    system_prompt=job["system_prompt"],
                    use_worktree=True,
                    repo_path=job["repo_path"],
                )
                await session.send(job["task"])
                logger.info("Worker %r spawned by job %s", job["name"], job["job_id"])
            except Exception:
                logger.exception("Worker spawn job %s failed", job["job_id"])
            finally:
                self._spawn_queue.task_done()
```

```python
# app/main.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await manager.auto_resume_orchestrators()
    manager.start_background_tasks()
    yield
    await manager.shutdown_all()
```

```python
# app/tools.py
@tool("spawn_worker", "...", {...})
async def spawn_worker(args):
    if not _manager:
        return {"content": [{"type": "text", "text": "Orchestra not initialized"}], "is_error": True}

    job_id = await _manager.enqueue_worker_spawn(
        name=args["name"],
        task=args["task"],
        repo_path=args["repo_path"],
        scope=args["repo_path"],
        model=args.get("model", "claude-sonnet-4-6"),
        system_prompt=args.get("system_prompt", ""),
    )

    return {
        "content": [{
            "type": "text",
            "text": (
                f"Worker '{args['name']}' spawn queued.\n"
                f"Job: {job_id}\n"
                "Use list_workers to check status."
            ),
        }]
    }
```

И обязательно вынести blocking git worktree из event loop:

```python
# app/manager.py create_session
if use_worktree and repo_path:
    wt = await asyncio.to_thread(create_worktree, repo_path, name, scope)
    session.cwd = wt.path
    session.worktree_path = wt.path
    session.branch = wt.branch
```

То же для remove:

```python
await asyncio.to_thread(remove_worktree, repo_path, session.worktree_path)
```

Дополнительный защитный фикс для диагностики и восстановления:

```python
# app/session.py
TURN_TIMEOUT_SEC = 300

await self._client.query(message)
await asyncio.wait_for(self._listen_loop(), timeout=TURN_TIMEOUT_SEC)
```

В `except asyncio.TimeoutError` нужно логировать timeout, делать `await self.interrupt()`, переводить session в `ERROR` или перезапускать client через `resume=session_id`. Это не лечит root cause, но убирает вечный hang.

Для снижения backpressure стоит также выключить partial stream events, если они не критичны:

```python
ClaudeAgentOptions(
    ...,
    include_partial_messages=False,
)
```

или держать один постоянный receiver task на session, который всегда drain'ит `receive_messages()`, даже когда session считается IDLE. Сейчас consumer живёт только внутри `_listen_loop()` на turn.

## Вердикт

Основной баг в Orchestra lifecycle: MCP tool handler запускает тяжёлый nested worker startup в том же event loop и в том же временном окне, где SDK должен отправить control response и продолжать читать следующие control requests. Поэтому второй MCP call не доходит до Python handler.

Фикс: `spawn_worker` должен быть быстрым enqueue-only operation; actual spawn должен выполняться supervisor task'ом вне MCP response path, а sync `git worktree` операции должны идти через `asyncio.to_thread()`. После этого `list_workers` сможет отвечать в том же turn: максимум он покажет worker как queued/starting, но не повесит orchestrator CLI.
