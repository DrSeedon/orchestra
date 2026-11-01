# V-1175 — проверка автоматического рестарта

## Результат

Снимок выполнен 2026-10-31 около 21:31 UTC по штатному SSH-маршруту `kesha@localhost`, от имени `kesha`; unit также настроен на `User=kesha`, `Group=kesha`.

- `orchestra` активен (`active/running`), новый `MainPID=3752461` вместо `3648960`; `ExecMainStartTimestamp=2026-10-31 22:30:03 CET`, `InvocationID=f8d05ffd2dfa4bb6addc1cdc1f3b3e7d`.
- `http://127.0.0.1:8888/` вернул `302`.
- `oom_score_adj=800` у PID 3752461.
- systemd: `MemoryHigh=15032385536`, `MemoryMax=17179869184`; его реальный cgroup `/system.slice/orchestra.service` показывает те же значения `memory.high` и `memory.max` (14 GiB / 16 GiB).
- В окружении процесса присутствуют имена `MULTICODE_HUB_BASE_DIR`, `MULTICODE_HUB_MAX_THREADS`, `MULTICODE_HUB_SSH`, `MULTICODE_HUB_SSH_KEY`, `MULTICODE_MCP_BASE`, `MULTICODE_MCP_TOKEN_FILE`; значения не читались и не сохранялись.
- VPS checkout: `main`, `HEAD=0062677b4fc69643e2f09ecc3a8acb86bf838ac0`, чистый. CWD живого процесса — `/home/kesha/orchestra`.

## Восстановление и cut_names

По полному журналу текущего systemd invocation (`192` записей) приложение завершило startup, опубликовало systemd readiness и восстановило `26` фоновых задач (`expired 0`). В журнале есть `Resumed orchestrator` для 10 оркестраторов и `Resumed worker` для 37 воркеров. Записей с systemd priority 0–3 нет. Есть информационные сообщения о `rate_limited` при запросе Anthropic usage; сервис при этом завершил startup.

Сторож сохранил только `AUTO_RESTART_DONE old_pid=3648960 http=200 pending_commit=0062677b4`, не тело JSON ответа `/api/restart`, поэтому исходный массив ответа `cut_names` отдельно не сохранился. Проверил live БД, выбранную из `ORCHESTRA_DB_PATH` окружения PID 3752461: за точное окно запроса, 2026-10-31 21:24–21:27 UTC, нет ни одной `type='system'` записи о прерванном ходе. Это штатный долговечный след каждого элемента `cut_ids`: `app/routes/system.py` записывает такую запись для каждого cut session. Durable audit trail поддерживает вывод `cut_names=[]`; восстанавливать конкретных прерванных агентов не требуется. Текущее перечисление агентов не показывает потерянных cut-сессий.

Ограничение: массив из исходного HTTP JSON недоступен для прямой сверки, вывод `[]` основан на полном per-cut журнале live БД за точное окно вызова, а не на сохранённом теле ответа.

## V-1174 и error-watch cron

Исправление V-1174 присутствует в живом `HEAD=0062677...`; CLI импортирует `/home/kesha/orchestra/app/error_watch.py`. Активная запись фоновой задачи `bg-eafbc9d22e` имеет тип `cron_command`, расписание `7 * * * *`, команду `cd /home/kesha/orchestra && /opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m app.error_watch scan` и pattern `ERROR-WATCH:`.

Для запуска этого CLI отдельный restart сервиса не нужен: `cron_command` — задача `bg_manager` внутри Python-процесса Orchestra; на срабатывании `app/bg_jobs.py` создаёт shell-процесс, который запускает указанную Python-команду из checkout, и импорт проверен тем же runtime из `/home/kesha/orchestra`. После рестарта cron-задача восстановлена и активна. Снимок сделан в 21:31 UTC, поэтому следующий запуск по расписанию — в 22:07 UTC. Отдельного процесса `python -m app.error_watch` в момент снимка не было; фактический CLI запускается только по расписанию. Команды запуска или изменения задачи не выполнялись.

## Доказательства и охват

Сырые receipts сохранены в общем игнорируемом `.orchestra/private/V-1175/raw/`: `vps-snapshot.txt`, `journal-db-raw.txt`, `old-pid-journal.jsonl`, `cut-window.json`, `canonical-cut-and-cron.json`, `cut-audit-final.json`, `live-code-cron.txt`, `error-watch-processes.txt`, `platform-state.json` и соответствующие `.stderr`. Файлы содержат выбранные значения, имена env без значений, журнальные строки/состояния и ограниченные записи SQLite; секреты в отчёт не выводились. Текущая startup journal выборка покрывает ровно InvocationID выше. Перерывов и внешних изменений не выполнялось.
