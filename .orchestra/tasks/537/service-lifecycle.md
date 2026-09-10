# #537 — остановка процессов вместе с Orchestra

Реализовано в `fix/537-service-lifecycle` от `e8c75e75` (тот же main, который был на VPS при исследовании). Владелец 10.09.2026 разрешил удалить усыновление и упростить жизненный цикл. Деплой, изменение живого юнита и рестарт не выполнялись.

## Поведение

Каждый shutdown останавливает все загруженные сессии. Нет публикации/подбора каналов агентов через FDSTORE, транзакции handover и её rollback, adopted-транспортов, восстановления живого хода по старым каналам, stale-tools refresh для усыновлённого процесса, поиска сирот по сохранённому PID/argv. Удалены соответствующие тесты и старый стенд бесшовного рестарта; проверки HTTP admission, журнала, сокета и guard сохранены.

Codex запускается внутри новой `runtime-<uuid>` cgroup, вложенной в текущую группу супервизора. Маленький launcher входит в неё **до exec**, поэтому Node-обёртка, native writer, MCP и обычные tool-потомки наследуют её даже после setsid. Внешний `systemd-run --user --scope` удалён. Для усыпления сначала завершается принадлежащий процесс, затем при необходимости `cgroup.kill` убирает всю вложенную группу. Код ждёт `populated=0` и завершения launcher до освобождения владельца. Ошибка очистки сохраняет владельца и блокирует замену до успешного повтора.

Если cgroup v2 не делегирована или `cgroup.kill` недоступен, CLI запускается непосредственно в группе супервизора, с предупреждением и запретом hibernate, как прежний неподдерживаемый режим. Он не выносится в другую systemd-группу. В подготовленных юнитах выставлены `Delegate=yes`, `KillMode=control-group`, `SendSIGKILL=yes`, конечный TimeoutStopSec и `FileDescriptorStoreMax=0`.

Продолжение использует сохранённый native thread ID. Уведомление после рестарта прямо говорит об оборванном ходе/локальных командах и требует проверить результат последнего внешнего действия перед повтором. Незаписанный хвост и exactly-once для внешних действий не обещаются. История, рабочие файлы и строки БД не удаляются; старые колонки handover остаются неиспользуемыми без разрушительной миграции. Проверка writer conflict, durable-доставки, обычная смена runtime, socket activation, readiness и restart guard сохранены.

## Проверка

Python: `/mnt/data/Projects/Python/orchestra/.venv/bin/python`; импорт приложения: `/mnt/data/Projects/Python/orchestra-service-lifecycle/app/manager.py`. Все pytest — `python -m pytest`, последовательно под `nice=15`, `MemoryMax=2G`. Для proof-тестов задан отдельный фиктивный INTERNAL_TOKEN; боевые credentials и провайдерские CLI не используются.

- До изменения три новых проверки падали: общий shutdown сохранял backend вместо stop; backend позволял adopt; юнит сохранял процессы и FDSTORE.
- Основной набор: 764 passed, 5 skipped (сборка Python без `os.pidfd_open`; guard проверен подстановкой, сам guard не менялся) — Codex/Grok, Session/Manager, restart/guard/admission, hibernate, writer conflict, фоновые задания, hot apply.
- Дополнительное восстановление/доставки/idle-watch: 84 passed, 1 deselected (live probe).
- Socket activation/CLOEXEC на настоящих дескрипторах и процессах: 2 passed.
- В отдельном делегированном тестовом юните: 5 passed. Обёртка → writer → setsid-потомок, игнорирование TERM, освобождение настоящего flock, немедленная остановка launcher, отказ войти в cgroup без запуска CLI, retry после ошибки очистки. CodexBackend проходит connect/disconnect/connect через настоящие stdio и fixture JSON-RPC сервер с тем же thread ID.
- Два одноразовых юнита `orchestra-test-537-<uuid>.service`: 2 passed. Обычный restart и SIGKILL только супервизору с Restart=on-failure. Старые writer/tool не остаются runnable; новая генерация берёт тот же flock и читает сохранённую fixture-историю. Production-сервис не затрагивается. Это проверка механики ОС, не вызов реального провайдера.
- Дополнительный delivery/heartbeat набор: 21 passed, 3 failed. Все три воспроизведены **на чистом исходном e8c75e75**: `test_t1_http_status_lookup_returns_the_same_committed_resource`, `test_heartbeat_dead_process_recovery_publishes`, `test_heartbeat_zombie_without_backend_publishes`. Они не исправляются в #537.
- Один объединённый прогон завершился RC=137 на ограничении памяти 2 GiB; наборы разделены без повышения лимита. Полный репозиторный suite не запускался.

OS-пробы воспроизводятся:

```sh
systemd-run --user --quiet --wait --pipe \
  -p WorkingDirectory=/mnt/data/Projects/Python/orchestra-service-lifecycle \
  -p Delegate=yes -p MemoryMax=2G -p Nice=15 \
  --setenv=ORCHESTRA_CGROUP_TEST_REQUIRED=1 \
  /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest \
  tests/test_runtime_process_group.py -q --timeout=20

systemd-run --user --scope --quiet -p MemoryMax=2G \
  nice -n 15 /mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest \
  tests/test_service_process_tree_537.py -q --timeout=35
```

## Применение на VPS — отдельно по команде владельца

Код и настройки юнита должны применяться согласованно. Не устанавливать весь шаблон поверх существующих локальных drop-in вслепую. После обновления проверить effective KillMode/Delegate/SendSIGKILL/TimeoutStopUSec/FileDescriptorStoreMax; в первом переходе учесть старое FDSTORE и процессы уже вне service cgroup. Новые настройки не переносят такие процессы назад. Их область и принадлежность проверяются заново до любых сигналов.

Сохранить cut_names, после разрешённого рестарта проверить старые PID/cgroups, готовность HTTP/TG, продолжение прежних диалогов, доставки и hibernate/wake. До этого нельзя объявлять дефект исправленным в работающем VPS. Локальные фоновые команды внутри группы сервиса теперь прерываются при рестарте; отдельные удалённые действия и намеренно вынесенные пользователем процессы не получают обещания exactly-once или остановки.

Источники контракта ОС: [systemd.kill](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.kill.xml), [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).
