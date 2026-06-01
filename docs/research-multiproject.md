# Ресёрч: разделение тасок одного оркестратора на несколько проектов

**Дата:** 2026-05-31
**Задача:** В seedon все таски лежат в `project="seedon"`. Нужно разделить на два направления —
бизнес (`seedon-biz`) и техника (`seedon-tech`) — с **раздельной нумерацией** (#1 в biz ≠ #1 в tech).

---

## TL;DR (короткий ответ)

**Хорошая новость:** механика уже почти полностью готова. Таски хранятся per-project,
нумерация per-project, `task_create(project=...)` принимает любой project_id. Чтобы получить
`seedon-biz` и `seedon-tech` с раздельной нумерацией — **код менять почти не нужно**, достаточно
просто начать передавать разные `project` в `task_create`.

**Плохая новость / подводный камень:** есть ОДНО архитектурное ограничение —
`tm_projects.scope` объявлен `UNIQUE`, а `ensure_project()` при создании таски привязывает
project к scope оркестратора. Если **один** оркестратор (один SCOPE) попытается создать таски
в двух проектах — второй проект упадёт на `UNIQUE(scope)` либо привяжется криво. Детали и фикс — в §6.

**Рекомендация:** **Вариант (a) — отдельные проекты**, реализованный одним из двух способов:
- Если biz и tech ведут **разные sub-оркестраторы** (разный scope) → работает **из коробки**, 0 строк кода.
- Если **один** оркестратор ведёт оба → нужна правка `ensure_project` (~5 строк, см. §6).

---

## 1. Текущая реализация тасок

### 1.1 Схема БД (`app/db.py:98-156`)

```sql
CREATE TABLE tm_projects (
    id TEXT PRIMARY KEY,              -- "seedon", "orchestra", "parsing-hub"
    name TEXT NOT NULL,
    prefix TEXT NOT NULL DEFAULT 'TASK',  -- 3 буквы, генерится из id
    scope TEXT UNIQUE,               -- ⚠️ путь оркестратора, 1 scope ↔ 1 project
    yougile_project_id TEXT,
    yougile_board_id TEXT,
    yougile_enabled INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(prefix)
);

CREATE TABLE tm_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- глобальный rowid (не виден юзеру)
    par_number INTEGER NOT NULL,            -- ← номер таски, который видит юзер (#42)
    project_id TEXT NOT NULL REFERENCES tm_projects(id),
    title, description, price_rub, paid_rub, status, assignee, ...
);

-- КЛЮЧЕВОЕ: номер уникален В ПРЕДЕЛАХ проекта, не глобально
CREATE UNIQUE INDEX idx_tm_tasks_par_project ON tm_tasks(project_id, par_number);
```

**Вывод:** таблица изначально спроектирована мультипроектной. `par_number` (видимый номер
таски) — per-project. Глобальный `id` — это просто rowid, юзеру не показывается.

### 1.2 Нумерация — УЖЕ per-project (`app/tm.py:59-64`)

```python
def _next_par(conn, project_id) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(par_number), 0) + 1 FROM tm_tasks WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    return row[0]
```

`MAX(par_number) WHERE project_id = ?` → каждый проект имеет **свою независимую** последовательность.
`seedon-biz` начнётся с #1, `seedon-tech` тоже с #1 — параллельно и без коллизий.
Уникальный индекс `(project_id, par_number)` гарантирует это на уровне БД.

### 1.3 Префиксы (`app/tm.py:69-82`)

Каждый проект получает 3-буквенный `prefix` (генерится из id): `seedon` → `SEE`.
Префиксы — legacy для поиска тасок типа `PAR-42`, но БД хранит и резолвит таски по
числу + project_id. Префикс должен быть **уникальным** (`UNIQUE(prefix)`), поэтому
`seedon-biz` и `seedon-tech` получат разные префиксы (например `SEE` и `SE1`) автоматически
через `_generate_prefix`.

---

## 2. Как оркестратор создаёт таски в разных проектах

### 2.1 MCP tool `task_create` (`app/mcp_stdio.py:430-444`)

```python
async def task_create(title: str, project: str, ...) -> str:
    result = await _api("POST", "/api/tm/tasks", json={
        "title": title, "project": project, ...,
        "scope": SCOPE, "priority": priority,
    })
```

`project` — **обязательный явный параметр**. Агент передаёт project_id любой строкой.
`SCOPE` (`ORCHESTRA_SCOPE` env, `app/mcp_stdio.py:21`) добавляется отдельно и используется
только для `ensure_project(scope=...)` на бэкенде.

**Можно ли передать любой project?** Да. Никакой валидации «project должен совпадать со scope»
нет. dev-lead **может** вызвать `task_create(project="seedon-tech", ...)`, а biz-lead —
`task_create(project="seedon-biz", ...)`. Никаких ограничений в коде нет.

### 2.2 Бэкенд `api_create_task` (`app/tm.py:751-779`)

```python
def api_create_task(project_id, title, ..., scope="", ...):
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_project(conn, project_id, scope=scope or None)   # ⚠️ см. §6
        task = create_task(conn, project_id, title, ...)
        conn.commit()
```

`ensure_project` (`app/tm.py:85-101`): если проект с таким `id` уже есть — возвращает его как
есть (scope не трогает). Если нет — **создаёт новый**, проставляя `scope` оркестратора.
Тут и зарыт подводный камень из §6.

### 2.3 `task_list` / `task_get` / `task_update` — резолвинг project (`app/main.py:1290-1333`)

```python
@app.get("/api/tm/tasks")
async def tm_list_tasks(project="", scope="", ...):
    proj = project
    if not proj and scope:                       # явный project имеет приоритет
        p = _tm.get_project_by_scope(conn, scope)  # fallback: scope → project
        proj = p["id"] if p else None
    return _tm.api_list_tasks(proj, ...)
```

Логика везде одинаковая:
1. Если передан явный `project` → используется он.
2. Иначе → `scope → project` через `get_project_by_scope` (`app/tm.py:104-106`,
   `SELECT ... WHERE scope = ?`).

MCP `task_list` (`app/mcp_stdio.py:476-491`): если агент НЕ передал `project`, шлёт `scope=SCOPE`,
и бэкенд резолвит единственный проект этого scope. **Вот здесь — второе ограничение:**
агент без явного `project` увидит только ОДИН проект (тот, что привязан к его scope). См. §6.

---

## 3. Нумерация: глобально или per-project?

**Per-project, уже реализовано.** (§1.2). Доказательства:
- `_next_par` фильтрует по `project_id`.
- `UNIQUE INDEX (project_id, par_number)` — БД-гарантия.
- `get_task_by_par` (`app/tm.py:286-302`) при отсутствии project_id и неоднозначности
  (`#5` есть в двух проектах) **бросает ошибку** `"Ambiguous task #5 — exists in projects: ..."`
  и требует фильтр по проекту. То есть код уже готов к коллизии номеров между проектами.

Никаких доработок нумерации не требуется.

---

## 4. Что нужно поменять

### Сценарий A — biz и tech ведут РАЗНЫЕ sub-оркестраторы (разный scope)

**Изменения кода: НЕТ (0 строк).** Работает из коробки:
- biz-lead запущен в scope `/path/seedon-biz`, dev-lead — в `/path/seedon-tech` (или любые
  два разных scope-пути).
- Каждый создаёт таски без явного project — `ensure_project` сам создаст проект, привязанный
  к его scope, при первой таске. Либо передают явный `project="seedon-biz"` / `"seedon-tech"`.
- `task_list` каждого покажет только его проект (scope-фильтр). Нумерация раздельная.

⚠️ **Нюанс:** project_id, который `ensure_project` создаст «по scope», будет = тому, что передал
агент в `task_create(project=...)`. Если агенты не передают project явно при list/create через
scope-фолбэк — project_id создастся только при **первом** `task_create` с явным project.
Чистый путь: **всегда передавать явный `project`** в `task_create`, а scope использовать только
как удобный фильтр для list.

### Сценарий B — ОДИН оркестратор ведёт ОБА проекта

Нужна правка (см. §6), потому что `tm_projects.scope UNIQUE` не даёт привязать два проекта
к одному scope, и scope-фолбэк в list/get вернёт только один проект.

### Подготовка данных (для обоих сценариев)

Текущие таски лежат в `project="seedon"`. Их надо либо:
- **оставить** в `seedon` как архив, новые класть в `seedon-biz`/`seedon-tech`; либо
- **мигрировать** — проставить каждой таске новый `project_id` (`UPDATE tm_tasks SET project_id=...`).
  ⚠️ При миграции `par_number` придётся **перенумеровать** в рамках новых проектов, иначе можно
  словить конфликт `UNIQUE(project_id, par_number)`. Это разовый SQL-скрипт, не код фичи.
  Также мигрировать `tm_clients.project_id` (платежи привязаны к project через клиента).

---

## 5. Варианты реализации (сравнение)

| | (a) Отдельные проекты | (b) Теги/категории внутри 1 проекта | (c) Проект ↔ sub-orch |
|---|---|---|---|
| **Раздельная нумерация** | ✅ да (из коробки) | ❌ нет — одна сквозная нумерация | ✅ да (= вариант a) |
| **Изменения кода** | 0 (сценарий A) / ~5 строк (B) | 🔴 много: новое поле `category`, фильтры, MCP-параметр, UI | 0 (если scope разный) |
| **task_list фильтрация** | ✅ по project, готово | нужен новый фильтр по тегу | ✅ по scope, готово |
| **Платежи/долги** | ✅ раздельные per-project (биллинг и так per-project) | 🔴 общий пул — нельзя раздельно считать долг biz vs tech | ✅ раздельные |
| **YouGile sync** | ✅ раздельные доски per-project | 🔴 одна доска, теги колонками — костыль | ✅ раздельные |
| **Соответствие архитектуре** | ✅ БД спроектирована под это | ❌ против существующей модели | ✅ |
| **Подводные камни** | scope UNIQUE (§6) | сквозная нумерация ломает требование #1≠#1 | то же что (a) |

### Почему НЕ (b) теги

Требование задачи — **раздельная нумерация** (`#1 в tech ≠ #1 в biz`). Теги внутри одного
проекта дают **общую** последовательность `par_number` (она per-project, а проект один) —
прямое противоречие требованию. Плюс платежи/долги/YouGile в Orchestra устроены **per-project**
(см. `_distribute_payment` `app/tm.py:433-442` — распределяет долг `WHERE project_id IN (...)`),
так что биз и тех-долги смешаются в один котёл. Вариант отклонён.

### (a) и (c) — фактически одно и то же

Вариант (c) «проект привязан к sub-orch» = вариант (a), реализованный через разные scope
(Сценарий A из §4). Разница только в том, **кто** передаёт project_id: автоматически по scope (c)
или явным параметром (a). **Рекомендую (a) с явным `project`** — детерминированнее
(см. принцип Agent Determinism в CLAUDE.md): агент всегда явно указывает направление, нет магии
скрытого резолва по scope.

---

## 6. ⚠️ Подводный камень: `tm_projects.scope UNIQUE`

### Проблема

```sql
scope TEXT UNIQUE   -- app/db.py:102
```

`ensure_project` (`app/tm.py:85-101`) при создании проекта пишет туда `scope` оркестратора.
Два проекта с одним scope невозможны. Последствия для **Сценария B** (один оркестратор, два проекта):

1. **При создании:** первый `task_create(project="seedon-biz")` создаст проект biz со scope
   оркестратора. Второй `task_create(project="seedon-tech")` вызовет `ensure_project` для tech.
   Так как tech ещё нет — попытка INSERT со **тем же scope** → `IntegrityError UNIQUE(scope)` →
   таска не создастся, агент получит ошибку.

2. **При list/get/update без явного project:** `get_project_by_scope` вернёт ровно один проект
   (или упадёт, если их каким-то образом стало два) — агент не сможет «через scope» увидеть оба.

### Фиксы (по возрастанию инвазивности)

**Фикс 1 — минимальный (для Сценария A, разные scope): ничего не делать.**
Если biz и tech на разных scope — UNIQUE не мешает, каждый проект на своём scope. 0 строк.

**Фикс 2 — для Сценария B: не привязывать scope при явном project (~3-5 строк).**
В `ensure_project` / `api_create_task` передавать `scope=None`, когда project задан явно
агентом (а не выведен из scope). Тогда оба проекта seedon-biz/seedon-tech создадутся со
`scope=NULL`, UNIQUE(NULL) в SQLite не конфликтует (NULL != NULL). Минус: теряется scope-фолбэк
для list — агент **обязан** всегда передавать явный `project` в `task_list`. Это согласуется
с рекомендацией §5 (явный project = детерминизм).

**Фикс 3 — полноценный (если нужен один scope ↔ много проектов с scope-резолвом):**
- снять `UNIQUE` со `scope`, сделать связь scope→projects «один ко многим»;
- `get_project_by_scope` → `get_projects_by_scope` (список);
- в list при scope без project — возвращать таски **всех** проектов scope (или дефолтный);
- затронет: `app/db.py` (схема + миграция), `app/tm.py:104` (`get_project_by_scope`),
  `app/main.py:1290-1346` (4 хендлера), `_resolve_client_id` (`app/main.py:1336`).
  Это уже полноценная фича на ~30-50 строк + миграция. **Избыточно**, если достаточно Фикса 2.

### Рекомендованный путь

**Сценарий A + Фикс 1** (разные sub-оркестраторы на разных scope) — ноль кода, чисто
организационное решение. Либо, если seedon ведёт один оркестратор:
**Сценарий B + Фикс 2** (~5 строк: при явном project не писать scope, всегда передавать
project явно). Оба дают раздельную нумерацию, раздельные платежи/долги, раздельный YouGile.

---

## 7. Чек-лист реализации (рекомендованный = Сценарий A или B+Фикс 2)

1. **Решить организационно:** один оркестратор на оба направления (→ B+Фикс2) или два
   sub-оркестратора на разных scope (→ A, 0 кода). Это вопрос к PM/юзеру.
2. **Данные:** решить судьбу текущих тасок `project="seedon"` — архив или миграция
   (разовый SQL, не код фичи; при миграции перенумеровать par_number, мигрировать tm_clients).
3. **Если Сценарий B:** правка `ensure_project`/`api_create_task` — не привязывать scope при
   явном project (Фикс 2, ~5 строк).
4. **Промпты агентов:** biz-lead и dev-lead должны **всегда** передавать явный
   `task_create(project="seedon-biz" | "seedon-tech")`. Прописать в их system_prompt жёстко
   (Agent Determinism: один маршрут, без выбора).
5. **Клиенты/платежи:** если биллинг раздельный — завести `tm_clients` для каждого проекта
   (`ensure_client(project_id=...)`), иначе платежи/долги привязаны к project через клиента.
6. **YouGile (если включён):** каждый новый проект → своя доска
   (`yougile_project_id`/`yougile_board_id` в `tm_projects`), иначе sync будет лить обе ветки
   на одну доску.

---

## Найденные баги/наблюдения (попутно)

- **`get_project_by_scope` хрупок при будущей мультипроектности на одном scope.** Сейчас
  `WHERE scope = ?` молча берёт первую строку. Если когда-нибудь снять `UNIQUE(scope)` без
  правки этого метода — будет недетерминированный выбор проекта. Не баг сейчас (UNIQUE держит),
  но мина на будущее.
- **Платежи привязаны к project косвенно через `tm_clients.project_id`** (`_distribute_payment`,
  `app/tm.py:433`). При разделении seedon на два проекта надо явно решить: один клиент-плательщик
  на оба проекта (тогда долг считается per-project, но клиент один) или два клиента. Текущий код
  ищет клиента `get_client_for_project(project_id)` — на новый project_id клиента не будет,
  пока его не создашь. Платёж/`payment_status` для нового проекта без клиента → ошибка
  `"No client found for project scope"`.
