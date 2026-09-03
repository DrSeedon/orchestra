# #113 — план снижения memory pressure

Дата: 2026-08-01. Основа: `docs/tasks/113/research.md`, принят orchestrator. План ничего не внедряет и не требует restart/reboot.

## Решение

1. **ONNX ownership теперь CONFIRMED**, а не LIKELY: isolated differential probe четырежды воспроизвёл ~0.89 GiB прироста `PSS+SwapPss` при создании текущего bge-m3 embedder.
2. Безопасная первая RAG-мера — вернуть default batch с 64 на 16: ожидаемо **−0.8 GiB transient peak**, без смены модели и retrieval quality.
3. Резидентный embedder — product cost, не утечка. При активном `search_memory` перенос в child process сам по себе освобождает **0 GiB на машине**; выигрыш появляется только когда child действительно idle и завершён.
4. Optional child-process + idle-exit оставлен отдельным тикетом: его можно принять или зарубить без влияния на batch cap и bg-job reaper.
5. `codex_review` process-group cleanup чинится независимо в `app/bg_jobs.py`. Он ограничивает жизнь сирот, но не уменьшает легитимные ~0.33 GiB на каждый текущий review.
6. #111 не дублируется: в этом плане нет механики hibernation.

## Доказательство владельца RAG/ONNX

### Критерий до эксперимента

- ownership подтверждён, если load + first embed добавляет ≥0.70 GiB `PSS+SwapPss`;
- unload технически жизнеспособен, если `del + gc + malloc_trim(0)` возвращает ≥70% delta за 10 секунд;
- всё выполняется в isolated process из `/tmp`, production PID не модифицируется.

### Результат

Текущая модель и кеш: `AlpEge/bge-m3-onnx-int8`, 570,117,086-byte ONNX. Метрика — `/proc/self/smaps_rollup`, KiB.

| Run | Baseline retained | После load+embed | Delta | После unload+trim | Returned | Returned % |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8,459 | 940,640 | 932,181 | 83,499 | 857,141 | 91.95% |
| 2 | 8,892 | 942,455 | 933,563 | 84,543 | 857,912 | 91.90% |
| 3 | 8,859 | 942,115 | 933,256 | 84,618 | 857,497 | 91.88% |
| 4 | 8,894 | 942,780 | 933,886 | 84,624 | 858,156 | 91.89% |
| **Mean** | — | — | **0.8900 GiB** | — | **0.8179 GiB** | **91.90%** |

Дополнительные falsifiers тоже пройдены:

- `Pss_Anon`: ~6 MiB → 913–915 MiB после load;
- ONNX mappings: 0 → 9;
- один embedding имеет ожидаемые 1024 dimensions;
- после unload повторный load+embed успешен; cold construct **3.97 s**, embedding **41 ms**;
- `del+gc` без `malloc_trim` оставил ~0.64 GiB retained: безопасно получить полный выигрыш внутри main PID одной сборкой мусора нельзя.

**Итог:** текущий ONNX embedder непосредственно владеет ~0.89 GiB process footprint. Это доказывает owner, но не превращает все 1.6–2.4 GiB main PID в ONNX: остаток и batch arenas считаются отдельно.

### Реальная полезность idle-unload

За текущий boot найдено 46 фактических `mcp__orchestra__search_memory` calls за 5,849 s: средний gap 130 s, максимальный 842 s, только 5 gaps ≥300 s. При TTL=300 s модель была бы выгружена максимум **1,372 s / 23.5%** этого busy interval; merge backfills в этот подсчёт не входят и могут только уменьшить долю. Поэтому gross idle gain 0.82–0.89 GiB превращается в **≤0.19–0.21 GiB time-weighted gain** во время сегодняшней активной работы, но почти в полный gain ночью/в длинных паузах.

## RAG-варианты: память против качества

| Вариант | Что теряет `search_memory` | Выигрыш на машине | Цена | Риск | Решение |
|---|---|---:|---|---|---|
| Текущая lazy load без unload | Ничего; cold load уже отложен до первого embed | **0 GiB** после первого вызова | уже есть | модель остаётся навсегда | Не считать лечением |
| In-process idle unload | Retrieval quality не меняется; первый запрос после idle получает **+~4 s** | `gc` только **~0.26 GiB**; с process-wide `malloc_trim` **0.818 GiB idle**, busy weighted ≤0.19 GiB | low/medium | гонка двух executors; global allocator trim всего FastAPI PID | Не внедрять в main |
| Embedder child process + idle exit | Та же модель/векторы, quality loss **0**; cold query +~4 s | **0 GiB active**, **~0.89 GiB idle**; busy weighted ≤0.21 GiB | high, ~1–2 дня | IPC/lifecycle, search может ждать текущий embed | Optional T2; только если нужен ночной/idle gain |
| Batch 16 вместо 64 | Та же модель и embeddings; quality loss **0**; backfill batches мельче | **~0.8 GiB transient peak**, steady 0 | trivial, <0.5 дня | backfill может быть медленнее; старый benchmark не показал throughput gain у 64 | **Рекомендовано, T1** |
| Лёгкая multilingual модель | Нужен полный reindex; 384d вместо 1024d. На прежнем русском abstract-query probe e5-small separation margin был 0.055 против 0.237 у bge-m3 (**−77%**); Orchestra golden set отсутствует | ориентир **0.55–0.75 GiB steady**, peak тоже ниже; не Tier-1 без загрузки/benchmark кандидата | medium, 1–2 дня + reindex | недостоверный semantic recall, schema/model migration | Не планировать до held-out benchmark |
| FTS5-only, без local embeddings | Сохраняется exact lexical match; теряются paraphrase, semantic и cross-language matches | **~0.89 GiB steady + до 0.8 GiB peak** | medium, ~1 день | деградация главной функции memory search | Только emergency/product decision |
| Remote embeddings | Зависит от remote model; latency/network и data egress | тот же **~0.89 GiB steady + peak** локально | medium/high | subscription-only policy запрещает API keys; внешний отказ | REFUTED текущей политикой |

Размеры лёгких моделей — ориентир, не обещанный RAM gain: installed FastEmbed registry указывает multilingual MiniLM ONNX ~0.22 GB против текущего ONNX 0.57 GB, но ни memory benchmark, ни retrieval evaluation на Orchestra corpus не запускались. Поэтому модель не меняется в этом плане.

## `codex_review`: что именно исправляет reaper

- Текущий hard job timeout уже **600 s** (`app/mcp_stdio.py:1060-1075`).
- Баг после normal leader exit: `_kill_proc()` сразу возвращает при `proc.returncode is not None`; descendant, закрывший inherited stdout, может остаться в той же process group без верхней границы (`app/bg_jobs.py:114-133, 676-706, 752-757`).
- Все local run processes стартуют через `preexec_fn=os.setsid`, поэтому сохранённый `pgid == leader pid` известен даже после исчезновения leader.
- T3 делает unconditional terminal group reap: `SIGTERM`, bounded grace, затем `SIGKILL`, с проверкой существования группы. Periodic system-wide process scan не нужен.

**Цена памяти:** пока review законно работает, gain **0 GiB** — три concurrent reviews всё ещё удерживают ~1.0 GiB. После завершения T3 гарантированно возвращает process footprint потенциальной сироты: **~0.33 GiB/review**, до **~0.99 GiB** для трёх завершившихся trees. Текущий snapshot сирот не нашёл, поэтому immediate measured gain сейчас 0 GiB; ценность тикета — строгая верхняя граница.

## Idle hibernation #111 — только цена

- 8 live idle roots в 14:10: **3.30 GiB PSS+SwapPss**.
- 9 live idle roots в 14:22: **3.54 GiB PSS+SwapPss** = 1.11 GiB resident PSS + 2.43 GiB SwapPss.
- Это gross attributable footprint и пересекается с Serena/CLI/MCP; фактический before/after gain ещё не измерен.
- В #113 нет изменений hibernation, `app/tg_bridge.py`, `app/manager.py` или `app/workspace.py`.

## Reboot — формулировка для пользователя

**Reboot освобождает process swap entries только до текущего footprint ceiling, но не чинит cardinality или RAG reload; при наблюдавшейся нагрузке swap вернулся за часы.**

## Scope файлов

Разрешённые изменения:

- `app/rag.py`
- `app/rag_service.py`
- новый `app/rag_embedder.py` — только если отдельно принят optional T2
- `app/bg_jobs.py`
- `tests/test_rag.py`
- новый `tests/test_rag_service.py` — только для optional T2
- `tests/test_bg_jobs.py`

Не трогать:

- `app/manager.py`, `app/workspace.py`, `app/routes/sessions.py` (#93)
- `app/tg_bridge.py` (#111/#114)
- `pipelines/`
- `app/static/js/app.js`
- RAG routes/API contract и SQLite schema/index — смена модели не планируется

## Tickets

Тикеты логически независимы: у всех `blocked-by: none`. Они могут менять соседние строки RAG-файлов, но ни один не требует результата другого; Phase 3 применяет только явно одобренные тикеты.

### T1 — Ограничить RAG transient peak без смены качества

- **Files:** `app/rag.py`, `tests/test_rag.py`
- **Цена:** trivial, <0.5 дня.
- **Риск:** low; меняется только default batch, env override сохраняется.
- **Ожидаемый выигрыш:** **~0.8 GiB transient PSS peak**, steady 0 GiB. Основание: direct benchmark batch16=1.6 GiB против batch64=2.4 GiB.
- **AC:**
  - без `RAG_EMBED_BATCH` `EMBED_BATCH == 16`;
  - `RAG_EMBED_BATCH=32` по-прежнему даёт 32;
  - bge-m3 model, dimension=1024, pooling/prefix и существующая vec.db schema не меняются;
  - test/probe подтверждает одинаковую длину и численную эквивалентность embeddings при batch16/64 на одном input set;
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_rag.py` проходит.
- **blocked-by:** none

### T2 (OPTIONAL) — Изолировать embedder в lazy child с idle-exit

- **Files:** `app/rag.py`, `app/rag_service.py`, новый `app/rag_embedder.py`, новый `tests/test_rag_service.py`, `tests/test_rag.py`
- **Цена:** high, 1–2 дня.
- **Риск:** medium/high; process lifecycle и синхронный IPC между двумя RAG executors. Не принимать ради active-memory gain: его нет.
- **Ожидаемый выигрыш:** **0 GiB active; ~0.89 GiB gross / ~0.82 GiB measured reclaim idle**. На сегодняшнем busy trace при TTL300 — upper-bound **≤0.21 GiB average**; в длинной паузе — полный gain.
- **Что:** parent хранит лёгкий locked client; child стартует через `multiprocessing` spawn на первом embed, использует ту же bge-m3 и возвращает 1024d vectors через pipe. После `RAG_EMBED_IDLE_SECONDS` без запроса child сам выходит; следующий request поднимает его заново. Exit процесса освобождает allocator без `malloc_trim` main PID.
- **AC:**
  - `rag_service.initialize()` не создаёт ONNX mappings и child до первого embed;
  - первый search/backfill стартует ровно один child; concurrent calls не создают второй;
  - текущая bge-m3 выдаёт numerically equivalent embeddings и существующий vec.db не reindexится;
  - child не завершается во время in-flight embed; после configurable test TTL завершается и освобождает ≥0.75 GiB `PSS+SwapPss` в integration probe;
  - следующий search автоматически создаёт новый child и возвращает результат; measured cold penalty записан в report;
  - каждый IPC request имеет parent-side `Connection.poll(RAG_EMBED_REQUEST_TIMEOUT_SECONDS)`; default 300 s, timeout не может зависнуть на `recv()`;
  - timeout или mid-request child death закрывает pipe, делает bounded `terminate → kill → join` (≤5 s) и surfaced как `RuntimeError` с exception class; запрос молча не retry-ится, следующий request создаёт чистый child;
  - request lock сериализует embeds, но shutdown его не ждёт: отдельный closing event + короткий state lock атомарно запрещают новые requests и detaches pipe/process; закрытие pipe прерывает текущий `poll/recv`, затем bounded `terminate → kill → join` завершается ≤5 s;
  - test с request, заблокированным в `poll()`: `rag_service.shutdown()` завершается ≤5 s, request получает `RuntimeError`, orphan child отсутствует;
  - no `malloc_trim` вызывается в main PID;
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_rag.py tests/test_rag_service.py` проходит.
- **blocked-by:** none

### T3 — Гарантированно reap process group завершившегося bg run

- **Files:** `app/bg_jobs.py`, `tests/test_bg_jobs.py`
- **Цена:** low, ~0.5 дня.
- **Риск:** low/medium; ошибочный PGID может задеть чужой процесс, поэтому использовать только сохранённый `pgid=proc.pid`, созданный собственным `os.setsid`, и reap немедленно после завершения leader, до validation/notification. POSIX запрещает назначать новый PID, совпадающий с активным process-group ID; пока descendant держит group, этот PGID не переиспользуется [1].
- **Ожидаемый выигрыш:** active gain 0 GiB; после leaked completion **~0.33 GiB/review**, до **~0.99 GiB** для трёх trees. Current immediate gain 0 GiB, потому что сироты в snapshot не найдены.
- **AC:**
  - terminal path `run` всегда посылает TERM сохранённому `pgid=proc.pid`, даже если leader уже `returncode=0` и stdout EOF; `os.getpgid(proc.pid)` после exit не используется;
  - cleanup начинается сразу после reader completion и **до** artifact validation, DB transition и success/failure notification;
  - после bounded 2 s grace живой group получает KILL и ещё ≤2 s на исчезновение; отсутствие group (`ProcessLookupError`) считается успехом;
  - `PermissionError` или process group, живой после KILL grace, переводит job в failed; ожидающий worker получает ровно один `_fail_notify()`, а `_trigger()` и `_expire_notify()` не вызываются;
  - integration test: leader создаёт child, child закрывает stdout и остаётся sleeping, leader выходит 0; после `_run_exec()` child PID/process group отсутствует;
  - timeout, cancel, non-zero и success-artifact semantics существующих jobs не меняются;
  - для каждого terminal outcome выбирается ровно один notification path; success trigger отправляется один раз и только после успешного cleanup;
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_bg_jobs.py` проходит.
- **blocked-by:** none

## Порядок Phase 3, если тикеты одобрены

Порядок нужен только для минимизации риска, не как dependency: **T3 → T1 → optional T2**. После каждого тикета — его узкий test file и проверка AC. Общий suite запускается один раз после выбранного набора. Никаких restart, process kill или before/after production измерений без отдельной команды пользователя.

## Источник process-group инварианта

1. POSIX `fork()` / Process Group ID Reuse: child PID не может совпадать с активным PGID, а PGID не переиспользуется до конца lifetime группы — https://pubs.opengroup.org/onlinepubs/9799919799/functions/fork.html и https://pubs.opengroup.org/onlinepubs/009696699/basedefs/xbd_chap04.html
