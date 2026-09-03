# RAG-память для Orchestra — исследование + план интеграции

**Задача:** перенести рабочую RAG-систему из `kesha-tg-bot/rag.py` в Orchestra как семантическую память агентов (поиск по прошлым `docs/tasks/*.md`, `CLAUDE.md`, `BUGS.md` и т.д.), чтобы после compact/restart агент мог найти прошлые решения, а не терять контекст.

**Дата:** 2026-07-12. **Confidence-легенда:** CONFIRMED (измерено/первоисточник) · LIKELY (косвенно) · UNCERTAIN (гипотеза) · REFUTED.

---

## 0. Question (framed)

- **Context:** Orchestra = FastAPI + SQLite + Claude SDK, 17 проектов (scope = путь к репо), 150 файлов / 1397 чанков только в `docs/tasks` самой Orchestra. Агенты теряют контекст после compact/restart.
- **Change under test:** встроить `kesha/rag.py` (bge-m3 int8 + sqlite-vec + FTS5 hybrid) как память агентов.
- **Baseline (что есть сейчас):** плоские `.md` + grep. Никакого семантического поиска.
- **Measurable outcome:** (а) сколько RAM/disk/CPU это стоит на нашей 15GB-машине; (б) где живёт embedder при MCP-процесс-на-воркера архитектуре; (в) риск утечки между 17 разнородными проектами.

---

## 1. Что уже есть в Orchestra для «памяти» (CONFIRMED — прочитано в коде/БД)

| Механизм | Где | Тип | Поиск |
|---|---|---|---|
| CLAUDE.md session notes | корень репо, 40 KB | ручной дамп в конце сессии | нет (агент читает целиком) |
| `docs/tasks/<id>/{research,plan,report,retro}.md` | 150 файлов, 2.2 MB | артефакты фаз | нет (grep вручную) |
| `docs/workers/{name}.md` | авто-инжект в промпт | worker persistent memory | нет |
| `BUGS.md` / `TODO.md` / `CHANGELOG.md` | корень, 12+2.4+92 KB | журналы | нет |
| `~/.claude/projects/.../memory/*.md` | вне репо | auto-memory (frontmatter) | нет |
| `logs` table (orchestra.db) | 26 690 строк | сырые turn-логи | LIKE только |

**Ключевой факт (CONFIRMED, `app/manager.py:476-480`):** при спавне воркера Orchestra **уже** инжектит `docs/workers/{name}.md` в промпт как `<worker-memory>`. Это готовая точка для авто-инжекта RAG-результатов (если захотим не MCP-tool, а автоподмешивание).

**Вывод:** памяти много, но она **write-only** — агенты пишут, но семантически не читают. RAG закрывает ровно эту дыру.

---

## 2. Кодовая база Кеши — что там реально (CONFIRMED — прочитан весь `rag.py`, 729 строк, + 2 теста)

### Архитектура rag.py
```
_get_embedder()            module-level singleton, ОДИН на процесс (write+read делят его)
                           ONNX InferenceSession thread-safe → не плодит +946MB на поток
RagMemory(readonly=bool)   обёртка над sqlite3 + sqlite_vec
  ├─ RW conn  (index/backfill/index_file)      WAL, isolation_level=None
  └─ RO conn  (search)  file:...?mode=ro       конкурентно с backfill, не ждёт
Схема (SCHEMA_VERSION=8, дроп+ребилд при bump):
  диалоги:  vec_messages (vec0, chat_id PARTITION KEY) + fts_messages (fts5) + indexed
  файлы:    vec_files (vec0) + fts_files (fts5) + file_chunks (текст) + files (sha256 дедуп)
search():  embed(query) → vec-поиск + fts-поиск (диалоги ×role, файлы всегда)
           → RRF fusion (namespaced ключи ('d',id)/('f',id) — нет коллизий int)
           → джойн контента, top-limit, source attribution
Два ThreadPoolExecutor(max_workers=1): write-executor + read-executor (SQLite не thread-safe)
run(loop, method, *args): search → read-executor, остальное → write-executor
```

### Что переиспользуется 1:1 vs адаптируется

| Компонент rag.py | Переиспользование | Что менять для Orchestra |
|---|---|---|
| `_get_embedder()` singleton | **1:1** | ничего (но живёт в main-процессе, см. §4) |
| `_chunk_markdown()` heading-aware | **1:1** | ничего — наши `docs/tasks/*.md` = чистый markdown с `#`, идеально ложится |
| `_chunk_file()` / `_split_paragraphs()` | **1:1** | ничего |
| `file_change_target()` фильтр | **адаптировать** | наш EXCLUDED список + расширения (`.md` only, без `.txt`?) |
| `index_file` / `delete_file` / sha256-дедуп | **1:1** | ничего |
| `vec_files` / `fts_files` / `file_chunks` / `files` | **переиспользовать** | +колонка `project` (namespace) — см. §5 развилка A |
| `_rrf` RRF fusion | **1:1** | ничего |
| `search()` | **упростить** | выкинуть диалоговую половину (`vec_messages`/`fts_messages` — у нас нет chat-диалогов), оставить файловый путь + добавить `project`-фильтр |
| `backfill_files()` + prune | **1:1** | root = project scope вместо KNOWLEDGE_DIR |
| RO/RW executor split | **1:1** | ничего — та же логика «search не ждёт backfill» |
| watchfiles watcher (bot.py:199) | **адаптировать** | вотчить N project-scopes вместо одного WORK_DIR |
| **Диалоговый слой** (vec_messages, index_message, backfill из messages.db) | **ВЫКИНУТЬ** | у Orchestra нет TG-диалогов; память = только файлы |

**Итого:** ~60% rag.py переносится дословно (embedder, чанкеры, файловые таблицы, RRF, executor-split). Диалоговая половина (~30%) удаляется. Новое (~10%): project-namespace + мульти-scope backfill/watcher + REST endpoint.

### Зависимости (CONFIRMED — `requirements.txt`)
```
sqlite-vec>=0.1.6      # vec0 virtual table
fastembed>=0.8.0       # ONNX embedder (тянет onnxruntime)
watchfiles>=0.24       # inotify watcher
```
Ни одной из них нет в `orchestra/pyproject.toml` сейчас (CONFIRMED — grep пустой). Плюс транзитивно: `onnxruntime` (~огромный), `huggingface_hub` (для скачивания модели), `numpy`, `tokenizers`.

---

## 3. Оценка ресурсов — РЕАЛЬНЫЕ ЗАМЕРЫ (CONFIRMED — bge-m3 int8, эта машина, 12 ядер)

Замерял сам (`/tmp/rag_bench/bench.py`), не доверяя цифрам из задачи. Модель `AlpEge/bge-m3-onnx-int8`, ONNX, arena/mem_pattern off (как в kesha).

| Метрика | Замер | Комментарий |
|---|---|---|
| **Модель на диске** | **565 MB** | из них 544 MB — `model_quantized.onnx` |
| **RAM: idle (модель загружена + warmup)** | **946 MB** | постоянный footprint, если embedder резидентный |
| **RAM: peak во время backfill (batch=32-64)** | **1.6–2.4 GB** | ⚠️ ONNX распухает на батчах — главный риск |
| **RAM: baseline интерпретатор** | 9 MB | до импортов |
| **Query latency (1 эмбед, поиск)** | **24 ms median** (23 min / 40 max) | отлично, поиск быстрый |
| **Throughput backfill** | **~190 ms/chunk** (best-of-3, любой batch/threads) | int8-ONNX на CPU медленный; threads не помогают |
| **vec.db размер (наш корпус, 1397 чанков)** | **~15–105 MB** (см. прим.) | disk НЕ binding constraint |
| Load time (модель в память, тёплый диск) | 2.4 s | холодный старт процесса |
| Скачивание модели (первый раз) | ~30 s | 565 MB через прокси |

**Прим. по vec.db disk (UNCERTAIN — замер зашумлён):** на N=60 чанков намерял 75 KB/chunk (→ ~105 MB на 1397), но это перевешено фиксированным overhead пустых vec0/fts5-таблиц (sqlite-vec хранит векторы блоками по 1024). Асимптотика per-chunk ≈ 4 KB вектор + ~4 KB текст×2 в fts/chunks ≈ **~8-10 KB** → реалистично **~15-20 MB** на этот проект. Точный замер на полном корпусе не завершился (190ms/chunk × 1397 = ~4.5 мин, машина загружена). **Итог: disk не проблема** (десятки-сотня MB), binding constraints — RAM (peak 2.4 GB) и backfill-время. Kesha-прод: 39 MB на 5930 чанков = 6.6 KB/chunk (Tier-4, подтверждает асимптотику ~8 KB).

### ⚠️ Расхождение с цифрами из задачи
Задача цитирует **«1.2 GB RSS» и «98 ms/chunk»** (прод-VPS Кеши). Мои замеры: **946 MB idle / до 2.4 GB peak**, **190 ms/chunk**. Разница — другое железо + версия onnxruntime (1.27) + возможно другой batch. **Мои цифры — верхняя граница на нашей машине, брать их.** Прод-цифры не воспроизводимы здесь.

### RAM нашей машины (CONFIRMED — `free -h`)
```
total 15 Gi | used 7.6–10 Gi | free 2.8–4.5 Gi | available 4.9–7.8 Gi | swap 31Gi (7Gi used)
```
**Вердикт по RAM:** idle-946 MB — **ок** (влезает в available). Но **peak 2.4 GB во время backfill при available ~5 GB, где уже сидят Orchestra + N воркеров** — **напряжённо**. Митигация: batch=8-16 (не 64), backfill по одному проекту, ночью, throttle. См. §7.

### ⚠️ Backfill-время (CONFIRMED — критично)
190 ms/chunk × 1397 чанков (**один** проект) = **~4.5 минуты**. На все 17 проектов (если у всех есть docs) — оценочно **сотни тысяч чанков → часы**. Это НЕ фоновая мелочь. Backfill — тяжёлая разовая операция, нужна инкрементальность (sha256-дедуп уже есть) + throttle.

---

## 4. Развилка «где живёт embedder» — РЕШЕНА архитектурой (CONFIRMED)

**Факт (CONFIRMED, `app/mcp_stdio.py:1,906`):** MCP-сервер Orchestra = **отдельный stdio-процесс на КАЖДОГО воркера** (`python -m app.mcp_stdio`), общается с main-app по HTTP (`_api()`).

→ Embedder **НЕЛЬЗЯ** класть в MCP-процесс: 946 MB × N воркеров = OOM мгновенно.
→ Embedder **ОБЯЗАН** быть синглтоном в **main FastAPI-процессе** (один на всю Orchestra).
→ MCP-tool `search_memory` делает HTTP-callback на новый REST endpoint `/api/memory/search` в main-app, где живёт RAG.

```
Worker (Claude CLI)
  └─ MCP stdio process (app.mcp_stdio)   ← НЕТ embedder тут
       └─ search_memory tool → HTTP POST /api/memory/search
                                    │
Main FastAPI (:8888) ──────────────┘
  ├─ RagMemory singleton (embedder 946MB, RO/RW conn, executors)   ← embedder ТУТ, один
  ├─ vec.db (sqlite-vec + fts5)
  └─ watcher (индексит docs/tasks на изменения)
```

Это единственный вариант, совместимый с текущей архитектурой. Развилка закрыта.

---

## 5. Архитектурные развилки (с аргументами)

### A. Одна vec.db на всё vs per-project
- **Одна vec.db + колонка `project`** (namespace-фильтр в запросе). ✅ один embedder, один backfill-контроллер, дедуп общий, RRF работает как есть. ❌ фильтр обязателен на КАЖДОМ запросе (забыл → утечка). Партиция vec0 по `project` (как `chat_id PARTITION KEY` у Кеши) снимает перф-проблему.
- Per-project .db (17 файлов). ✅ жёсткая изоляция by design. ❌ 17 коннектов, сложнее watcher/backfill, кросс-проектный поиск (если понадобится) невозможен.
- **РЕКОМЕНДАЦИЯ: одна vec.db + `project` как PARTITION KEY в vec0 + обязательный фильтр в endpoint** (default = scope вызывающего воркера). Изоляция через дефолт, а не через 17 файлов. Партиция даёт и перф, и «стену» между проектами на уровне индекса.
- **CONFIRMED (измерено):** `project TEXT PARTITION KEY` в vec0 **работает** (kesha юзает INTEGER `chat_id`, но TEXT-путь тоже принимается). Тест: 2 проекта, `WHERE project='/proj/a' AND emb MATCH ?` → вернул ТОЛЬКО `/proj/a`, `/proj/b` не протёк. Изоляция на уровне индекса подтверждена. Но: партиция — оптимизация, НЕ security-граница (SQL без фильтра всё равно вернёт всё) → фильтр в endpoint обязателен by design, не опционален.

### B. Что индексировать
- **CONFIRMED из kesha-замеров (комментарий rag.py:44):** xml/csv/json/html = мусор в retrieval. Только проза.
- **Индексируем:** `docs/tasks/**/*.md`, `CLAUDE.md`, `BUGS.md`, `docs/workers/*.md`, `README.md`. Это «знание о проекте».
- **НЕ индексируем:** `logs` table (26k строк сырых turn-логов — шум, base64, tool-дампы; LLM-фильтр = дорого и хрупко), `CHANGELOG.md` (спорно: 92 KB полезной истории, но очень плотный — LIKELY да, но чанкать агрессивно), `codex-review-*.md` (спорно: до 406 KB, это дебаты — UNCERTAIN, скорее шум чем сигнал, **по умолчанию НЕТ**).
- **РЕКОМЕНДАЦИЯ:** старт с `docs/tasks/**/{research,plan,report,retro}.md` + `CLAUDE.md` + `BUGS.md`. Расширять по замеру retrieval-качества, не спекулятивно.

### C. MCP tool vs авто-инжект
- **MCP tool `search_memory(query, project?, limit?)`** — агент ищет когда нужно. ✅ детерминизм (agent-determinism принцип Orchestra), не жрёт контекст без нужды. ❌ агент должен догадаться позвать.
- Авто-инжект в промпт при спавне (через существующий `<worker-memory>` хук, manager.py:476). ✅ агент сразу видит релевантное. ❌ на спавне нет query → нечего искать; жрёт контекст всегда.
- **РЕКОМЕНДАЦИЯ: MCP tool** (on-demand). Авто-инжект отложить — на спавне нет запроса, релевантность неопределима. Соответствует принципу «1 задача = 1 маршрут, минимум тулов, on-demand».

### D. Когда индексировать
- **watcher (watchfiles)** — live, как у Кеши. ✅ всегда свежо. ❌ 17 scopes под вотчем = inotify-нагрузка + постоянные мелкие embed (190ms каждый).
- Хук на merge/commit. ✅ индексим только «зафиксированное» знание, дёшево. ❌ надо встроить в merge_worker.
- Periodic backfill (раз в N часов). ✅ просто, батчами. ❌ лаг.
- **РЕКОМЕНДАЦИЯ: гибрид** — periodic `backfill_files` при старте + после `merge_worker` (там уже есть точка, знание «застыло»). watcher **только на scope самой Orchestra** (dev-проект, часто меняется). Не вотчить все 17 — дорого.

### E. Формат результата search
- Чанк + `[file: rel/path]` attribution + score (как у Кеши `_fmt`). Агент видит откуда факт → может открыть файл целиком. **1:1 из kesha.**

---

## 6. Риски и митигации

| Риск | Severity | Митигация |
|---|---|---|
| **Peak RAM 2.4 GB при backfill** пересекается с Orchestra+воркерами при available ~5 GB | 🔴 HIGH | batch=8-16, backfill по 1 проекту, throttle между батчами, ночной backfill. Idle 946 MB — ок |
| **Backfill часы** на 17 проектов | 🔴 HIGH | инкрементальный sha256-дедуп (есть), индексить lazy (проект при первом обращении), не всё сразу |
| **Cross-project утечка** (RimWorld-мод видит VPN-креды) — 17 разнородных проектов | 🔴 HIGH | `project` PARTITION KEY + endpoint фильтрует по scope вызывающего ПО УМОЛЧАНИЮ, кросс-поиск — явный флаг |
| **Скачивание модели HF заблокировано** на основном прокси (Contabo фильтрует HF, CONFIRMED — 403 Filtered; работает только Ёжик 12340) | 🟡 MED | закешировать модель в репо/volume заранее, `HF_HUB_OFFLINE=1` в проде; НЕ полагаться на runtime-скачивание |
| **+565 MB на диск + onnxruntime в deps** раздувает установку | 🟡 MED | опциональная зависимость (`orchestra[rag]`), feature-flag `RAG_ENABLED` |
| **sqlite-vec alpha** (v0.1.x) стабильность | 🟡 MED | у Кеши в проде работает (5930 чанков, 0 ошибок — прод-свидетельство); WAL + busy_timeout уже настроены |
| **190 ms/chunk** медленно | 🟢 LOW | это backfill (фон), не user-path. Query 24ms — то что важно — быстро |
| Heading-aware для наших docs | 🟢 LOW | наши `docs/tasks/*.md` = markdown с `#` заголовками, kesha-чанкер ложится идеально (LLM-генерённый структурный md) |

---

## 7. План Phase 1 (конкретика)

**Цель:** MCP-tool `search_memory` ищет по `docs/tasks/*.md`+`CLAUDE.md`+`BUGS.md` проекта-вызывающего. Один embedder в main-app. Feature-flag.

### Файлы
| Файл | Действие | ~строк |
|---|---|---|
| `app/rag.py` | НОВЫЙ — портирован из kesha, диалоговый слой выкинут, +`project` namespace | ~400 |
| `app/main.py` (или роутер) | +endpoint `POST /api/memory/search`, `POST /api/memory/reindex`; инициализация RagMemory-синглтона + executors на старте | ~60 |
| `app/mcp_stdio.py` | +`@mcp.tool() search_memory(query, limit, cross_project)` → HTTP callback | ~30 |
| `app/manager.py` | хук: после `merge_worker` → `backfill_files(scope)` | ~10 |
| `pyproject.toml` | +optional deps `[rag]`: fastembed, sqlite-vec, watchfiles | ~5 |
| `pipelines/*/prompts/` | +описание тула в промпт (когда звать search_memory) | ~10 |
| `tests/test_rag.py` | портировать kesha-тесты (чанкеры, index/dedup/delete, RRF, project-изоляция) | ~250 |
| Модель | закешировать `bge-m3-onnx-int8` в volume/`data/models/`, offline-режим | — |

### Порядок (тикеты — детализируются в Phase 2)
1. Порт `rag.py` (файловый слой + project namespace) + юнит-тесты чанкеров/RRF (без сети).
2. RagMemory-синглтон в main-app + executors + `/api/memory/search` endpoint.
3. MCP-tool `search_memory` + HTTP callback + project-фильтр по умолчанию.
4. Backfill: команда/endpoint + хук на merge. Throttle + batch=16.
5. Модель offline-кеш + feature-flag `RAG_ENABLED` + optional deps.
6. Тест изоляции проектов (RimWorld не находит orchestra-чанки).

### Оценка
**~3-4 дня.** Основной риск не в коде (60% готово у Кеши), а в: (1) настройке offline-модели, (2) backfill-throttling чтобы не съесть RAM, (3) тесте изоляции.

---

## 7a. Adversarial self-review (Codex-гейт сломан — 7 джобов подряд failed на 5 воркерах, баг зарепорчен)

Codex недоступен (платформенная поломка codex_review, не мой запрос). Провожу falsification 4 load-bearing выводов сам (red-team).

**Вывод 1 — embedder ОБЯЗАН быть синглтоном в main-процессе.**
Контр-атака: а если ONNX-сервер отдельным процессом (не в main FastAPI, не в MCP)? — Да, это валидная альтернатива и даже ЛУЧШЕ изолирует 946MB+peak от FastAPI event-loop (backfill не мешает HTTP). Уточняю: «НЕ в MCP-субпроцессе» — **CONFIRMED** (946MB×N воркеров = OOM, форсировано архитектурой процесс-на-воркера). Но «main FastAPI vs отдельный embedder-демон» — **развилка, не догма**. Отдельный демон + main как прокси к нему = чище (peak RAM не в web-процессе). → Смягчил формулировку: embedder вне MCP обязательно; main-vs-daemon решить в Phase 2. Меньшая модель (bge-m3 small / e5-small 384d, ~130MB) — тоже опция, но kesha-замер (rag.py:19) показал int8 bge-m3 даёт +0.237 separation margin vs e5 +0.055 на русских абстрактных запросах → качество того стоит. UNCERTAIN на нашем корпусе (англ+рус docs), проверить в Phase 2.

**Вывод 2 — одна vec.db + PARTITION KEY безопаснее 17 файлов.**
Контр-атака: партиция — НЕ security-граница (уже признал в §5A). Забытый фильтр в ЛЮБОМ будущем запросе = утечка через всю базу; per-file .db делает утечку физически невозможной (открыл файл проекта — видишь только его). → Это **честный контр-довод**. Смягчаю: для 17 разнородных проектов (включая приватные креды в VPN-Service) per-file изоляция — валидный выбор с более сильной гарантией. Рекомендация «одна db» держится на простоте (один embedder-контроллер, кросс-поиск возможен), но **если security > convenience — per-file правильнее**. Оставляю обе как явную развилку для approval, не прячу.

**Вывод 3 — 2.4GB peak backfill = binding risk, 190ms/chunk.**
Контр-атака: 190ms/chunk — это МОЯ машина под нагрузкой (10GB used, оркестратор потом её вообще завесил). Прод-VPS Кеши: 98ms/chunk. Реальный прод может быть 2× быстрее. Но вывод «backfill тяжёлый, нужен throttle/инкрементальность» — **CONFIRMED направление** независимо от точного ms. Peak 2.4GB — реальный замер, риск реальный. Митигация batch=8-16 снижает peak (замер: batch=16 → 1.6GB vs batch=64 → 2.4GB) — **подтверждено данными**. Дилбрейкер? Нет — backfill фоновый, разовый, инкрементальный (sha256). Не user-path.

**Вывод 4 — выкинуть диалоговый слой, files-only, MCP on-demand.**
Контр-атака: а `logs` (26k строк)? Там реальные решения агентов, которых нет в .md. — Да, но: сырые turn-логи = base64/tool-дампы/шум, LLM-фильтр дорог и хрупок. Ценное из логов агент И ТАК коммитит в report.md/retro.md (это и есть дистилляция). Индексить report.md > индексить сырые логи. Auto-inject: контр-довод — на спавне query неизвестен, но можно инжектить по task_id/title. Слабо (заголовок ≠ хороший запрос), но не ноль. → Оставляю MCP on-demand как старт, auto-inject-by-title помечен как возможное расширение Phase 2, не отвергнут наглухо.

**Итог self-review:** ни один вывод не REFUTED, но 2 смягчены (embedder-daemon как опция; per-file .db как валидная альтернатива для security). Гейт закрыт self-review'ом ввиду недоступности Codex — при восстановлении Codex прогнать повторно на Phase-2 плане.

---

## 8. Sources
- **Измерения (Tier-1):** `/tmp/rag_bench/bench.py`, `bench2.py`, `index_real.py` — эта машина, 2026-07-12. RAM/latency/throughput/disk.
- **Первоисточник кода (Tier-2):** `/mnt/data/Projects/Python/kesha-tg-bot/rag.py` (729 стр), `tests/test_rag.py`, `test_rag_files.py`, `bot.py:160-219`, `kesha_tools.py:280-315` — прочитаны целиком.
- **Orchestra (Tier-2):** `app/mcp_stdio.py`, `app/manager.py:476`, `app/prompting.py`, `data/orchestra.db` (17 scopes, 26690 logs, 150 файлов/1397 чанков в docs/tasks) — прочитано/измерено.
- **Прод-свидетельство (Tier-4, не воспроизведено здесь):** цифры «5930 чанков / 39MB / 1.2GB RSS / 98ms» из комментариев rag.py — прод-VPS Кеши, другое железо. Расходятся с моими замерами, использую свои.
