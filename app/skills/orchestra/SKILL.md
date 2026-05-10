---
name: orchestra
description: "Управление Orchestra AI-оркестратором из любой Claude Code сессии. Показывает агентов, отправляет сообщения, спавнит воркеры, читает логи, рестартит сервис. Триггеры: '/orchestra', 'orchestra status', 'покажи агентов', 'отправь в оркестру', 'orchestra agents', 'список воркеров', 'orchestra send', 'что делают агенты'."
roles: [all]
integrations: []
---

# Orchestra Skill — управление AI-оркестратором

## Что это

Orchestra — локальный оркестратор AI-агентов на `http://127.0.0.1:8888`.
Этот skill позволяет управлять им прямо из любой Claude Code сессии через HTTP API.

## Когда вызывать

- `/orchestra` — показать общий статус
- "orchestra status", "покажи агентов", "что делают агенты" → [Status](#status)
- "отправь в оркестру", "отправь агенту", "orchestra send" → [Send](#send)
- "создай воркера", "spawn worker", "запусти агента" → [Spawn](#spawn)
- "покажи логи", "orchestra logs" → [Logs](#logs)
- "перезапусти orchestra", "orchestra restart" → [Restart](#restart)

## Base URL

```
http://127.0.0.1:8888
```

Все запросы — через `curl`. `scope` — путь к проекту (например `/mnt/data/Projects/Python/orchestra`).

---

## Actions

### Status

Показать всех агентов: имя, статус, модель, контекст %, стоимость.

**Шаг 1** — получить список сессий:
```bash
curl -s "http://127.0.0.1:8888/api/sessions" | python3 -m json.tool
```

Если нужно фильтровать по проекту (scope):
```bash
curl -s "http://127.0.0.1:8888/api/sessions?scope=/path/to/project" | python3 -m json.tool
```

**Шаг 2** — получить статистику:
```bash
curl -s "http://127.0.0.1:8888/api/stats" | python3 -m json.tool
```

**Шаг 3** — для каждого активного агента получить контекст (опционально, если нужен %):
```bash
curl -s "http://127.0.0.1:8888/api/sessions/{name}/context?scope={scope}"
```

**Вывод пользователю** — таблица:
```
🤖 Orchestra Agents
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name             Status    Model           Context  Cost
Orchestra-main   idle      claude-opus-4   12%      $0.042
worker-fix-bug   running   claude-sonnet   67%      $0.018
old-worker       stopped   claude-haiku    —        $0.003
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total: 3 agents | Running: 1 | Cost today: $0.063
```

Поля из API-ответа сессии:
- `name` — имя агента
- `status` — idle / running / stopped / error
- `model` — модель
- `context_pct` — контекст %
- `total_cost` — стоимость (USD)
- `is_orchestrator` — true/false

---

### Send

Отправить сообщение конкретному агенту.

**Нужно знать**: имя агента (`name`) и scope проекта (`scope`).

Если пользователь не указал scope — спроси или используй scope текущего проекта:
```bash
# scope — обычно cwd проекта, например /mnt/data/Projects/Python/orchestra
```

**Запрос:**
```bash
curl -s -X POST "http://127.0.0.1:8888/api/sessions/{name}/send" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Твоё сообщение здесь",
    "scope": "/path/to/project",
    "sender": "claude-code"
  }'
```

Ответ `{"ok": true}` — сообщение доставлено. Агент обработает его асинхронно.

**Если агент не найден** — API вернёт 404. Проверь имя через `/api/sessions`.

---

### Spawn

Создать нового воркера.

**Параметры** (спросить у пользователя если не указаны):
- `name` — имя агента (только `[a-zA-Z0-9._-]`, 1-50 символов)
- `cwd` — рабочая директория (должна существовать)
- `model` — модель (дефолт: `claude-sonnet-4-6`)
- `scope` — область видимости (дефолт = `cwd`)
- `system_prompt` — системный промпт (опционально)
- `use_worktree` — создать git worktree (default: false)
- `repo_path` — путь к git-репо (обязателен если `use_worktree=true`)
- `is_orchestrator` — является ли оркестратором (default: false)

**Доступные модели:**
```bash
curl -s "http://127.0.0.1:8888/api/models"
```
Ключевые: `claude-opus-4`, `claude-sonnet-4-6`, `claude-haiku-4-5`

**Запрос:**
```bash
curl -s -X POST "http://127.0.0.1:8888/api/sessions" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-worker",
    "cwd": "/path/to/project",
    "model": "claude-sonnet-4-6",
    "scope": "/path/to/project",
    "system_prompt": "Ты воркер. Делай задачи.",
    "use_worktree": false
  }'
```

Ответ — объект созданной сессии с `id`, `name`, `status`.

**Если `use_worktree: true`** — обязательно добавь `repo_path`:
```json
{
  "name": "feature-worker",
  "cwd": "/path/to/project",
  "model": "claude-sonnet-4-6",
  "use_worktree": true,
  "repo_path": "/path/to/project"
}
```

---

### Logs

Показать последние логи агента.

**Запрос:**
```bash
curl -s "http://127.0.0.1:8888/api/sessions/{name}/logs?scope={scope}&after_id=0" | python3 -m json.tool
```

Каждый лог-объект содержит:
- `role` — `assistant` / `user` / `tool` / `system`
- `content` — текст сообщения
- `timestamp` — время
- `id` — ID для пагинации (`after_id`)

**Показать последние N строк** — возьми хвост массива после парсинга.

**Для SSE-стриминга** (реалтайм, если нужно):
```bash
curl -sN "http://127.0.0.1:8888/api/sessions/{name}/stream?scope={scope}&after_id=0"
```
Каждая строка `data: {...}` — JSON-объект лога.

---

### Restart

Перезапустить Orchestra сервис (если завис или нужен хот-релоад Python-кода).

**Запрос:**
```bash
curl -s -X POST "http://127.0.0.1:8888/api/restart"
```

⚠️ Рестарт нужен **только** при изменении Python-кода. Статика (JS/CSS/HTML) подтягивается автоматически без рестарта.

После рестарта подождать 2-3 секунды и проверить:
```bash
curl -s "http://127.0.0.1:8888/api/stats"
```

---

## Дополнительные операции

### Список оркестраторов
```bash
curl -s "http://127.0.0.1:8888/api/orchestrators" | python3 -m json.tool
```

### Остановить агента (unload из памяти, данные сохраняются)
```bash
curl -s -X POST "http://127.0.0.1:8888/api/sessions/{name}/stop" \
  -H "Content-Type: application/json" \
  -d '{"scope": "/path/to/project"}'
```

### Удалить агента полностью
```bash
curl -s -X DELETE "http://127.0.0.1:8888/api/sessions/{name}?scope=/path/to/project"
```

### Прервать текущее выполнение (interrupt)
```bash
curl -s -X POST "http://127.0.0.1:8888/api/sessions/{name}/interrupt" \
  -H "Content-Type: application/json" \
  -d '{"scope": "/path/to/project"}'
```

### Компактировать контекст агента (когда > 80%)
```bash
curl -s -X POST "http://127.0.0.1:8888/api/sessions/{name}/compact" \
  -H "Content-Type: application/json" \
  -d '{"scope": "/path/to/project"}'
```
Работает только когда агент в `idle` (не `running`).

### Системный промпт агента
```bash
curl -s "http://127.0.0.1:8888/api/sessions/{name}/prompt?scope=/path/to/project"
```

### Входящие сообщения (inbox) агента
```bash
curl -s "http://127.0.0.1:8888/api/sessions/{name}/inbox?scope=/path/to/project"
```

### Список jobs (spawn/kill задачи)
```bash
curl -s "http://127.0.0.1:8888/api/jobs?scope=/path/to/project"
```

---

## Типичные сценарии

### "Покажи что происходит в orchestra"

1. `GET /api/sessions` — все агенты
2. `GET /api/stats` — общая статистика
3. Вывести таблицу (см. [Status](#status))

### "Отправь оркестратору сообщение X"

1. `GET /api/orchestrators` — найти оркестратор, получить `name` и `scope`
2. `POST /api/sessions/{name}/send` с `message`, `scope`, `sender: "claude-code"`

### "Создай воркера для проекта X"

1. Уточнить у пользователя: name, cwd, задачу (для system_prompt)
2. `POST /api/sessions` с параметрами
3. Сообщить `id` и `name` созданного агента

### "Покажи логи агента Y"

1. Если scope не известен — `GET /api/sessions` найти агента
2. `GET /api/sessions/{name}/logs?scope={scope}&after_id=0`
3. Показать последние 20-30 записей, роль + контент

### "Контекст агента переполнен"

1. Проверить статус: `GET /api/sessions/{name}/context?scope={scope}`
2. Если агент `running` — дождаться `idle` или сделать interrupt
3. `POST /api/sessions/{name}/compact` с `{"scope": "..."}`

---

## Error Handling

- **Нет ответа / Connection refused** → Orchestra не запущена. Запустить: `sudo systemctl start orchestra`
- **404** → агент не найден. Проверить имя и scope через `GET /api/sessions`
- **409** → агент с таким именем уже существует
- **400** → невалидные параметры (прочитать `error` в ответе)
- **Агент running** → compact/stop недоступны, нужен interrupt сначала

## Примечания

- Dashboard доступен в браузере: http://localhost:8888
- `scope` для большинства endpoints — путь к проекту. Если не знаешь scope — получи его из `GET /api/sessions` (поле `scope` в объекте агента)
- Worktree-агенты работают в изолированных ветках git — их изменения не влияют на основной репо до мержа
- Модель `claude-opus-4` — оркестраторы. `claude-sonnet-4-6` — воркеры. `claude-haiku-4-5` — быстрые задачи
