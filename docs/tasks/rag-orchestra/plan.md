# RAG-память для Orchestra — Phase 2: план + сегментация

**Задача:** портировать `kesha/rag.py` (bge-m3 int8 + sqlite-vec + FTS5 hybrid) в Orchestra как семантическую память агентов. Расширенный scope: индексировать **все .md проекта** + **логи агентов** (`user_message`, `text`) из `orchestra.db`.

**Дата:** 2026-07-12. **Confidence:** CONFIRMED (измерено/первоисточник) · LIKELY · UNCERTAIN.

**База:** research.md (одобрен). Этот документ отвечает на вопрос сегментации (что индексировать), затем режет на тикеты.

---

## 0. Что индексируем и почему — сигнал/шум по категориям (CONFIRMED — замерено на живой orchestra.db)

Замер distribution `logs` (27 780 строк, 75.5 MB) — **не гипотеза, реальные числа этой БД**:

| type | rows | bytes | % байт | вердикт |
|---|---:|---:|---:|---|
| `tool_result` | 8 148 | **64.3 MB** | **85.2%** | 🔴 ШУМ — base64-картинки (топ-записи 660 KB каждая), HTTP-дампы, git-вывод |
| `tool` | 8 095 | 6.8 MB | 9.0% | 🔴 ШУМ — JSON-аргументы вызовов тулов, машинные |
| `text` (агент) | 6 381 | 2.2 MB | 3.0% | 🟡 СМЕШАННО — короткие = нарратив, длинные = отчёты/анализ |
| `user_message` | 1 599 | 1.77 MB | 2.3% | 🟢 СИГНАЛ — инструкции юзера (2.6% мелкого шума) |
| `status` | 1 574 | 128 KB | 0.2% | 🔴 ШУМ — технический прогресс |
| `subagent_*` | 1 850 | 234 KB | 0.3% | 🔴 ШУМ — телеметрия |
| `error` | 132 | 4.6 KB | 0.006% | 🔴 ШУМ — стектрейсы |

### Ключевой вывод: 94% байт логов = `tool_result`+`tool` = машинный шум. Индексируем ТОЛЬКО `user_message` + `text` (5.3% байт, но 100% семантики).

### ⭐ Под-категория `user_message` с `[from:agent-name]` = inter-agent send_message (CONFIRMED — замерено)

`user_message` физически хранит ДВА разных потока: реальные сообщения человека И `send_message` между агентами (воркер→оркестратор DONE-репорты, оркестратор→воркер задачи, координация). Различаются префиксом `[from:...]`:

| под-категория | rows | % от user_message | avg длина | tiny(<100) | long(>500) | вердикт |
|---|---:|---:|---:|---:|---:|---|
| `[from:agent]` (send_message) | 642 | 40% | **1240 симв** | 8 (1.2%) | 467 (73%) | 🟢🟢 **высочайший сигнал** |
| человек (без `[from:]`) | 963 | 60% | ~640 симв | — | — | 🟢 сигнал (research §user_message) |

**Сэмплы `[from:]` (замерено):** «DONE #7 (фикс биома-сдвига): root cause нашёл через сравнение...», «Research approved. Proceed to plan», «БЛОКЕР по ассетам — половины путей нет...», «СРОЧНАЯ оптимизация — search_memory висит 300с, root cause: single-thread...». Это **дистиллированные результаты задач + координация + root-cause находки** — ровно то, что RAG должен помнить после compact/restart. Плотнее обычных сообщений (avg 1240 vs 640), почти без шума (1.2% tiny).

**Решение:** индексировать ОБЕ под-категории, но с разным `kind` для атрибуции:
- `[from:]` → `kind='agent_msg'` (send_message; в результате видно кто автор → «этот DONE-репорт от воркера X»)
- человек → `kind='user_msg'`

Разделение по kind даёт: (1) атрибуцию в результате, (2) возможность будущего kind-фильтра (искать только среди DONE-репортов агентов). Извлечение автора из `[from:NAME]` — regex в `index_log`, автор кладётся в `kind`-метаданные или отдельную колонку. **Порог длины для `agent_msg` не нужен** (73% длинные, шума нет) — фильтр `LENGTH >= MIN_LOG_LEN` применять только к `text` и человеческим `user_msg`.

### Детализация «смешанных» категорий (замерено по длине — length = дешёвый прокси сигнала)

**`user_message` (1 599 строк) — распределение длины:**
| длина | rows | % | что это |
|---|---:|---:|---|
| <20 симв | 42 | 2.6% | «ау», «здох?», «го», «пни его» — 🔴 шум |
| 20–100 | 337 | 21% | короткие команды — 🟡 частично |
| 100–500 | 534 | 33% | инструкции — 🟢 сигнал |
| >500 | 686 | 43% | развёрнутые ТЗ — 🟢 чистый сигнал |

→ **Опровергнута гипотеза «80% это ок/го»**: мелкого шума (<20) всего **2.6%**. `user_message` — качественный источник. Фильтр: `LENGTH(content) >= 20` (или лучше — по числу слов ≥3, как kesha `_expand_query`).

**`text` / агент (6 381 строк) — распределение длины:**
| длина | rows | % | что это |
|---|---:|---:|---|
| <20 | 99 | 1.6% | «Делаю.», «Проверю:» — 🔴 шум |
| 20–100 | 1 683 | 26% | нарратив: «SSH отвалился, повторю», «Проверю лог:» — 🔴 в основном шум |
| 100–500 | 3 348 | 52% | смесь: короткий вывод/начало отчёта — 🟡 |
| >500 | 1 252 | 20% | отчёты, анализ, решения — 🟢 сигнал |

→ `text` — самый шумный из «полезных». Наблюдение из сэмплов: <100 симв = tool-нарратив («Не стартовал. Проверю лог:»), >500 = субстантив («честный разбор подходит ли Box3D», «HTTP+auth — пароль летит открытым текстом»). **Фильтр по длине ≥ порога (кандидат: 200 симв) отсекает основной нарративный шум дёшево, без LLM.**

### Файлы (.md) — сигнал по категориям (качественная оценка, research §5B)
| категория | signal/noise | вердикт |
|---|---|---|
| `docs/tasks/**/{research,plan,report,retro}.md` | 🟢 высокий | дистиллированные решения фаз — **ДА** |
| `CLAUDE.md` | 🟢 высокий | session notes, правила, контекст — **ДА** |
| `BUGS.md`, `TODO.md` | 🟢 высокий | живые журналы проблем — **ДА** |
| `docs/workers/*.md` | 🟢 высокий | worker memory — **ДА** |
| `README.md`, `architecture.md` | 🟢 средний | описание проекта — **ДА** |
| `CHANGELOG.md` | 🟡 средний | 92 KB плотной истории — **ДА, но агрессивно чанкать** (heading-aware уже это делает) |
| `docs/tasks/**/codex-review-*.md` | 🔴 низкий | до 406 KB дебатов, шум > сигнал — **НЕТ по умолчанию** |
| `.git`, `node_modules`, `.venv`, бинарники | — | исключены `EXCLUDED_DIRS` + `FILE_EXTENSIONS={.md}` |

**Решение по .md:** индексируем ВСЕ `.md` (расширение-фильтр) кроме `EXCLUDED_DIRS` и явного блэклиста `codex-review-*.md`. 309 .md в orchestra-scope (замерено) — объём приемлемый.

### Ответы на 5 research-вопросов орка

1. **% полезных логов** — по байтам 5.3% (`user_message`+`text`), но это 100% семантики. `tool_result`/`tool` (94% байт) — машинный мусор. По строкам полезных ~29% (7 980 из 27 780). Самый плотный сигнал — `agent_msg` (`[from:]` send_message): 642 строки, avg 1240 симв, 1.2% шума → индексируем целиком. Обычные `user_msg` и `text` — после length-фильтра ~60-70% ценны.
2. **LLM-фильтр нужен?** — **НЕТ на старте.** type-фильтр (`IN ('user_message','text')`) + length-фильтр даёт достаточную precision дёшево. LLM-фильтр дорог и хрупок (research §7a, self-learning эксперимент #85 показал regex-gate precision 0.42 — не полагаться на дешёвые эвристики для тонкой классификации; length-порог грубее, но честнее и без ложной уверенности). Метка **UNCERTAIN** — качество retrieval мерить после запуска, LLM-rerank отложить в возможное расширение.
3. **Как чанкить логи?** — **один лог = один документ**, чанкер `_chunk()` (char-window, уже есть для сообщений kesha). Лог редко > CHUNK_CHAR_LIMIT=1200; длинные отчёты (>500) разобьются с overlap. НЕ группировать по turn/session (теряется атрибуция message_id, растёт вектор, размывается семантика — kesha-урок «голосовые на 500 слов размывают в 1 вектор», rag.py:35).
4. **Namespace** — по `project` (scope) обязательно (изоляция). Внутри проекта — по **источнику/kind**: `file` / `user_msg` / `agent_msg` (последний = send_message с `[from:]`, отдельно т.к. высочайший сигнал). RRF namespaced-ключи (как kesha `('d',id)`/`('f',id)`): `('file',cid)`/`('log',lid)` + `kind`-колонка внутри логов различает user_msg/agent_msg. Коллизий int нет (файлы и логи в разных таблицах).
5. **Аналогия с kesha** — да, 1:1 паттерн. kesha: диалоги (`vec_messages`, namespace `'d'`) vs файлы (`vec_files`, namespace `'f'`). Orchestra: **файлы** (`vec_files`, `'file'`) + **логи** (`vec_logs`, `'umsg'`/`'amsg'`). Отличие: kesha джойнит контент из внешней `messages.db` (ATTACH); у нас логи в `orchestra.db` — либо ATTACH orchestra.db read-only, либо копируем текст чанка в `log_chunks` (как `file_chunks`). **Выбор: копировать в `log_chunks`** (self-contained vec.db, не завязан на схему orchestra.db, устойчив к её миграциям).

---

## 1. Архитектура (из research, подтверждена)

```
Worker (Claude CLI)
  └─ MCP stdio process (app.mcp_stdio)          ← НЕТ embedder (946MB × N = OOM)
       └─ search_memory(query, limit, cross_project=False)
            → HTTP POST /api/memory/search  {query, limit, scope=ORCHESTRA_SCOPE(env), cross_project}
                                    │  scope берётся из ENV воркера, НЕ из аргумента (security)
Main FastAPI (:8888) ──────────────┘
  ├─ RagMemory singleton (embedder 946MB, RO/RW conn, 2× ThreadPoolExecutor)   ← один на всё
  ├─ vec.db (sqlite-vec vec0 + fts5): vec_files + vec_logs, namespace project
  ├─ backfill: .md walk (все проекты) + logs-cursor (user_message/text)
  └─ хук: после merge_worker → backfill_files(scope)
```

**Security-инвариант (CONFIRMED из mcp_stdio.py:22):** MCP-процесс знает свой `ORCHESTRA_SCOPE` из env (server-инжектит на спавне). Endpoint фильтрует по scope, который **MCP берёт из своего env**, а не из аргумента тула → воркер не может запросить чужой проект (нет параметра scope у тула вообще; `cross_project=True` → явный опт-ин, снимает фильтр). Утечка между 17 проектами закрыта by design.

---

## 2. Файлы (что меняется)

| Файл | Действие | ~строк |
|---|---|---|
| `app/rag.py` | **НОВЫЙ** — порт kesha, диалоговый слой→логовый, +`project` namespace, +`vec_logs`/`log_chunks` | ~450 |
| `app/routes/memory.py` | **НОВЫЙ** — `POST /api/memory/search`, `POST /api/memory/reindex` | ~70 |
| `app/rag_service.py` | **НОВЫЙ** — синглтон-обёртка: init embedder+executors, backfill-оркестрация, feature-flag | ~120 |
| `app/main.py` | +init RagService в lifespan (за флагом), +`include_router(memory_router)` | ~8 |
| `app/mcp_stdio.py` | +`@mcp.tool() search_memory(query, limit, cross_project)` → `_api` callback | ~30 |
| `app/routes/sessions.py` | хук после успешного merge (:630) → `rag_service.backfill_scope(scope)` (fire-and-forget) | ~6 |
| `pyproject.toml` | +optional-deps `[project.optional-dependencies] rag = [...]` | ~6 |
| `pipelines/default/prompts/modules/` | +описание тула search_memory (когда звать) | ~12 |
| `tests/test_rag.py` | порт kesha-тестов (чанкеры, index/dedup/delete, RRF, изоляция) + новые (логи, project namespace) | ~350 |
| `.env.example` | +`RAG_ENABLED=false`, `RAG_DB_PATH`, `RAG_MODEL` | ~4 |
| `data/models/` | закешировать bge-m3-onnx-int8 offline (Ёжик-прокси, HF заблокирован на Contabo) | — |

**НЕ трогаем:** `app/db.py` (логи читаем SELECT, не мигрируем схему), `app/manager.py` (worker-memory инжект оставляем как есть), диалоговый слой kesha (выкинут при порте).

---

## 3. Схема vec.db (порт kesha, адаптирован)

```sql
-- ФАЙЛЫ (из kesha 1:1, +project)
files(file_id PK, project TEXT, path TEXT, sha256 TEXT, mtime REAL, UNIQUE(project,path))
vec_files USING vec0(chunk_id PK, file_id INT, project TEXT PARTITION KEY, embedding FLOAT[1024])
file_chunks(chunk_id PK, file_id INT, text TEXT)
fts_files USING fts5(text)

-- ЛОГИ (новое, зеркало файлового слоя)
logs_indexed(log_id PK, project TEXT)                      -- дедуп: какие log.id уже проиндексированы
vec_logs USING vec0(chunk_id PK, log_id INT, kind TEXT,    -- kind: 'user_msg'|'agent_msg'|'text'
                    project TEXT PARTITION KEY, embedding FLOAT[1024])
log_chunks(chunk_id PK, log_id INT, kind TEXT, author TEXT, text TEXT)  -- author = [from:X] для agent_msg; self-contained текст
fts_logs USING fts5(text)
```
`chunk_id = source_id * CHUNK_STRIDE + idx` (kesha-паттерн, файлы и логи в разных таблицах → без коллизий). `SCHEMA_VERSION` bump → дроп+ребилд (индекс производный, безопасно).

---

## Tickets

### T1 — Порт rag.py: файловый слой + project namespace + чистые функции
- **Files:** `app/rag.py` (новый), `tests/test_rag.py` (новый)
- **Что:** портировать из kesha: `_pack`, `_chunk`, `_chunk_markdown`, `_chunk_file`, `_split_paragraphs`, `_split_oversized`, `file_change_target`, `_rrf`, `_get_embedder` (1:1). Файловые таблицы + `index_file`/`delete_file`/`backfill_files` с добавленным `project`. **Выкинуть** диалоговый слой (`vec_messages`/`index_message`/`backfill`/ATTACH messages.db). `KNOWLEDGE_DIR`→параметр (scope передаётся явно).
- **AC:**
  - `_chunk_markdown(MD_SAMPLE)` даёт heading-aware чанки, старт «чисто» (порт kesha-теста)
  - `index_file(project, rel, content)` → строки в `files`/`vec_files`/`file_chunks`/`fts_files`, все с `project`
  - Повторный `index_file` того же контента → 0 (sha256-дедуп)
  - `delete_file` удаляет все чанки; изменённый контент → replace
  - `file_change_target` фильтрует по расширению `.md` и `EXCLUDED_DIRS`
  - `_rrf([('file',5)],[('umsg',5)])` не схлопывает разные namespace
  - Тесты чанкеров/RRF/`file_change_target` идут **без сети** (чистые функции)
- **blocked-by:** none

### T2 — Логовый слой: index_log + backfill_logs с type/kind/length фильтром
- **Files:** `app/rag.py`, `tests/test_rag.py`
- **Что:** `vec_logs`/`log_chunks`/`fts_logs`/`logs_indexed` таблицы. `_classify_log(type, content)` → `(kind, author)`: `user_message`+`[from:X]` → `('agent_msg', 'X')`; `user_message` без префикса → `('user_msg', None)`; `text` → `('text', None)`. `index_log(project, log_id, kind, author, content)`. `backfill_logs(project, conn_orchestra)` — читает `logs JOIN sessions` где `type IN ('user_message','text')` и `log_id NOT IN logs_indexed`, батчами. **Length-фильтр применяется по kind:** `agent_msg` — без порога (73% длинные, шума 1.2%); `user_msg`/`text` — `LENGTH(content) >= MIN_LOG_LEN`. Автор `[from:NAME]` парсится regex.
- **AC:**
  - `_classify_log('user_message', '[from:worker-x] DONE #7')` → `('agent_msg', 'worker-x')`
  - `_classify_log('user_message', 'обычное сообщение')` → `('user_msg', None)`
  - `index_log('/p', 42, 'agent_msg', 'worker-x', text)` → строки в vec_logs/log_chunks/fts_logs с project, kind, author
  - `backfill_logs` пропускает `tool`/`tool_result`/`status`/`error` (только user_message+text)
  - `backfill_logs` пропускает КОРОТКИЕ `text`/`user_msg` (< MIN_LOG_LEN), но НЕ короткие `agent_msg`
  - Повторный `backfill_logs` → 0 новых (дедуп через `logs_indexed`)
  - kind+author сохраняются и доступны для search-атрибуции
- **blocked-by:** T1

### T3 — Unified search: files + logs, project-фильтр, source attribution
- **Files:** `app/rag.py`, `tests/test_rag.py`
- **Что:** `search(project, query, limit, cross_project=False, kinds=None)`. Порт kesha `search`: vec+fts по файлам И логам, RRF fusion namespaced (`'file'`/`'log'`), джойн текста из `*_chunks`, top-limit. Фильтр `WHERE project=?` на каждом под-запросе (снимается при `cross_project=True`). Опциональный `kinds` фильтрует логи по kind (напр. только `agent_msg`). Результат: `{source, project, path|log_id, kind, author, content, score}`.
- **AC:**
  - `search('/p', q)` возвращает только чанки проекта `/p` (изоляция — вставить 2 проекта, проверить 0 протечки)
  - `cross_project=True` → возвращает из обоих проектов
  - Результат файла имеет `source='file'` + `path`; результат лога — `source='log'` + `kind` (+`author` для agent_msg)
  - `kinds=['agent_msg']` → только send_message-логи в результате
  - Пустой query → `[]`; query с спецсимволами FTS5 → фолбэк на phrase-quote (порт kesha)
  - RRF: файл и лог с равными int-id не схлопываются
- **blocked-by:** T2

### T4 — RagService синглтон + executors + feature-flag
- **Files:** `app/rag_service.py` (новый), `app/main.py`, `.env.example`
- **Что:** синглтон-обёртка: 2× `ThreadPoolExecutor(max_workers=1)` (write/read), RW+RO `RagMemory`-инстансы, `set_executor`, async `search()`/`backfill_scope()`/`reindex_all()` через `run(loop, method, ...)` (порт kesha executor-split 1:1). Init в `main.py` lifespan ТОЛЬКО если `RAG_ENABLED=true` (иначе no-op, Orchestra работает без rag-deps). Модель offline: `HF_HUB_OFFLINE=1`, путь `data/models/`.
- **AC:**
  - `RAG_ENABLED=false` (default) → lifespan не грузит embedder, `import app.rag_service` не тянет fastembed/onnx
  - `RAG_ENABLED=true` → embedder-синглтон создан один раз, search использует read-executor, index — write-executor (порт kesha `test_run_routes_search_to_read_executor`)
  - RO-коннект видит записи RW без реконнекта (WAL, порт kesha-теста)
  - RO-коннект не может писать (fail loud)
- **blocked-by:** T3

### T5 — REST endpoints + MCP tool search_memory
- **Files:** `app/routes/memory.py` (новый), `app/main.py` (include_router), `app/mcp_stdio.py`
- **Что:** `POST /api/memory/search` (body: query, limit, scope, cross_project) → `rag_service.search`. `POST /api/memory/reindex` (body: scope) → `backfill_scope`. MCP-тул `search_memory(query, limit=5, cross_project=False)` — **scope НЕ параметр**, MCP шлёт `ORCHESTRA_SCOPE` из env → endpoint. Форматирует результат для агента (`[file: path]` / `[msg]` + content + score).
- **AC:**
  - `POST /api/memory/search` с `Authorization: Bearer INTERNAL_TOKEN` → 200 + результаты (middleware пропускает internal-token, main.py:97)
  - MCP `search_memory` не имеет параметра `scope` (нельзя запросить чужой проект)
  - `cross_project=False` (default) → только свой scope; `True` → все проекты
  - `RAG_ENABLED=false` → endpoint возвращает понятную ошибку (не 500)
  - Результат содержит source-атрибуцию (агент видит откуда факт)
- **blocked-by:** T4

### T6 — Backfill: .md + логи, хук на merge, throttle
- **Files:** `app/rag_service.py`, `app/routes/sessions.py`
- **Что:** `backfill_scope(scope)`: walk `.md` (кроме `codex-review-*.md`) + `backfill_logs` из orchestra.db для этого scope. Батч `EMBED_BATCH=16` (не 64 — RAM peak, research §6). Хук в `merge_session` (:630 после `result.get("ok")`) — fire-and-forget `asyncio.create_task(rag_service.backfill_scope(scope))`, обёрнут в try (merge не падает если RAG сломан). Startup: НЕ бэкфиллить все 17 проектов (research — часы); lazy — проект при первом обращении ИЛИ ручной `/api/memory/reindex`.
- **AC:**
  - `backfill_scope('/p')` индексирует `.md` + логи проекта `/p`
  - `codex-review-*.md` пропущены (блэклист)
  - merge успешен даже если `backfill_scope` кинул исключение (try-wrap, warning в лог)
  - Повторный backfill дёшев (sha256 + logs_indexed дедуп → 0 работы)
  - batch=16 (не 64) — RAM-митигация
- **blocked-by:** T5

### T7 — Optional deps + offline model + prompt-описание тула
- **Files:** `pyproject.toml`, `pipelines/default/prompts/modules/*.md`, `.env.example`
- **Что:** `[project.optional-dependencies] rag = ["fastembed>=0.8.0","sqlite-vec>=0.1.6","watchfiles>=0.24"]`. Инструкция закеша модели (`data/models/bge-m3-onnx-int8/`, Ёжик-прокси 12340 — Contabo блокирует HF, research §6). Описание тула в промпт: «когда потерял контекст после compact/restart — `search_memory('<тема прошлой задачи>')` найдёт прошлые решения». Feature-flag doc в `.env.example`.
- **AC:**
  - `uv sync` без `--extra rag` → Orchestra стартует, RAG выключен, тесты не-rag зелёные
  - `uv sync --extra rag` → fastembed/sqlite-vec/watchfiles ставятся
  - Промпт-модуль описывает search_memory (детерминированный триггер: after compact/restart)
- **blocked-by:** T6

---

## 4. Риски (из research §6, актуализированы)

| Риск | Severity | Митигация |
|---|---|---|
| Peak RAM 2.4 GB при backfill | 🔴 HIGH | batch=16 (замер: 1.6GB vs 2.4GB@64), lazy backfill, не все 17 сразу |
| Cross-project утечка (17 разнородных, вкл. креды) | 🔴 HIGH | scope из ENV MCP (не аргумент тула), фильтр на каждом под-запросе, cross_project=явный опт-ин |
| Backfill логов дубли при ре-ране | 🟡 MED | `logs_indexed` дедуп по log_id (зеркало kesha `indexed`) |
| Модель HF заблокирована на Contabo | 🟡 MED | offline-кеш в `data/models/`, `HF_HUB_OFFLINE=1`, скачать через Ёжик 12340 |
| +onnxruntime раздувает установку | 🟡 MED | optional-deps `[rag]` + `RAG_ENABLED` флаг |
| Логи `text` шумные (нарратив) | 🟡 MED | length-фильтр `>= MIN_LOG_LEN` (замер: <100 симв = tool-нарратив) |
| sqlite-vec alpha | 🟢 LOW | kesha-прод 5930 чанков 0 ошибок; WAL+busy_timeout настроены |

## 5. Что осознанно НЕ делаем (scope guard)
- LLM-фильтр логов — отложен (дорого/хрупко, type+length достаточно). UNCERTAIN, мерить retrieval после запуска.
- Auto-inject в промпт при спавне — MCP on-demand достаточно (agent-determinism), auto-inject-by-title — возможное расширение.
- watchfiles live-watcher на 17 scopes — дорого; старт с backfill-on-merge + ручной reindex. Watcher только на orchestra-scope — отложено.
- Индексация `tool`/`tool_result` — никогда (94% байт = машинный шум, base64).
- codex-review-*.md — по умолчанию нет (шум > сигнал).

## 6. Оценка
**~3-4 дня.** Риск не в коде (60% из kesha 1:1), а в: offline-модель, backfill-throttle (RAM), тест изоляции проектов. Тяжёлые бенчмарки (загрузка embedder, реальный backfill) на этой машине НЕ гоняем — только код + юнит-логика; embed-зависимые тесты помечаем `@pytest.mark.rag` (skip без модели).
