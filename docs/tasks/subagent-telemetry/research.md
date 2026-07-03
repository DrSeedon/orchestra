# Research — полная телеметрия субагентов (ничего не терять)

**Дата:** 2026-07-01
**SDK:** claude-agent-sdk **0.2.87**
**Задача:** собирать ВСЁ что SDK даёт по субагентам в БД. Сейчас теряем output_file, summary, per-subagent usage, полный транскрипт.

---

## Что SDK реально шлёт (инспект всех полей)

### TaskStartedMessage
`subtype, data(dict), task_id, description, uuid, session_id, tool_use_id, task_type`
→ Ловим: description, task_type, task_id. **Теряем: data, uuid, session_id, tool_use_id.**

### TaskProgressMessage
`subtype, data(dict), task_id, description, usage(TaskUsage), uuid, session_id, tool_use_id, last_tool_name`
→ Ловим: description, last_tool_name, usage.total_tokens. **Теряем: usage.tool_uses, usage.duration_ms, data, tool_use_id.**

### TaskNotificationMessage (ФИНАЛ субагента — тут больше всего теряем)
`subtype, data(dict), task_id, status('completed'|'failed'|'stopped'), output_file, summary, uuid, session_id, tool_use_id, usage(TaskUsage|None)`
→ Ловим: status, summary[:500]. **ТЕРЯЕМ: output_file (файл с результатом субагента!), полный summary, usage (финальные токены!), data.**

### TaskUsage (TypedDict)
`total_tokens, tool_uses, duration_ms` — полная стоимость/активность субагента.

### StreamEvent (parent_tool_use_id) — уже подключено ✅ (subagent visibility)

### Транскрипт — 2 пути:
1. **`get_subagent_messages(session_id, agent_id, directory=None, limit=None, offset=0)`** → `list[SessionMessage]`. Читает JSONL-транскрипт субагента. `SessionMessage = {type, uuid, session_id, message, parent_tool_use_id}`.
2. **`list_subagents(session_id, directory=None)`** → `list[str]` (agent_id всех субагентов сессии).
3. **SubagentStopHookInput.agent_transcript_path** — путь к JSONL транскрипту (альтернатива).

`agent_id` для get_subagent_messages = **task_id** из Task*-сообщений (проверить рантаймом, но по смыслу совпадает).

---

## Cost субагентов — ВАЖНОЕ УТОЧНЕНИЕ

`ResultMessage.total_cost_usd` (backend_claude.py:340) = **кумулятивная стоимость всей сессии, УЖЕ включает субагентов** (они бегут в той же сессии/биллинге). Значит:
- **Общий cost НЕ теряется** — субагентские токены уже в parent total_cost_usd.
- **Теряется ПЕР-СУБАГЕНТ атрибуция**: сколько нажёг КОНКРЕТНЫЙ субагент (только TaskProgress/Notification.usage даёт это).
→ Не «добавлять к total» (будет двойной счёт!), а **хранить отдельно для аналитики** «этот субагент = N токенов».

⚠️ **РИСК двойного счёта**: если наивно прибавить TaskUsage.total_tokens к session cost — задвоим (они уже в total_cost_usd). Per-subagent usage = ТОЛЬКО для отображения/аналитики, НЕ для арифметики session cost.

---

## Текущее хранилище

`logs` таблица: `(id, session_id, ts, type, content)` — без metadata-колонки. `add_log(session_id, ts, type, content)`.
Субагентские события сейчас: subagent_start/progress/end логируются как строки `desc | key=val`. Live tool events субагента — broker-only (не в DB, subagent-visibility задача).

Таблицы `subagents` НЕТ.

---

## Что нужно решить (для плана)

### A. Хранилище: JSON в logs vs таблица subagents
- **JSON в logs.content**: subagent_start/end логируем как JSON со всеми полями. Просто, без миграции. Минус: транскрипт большой, query по субагентам неудобен.
- **Таблица `subagents`**: `(task_id PK, session_id FK, description, task_type, status, total_tokens, tool_uses, duration_ms, output_file, summary, started_at, ended_at)`. Плюс: query «покажи субагентов сессии», cost-аналитика, база для «отдельного чата субагента» (идея юзера). Минус: миграция + upsert-логика (start→progress→end обновляют одну строку).

### B. Транскрипт: стрим vs endpoint пост-фактум
- Live-стрим уже частично есть (subagent visibility, эфемерно).
- **Полный транскрипт**: `GET /api/subagent/{session_id}/{task_id}/messages` → get_subagent_messages. Достаём по клику «раскрыть». Проще стрима, не грузит БД, лениво. **База для «отдельного чата субагента»** (юзер хочет).
- `directory` param: транскрипты лежат в session store директории. Нужно узнать path (config_dir профиля / CLAUDE_CONFIG_DIR).

### C. Runtime-probe (ещё не сделан — нужен живой субагент)
- Что реально в `data: dict` каждого Task-типа? (может дублировать явные поля или нести extra).
- Совпадает ли `task_id` с `agent_id` для get_subagent_messages?
- Где физически лежат JSONL транскрипты (directory)?
→ Проверить залогировав сырые msg при живом субагенте (Explore-агенты как юзер гонял).

---

## Файлы под правку
- `app/backend_claude.py` — TaskProgress/Notification: доставать usage(все 3 поля), output_file, summary(полный), data.
- `app/session.py` — persist субагентской телеметрии (в logs JSON или в subagents table).
- `app/db.py` — если таблица subagents: схема + upsert + get.
- `app/routes/` — endpoint транскрипта (get_subagent_messages).
- `app/events.py` — возможно новые типы/метаданные.

## Риски
1. **Двойной счёт cost** — per-subagent usage НЕ прибавлять к session total (уже включён). Только хранить отдельно.
2. **Транскрипт directory** — нужен правильный path к session store (профиль-зависимый). Если неверный → get_subagent_messages вернёт пусто.
3. **data dict** — не изучен рантаймом. Может быть пустой/дублирующий. Не блокер, но проверить.
4. **task_id == agent_id?** — предположение, проверить.
5. **Объём транскрипта** — большой субагент = много сообщений. Endpoint с limit/offset (SDK поддерживает) — пагинация.
6. **upsert start→progress→end** — если таблица: start создаёт строку, progress/end обновляют. Race если события вне порядка (маловероятно, но guard).
