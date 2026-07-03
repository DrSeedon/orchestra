# Plan — полная телеметрия субагентов

**Дата:** 2026-07-01
**Основа:** research.md. Собрать ВСЁ, ничего не терять, база для «отдельного чата субагента».

---

## Решения по развилкам

### A. Хранилище → **таблица `subagents`** (не JSON в logs)
Обоснование: юзер хочет «отдельный чат субагента» + cost-аналитику пер-субагент. JSON в logs это не даёт (нельзя query «субагенты сессии X с токенами»). Таблица = одна строка на субагента.

**⚠️ ИСПРАВЛЕНО ПО CODEX (3 blocking):**
- `task_id` НЕ глобально уникален → PK = автоинкремент `id`, UNIQUE(session_id, task_id).
- **`sdk_session_id`** обязателен: DB `session_id` = Orchestra id, но `get_subagent_messages()` требует SDK/Claude session_id. Без него транскрипт-endpoint вернёт ПУСТО. Берём из Task*-message.`session_id`.
- Собрать `tool_use_id` (мост к live parent_tool_use_id), `raw_json` (data-dict, «ничего не терять»).

```sql
CREATE TABLE IF NOT EXISTS subagents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,  -- Orchestra id
    task_id TEXT NOT NULL,
    sdk_session_id TEXT DEFAULT '',       -- Claude SDK session id (для get_subagent_messages)
    tool_use_id TEXT DEFAULT '',          -- мост к StreamEvent.parent_tool_use_id
    description TEXT DEFAULT '',
    task_type TEXT DEFAULT '',
    status TEXT DEFAULT 'running',        -- running | completed | failed | stopped
    total_tokens INTEGER DEFAULT 0,
    tool_uses INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    last_tool_name TEXT DEFAULT '',
    output_file TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    raw_json TEXT DEFAULT '',             -- data-dict финала (ничего не терять)
    started_at TEXT NOT NULL,
    ended_at TEXT,
    UNIQUE(session_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);
```
Миграция: `CREATE TABLE IF NOT EXISTS` в `init_db`. Без ALTER.

**upsert через `ON CONFLICT(session_id, task_id)`:**
- COALESCE с `''` НЕ работает (`''` != NULL). Использовать `COALESCE(NULLIF(excluded.x, ''), subagents.x)` — пустое из progress не затирает.
- Числа (токены): брать latest/final, НЕ суммировать progress-события (`TaskProgress.usage` кумулятивен). `excluded.total_tokens` побеждает если > 0.
- Если `TaskNotification.usage is None` — оставить последние progress-значения (тот же NULLIF-guard).

### B. Транскрипт → **endpoint пост-фактум** (не стрим в БД)
`GET /api/subagent/{session_id}/{task_id}/messages?limit=&offset=` → `get_subagent_messages`.
Обоснование: транскрипт большой, лениво по клику. НЕ дублируем в БД (SDK уже хранит JSONL). База для «чата субагента». Пагинация через SDK limit/offset.

**⚠️ ИСПРАВЛЕНО ПО CODEX:**
- route `{session_id}` = Orchestra DB id → в БД находим строку subagents → в `get_subagent_messages` передаём **`sdk_session_id`** (не Orchestra id!) и **`agent_id`** (см. probe: task_id или из mapping).
- `directory` = **cwd проекта** (session.cwd/worktree), НЕ config_dir.
- Кастомные профили: SDK читает `CLAUDE_CONFIG_DIR` из **process env**, не из параметра. Endpoint должен учитывать `session.profile/config_dir` (выставить env или передать directory). Иначе пусто вне personal-профиля.
- Path traversal: `task_id`/`session_id` из URL → валидировать (только [\w-], не пускать в fs path напрямую). SDK берёт agent_id для имени файла — санитизировать.
- fallback: если `task_id != agent_id` (probe покажет) → `list_subagents(sdk_session_id, cwd)` + mapping через tool_use_id.

### C. Cost → **хранить пер-субагент, НЕ прибавлять к session total**
TaskUsage уже в parent total_cost_usd. `subagents.total_tokens` = только для аналитики/отображения. НЕ трогаем session cost арифметику.

---

## Изменения по файлам

### 1. `app/db.py`
- `init_db`: `CREATE TABLE subagents` (+ index).
- `subagent_upsert(task_id, session_id, **fields)` — INSERT OR UPDATE. start создаёт (started_at), progress/end обновляют переданные поля (COALESCE — не затирать пустым).
- `get_subagents(session_id) -> list[dict]` — для дашборда/аналитики.
- `get_subagent(task_id) -> dict | None`.

WHY upsert с COALESCE: события приходят start→progress(N раз)→end. Каждое несёт подмножество полей. Не затирать summary пустой строкой из progress.

### 2. `app/backend_claude.py` — доставать ВСЁ
- `TaskStartedMessage` → event metadata: `{subagent_id, description, task_type, phase:"start"}`.
- `TaskProgressMessage` → metadata: `{subagent_id, description, last_tool_name, total_tokens, tool_uses, duration_ms, phase:"progress"}` (все 3 из TaskUsage).
- `TaskNotificationMessage` → metadata: `{subagent_id, status, summary(ПОЛНЫЙ, не [:500]), output_file, total_tokens, tool_uses, duration_ms, phase:"end"}`.
- Хелпер `_task_usage(usage) -> dict` — вытащить 3 поля из TaskUsage (TypedDict/obj).
- Content строки для UI оставить (back-compat с subagent visibility рендером), метаданные — в metadata.

### 3. `app/session.py` — persist телеметрию
- В `_handle_event` для subagent_start/progress/end: помимо `_log` (как сейчас, для TG/чата) → вызвать `subagent_upsert(task_id, session_id, ...)` с полями из metadata.
- Fire-and-forget через тот же _db_executor (не блокировать loop).
- subagent_start: upsert(status=running, started_at=now, description, task_type).
- subagent_progress: upsert(last_tool_name, total_tokens, tool_uses, duration_ms).
- subagent_end: upsert(status, summary, output_file, ended_at=now, финальные токены).

### 4. `app/routes/sessions.py` (или новый routes/subagent.py)
- `GET /api/subagents/{session_id}` → get_subagents (список + телеметрия).
- `GET /api/subagent/{session_id}/{task_id}/messages?limit=100&offset=0` → get_subagent_messages, JSON. Найти `directory` (session store path — из config_dir профиля сессии или CLAUDE_CONFIG_DIR). Обернуть в try — если транскрипта нет, вернуть {messages:[], error}.

### 5. `app/events.py`
- Дополнить комментарии metadata для subagent_* (subagent_id, phase, токены). Тип не меняем.

---

## Что НЕ трогаем
- session cost арифметику (двойной счёт!).
- subagent visibility live-стрим (уже работает, broker-only).
- Существующий рендер subagent_* на фронте (аккордеон) — metadata добавляется, content-строки сохранены для back-compat.

---

## ✅ PROBE ВЫПОЛНЕН (через SDK source + реальные локальные транскрипты, live не нужен)

Разобрал `claude_agent_sdk/_internal/sessions.py` + проверил на РЕАЛЬНЫХ транскриптах в `~/.claude/projects/`:

1. **Путь**: `~/.claude/projects/<projectDirSlug>/<sdk_session_id>/subagents/**/agent-<agent_id>.jsonl`. Проверено — файлы существуют, `list_subagents` + `get_subagent_messages` РАБОТАЮТ на живых данных (вернули 2 субагента + транскрипт).
2. **`directory=None` работает** — SDK ищет по всем `~/.claude/projects/`. Безопасный fallback (не нужно вычислять projectDirSlug).
3. **`session_id` = SDK session UUID** (валидируется как UUID). НЕ Orchestra id. → `sdk_session_id` в таблице ОБЯЗАТЕЛЕН.
4. **`agent_id` ≠ `task_id`** ⚠️ ПОДТВЕРЖДЕНО: `agent_id` = имя файла `agent-{id}` (напр. `ae795e652a2bbf63a`), в транскрипте только `agentId`, НЕТ task_id/toolUseId. TaskStartedMessage.task_id — ДРУГОЙ идентификатор. Прямой связи task_id↔agent_id в транскрипте НЕТ.
5. **`data: dict`** — не проверял (нужен live), но по требованию «ничего не терять» → в `raw_json`.

### СЛЕДСТВИЕ для дизайна (ВАЖНО — упрощает):
**Декуплим таблицу и транскрипт-endpoint:**
- Таблица `subagents` = телеметрия из Task*-сообщений (task_id, tokens, summary, output_file, sdk_session_id). Ключ — task_id.
- Транскрипт-endpoint = НЕЗАВИСИМО перечисляет SDK-транскрипты через `list_subagents(sdk_session_id, directory=None)` + `get_subagent_messages`. НЕ требует task_id↔agent_id маппинга.
- Корреляция таблица↔транскрипт: по `sdk_session_id` + порядок/description (не по общему id). Для MVP достаточно: «вот телеметрия субагентов сессии» + «вот их транскрипты» — фронт покажет оба списка по одной сессии.
- Endpoints:
  - `GET /api/subagents/{orchestra_session_id}` → строки из таблицы (телеметрия).
  - `GET /api/subagent-transcripts/{orchestra_session_id}` → `list_subagents(sdk_session_id)` (список agent_id).
  - `GET /api/subagent-transcript/{orchestra_session_id}/{agent_id}?limit=&offset=` → `get_subagent_messages(sdk_session_id, agent_id)`. agent_id санитайзить ([\w-]+).
  - `sdk_session_id` берём из `sessions` таблицы (session.session_id — Claude id) ИЛИ из subagents.sdk_session_id.

---

## Порядок реализации
1. Runtime-probe (живой субагент) → уточнить task_id/directory/data.
2. db.py: таблица + upsert + get.
3. backend_claude.py: доставать все поля в metadata.
4. session.py: upsert телеметрии.
5. routes: endpoints (список + транскрипт).
6. Тесты: upsert (start→progress→end, COALESCE не затирает), get_subagents, endpoint транскрипта (мок get_subagent_messages).
7. Codex review (Contabo 12343).

## Тесты
- `subagent_upsert`: start создаёт → progress обновляет токены, НЕ затирает description → end ставит summary/status, COALESCE сохраняет прошлые поля.
- `get_subagents(session_id)`: возвращает все, сортировка по started_at.
- endpoint транскрипта: мок get_subagent_messages → JSON; отсутствие файла → graceful {error}.
- Двойной счёт: убедиться session cost НЕ меняется от subagent usage.
