# Research — сделать субагентов ВИДИМЫМИ (live-логи)

**Дата:** 2026-07-01
**Задача:** НЕ банить субагентов (Claude Code SDK зашит их юзать). Проблема — они выглядят как ЗАВИСАНИЕ: юзер видит «🤖 Sub-agent: X» + тишина + «✅ completed», не зная что внутри. Показать их активность live.
**SDK:** claude-agent-sdk **0.2.87**.

---

## TL;DR

Хорошая новость: **SDK отдаёт ВСЁ про субагентов**, Orchestra это частично дропает, частично мешает с основным потоком. Три источника данных:

1. **StreamEvent с `parent_tool_use_id != None`** — live partial-текст/дельты субагента. **Сейчас ДРОПАЕТСЯ** (backend_claude.py:250). Включить = live-стриминг вывода субагента.
2. **AssistantMessage/UserMessage с `parent_tool_use_id != None`** — полные tool_use/tool_result/text субагента. **Сейчас НЕ фильтруются** → эмитятся как события основного агента, БЕЗ атрибуции (мешаются с родителем!). Надо тегировать `parent_tool_use_id`.
3. **TaskStartedMessage / TaskProgressMessage / TaskNotificationMessage** — метаданные (старт/прогресс-хартбит/финал). Уже ловим (backend_claude.py:288-305), но плоско.

**Вывод:** это НЕ «SDK даёт мало». SDK даёт полное дерево. Проблема — Orchestra (а) выкидывает live-partial субагента, (б) не связывает события субагента с его task_id → нельзя отрисовать вложенно.

---

## 1. Что SDK реально даёт по субагентам

### Метаданные (уже ловим, backend_claude.py:288-305)
| Message | Поля | Что даёт |
|---------|------|----------|
| `TaskStartedMessage` | `task_id, description, task_type, tool_use_id, session_id, data` | старт субагента |
| `TaskProgressMessage` | `task_id, description, last_tool_name, usage, tool_use_id, data` | хартбит: какой тул сейчас + токены |
| `TaskNotificationMessage` | `task_id, status, summary, output_file, usage` | финал + может писать в файл! |

`TaskUsage` (TypedDict): `total_tokens, tool_uses, duration_ms`.
`data: dict[str, Any]` — сырое поле, может нести доп. детали (проверить в рантайме на живом субагенте).

### Полные логи (НЕ используем должным образом)
**Ключевое:** `AssistantMessage` И `UserMessage` имеют поле **`parent_tool_use_id`**.
- Субагент вызвал Bash → приходит `AssistantMessage(content=[ToolUseBlock(Bash)], parent_tool_use_id="task_xxx")`.
- Результат → `UserMessage(content=[ToolResultBlock], parent_tool_use_id="task_xxx")`.
- Текст субагента → `AssistantMessage(content=[TextBlock], parent_tool_use_id="task_xxx")`.

→ **Полная активность субагента (его tool-вызовы, их вывод, его текст) ДОСТУПНА.** Проблема: `_convert` (backend_claude.py:262-286) НЕ смотрит на `parent_tool_use_id` для Assistant/User → эмитит их как обычные `tool_use`/`tool_result`/`text` события основного агента. Они СЕЙЧАС уже в потоке, но неотличимы от родителя → выглядят как будто основной агент сам это делает, ИЛИ (если CLI буферизует) прилетают пачкой после «тишины».

### Live-стрим субагента (ДРОПАЕТСЯ)
`StreamEvent.parent_tool_use_id` — партиалы субагента. backend_claude.py:250:
```python
if msg.parent_tool_use_id is not None:
    return events   # ← субагентские партиалы ВЫКИДЫВАЕМ
```
Комментарий (стр 246): «v1 streaming scope: ONLY main-agent text». Осознанное ограничение v1. Снять его = live-typing вывода субагента.

### SDK-функции для субагентов (бонус, не для live)
`list_subagents(session_id, directory)` → list[str] (id субагентов).
`get_subagent_messages(session_id, agent_id, ...)` → list[SessionMessage] (полный транскрипт субагента из стора, ПОСТ-фактум).
→ полезно для «раскрыть завершённого субагента» (клик → подтянуть транскрипт), но не для live.

---

## 2. Nested субагенты (субагент → свои субагенты)

- SDK-типы это поддерживают структурно: `parent_tool_use_id` — цепочка. Субагент A (task_1) спавнит субагента B → события B несут `parent_tool_use_id` B, а B стартовал внутри A.
- **НО** плоский `parent_tool_use_id` даёт только ОДИН уровень родителя, не полную глубину. Чтобы построить ДЕРЕВО, надо трекать маппинг `task_id → parent task_id` по `TaskStartedMessage` (у него есть `tool_use_id` = откуда запущен).
- **Наша версия 0.2.87** — типы позволяют. Реально ли CLI шлёт nested-события — надо проверить экспериментом (спавнить субагента который сам спавнит). Практически: для v1 достаточно ОДНОГО уровня (родитель → субагенты), nested-дерево — v2.

---

## 3. План: как показать live-логи субагента

### Backend (app/backend_claude.py, app/events.py)
1. **Тегировать события субагента `parent_tool_use_id`:**
   - В `_convert`, для `AssistantMessage`/`UserMessage`: если `msg.parent_tool_use_id` задан → добавить в `AgentEvent.metadata` поле `subagent_id=parent_tool_use_id`. Событие остаётся tool_use/tool_result/text, но помечено принадлежностью субагенту.
2. **Включить live-partial субагента:**
   - backend_claude.py:250 — вместо `return events` эмитить `AgentEvent("subagent_stream", text, metadata={subagent_id})`. Отдельный тип, чтобы фронт клал его в блок субагента, не в основной.
3. **task_id в start/progress/end уже есть** — прокинуть его в metadata (сейчас в строку через `|`, лучше в metadata структурно).

### Events/persistence (app/session.py, app/events.py)
4. `AgentEvent` уже носит `metadata` (см. tool_use). Добавить `subagent_id` туда — минимально.
5. Live-partial субагента — через тот же `live_broker` что основной стриминг (session.py:519 роутит stream в broker). Роутить `subagent_stream` тоже, с subagent_id.

### Frontend (app/static/js/app.js:2229+)
6. Сейчас subagent_start/progress/end — плоские строки. Сделать **аккордеон**: subagent_start создаёт контейнер с `data-subagent-id`, последующие `subagent_stream`/tool_use[subagent_id]/progress кладутся ВНУТРЬ него (вложенный поток), subagent_end сворачивает.
7. Live-typing вывода субагента — как у основного (typewriter уже есть для stream).

### TG (app/tg_bridge.py)
8. Сейчас TG субагентов не рендерит (grep пусто). Минимум — при subagent_end слать «🤖 Sub-agent X: <summary>». Live-стрим в TG НЕ слать (спам, как решили для основного — final-only). Опционально: одно сообщение «субагент работает: tool=X» с edit по прогрессу.

---

## Оценка сложности

| Часть | Сложность | Заметки |
|-------|-----------|---------|
| Тегировать subagent_id в metadata (Assistant/User) | низкая (~15 стр) | backend_claude._convert |
| Включить subagent_stream (снять дроп :250) | низкая (~10 стр) | + роутинг в broker |
| task_id/parent в metadata структурно | низкая | заменить `|`-строки |
| Frontend аккордеон вложенности | **средняя** (~60-80 стр JS) | группировка по subagent_id, сворачивание |
| TG subagent_end сообщение | низкая (~15 стр) | tg_bridge |
| Nested-дерево (>1 уровень) | высокая | v2, отдельно. Нужен маппинг task→parent + эксперимент |

**MVP (рекомендую):** тегирование subagent_id + subagent_stream + фронт-аккордеон ОДНОГО уровня + TG-финал. Nested — отдельная задача после проверки что CLI их реально шлёт.

---

## Риски / edge cases

1. **Смешение с основным потоком** — сейчас subagent Assistant/User события уже эмитятся без тега. Если добавим тег, но фронт старый — они всё равно покажутся в основном (back-compat ок, просто без группировки). Не ломает.
2. **Объём partial-ов** — субагент может генерить много. Как основной поток, через bounded broker queue (drop-oldest уже есть, live_broker.py). Не заспамит.
3. **parent_tool_use_id для nested** — плоский, только 1 родитель. Для дерева нужен доп. маппинг. MVP — не строим дерево, только «субагент под родителем».
4. **`data` поле** — не изучено что внутри. Проверить экспериментом, но не блокер (метаданных из явных полей достаточно).
5. **Персистентность** — live-partial субагента эфемерны (как основной stream, не в DB). Финал субагента (subagent_end) — в лог. При reconnect SSE — только финал, live уже прошёл (как основной stream, ок).

---

## Рекомендация

**MVP из 4 частей** (backend теги + subagent_stream + фронт-аккордеон 1 уровень + TG-финал). ~110-130 строк, средняя сложность. Nested-дерево — отдельная задача (сначала эксперимент: реально ли CLI 0.2.87 шлёт nested-события).

Ключевая правка ДЕШЁВАЯ и с наибольшим эффектом: **снять дроп на backend_claude.py:250** + тегировать subagent_id. Это сразу превращает «тишину» в живой поток. Фронт-аккордеон — косметика поверх.

НЕ реализую — жду решения оркестратора (MVP / что-то урезать / расширить до nested).
