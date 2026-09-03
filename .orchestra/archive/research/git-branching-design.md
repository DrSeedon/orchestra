# Git Branching Per Task — Design Document

## Summary

Привязка веток к задачам (PAR-номерам): каждая задача работается в именованной ветке `PAR-{N}/{worker-name}`, коммиты автоматически линкуются при merge, system workers получают свежую ветку после каждого merge.

## Current State

### Что есть
- `create_worktree(repo_path, name, scope)` → ветка `feat/{scope_slug}/{name}`, привязана к ВОРКЕРУ, не к задаче
- `merge_worktree_to_main(worktree_path, repo_path)` → мержит текущую checked-out ветку в main, парсит PAR из commit messages, линкует коммиты к задачам
- Один worktree = один воркер = одна ветка
- Task Manager хранит `git_commits` JSON в задаче — заполняется при merge через `_parse_merged_commits`
- Воркерам в промпте сказано добавлять `PAR-N:` в commit messages

### Что НЕ работает
- Ветка привязана к воркеру, не к задаче → при переключении задачи коммиты от разных задач в одной ветке
- System worker делает задачу за задачей в одной ветке → merge мержит ВСЁ, включая незавершённое
- Нет механизма "дай воркеру новую ветку для новой задачи"
- `spawn_worker` не принимает `task_id` → нет автоматической привязки

### Критические проблемы текущего кода (найдены при ревью)
1. **auto-save при merge** (`workspace.py:97-110`): `merge_worktree_to_main` при dirty tree делает `git add -A && git commit -m "auto-save: {branch}"` — коммит без PAR-номера, мержит незавершённое
2. **merge без проверки статуса** (`main.py:427`): endpoint не проверяет что worker idle — можно замержить промежуточное состояние пока worker ещё пишет
3. **`branch -D` при коллизии** (`workspace.py:47-48`): `create_worktree` при ошибке удаляет ветку через `branch -D` — может удалить незамердженные коммиты чужой ветки
4. **merge без проверки HEAD=main** (`workspace.py:141`): `git merge branch` выполняется в основном репо, но не проверяет что HEAD стоит на main
5. **`git worktree add` без start point** (`workspace.py:44`): новая ветка стартует от текущего HEAD, не гарантированно от main

## Design

### Принципы
1. **Ветка = задача**, не воркер. Имя ветки содержит PAR-номер
2. **Один worktree = одна ветка** (ограничение git). Переключение — через `git checkout -b`
3. **Fail loud** — merge/switch отказывают при dirty tree или неправильном состоянии. Никакого auto-commit скрытых данных
4. **State guards** — merge и switch только когда worker idle. Running worker = reject
5. **Обратная совместимость** — задачи без PAR продолжают работать (ветка по worker name)

### Branch Naming

```
PAR-{N}/{worker-name}     — задача с PAR (основной случай)
feat/{scope_slug}/{name}   — без PAR (текущее поведение, fallback)
```

Валидация `task_id`: принимаем только `^(PAR-)?\d+$`. Мусор вроде `abc` или `PAR-1/foo` → ошибка.
Имя ветки проверяем через `git check-ref-format --branch`.

Примеры:
- `PAR-192/fix-merge-spaces` — disposable worker на задаче PAR-192
- `PAR-234/backend` — system worker "backend" работает над PAR-234
- `feat/mnt-data-projects-python-parsing/frontend` — system worker без задачи

### Flow: Disposable Worker

```
spawn_worker(name="fix-slash", task="...", repo_path="...", task_id="PAR-192")
  └─ create_worktree() → branch: PAR-192/fix-slash, base: main
  └─ task_update(PAR-192, status="in_progress", worker_session_id=...)
  └─ worker works, commits "PAR-192: fix slash"
  └─ worker reports DONE

merge_worker("fix-slash")
  └─ GUARD: worker must be idle
  └─ GUARD: worktree must be clean (no dirty files)
  └─ GUARD: repo HEAD must be on main
  └─ merge PAR-192/fix-slash → main
  └─ link commits to PAR-192

kill_worker("fix-slash")
  └─ remove worktree + branch cleanup
```

### Flow: System Worker (многозадачный)

```
spawn_worker(name="backend", task="...", repo_path="...", task_id="PAR-192")
  └─ create_worktree() → branch: PAR-192/backend, base: main
  └─ task_update(PAR-192, status="in_progress", worker_session_id=...)
  └─ worker works on PAR-192
  └─ worker reports DONE

merge_worker("backend")
  └─ GUARD: worker idle, clean tree, repo HEAD=main
  └─ merge PAR-192/backend → main
  └─ link commits to PAR-192
  └─ return hint: "branch merged — use switch_worker_branch for new task"

switch_worker_branch("backend", task_id="PAR-234")
  └─ GUARD: worker idle, clean tree
  └─ git fetch (optional, if remote exists)
  └─ git checkout -b PAR-234/backend refs/heads/main
  └─ update session.branch + session.task_id in DB
  └─ update worker prompt with new branch name

send_message("backend", "New task: PAR-234: ...")
  └─ worker continues in SAME worktree, NEW branch from fresh main
```

Ключевой момент: после merge system worker **остаётся живым**, но получает новую ветку. Worktree не пересоздаётся — только `git checkout -b` от обновлённого main.

**НЕ `git checkout main && git checkout -b ...`** — main может быть checked out в основном репо. Используем `git checkout -b PAR-234/backend refs/heads/main` — создаёт ветку от main ref без checkout main.

### Flow: Срочная задача (прерывание)

```
Worker "backend" работает над PAR-192 (branch PAR-192/backend)
Приходит срочная PAR-999

Оркестратор:
1. send_message("backend", "URGENT: commit WIP and stop")
   └─ worker commits "WIP: PAR-192 in progress"
   └─ worker reports STOPPED

2. switch_worker_branch("backend", task_id="PAR-999")
   └─ GUARD: idle + clean
   └─ git checkout -b PAR-999/backend refs/heads/main

3. send_message("backend", "PAR-999: urgent fix ...")
   └─ worker works on PAR-999

4. merge_worker("backend")  — мержит PAR-999/backend
5. switch_worker_branch("backend", task_id="PAR-192")
   └─ git checkout PAR-192/backend (ветка уже существует)
   └─ git merge refs/heads/main (подтянуть изменения от PAR-999)

6. send_message("backend", "Continue PAR-192")
```

### Merge: Guards и гарантии

`merge_worker(name)` ВСЕГДА мержит текущую checked-out ветку. Убираем опциональный `branch` override на MVP — он создаёт лишний write-path (checkout в worktree worker'а) и может конфликтовать с running worker.

**Обязательные guards при merge:**
1. Worker session idle (не running) — иначе reject
2. Worktree clean (no dirty files) — иначе reject, **БЕЗ auto-commit**
3. Repo HEAD == main — проверяем через `git symbolic-ref --short HEAD`, если не main — `git checkout main` в repo

**Изменение поведения vs текущий код:** текущий `merge_worktree_to_main` делает auto-save при dirty tree. Новое поведение — reject. Это breaking change, но правильный: auto-save без PAR-номера = мёртвый коммит, незавершённая работа в main.

## Edge Cases — Ответы на 10 вопросов

### 1. System worker получает 2 задачи параллельно

**Ответ: ЗАПРЕТИТЬ.** Один worktree = одна ветка = одна задача.

**Гарантия:** merge/switch guards требуют idle. Промпт оркестратора обновляем: "один active PAR на worker, sequence: DONE → merge_worker → switch_worker_branch → send next task".

### 2. Срочная задача на середине текущей

**Ответ: WIP commit → switch_branch → urgent task → merge → switch back.**

Ключевое: всегда коммитим перед переключением. `git stash` ненадёжен. WIP commit — явный, видимый, recoverable.

`switch_branch` проверяет dirty tree и reject'ит. Оркестратор ОБЯЗАН сначала попросить worker закоммитить.

### 3. merge_worker мержит текущую ветку — а если 2 незамердженных?

**Ответ: всегда мержим текущую checked-out.** Оркестратор знает порядок: merge → switch → work → merge → switch. Не копим незамердженные ветки.

### 4. Worktree ограничения — одна ветка на worktree

**Ответ: `git checkout -b new_branch refs/heads/main` в существующем worktree.** Git позволяет создать новую ветку от ref без checkout этого ref. `main` может быть checked out в основном репо — не мешает.

### 5. Конфликты при checkout — dirty working tree

**Ответ: `switch_branch` ОТКАЗЫВАЕТ при dirty tree.** Fail loud > auto-fix.

### 6. Disposable vs system workers — одинаковый flow?

**Ответ: ОДИНАКОВЫЙ flow создания ветки.** Разница в жизненном цикле:

| | Disposable | System |
|---|---|---|
| Spawn | + task_id → PAR-N/name | + task_id → PAR-N/name |
| Merge | merge → kill | merge → switch_branch |

### 7. Кто создаёт ветку — Orchestra при spawn

**Ответ: ORCHESTRA.** Воркер НИКОГДА не создаёт ветки сам. Ветка при spawn, новая ветка при switch — всё платформа.

### 8. Naming convention

**Формат:** `PAR-{N}/{worker-name}` (без `feat/` prefix — PAR-номер самодокументирующий).

### 9. Задача без PAR

**Ответ: fallback** на `feat/{scope_slug}/{name}`. Не запрещаем.

### 10. merge_worker с несколькими ветками

**Ответ: текущую checked-out.** Без override на MVP.

## Дополнительные Edge Cases

### 11. Race condition: два merge одновременно

**File-level lock:** `fcntl.LOCK_EX` на `.git/orchestra-merge.lock` защищает два merge.

**Per-session lock:** HTTP API допускает параллельные запросы — два `merge_worker` или `merge + switch` могут одновременно увидеть `idle + clean`. Решение: `asyncio.Lock` per session в `SessionManager`. Все мутирующие операции (merge, switch, send, stop) берут lock перед выполнением.

```python
class SessionManager:
    def __init__(self):
        self._session_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]
```

Merge endpoint: `async with manager._get_lock(session.id): ...`
Switch endpoint: `async with manager._get_lock(session.id): ...`

### 12. Merge конфликтует

**Текущее поведение:** `merge-tree --write-tree` проверяет конфликты ПЕРЕД merge. Если конфликты — возвращает список файлов, merge не происходит. Оркестратор решает.

### 13. main checked out в основном репо

**Проблема:** `git merge` в основном репо требует HEAD=main.
**Решение (фаза 1, не фаза 3):** перед merge:
1. Проверить `git status --porcelain` в основном репо → если dirty, reject "main repo has uncommitted changes"
2. Проверить `git symbolic-ref --short HEAD` → если не main, `git checkout main`
3. Если checkout fails (main checked out в другом worktree — не должно быть, но guard) → reject

### 14. `git checkout -b` от main в worktree

**Канонический алгоритм:** `git checkout -b PAR-234/backend refs/heads/main` — не требует checkout main, работает даже если main checked out в другом worktree.

### 15. Branch name collision

**Проблема:** `PAR-192/backend` уже существует (задача переоткрыта).
**Решение:** перед `create_worktree` проверять `git show-ref --verify refs/heads/{branch}`. Если существует и не checked out — **НЕ удалять** (могут быть незамердженные коммиты). Вместо этого вернуть ошибку. Оркестратор решает: другое имя или cleanup.
**УБРАТЬ `branch -D` fallback** из текущего `create_worktree` — это опасно для PAR-веток.

### 16. Crash recovery при switch_branch

**Проблема:** crash между `git checkout -b` и `save_session(branch=new_branch)`. DB хранит старую ветку, worktree на новой.
**Решение:** при `_load_from_db()` — reconcile фактическую ветку из worktree (`git rev-parse --abbrev-ref HEAD`) с DB. Если не совпадают — обновить DB. Worktree = source of truth.

## API Changes

### `spawn_worker` — добавить `task_id`

```python
@mcp.tool()
async def spawn_worker(name: str, task: str, repo_path: str,
                       model: str = "", system_prompt: str = "",
                       task_id: str = "") -> str:
```

`task_id` — строка `^(PAR-)?\d+$` или пустая. При spawn:
- Нормализуется в `PAR-{N}`
- Передаётся в `create_worktree` → branch name
- Записывается в `sessions.task_id`
- `task_update(par, status="in_progress", worker_session_id=session.id)` — автоматически

### `create_worktree` — добавить `task_id`, явный base

```python
def create_worktree(repo_path: str, name: str, scope: str,
                    task_id: str = "") -> Worktree:
```

Изменения:
1. Branch name: `PAR-{N}/{name}` если task_id, иначе `feat/{scope_slug}/{name}`
2. **Start point: `main`** — `git worktree add wt -b branch main` (явный base, не HEAD)
3. **Проверка коллизии:** `git show-ref --verify refs/heads/{branch}` перед созданием
4. **Убрать `branch -D` fallback** — вместо него ошибка с внятным сообщением

### `merge_worktree_to_main` — guards

Изменения:
1. **Убрать auto-commit** при dirty tree → return `{"ok": False, "error": "dirty working tree"}`
2. **Проверка HEAD=main** в основном репо → checkout main если нужно
3. Без изменений в API — guards внутренние

### Новый MCP tool: `switch_worker_branch`

```python
@mcp.tool()
async def switch_worker_branch(name: str, task_id: str) -> str:
    """After merge, switch worker to a new branch for a new task.
    Worker must be idle with clean working tree."""
```

Вызывает:
1. Check worker idle + clean tree
2. `switch_worktree_branch(worktree_path, new_branch, "refs/heads/main")`
3. Update `session.branch`, `session.task_id` в DB
4. Inject updated branch into worker's prompt context

### Новая функция: `switch_worktree_branch`

```python
def switch_worktree_branch(worktree_path: str, new_branch: str,
                           from_ref: str = "refs/heads/main") -> dict:
```

Алгоритм:
1. `git status --porcelain` → dirty? reject
2. Acquire repo-level `orchestra-merge.lock` (shared with merge, ensures main ref is stable)
3. `git show-ref --verify refs/heads/{new_branch}` → exists?
   a. Проверить не checked out в другом worktree: `git worktree list --porcelain` → если да, reject с "branch checked out in another worktree"
   b. `git checkout {new_branch}`
   c. **Всегда** `git merge refs/heads/main --no-edit` — existing branch = stale by definition, main мог уйти вперёд
   d. Если конфликт → return `{"ok": False, "conflicts": [...], "state": "conflict"}`. **Contract:** worktree остаётся на целевой ветке в conflicted state. Worker должен разрулить конфликт. Повторный switch невозможен (dirty tree reject). Оркестратор решает: просить worker резолвить, или `git merge --abort` и работать на старом коде
4. Не exists? `git checkout -b {new_branch} {from_ref}`
5. Release lock
6. Return `{"ok": True, "branch": new_branch}`

**Поведение однозначное:** existing branch → всегда merge main. Новая ветка → от refs/heads/main (уже fresh). Lock гарантирует что main ref не двигается пока switch читает его.

Flow "urgent task → return":
```
switch_worker_branch("backend", task_id="PAR-192")
  └─ checkout PAR-192/backend (exists)
  └─ git merge refs/heads/main (always for existing)
  └─ if conflicts → orchestrator decides
```

### Изменения в `session` / DB

Добавить `sessions.task_id`:
```sql
ALTER TABLE sessions ADD COLUMN task_id TEXT DEFAULT '';
```

Добавить `task_id` во ВСЕ пути persistence:
- `AgentSession` dataclass — поле `task_id: str = ""`
- `_to_db_dict()` — включить task_id
- `save_session()` — включить в INSERT/UPDATE
- `_load_from_db()` — читать task_id + **reconcile branch** из worktree
- `to_dict()` — включить task_id в API response

### Reconcile branch + task_id при загрузке

```python
_PAR_BRANCH_RE = re.compile(r"^PAR-(\d+)/")

async def _load_from_db(self, db_row: dict) -> AgentSession:
    # ... existing code ...
    # Reconcile branch AND task_id from actual worktree
    if session.worktree_path and Path(session.worktree_path).is_dir():
        actual = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=session.worktree_path, capture_output=True, text=True
        )
        if actual.returncode == 0:
            actual_branch = actual.stdout.strip()
            if actual_branch != session.branch:
                session.branch = actual_branch
                # Derive task_id from branch name
                m = _PAR_BRANCH_RE.match(actual_branch)
                session.task_id = f"PAR-{m.group(1)}" if m else ""
                save_session(session._to_db_dict())
```

## Implementation Plan

### Фаза 1: Core (branch naming + merge guards + session locks) — MUST HAVE

**Порядок:** DB → workspace → session → manager → API → MCP

1. **`app/db.py`** — миграция: `ALTER TABLE sessions ADD COLUMN task_id`
2. **`app/session.py`** — добавить `task_id` в dataclass, `_to_db_dict()`, `to_dict()`
3. **`app/workspace.py`**:
   - `create_worktree()`: task_id → branch name, явный base `main`, проверка коллизии через `git show-ref`, убрать `branch -D` fallback
   - `merge_worktree_to_main()`: убрать auto-commit → reject dirty, проверка dirty repo + HEAD=main
   - Валидация task_id: `^(PAR-)?\d+$`, branch через `git check-ref-format`
4. **`app/manager.py`**:
   - Протащить task_id через `create_session()`, `enqueue_worker_spawn()`
   - `_load_from_db()`: reconcile branch + task_id из worktree
   - **Per-session `asyncio.Lock`** для serialization merge/switch/send
5. **`app/main.py`** — `/api/sessions` POST: принять task_id; merge endpoint: acquire session lock + проверка session idle
6. **`app/mcp_stdio.py`** — `spawn_worker()`: добавить task_id параметр

### Фаза 2: switch_branch для system workers

1. **`app/workspace.py`** — `switch_worktree_branch()` с guards + always merge main for existing branches + worktree conflict check
2. **`app/main.py`** — `POST /api/sessions/{name}/switch-branch` (behind session lock)
3. **`app/mcp_stdio.py`** — tool `switch_worker_branch()`
4. **`app/manager.py`** — метод для обновления branch/task_id + prompt injection

### Фаза 3: Промпты

1. **`app/prompts/orchestrator.md`** — документация: task_id в spawn, switch_worker_branch flow, правило "один PAR на worker"
2. **`app/prompts/worker.md`** — обновить: ветка может меняться, всегда коммитить перед switch

## Migration

**Обратная совместимость полная:**
- `task_id` optional, default empty → текущие воркеры работают с `feat/` ветками
- merge guards (dirty reject) — breaking change для auto-save, но правильный: незавершённая работа не должна попадать в main
- Новые tools не ломают существующие

**Rollback:** не передавать `task_id`. Единственный неоткатываемый change — убираем auto-save при merge. Но это bug fix, не feature.
