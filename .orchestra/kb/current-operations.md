# Работающий сервис: запуск, миграция, владельцы состояния

## Orchestra не отвечает: startup failed / schema version

`systemctl show orchestra.service -p ActiveState -p SubState -p MainPID -p NRestarts` и
журнал сервиса отличают живой процесс от цикла рестартов. Открытый socket :8888 сам по себе
не означает работоспособность HTTP. Проверяй `/` и `/api/sessions` с ограничением времени.
Рестарт/остановка/запуск — только по полномочиям из [AGENTS.md](../../AGENTS.md).

`database schema needs offline migration` означает несовместимость схемы, а не временную
ошибку. Повторный рестарт её не исправит. Сначала свежий SQLite backup() после остановки
писателей, затем штатный перенос в отдельную пару DB/Git, сверка данных и переключение
конфигурации. Старые источники остаются для отката; репетиционная база не заменяет свежую.
[Перенос](../../app/task_migration.py), [последовательность и проверка 08.09](https://github.com/DrSeedon/orchestra/blob/9a1735f1695519a445f393802c2154bd37337e38/.orchestra/tasks/idle-watch/result.md).

## Где проверять текущее значение

- Пути рабочей базы и task Git: `ORCHESTRA_DB_PATH`, `ORCHESTRA_TASK_REPOSITORY` в окружении
  конкретного сервиса. Не предполагай, что используется файл `data/orchestra.db`.
- Модели и effort: [pipeline.yaml](../pipelines/default/pipeline.yaml), [models.py](../../app/models.py).
  Подписочный допуск: [quota_gate.py](../../app/quota_gate.py).
- Роль, промпт и память: [agent-control.md](agent-control.md).
- Задачи и обмен ноут/VPS: [tasks-and-projects.md](tasks-and-projects.md).
- Proxy, SSH и полномочия: [repo-ops.md](repo-ops.md). Исторический IP/процент/номер процесса
  не является текущей настройкой.

## Исторические исследования

[Прежние записи с исходными якорями и доказательствами](https://github.com/DrSeedon/orchestra/blob/9a1735f1695519a445f393802c2154bd37337e38/.orchestra/archive/knowledge-20260909/kb/current-operations.md).
Это материал для проверки гипотез, не текущие инструкции.
