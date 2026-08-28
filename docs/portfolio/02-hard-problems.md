# Восемь сложных решённых задач

## 1. Idle-воркеры навсегда запирались на `handoff_pending_effect`

- **Симптом.** Смена модели отказывала idle-сессии, а старый gate держал закрытыми 266 из 361 проверенной сессии (`docs/tasks/340/report.md`, разделы 1 и 5; #340).
- **Первая гипотеза была неверной.** Код считал autoincrement `logs.id` порядком событий. На живом WAL-safe снимке у 4 266 из 42 661 пар `tool_result.id < tool.id`, хотя `ts` был корректен во всех 42 661 парах (`docs/tasks/340/report.md`, раздел 1).
- **Причина.** `_log` отдаёт SQLite-вставки пулу потоков: `id` отражает порядок commit, а timestamp ставится раньше в event loop. Однопроходный matcher видел result до call и оставлял call `pending` (`docs/tasks/340/report.md`, раздел 1; текущий DB executor — `app/session.py:5049-5074`).
- **Исправление.** Пары сопоставляются по `(ts,id)`; блокируется только вызов, после которого в снимке нет ни одной строки, остальные едут как видимые `unresolved`, без replay side effect (`docs/tasks/340/report.md`, разделы 3–4; #340).
- **Доказательство.** Закрытых сессий стало 2 вместо 266, `ambiguous` — 0 вместо 4 320; восемь отдельных мутаций краснили свои named oracles, смежные suites дали 59 и 214 зелёных тестов (`docs/tasks/340/report.md`, разделы 5–6).

## 2. «Codex медленный из-за Python wrapper»

- **Симптом.** Managed Codex субъективно сильно отставал от standalone CLI; естественным подозреваемым был Python/stdio/app-server слой (`docs/tasks/240/measurements.md`; #240).
- **Первая гипотеза была неверной.** На одинаковом no-tool PONG `app-server` против `codex exec` добавил только +0.270/+0.756 s total-to-final, а local JSON-RPC имел median 0.058 ms (`docs/tasks/240/measurements.md`, таблица A/B и `No-model controls`).
- **Причина.** Большая final wall коррелировала с самой работой: в ретроспективе при 10–12 active turns median tool rounds вырос с 4 до 22, output — с 2 928 до 13 740 tokens; final wall вырос, но TTFT p90 не деградировал, а throughput вырос (`docs/tasks/255/measurements.md`, строки active=1 и active=10–12; #255).
- **Исправление.** Транспорт не переписывали. Сохранили CLI `app-server --stdio`, отдельно оптимизируют число tool-rounds, размер prompt/history и lifecycle reconnect (`app/runtime_registry.py:213-273`; `docs/tasks/240/architecture-snapshot.md`).
- **Доказательство.** В когорте 10–12 active turns — 0/22 terminal errors при quota 18–56%; TTFT median/p90 11.684/18.372 s против 9.273/35.575 s при одном active turn (`docs/tasks/255/measurements.md`, concurrency table).

## 3. `task_create` выходил за 30-секундный MCP deadline

- **Симптом.** Canonical Git commit успевал выполниться, HTTP-клиент получал timeout, а retry рисковал дублировать уже сделанную работу (`docs/tasks/408/measurements.md`, `Live incident timestamps`; task #405).
- **Первая гипотеза была неверной.** Увеличивать deadline не требовалось: MCP+HTTP overhead занимал 3.294–6.109 ms, legacy SQLite — 5.682–10.903 ms. Узкое место находилось не в transport и не в legacy writer (`docs/tasks/408/measurements.md`, `Before and after`).
- **Причина.** После каждого canonical commit синхронно перестраивался `current.db` размером 540 897 280 bytes; projection step занимал 36 821–36 893 ms, или 92.5% первого полного baseline (`docs/tasks/408/measurements.md`, `Measurement boundary` и `Before and after`).
- **Исправление.** Same-head projection валидируется и получает receipts без полной перезаписи; битая/удалённая проекция атомарно rebuild-ится из canonical JSON (`app/ia/runtime.py:74-102`; `app/ia/runtime.py:1071-1115`).
- **Доказательство.** A/B/A/B: end-to-end 38.029–39.876 s до, 3.144–4.784 s после — ускорение 8.0–12.7×. Отдельно удалённый `task-current.db` восстановил 684 rows из 1 545 JSON за 848.743 ms; финальный focused run — 46 passed (`docs/tasks/408/measurements.md`).

## 4. Restart отвечал успехом, но новый процесс не появлялся

- **Симптом.** Uvicorn писал `Finished server process`, service оставался active, listener копил connections, а новый MainPID мог появиться значительно позже (`docs/tasks/379/research.md:78-99`; #379).
- **Первая гипотеза была неверной.** Сохранённая socket queue не делала следующий Uvicorn непригодным: при `Recv-Q=350` новый процесс 3/3 раза отдал HTTP 200 и свёл queue в 0 (`docs/tasks/379/research.md:161-176`).
- **Причина.** Старый supervisor оставался жив после ASGI teardown; отдельно uvloop передавал activation FD дочерним Node/Codex/MCP-процессам без `FD_CLOEXEC`, что мешало настоящему rebind (`docs/tasks/379/research.md:91-139`, `docs/tasks/379/research.md:182-224`).
- **Исправление.** Same-UID helper адресует старый supervisor через pidfd только после durable `application_teardown_complete`; весь `LISTEN_FDS` range получает `FD_CLOEXEC` до импорта manager, не закрывая fd 3/4/5, нужные для listener и agent adoption (`docs/tasks/379/report.md`, разделы T1–T2; `app/main.py:370-437`).
- **Доказательство.** 32 focused restart/FD/seamless tests, 287 lifecycle/FD/manager tests и 7/7 пойманных мутаций; full flat suite честно оставлен без вердикта после process timeout, а не объявлен зелёным (`docs/tasks/379/report.md`, разделы `Проверки` и `Mutation evidence`).

## 5. Тестовый Uvicorn в worktree забирал Telegram updates у production

- **Симптом.** Два orphan-процесса с production token дали 383 `TelegramConflictError` за час; токен находился в 22 из 42 worktrees (`docs/tasks/324/report.md:13-16`; #324).
- **Первая гипотеза была неверной дважды.** Наличие `INVOCATION_ID`, `NOTIFY_SOCKET` или `LISTEN_FDS` не отличает production: descendants наследуют их. Затем первая версия отчёта утверждала, что unit менять не надо, но tracked `ExecStart=uv run ...` форкал ребёнка и ломал PID identity (`docs/tasks/324/report.md`, разделы `The discriminator` и `systemd`; строка `RETRACTED`).
- **Причина.** `uv run` не делает `exec`: контроль дал `LISTEN_PID=2751595`, `app_pid=2751601`, `MATCH=False`; прямой interpreter дал `2751602 == 2751602`, `MATCH=True` (`docs/tasks/324/report.md:97-104`).
- **Исправление.** TG bridge разрешён только процессу, для которого `LISTEN_PID == os.getpid()`; проверка стоит до чтения token. Unit использует прямой interpreter и socket activation (`docs/tasks/324/report.md`, разделы `The change` и `systemd`; текущий guard — `app/tg_bridge.py`, функция `_unmanaged_instance_reason`).
- **Доказательство.** Три guard-мутации пойманы; targeted suites дали 199 и 157 passed. Независимое review нашло недостающую конфигурационную сторону и заставило отозвать исходное «unit change не нужен» (`docs/tasks/324/report.md:160-167`, раздел `Outcome of the handoff`).

## 6. Telegram timeout: неизвестно, отправлен файл или нет

- **Симптом.** Три 30-секундные попытки `send_photo` закончились HTTP 500, но provider мог принять файл до timeout; повтор мог создать дубль (`docs/tasks/333/research.md`, incident timeline; #333).
- **Первая гипотеза была неверной.** `HTTP 500` не доказывает «не отправлено», потому что route видел только отсутствие message id после ambiguous provider boundary; в том же incident window другие sends вернули 200/message ids (`docs/tasks/333/research.md`, разделы о incident и controls).
- **Причина.** У Telegram Bot API на этом пути нет клиентского idempotency key/status lookup, а старый retry не имел durable per-file receipt (`docs/tasks/333/contract.md`; `docs/tasks/333/report.md`, `Breaking changes and remaining limits`).
- **Исправление.** Добавлены snapshot+payload hash, stable `event_id`, per-target receipt states, FIFO chat lease и terminal `UNKNOWN`, который никогда не replay-ится вслепую; batching использует deterministic child IDs и атомарно помечает всю claimed group `UNKNOWN` при ambiguous boundary (`docs/tasks/333/report.md`, `Implemented surface`; `docs/tasks/402/report.md`, `Delivery and grouping contract`).
- **Доказательство.** Frozen #333 oracle — 13/13, focused TG/MCP — 298 passed. Batch-suite трижды дала 12 passed; дополнительно 16 и 90 regression tests, три мутации вернули `red_rc=1 → green_rc=0` (`docs/tasks/333/report.md`, `Acceptance evidence`; `docs/tasks/402/report.md`, `Tests and mutations`).

## 7. «Проблему памяти решит более сильный embedding»

- **Симптом.** RAG плохо разделял current/rejected и имел большой freshness debt; первая реакция — заменить embedding-модель (`docs/tasks/256/research.md:95-126`; #256).
- **Первая гипотеза была неверной.** На замороженных 28 queries GigaEmbeddings дала MRR 0.4726 против 0.4893 у bge-m3, Δ −0.0167 при split-half noise 0.1048; разницы стенд не видит (`docs/tasks/364/bench/results.json`; `docs/tasks/364/report.md`, `Вердикт`; #364).
- **Причина.** Seam был раньше retrieval: source-link coverage 7/12, current index coverage 547/1 092, freshness debt 545; prompt-only Markdown не принуждал stable fact identity, provenance и supersession (`docs/tasks/256/research.md:52-55`, `docs/tasks/256/research.md:100-126`).
- **Исправление.** Git остаётся canonical evidence, typed fact/task events получают stable IDs и heads, SQLite current/FTS и vector становятся rebuildable content-bound projections (`docs/tasks/256/research.md:201-290`; current code: `app/ia/task_store.py:308-390`, `app/ia/runtime.py:1633-1661`).
- **Доказательство.** Candidate embedding не внедрён; вместо «улучшения» зафиксирован честный verdict `не меняем`. Для projection-path удалённый индекс воспроизводимо rebuild-ится из canonical state (`docs/tasks/364/report.md`; `docs/tasks/408/measurements.md`, `Deleted task-current.db probe`).

## 8. Чат сначала показывал старое, потом догонял SSE

- **Симптом.** Первый кадр брался из IndexedDB, затем network/SSE перестраивали его; пользователь видел устаревшую историю как актуальную (`commit 735cf14e`; current rationale `app/static/js/app.js:2377-2381`).
- **Первая гипотеза была неверной.** Локальное зеркало не может доказать свежесть: его watermark обновляется тем же delayed poll. Следовательно, даже быстрый cached first paint не удовлетворяет контракту live-chat (`app/static/js/app.js:2377-2381`).
- **Причина.** Было два конкурирующих owners первого кадра — IndexedDB и server snapshot. Cache также мог replay-ить старый HTTP 200 (`app/routes/sessions.py:576-583`).
- **Исправление.** Один network-first snapshot рисуется атомарно, предыдущий fetch отменяется `AbortController`, затем SSE продолжается после последнего id; `no-store` выставлен клиентом и сервером (`app/static/js/app.js:2312-2327`, `app/static/js/app.js:2330-2415`; `app/routes/sessions.py:576-592`; commits `735cf14e`, `6de7cb70`).
- **Доказательство.** `git show --stat 735cf14e` — 418 insertions / 1 095 deletions в пяти файлах, то есть зеркало удалено, а не спрятано. Текущий прогон `uv run pytest -q tests/test_frontend.py tests/test_logs_sync.py` дал `128 passed, 1 skipped in 77.36s`.
