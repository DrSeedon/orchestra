# Формулировки для резюме

Числа ниже относятся к результату проекта/контура. Корректная атрибуция: Максим спроектировал продукт, prompts/pipelines, принимал архитектурные решения и результаты; research, реализацию и тесты выполняли в том числе Claude/Codex/Grok workers. Git author identity не позволяет назвать весь объём ручным кодом Максима (`docs/portfolio/01-architecture.md:126-128`; `docs/portfolio/04-stack.md:85-105`).

## Короткая версия — 6 строк

- Спроектировал и довёл до эксплуатации multi-runtime AI orchestrator для Claude, Codex, Grok и собственного OpenRouter Harness → единый lifecycle над 4 runtime с явной матрицей capabilities (`app/runtime_registry.py:29-53`, `app/runtime_registry.py:330-388`).
- Организовал безопасную параллельную разработку через Git worktrees, `owned_dirs` и guarded squash merge → рабочий контур накопил 556 agent sessions в 21 project scope; текущий tracker Orchestra содержит 145 задач `done` (`app/workspace.py:492-538`, `app/workspace.py:1229-1666`; `docs/portfolio/04-stack.md:72-83`, `docs/portfolio/04-stack.md:107-136`).
- Локализовал timeout создания задачи в синхронном rebuild проекции → сократил end-to-end latency с 38.029–39.876 s до 3.144–4.784 s, ускорение 8.0–12.7× без увеличения deadline (`docs/tasks/408/measurements.md`; task #405).
- Исправил ошибочную модель порядка SQLite events → после обнаружения 4 266 инверсий в 42 661 парах число заблокированных handoff-сессий снизилось с 266/361 до 2 (`docs/tasks/340/report.md`, §§1,5; #340).
- Увеличил effective Codex context 258 400→828 400 tokens → 19/34 новых turns использовали запросы выше старого потолка, immediate compact outcomes снизились 4→1 без ускорения quota burn в matched окне (`docs/tasks/312/measurements.md`; #312).
- Спроектировал receipt-backed Telegram delivery с честным terminal `UNKNOWN` → frozen acceptance 13/13 и focused TG/MCP regression 298 passed; ambiguous provider outcome больше не replay-ится вслепую (`docs/tasks/333/report.md`, `Acceptance evidence`; #333).

## Развёрнутая версия

- Спроектировал supervisor долгоживущих agent sessions → единый `BackendLike` contract обслуживает 4 неодинаковых runtime, не скрывая различия persistent/per-turn stream, steering, reconnect и hibernate (`app/backend_protocol.py:8-16`; `app/runtime_registry.py:330-388`).
- Разделил authority и execution → orchestrator задаёт role/task/acceptance, worker получает отдельные branch/worktree/`owned_dirs`, server повторно проверяет HEAD, dirty state и conflicts перед squash commit (`app/manager.py:701-767`; `app/workspace.py:492-538`; `app/workspace.py:1229-1666`).
- Построил restart-safe lifecycle → SQLite хранит session envelope/native IDs, startup восстанавливает orchestrators и workers, а server-side jobs переживают hibernate/restart (`app/db.py:48-141`; `app/manager.py:2207-2329`; `app/bg_jobs.py:474-510`).
- Довёл operational контур до 556 сохранённых sessions, 206 555 log records и 5 619 turn-usage rows в 21 scope → масштаб подтверждён read-only SQL-срезом на watermark `2026-08-28T11:02:18.095226+00:00`, а не README (`docs/portfolio/04-stack.md:107-136`).
- Перепроектировал slow canonical write path → при корпусе 684 tasks и `current.db` 540 897 280 B убрал rebuild из каждого запроса; end-to-end стал 8.0–12.7× быстрее (`docs/tasks/408/measurements.md`; task #405).
- Исправил cross-runtime handoff gate после полной реконструкции событий → 4 266/42 661 пар оказались инвертированы по SQLite `id`; переход на `(ts,id)` снизил false blocks 266→2 sessions и выдержал 8 targeted mutations (`docs/tasks/340/report.md`; #340).
- Проверил масштабирование по native model intervals, а не process count → 10–12 concurrent Codex turns завершились с 0/22 errors, TTFT p90 18.372 s и throughput 32.107 token/s (`docs/tasks/255/measurements.md`; #255).
- Настроил большой native Codex context на измерении до/после → effective ceiling вырос 258 400→828 400, 19/34 turns превысили старый предел, compact outcomes снизились 4→1; human quality честно оставлена `UNKNOWN` (`docs/tasks/312/measurements.md`; #312).
- Построил cost telemetry по 4 353 turns → оценил marginal tool call в $0.1349 для Claude и $0.1064 для Codex; 69%/72% marginal cost связано с cache read, поэтому optimization target — round-trips (`docs/tasks/345/call-to-dollar.md`; #345).
- Отказался от неподтверждённой замены embedding-модели → на 28 frozen queries GigaEmbeddings дала MRR 0.4726 против 0.4893, а Δ 0.0167 оказался в 6.3 раза меньше собственного noise; production model не менялась (`docs/tasks/364/bench/results.json`; `docs/tasks/364/report.md`; #364).
- Разделил canonical truth и быстрые проекции → Git JSON хранит task/fact/evidence history, SQLite/FTS/vector связаны с exact heads и rebuild-ятся; удалённая task projection восстановила 684 rows за 848.743 ms (`app/ia/task_store.py:308-390`; `app/ia/runtime.py:74-102`; `docs/tasks/408/measurements.md`).
- Спроектировал durable Telegram receipts и batch semantics → 13 frozen acceptance + 298 focused regression tests для per-file delivery; batch path трижды прошёл 12 tests и поймал 3 guard mutations (`docs/tasks/333/report.md`; `docs/tasks/402/report.md`; #333/#402).

## Чего не писать

- Не писать «написал 1.2 млн строк»: 16 203 из 16 578 tracked-файлов — `docs/`; честный объём проекта — 67 694 строки production Python, 88 202 tests и 15 608 frontend (`docs/portfolio/04-stack.md:42-70`).
- Не писать «выполнил 423 задачи»: это число каталогов artifacts. Трекер Orchestra на срезе показывает 145 `done` из 263 records (`docs/portfolio/04-stack.md:72-83`).
- Не писать «2 546 моих ручных коммитов»: 20 commit objects имеют foreign identity `vadimd`, а остальные Git identities не отделяют работу Максима от squash-коммитов model workers (`docs/portfolio/04-stack.md:85-105`).
- Не писать «сэкономил 15–17%»: это параметрическая оценка при гипотетическом сокращении tool calls на 20%, а не проведённый intervention (`docs/tasks/345/call-to-dollar.md`, `Пробелы`).
- Не писать «exactly-once Telegram»: после provider timeout честный контракт — durable `UNKNOWN`, не доказательство доставки или недоставки (`docs/tasks/333/report.md`, `Breaking changes and remaining limits`).
