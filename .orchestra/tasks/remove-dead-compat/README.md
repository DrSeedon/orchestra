# Удаление мёртвой совместимости

База: `715f0fc9`. Ветка: `codex/remove-dead-compat`. Удаление кода одобрено владельцем; данные, история, сервисы и удалённые репозитории не изменялись.

## Удалено

- Недостижимый `_change_runtime_with_packet_locked` и его частная цепочка: staging target/profile, ingress canary, capability verification, fallback/retirement. В рабочем Python не было вызывающего для корня; дочерние методы вызывались только внутри этой цепочки. Смена runtime уже использует `_change_runtime_chat_locked`.
- Неиспользуемые экспериментальные `stage_preflighted_handoff`, `classify_handoff_failure`, `decide_runtime_handoff_recovery` и три обслуживающих dataclass. Продукционный `recover_runtime_handoff` — другой, реально вызываемый путь, он сохранён.
- Больше не нужный `validated_handoff` в runtime capabilities и недостижимая live-canary проба. Инвентарь live-проб обновлён явно; рабочая проба нативного импорта остаётся.
- Четыре невостребованные операции `rule_propose/approve/retire/list` и создание таблицы improvement_rules для новых БД. Рабочих вызовов этих функций не найдено в app/scripts. Существующие таблицы не удаляются и не переписываются: отдельный regression test проверяет сохранность старой записи при двух init_db.
- Прямые тесты и вспомогательные функции удалённого механизма. Тест отказа по незавершённому эффекту перенесён на существующий путь native resume без in-place retarget; тесты обычной смены runtime и восстановления сохранены.

## Что используется и поэтому осталось

Read-only census текущих привязанных открытых назначений: ноутбук — 6 schema-2 и 1 schema-3; VPS — 28 schema-2 и 3 schema-3 (срез VPS 2026-09-08T04:43:54Z). Это назначения, не утверждение о том, что все их процессы выполняют ход сейчас. Старый review gate нужен для прежних назначений. `review-legacy-v1.md`, receipts и условия их приёмки не удалялись.

Нативное продолжение внутри runtime, импорт сохранившейся истории и восстановление долговечных handoff имеют рабочие вызывающие. Нулевой счётчик незавершённых handoff в одном срезе не делает поддерживаемый путь восстановления мёртвым. В local/VPS journal handoff сейчас только failed (2/5), improvement_rules — 0/0; эти данные не очищались.

## Проверка и размер

`compat-tests.txt`: **859 passed, 1 deselected, 2 warnings**, 62.50 s. Проверялись session/manager, адаптеры Claude/Codex/Grok, runtime registry/history, handoff recovery, effect classification, DB, merge test gate и writer-conflict. Две warnings — существующее предупреждение Starlette о cookies в тестовом клиенте. Live-проба исключена штатным фильтром; настоящие вызовы моделей не выполнялись. Это профильный набор, не все тесты репозитория.

Интерпретатор `/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest`; импорт app из `/mnt/data/Projects/Python/orchestra-remove-dead-compat/app/`. Прогоны последовательно через systemd scope MemoryMax=2G и nice=15. Проверены отсутствие ссылок на удалённые символы в app/scripts/tests и `git diff --check`.

`size.json`: Python в app/ **81 109 → 80 043 строк, −1 066** (физические строки с комментариями и пустыми). `session.py`: 5 348 → 4 430; `runtime_history.py`: 1 372 → 1 294; `runtime_registry.py`: 389 → 382; `db.py`: 4 202 → 4 139. Размеры не доказывают ускорение: производительность в этой задаче не измерялась.

Не выполнялись merge, push, выкладка или рестарт. Для включения Python-изменений после принятия потребуется разрешённый владельцем рестарт. Исторические отчёты не редактировались для сокрытия прежнего поведения.
