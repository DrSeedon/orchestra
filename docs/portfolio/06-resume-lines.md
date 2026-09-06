# Формулировки для резюме

Числа ниже относятся к результату проекта/контура. Корректная атрибуция: Максим спроектировал продукт, prompts/pipelines, принимал архитектурные решения и результаты; research, реализацию и тесты выполняли в том числе Claude/Codex/Grok workers. Git author identity не позволяет назвать весь объём ручным кодом Максима (`docs/portfolio/01-architecture.md:133-135`; `docs/portfolio/04-stack.md:93-113`).

## Короткая версия — 6 строк

- Спроектировал и довёл до эксплуатации multi-runtime AI orchestrator для Claude, Codex, Grok и собственного OpenRouter Harness → единый lifecycle над 4 runtime с явной матрицей capabilities (`app/runtime_registry.py:29-53`, `app/runtime_registry.py:330-388`).
- Организовал безопасную параллельную разработку через Git worktrees, `owned_dirs` и guarded squash merge → рабочий контур накопил 662 agent sessions в 21 project scope; текущий tracker Orchestra содержит 194 задачи `done` (`app/workspace.py:492-538`, `app/workspace.py:1229-1666`; `docs/portfolio/04-stack.md:80-90`, `docs/portfolio/04-stack.md:116-144`).
- Локализовал timeout создания задачи в синхронном rebuild проекции → сократил end-to-end latency с 38.029–39.876 s до 3.144–4.784 s, ускорение 8.0–12.7× без увеличения deadline (`.orchestra/tasks/408/measurements.md`; task #405).
- Исправил ошибочную модель порядка SQLite events → после обнаружения 4 266 инверсий в 42 661 парах число заблокированных handoff-сессий снизилось с 266/361 до 2 (`.orchestra/tasks/340/report.md`, §§1,5; #340).
- Увеличил effective Codex context 258 400→828 400 tokens → 19/34 новых turns использовали запросы выше старого потолка, immediate compact outcomes снизились 4→1 без ускорения quota burn в matched окне (`.orchestra/tasks/312/measurements.md`; #312).
- Спроектировал receipt-backed Telegram delivery с честным terminal `UNKNOWN` → frozen acceptance 13/13 и focused TG/MCP regression 298 passed; ambiguous provider outcome больше не replay-ится вслепую (`.orchestra/tasks/333/report.md`, `Acceptance evidence`; #333).

## Развёрнутая версия

- Спроектировал supervisor долгоживущих agent sessions → единый `BackendLike` contract обслуживает 4 неодинаковых runtime, не скрывая различия persistent/per-turn stream, steering, reconnect и hibernate (`app/backend_protocol.py:8-16`; `app/runtime_registry.py:330-388`).
- Разделил authority и execution → orchestrator задаёт role/task/acceptance, worker получает отдельные branch/worktree/`owned_dirs`, server повторно проверяет HEAD, dirty state и conflicts перед squash commit (`app/manager.py:701-767`; `app/workspace.py:492-538`; `app/workspace.py:1229-1666`).
- Построил restart-safe lifecycle → SQLite хранит session envelope/native IDs, startup восстанавливает orchestrators и workers, а server-side jobs переживают hibernate/restart (`app/db.py:48-141`; `app/manager.py:2207-2329`; `app/bg_jobs.py:474-510`).
- Довёл operational контур до 662 сохранённых sessions, 297 758 log records и 8 555 turn-usage rows в 21 scope → масштаб подтверждён read-only SQL-срезом на watermark `2026-09-06T06:00:18.075531+00:00`, а не README (`docs/portfolio/04-stack.md:116-144`).
- Перепроектировал slow canonical write path → при корпусе 684 tasks и `current.db` 540 897 280 B убрал rebuild из каждого запроса; end-to-end стал 8.0–12.7× быстрее (`.orchestra/tasks/408/measurements.md`; task #405).
- Исправил cross-runtime handoff gate после полной реконструкции событий → 4 266/42 661 пар оказались инвертированы по SQLite `id`; переход на `(ts,id)` снизил false blocks 266→2 sessions и выдержал 8 targeted mutations (`.orchestra/tasks/340/report.md`; #340).
- Проверил масштабирование по native model intervals, а не process count → 10–12 concurrent Codex turns завершились с 0/22 errors, TTFT p90 18.372 s и throughput 32.107 token/s (`.orchestra/tasks/255/measurements.md`; #255).
- Настроил большой native Codex context на измерении до/после → effective ceiling вырос 258 400→828 400, 19/34 turns превысили старый предел, compact outcomes снизились 4→1; human quality честно оставлена `UNKNOWN` (`.orchestra/tasks/312/measurements.md`; #312).
- Построил cost telemetry по 4 353 turns → оценил marginal tool call в $0.1349 для Claude и $0.1064 для Codex; 69%/72% marginal cost связано с cache read, поэтому optimization target — round-trips (`.orchestra/tasks/345/call-to-dollar.md`; #345).
- Отказался от неподтверждённой замены embedding-модели → на 28 frozen queries GigaEmbeddings дала MRR 0.4726 против 0.4893, а Δ 0.0167 оказался в 6.3 раза меньше собственного noise; production model не менялась (`.orchestra/tasks/364/bench/results.json`; `.orchestra/tasks/364/report.md`; #364).
- Разделил canonical truth и быстрые проекции → Git JSON хранит task/fact/evidence history, SQLite/FTS/vector связаны с exact heads и rebuild-ятся; удалённая task projection восстановила 684 rows за 848.743 ms (`app/ia/task_store.py:308-390`; `app/ia/runtime.py:74-102`; `.orchestra/tasks/408/measurements.md`).
- Спроектировал durable Telegram receipts и batch semantics → 13 frozen acceptance + 298 focused regression tests для per-file delivery; batch path трижды прошёл 12 tests и поймал 3 guard mutations (`.orchestra/tasks/333/report.md`; `.orchestra/tasks/402/report.md`; #333/#402).

## Чего не писать

- Не писать «написал 1.4 млн строк»: 17 615 из 18 083 tracked-файлов — `.orchestra/`; честный объём проекта — 80 863 строки production Python, 109 874 tests и 16 819 frontend (`docs/portfolio/04-stack.md:46-78`).
- Не писать «выполнил 505 задач»: это число каталогов artifacts. Трекер Orchestra на срезе показывает 194 `done` из 366 records (`docs/portfolio/04-stack.md:80-90`).
- Не писать «2 934 моих ручных коммитов»: 20 commit objects имеют foreign identity `vadimd`, ещё один — служебную `Orchestra`, а остальные Git identities не отделяют работу Максима от squash-коммитов model workers (`docs/portfolio/04-stack.md:93-113`).
- Не писать «сэкономил 15–17%»: это параметрическая оценка при гипотетическом сокращении tool calls на 20%, а не проведённый intervention (`.orchestra/tasks/345/call-to-dollar.md`, `Пробелы`).
- Не писать «exactly-once Telegram»: после provider timeout честный контракт — durable `UNKNOWN`, не доказательство доставки или недоставки (`.orchestra/tasks/333/report.md`, `Breaking changes and remaining limits`).
