# Рабочее хранение после переключения 08.09.2026

Ноутбук и VPS работают на SQLite schema 1 и приватном Git-владельце задач. На диске обоих узлов main включает `84cfa1ae`; VPS запущен с этим кодом. Локальный процесс восстановлен ранее на `a27f10e2`; последующая поправка затрагивает только утилиту миграции и не требует повторного рестарта.

## Проверено на работающих сервисах

| Проверка | Ноутбук | VPS |
|---|---:|---:|
| Задачи в SQLite и HTTP `/api/tm/tasks` | 1653 | 1653 |
| Сохранённые исходные локальные ID и номера | 896 | 757 |
| `PRAGMA integrity_check` | ok | ok |
| Ошибки внешних ключей | 0 | 0 |
| Префикс новых задач | пустой | V- |
| `/api/sessions` | HTTP 200, 76 сессий | HTTP 200, 57 сессий |

Оба Git-хранилища и приватный hub сошлись на `403067a252e39447fa6a1a84c638033e8fd048e6`. После переключения оба systemd-сервиса active, `NRestarts=0`. Финальная остановка VPS, перенос свежей базы и запуск заняли 51.843 секунды; `cut_names=[]`. На VPS осталась отдельная сетевая ошибка Telegram `ServerDisconnectedError`; она не остановила dashboard и не является ошибкой миграции.

Первая попытка выкладки была ошибочной: новый код перезапустили до переноса schema 0. Он отказал при старте. Ноутбук затем восстановили через свежую миграцию, VPS временно вернули на старую ветку. Окончательная выкладка VPS сначала подготовила Git при работающем сервисе, затем после остановки сделала новый SQLite backup и проверила отсутствие изменения задач. Скрипт оператора предусматривал возврат старого кода и `.env` при отказе переноса или запуска; откат не потребовался.

## Рабочие пути и синхронизация

Пути задаются в `.env` через `ORCHESTRA_DB_PATH` и `ORCHESTRA_TASK_REPOSITORY`:

- Ноутбук: `data/storage-recovery-local-20260908/orchestra.db` и `data/storage-recovery-local-20260908/tasks`.
- VPS: `data/storage-final-vps-20260908/orchestra.db` и `data/storage-preflight-final-20260908/tasks`.
- Приватный hub VPS: `/home/kesha/.local/state/orchestra/task-sync.git`. Публичный origin кода не содержит задачи, базы и журналы.

Обычный обмен выполняется явно, без обязательной сети для локальной работы и без нового фонового демона:

```sh
# Ноутбук, из корня Orchestra
.venv/bin/python -m scripts.sync_tasks --database data/storage-recovery-local-20260908/orchestra.db --repository data/storage-recovery-local-20260908/tasks --origin ''

# VPS, от kesha, из /home/kesha/orchestra
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m scripts.sync_tasks --database data/storage-final-vps-20260908/orchestra.db --repository data/storage-preflight-final-20260908/tasks --origin V
```

Одна задача, изменённая несовместимо на двух узлах, требует разрешения Git-конфликта. Совпадающие имена проектов не объединяются автоматически. Старые источники и снимки оставлены для восстановления; рабочий код их больше не использует. Репетиционные базы никогда не подменяют финальную базу.

## Проверка изменения инструмента переноса

`tests/test_task_migration.py` и `tests/test_git_task_api.py`: **18 passed in 4.89s**, отдельный worktree, MemoryMax=2G, nice=15, без NOTIFY_SOCKET. Импортированный модуль: `/mnt/data/Projects/Python/orchestra-storage/app/task_migration.py`.

Добавлены проверки переноса изменений runtime после подготовки и отказа при изменении исходного Git, подготовленного Git или acceptance-контракта в SQL. Остальные результаты и известные ограничения большого набора сохранены в `plan.md`. Это не заявление о зелёном полном suite.
