# Review #35 — Reliability & Failure Modes

Scope: `app/session.py`, `app/manager.py`, `app/backend_claude.py`, `app/workspace.py`, `app/tg_bridge.py`.
Lens: что падает под нагрузкой, что зависает, что течёт, что теряется при рестарте, что ломается при 10 параллельных агентах.

Severity: **P0** crash/data-loss/leak в обычном проде · **P1** ломается под нагрузкой/в гонке · **P2** деградация/редкий кейс · **P3** nit.

---

## P0 — Zombie CLI-процессы остаются после спавна, который упал на полпути

**`app/manager.py:503-529`** (`create_session`, блок `try/except`).

`_ensure_backend()` коннектится **только** при первом `send()`. Но `session.start()` (строка 524) НЕ коннектит backend, если `initial_message` нет — а в `_spawn_worker_loop` (`manager.py:355-365`) сначала `create_session(...)`, потом отдельно `await session.send(job["task"])`. То есть backend поднимается в `send()`, уже ПОСЛЕ выхода из `create_session`'s `try/except`.

Проблема в другом сценарии: если `create_session` падает на `create_worktree`/`_inject_skills` (строки 508-512) ПОСЛЕ того как worktree создан, но ДО `self.sessions[session.id] = session` — мы делаем `delete_session(session.id)` (строка 528), но **worktree на диске и git-ветка НЕ удаляются**. `remove_worktree` вызывается только в `manager.remove()`, а сюда мы не попадаем (сессии нет в реестре). Накапливается мусор: осиротевшие worktrees + ветки `task-N/<name>`, которые при повторном спавне с тем же именем дадут `worktree already exists` (`workspace.py:69`) и спавн будет падать вечно.

**Фикс:** в `except` блоке `create_session` — если worktree уже создан, откатить его:
```python
except Exception:
    delete_session(session.id)
    if session.worktree_path:
        try:
            await asyncio.to_thread(remove_worktree, repo_path, session.worktree_path)
        except Exception:
            pass
    raise
```

---

## P0 — Backend-процесс не убивается, если connect() частично прошёл и упал

**`app/session.py:236-246`** (`_ensure_backend`) + **`app/backend_claude.py:128-134`** (`connect`).

`ClaudeBackend.connect()` делает `self._client = self._make_client()` затем `await client.connect()` с таймаутом 60с. Если `connect()` бросит **TimeoutError** (CLI повис на старте), `self._client` уже установлен, но в `_ensure_backend` мы ловим исключение и делаем `self._backend = None` — **не вызвав `disconnect()`**. Объект `ClaudeSDKClient` с уже спавненным CLI-субпроцессом теряется без закрытия → zombie CLI-процесс висит до смерти сервера.

То же в `reconnect()` (`backend_claude.py:181-185`): `disconnect()` → `_make_client()` → `connect()` с таймаутом; при таймауте новый client с живым subprocess протекает.

**Фикс:** в `ClaudeBackend.connect()`/`reconnect()` оборачивать `await client.connect()` в try и при любой ошибке звать `await client.disconnect()` перед `raise`:
```python
async def connect(self):
    self._client = self._make_client()
    try:
        await asyncio.wait_for(self._client.connect(), timeout=60)
    except Exception:
        try: await self._client.disconnect()
        except Exception: pass
        self._client = None
        raise
```

---

## P1 — `_log` / `_persist`: неограниченный fire-and-forget на дефолтный thread-pool → contention при 10 агентах

**`app/session.py:765-776`**.

```python
def _persist(self):
    fut = asyncio.get_event_loop().run_in_executor(None, save_session, ...)  # default executor
def _log(self, type, content):
    asyncio.get_event_loop().run_in_executor(None, add_log, ...)  # НЕ трекается вообще
```

Каждый `add_log`/`save_session` **открывает новое SQLite-соединение** (`db._conn()`, `db.py:28`) — нет пула, нет переиспользования. Дефолтный executor = `min(32, cpu+4)` потоков (тот же, что использует `asyncio.to_thread` в `create_worktree`/`merge`/`_auto_commit`).

При 10 RUNNING-агентах каждый стримит десятки событий → сотни `_log` в секунду, каждый = новый коннект + `PRAGMA journal_mode=WAL` + `busy_timeout`. Под нагрузкой:
1. Thread-pool забивается логами → `asyncio.to_thread(create_worktree)` и merge-операции встают в очередь за логами (тот же пул) → спавн/мерж тормозят на секунды.
2. `_log` фьючи **не трекаются** (`_persist` хотя бы кладёт в `_persist_futs`) — при shutdown часть логов теряется, исключения внутри `add_log` проглатываются молча (fire-and-forget без `add_done_callback`).
3. WAL-файл растёт без принудительного checkpoint при тысячах мелких write-транзакций.

**Фикс (минимальный):**
- Выделить **отдельный** `ThreadPoolExecutor(max_workers=4)` под DB-запись, чтобы логи не конкурировали с git-операциями на дефолтном пуле.
- Либо батчить логи: копить в очередь, флашить пачкой раз в N мс одним коннектом.
- Добавить `add_done_callback` на `_log`-futures чтобы исключения попадали в лог, а не в `Future exception was never retrieved`.

---

## P1 — `auto_resume_all`: одновременный реконнект всех агентов после рестарта = шторм CLI-спавнов

**`app/manager.py:872-911`** + **`app/manager.py:913-923`** (`_inject_restart_notice`).

При рестарте `auto_resume_all` грузит все idle+running сессии из DB. Сами `_load_from_db` → `session.start()` (без initial_message) backend НЕ коннектят — это ок. Но `_inject_restart_notice` для каждой бывшей `running`-сессии делает `session.send(...)` → `_ensure_backend()` → спавн CLI. Джиттер есть (`sleep(3 + random(0,12))`, строка 915), окно 12с.

Если было 15 running-агентов — 15 CLI-процессов поднимаются в окне 12с, каждый `connect()` с `timeout=60`, каждый грузит resume-сессию (тяжёлый IO). На слабой машине/при медленном прокси часть упрётся в 60с-таймаут connect → P0-зомби выше + сессия останется IDLE с потерянным «continue»-сообщением.

Плюс: `_load_from_db` для каждого worktree-воркера делает **синхронный** `subprocess.run(git rev-parse)` (`manager.py:724-733`) прямо в event-loop'е resume (не через `to_thread`) — при 15 воркерах это 15 блокирующих git-вызовов подряд, event loop стоит.

**Фикс:**
- `subprocess.run` в `_load_from_db` (строки 724-733) → `await asyncio.to_thread(...)`. Сейчас блокирует loop.
- Ограничить параллелизм реконнектов семафором (например 3-4 одновременных `_inject_restart_notice`), а не полагаться на 12с-джиттер.

---

## P1 — Гонка спавна vs `change_orchestrator_scope`: worktree создаётся вне queue, два пути к `create_session`

**`app/manager.py:344-372`** (queue) vs **`app/main.py:391`** (прямой HTTP).

`spawn_worker` MCP-тул идёт через `enqueue_worker_spawn` → единственный `_spawn_worker_loop` — спавны сериализованы (хорошо). Но HTTP-эндпоинт `POST /api/sessions` (`main.py:386`) зовёт `manager.create_session` **напрямую**, в обход очереди. Два параллельных HTTP-спавна с одинаковым `name` могут оба пройти `get_session_by_name` (строка 431) до того как любой запишет в DB → оба создают worktree → второй падает на `worktree already exists`, но первый уже успел; либо гонка на `_pick_color`/`owned_dirs`-overlap-скане (читает `self.sessions`, который ещё не обновлён).

`change_orchestrator_scope` (`manager.py:565-625`) честно документирует TOCTOU: «Full closure needs a scope-level spawn lock» (строка 599) — но этого лока нет. Воркер может заспавниться в old_scope между проверкой `_live_workers_in_scope` и `change_scope`.

**Фикс:** ввести `scope`-level lock (`get_session_lock` уже есть в менеджере, `manager.py:335`, но **нигде не используется**!). Брать его в `create_session` и в `change_orchestrator_scope`. Сейчас `_session_locks` — мёртвый код, реальной сериализации нет.

---

## P1 — `merge_worktree_to_main`: блокирующий fcntl.flock + длинная цепочка subprocess в event loop

**`app/workspace.py:252-402`**.

`merge_worktree_to_main` целиком синхронная: `fcntl.flock(LOCK_EX)` (блокирующий!) + ~10 `subprocess.run`. Вызывается через `asyncio.to_thread` в `merge_worker` MCP-тул? Проверить вызывающий код — если где-то зовётся напрямую в async-контексте, `fcntl.flock` **заблокирует весь event loop** до освобождения лока другим процессом.

Сценарий «5 мерджатся одновременно»: лок `.git/orchestra-merge.lock` — межпроцессный, но все мерджи в одном Orchestra-процессе идут через thread-pool. 5 потоков берут `flock` → 4 блокируются в потоке (ок, не loop), НО они держат потоки дефолтного пула → см. P1 про contention: логи/спавны встают за мерджами. При `max_workers≈min(32,cpu+4)` и медленном merge (cherry-pick больших веток) пул выедается.

**Фикс:** убедиться что merge ВСЕГДА через `asyncio.to_thread`/выделенный executor; вынести git-тяжёлые операции на отдельный bounded executor (1-2 воркера, мерджи всё равно сериализуются локом — параллелить их смысла нет).

---

## P1 — Потеря сообщений при рестарте mid-turn и mid-compact

**`app/session.py:107` `_pending_messages`** + **`manager.py:882`**.

`_pending_messages` живёт **только в памяти**. Сценарии потери:
1. Воркер RUNNING, юзер шлёт сообщение → оно в `_pending_messages` (codex) или инжектится (claude). Рестарт сервера → `_pending_messages` пропадает. `auto_resume_all` сбрасывает status в idle (`manager.py:882`), но очередь сообщений утеряна — воркер не узнает что ему писали.
2. **Mid-compact (`compact()`, `session.py:591-661`):** если рестарт случился между `self.session_id = None` (строка 648) и сохранением нового session_id после `self.send(preamble...)` — `_persist` мог записать `session_id=None` в DB. При resume `session_id IS NOT NULL` фильтр (`manager.py:879`) **отбросит эту сессию** → агент не восстановится вообще, контекст потерян. Плюс `_compacting=True` не персистится → после рестарта флаг сбросится, но summary-инъекция уже наполовину сделана = разорванный контекст.

**Фикс:**
- Персистить `_pending_messages` в DB (или в inbox-таблицу) при добавлении.
- В `compact()`: не обнулять `session.session_id` до получения нового; делать compact атомарно — хранить старый session_id как fallback в DB пока новый не подтверждён. При resume mid-compact — откатываться на старый session_id.

---

## P2 — `_claude_event_loop`: бесконечный reconnect-цикл при стабильно падающем backend

**`app/session.py:256-298`**.

`while True` с реконнектом внутри `except`. Если backend падает сразу после `reconnect()` (например, битый resume session_id, или Anthropic стабильно 500), цикл: events() кидает → reconnect (2с sleep) → send → events() снова кидает → ... Реконнект ограничен только тем, что при провале самого `reconnect()` ставит `_backend=None` и выходит. Но если `reconnect()` УСПЕШЕН, а следующий `events()` сразу падает — бесконечная карусель с 2с паузой, жжёт CLI-спавны и логи без предела. Нет счётчика попыток/backoff.

**Фикс:** счётчик последовательных reconnect'ов (сброс при успешном событии); после N (3-5) подряд — сдаться, status=IDLE, `report` оркестратору «backend unstable», не крутиться вечно.

---

## P2 — Network failures: connect/reconnect ретраят, но send() и query() — нет

**`app/backend_claude.py:136-139`** (`send`) + **`139` `query`**.

`send()` просто `await self._client.query(message)`. Если CLI/прокси умер ровно в этот момент (прокси Hiddify на 127.0.0.1:12334 — единая точка отказа, упоминается в CLAUDE.md), `query()` бросит. В `session.send` (claude, RUNNING-ветка, `session.py:180-188`) исключение ловится → сообщение в `_pending_messages` — ок. Но в `_flush_pending` (`session.py:469-483`) при провале `backend.send` сообщения **уже извлечены из очереди** (`session.py:459-460` `_pending_messages.clear()`) и при ошибке НЕ возвращаются обратно → **потеря batch'а сообщений**.

**Фикс:** в `_flush_pending` при ошибке возвращать `msgs` обратно в начало `_pending_messages`:
```python
except Exception as e:
    self._pending_messages[:0] = msgs  # вернуть в начало
    self.status = AgentStatus.IDLE
    self._persist()
```

---

## P2 — Disk: worktrees/логи/WAL/uploads растут, чистки нет (кроме uploads)

1. **Worktrees** (`workspace.py:547-569`): удаляются только при явном `manager.remove()`. Осиротевшие (P0 выше), плюс если юзер килляет сессию через DB напрямую — worktree остаётся. Нет периодической сборки `git worktree prune`.
2. **Логи в SQLite** (`db.add_log`): пишутся каждое событие, **нет ретеншна/чистки**. Таблица logs растёт бесконечно. При долгоживущих агентах (оркестратор недели работает) — гигабайты.
3. **WAL** (`db.py:32`): `journal_mode=WAL`, но нигде нет `wal_checkpoint(TRUNCATE)`. При тысячах мелких write WAL-файл пухнет, читатели видят растущий `-wal`.
4. **Uploads** (`tg_bridge.py:96-106`): чистка есть (LRU по 1GB) — ок. Но `_media_cache`/`_transcription_cache` JSON растут без обрезки.

**Фикс:** периодическая задача: `DELETE FROM logs WHERE ts < now-Nd` + `PRAGMA wal_checkpoint(TRUNCATE)` + `git worktree prune` по scope раз в час.

---

## P2 — `_idle_hibernate` vs `send()`: гонка пробуждения

**`app/session.py:495-507`** vs **`session.py:190-198`**.

`_idle_hibernate` берёт `_lifecycle_lock`, проверяет `status==IDLE` и `_backend`, дисконнектит. `send()` тоже берёт `_lifecycle_lock` и кансельит `_hibernate_task` (строки 191-193). Лок защищает, НО: `_idle_hibernate` уже мог пройти проверки и начать `await self._disconnect_backend()` (внутри лока), а `send()` ждёт лок. После hibernate `send` входит, `_hibernated=True` → коннектит заново. Это ок по корректности, но `_disconnect_backend` (`session.py:736-756`) внутри лока делает `await self._listen_task` (cancel+await) — если listener в этот момент в `reconnect()` (2с sleep), hibernate ждёт его, держа лок, → `send()` залипает на секунды. Не дедлок, но залипание турна.

**Фикс:** низкий приоритет; задокументировать. Можно не ждать listener-cancel под локом, а отменять без await.

---

## P2 — `_refresh_context_from_api` и прочие `asyncio.create_task` без хранения ссылки → GC может убить задачу

**`app/session.py:421, 425, 440, 444, 447, 450`** и др.

`asyncio.create_task(self._refresh_context_from_api())` и ~6 других мест создают задачи без сохранения ссылки. Python GC может собрать задачу до завершения (задокументированный footgun asyncio — «task was destroyed but it is pending»). Для `_auto_compact`, `_auto_continue`, `_notify_scope_idle` — если потеряются, тихо не выполнятся (авто-компакт не сработает → агент упрётся в лимит контекста).

**Фикс:** держать set «живых» фоновых задач (как `_persist_futs`), добавлять туда, снимать в `add_done_callback`. Шаблон уже есть для persist — применить ко всем create_task.

---

## P3 — `_heartbeat_loop` зомби-детект для claude слишком мягкий

**`app/session.py:539-554`**.

Для claude zombie_timeout = 1800с (30 мин!) и при `_backend is not None` он НЕ убивает, только логирует «possible long thinking». То есть claude-агент, чей CLI реально завис (не codex), будет висеть RUNNING полчаса минимум, потом всё равно не киляется (ветка `else` на 552-554 только логирует). Реальный hang claude-агента детектится только через listener-death (отдельная ветка 559-574), а не через silence.

**Фикс:** для claude после 30 мин silence + backend alive — всё же форсить reconnect или interrupt, а не только лог.

---

## P3 — `stream_logs` per-topic loop без завершения + рост при пересоздании топиков

**`app/tg_bridge.py:848-969`** + **`tg_bridge.py:1157-1158`**.

Каждый топик = вечный `while True` с `sleep(2)`, polling логов из DB. Задачи кладутся в `_tasks` и в `ensure_topics` (`tg_bridge.py:827`) тоже плодятся (`asyncio.create_task(stream_logs(...))`). При пересоздании топика / повторном `ensure_topics` для того же orch — **дубль stream_logs** не проверяется → два цикла шлют одно и то же в TG (дублирование сообщений) + 2× нагрузка на DB poll. `_deferred_startup` стартует stream_logs для всех topics (1157), а `ensure_topics` (вызываемый и из `topic_sync_loop` каждые 30с) — для НОВЫХ. Если orch удалён и пересоздан — старый цикл по мёртвому session_id крутится вечно.

**Фикс:** реестр активных stream_logs-задач по orch_name; не плодить дубль; отменять при удалении топика.

---

## Сводка по приоритетам

| # | Severity | Файл | Суть |
|---|----------|------|------|
| 1 | **P0** | manager.py:503-529 | осиротевшие worktree+ветка при падении спавна |
| 2 | **P0** | backend_claude.py:128-185 | zombie CLI при таймауте connect/reconnect |
| 3 | **P1** | session.py:765-776 | `_log`/`_persist` забивают дефолтный thread-pool, конкурируют с git |
| 4 | **P1** | manager.py:724-733, 913-923 | блокирующий subprocess в loop + шторм реконнектов при рестарте |
| 5 | **P1** | manager.py:335, 565-625, main.py:391 | `_session_locks` мёртвый код, нет scope-lock, TOCTOU спавна |
| 6 | **P1** | workspace.py:252-402 | git-merge цепочка занимает потоки общего пула |
| 7 | **P1** | session.py:107, 591-661 | потеря `_pending_messages` и битый контекст при рестарте mid-compact |
| 8 | **P2** | session.py:256-298 | бесконечный reconnect без backoff/лимита |
| 9 | **P2** | session.py:455-483 | потеря batch'а сообщений в `_flush_pending` при ошибке |
| 10 | **P2** | db/workspace/tg | нет ретеншна логов, WAL checkpoint, worktree prune |
| 11 | **P2** | session.py:495-507 | залипание турна при hibernate-vs-send гонке |
| 12 | **P2** | session.py:421+ | `create_task` без ссылки → GC убивает фоновые задачи |
| 13 | **P3** | session.py:539-554 | claude zombie-detect 30 мин и всё равно не киляет |
| 14 | **P3** | tg_bridge.py:848-969 | дубль stream_logs, утечка циклов по мёртвым топикам |

### Топ-3 на немедленный фикс
- **P0 #2** (zombie CLI при connect-таймауте) — прямая утечка процессов, ровно то про что просили. ~6 строк.
- **P0 #1** (осиротевшие worktree) — ломает повторный спавн навсегда + ест диск. ~5 строк.
- **P1 #5** (`_session_locks` не используется) — лок написан, но мёртв; реальной сериализации спавнов через HTTP нет. Включить уже готовый механизм.
