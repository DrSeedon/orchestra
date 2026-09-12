# V-555 — динамические воркфлоу

Удалены реализация старого инструмента, его приватные валидаторы и launch-failure helper,
MCP-регистрация, специальные карточки/preview/CSS, запреты в pipeline и указание в full-cycle.
Низкоуровневый open_fan и механизм барьеров сохранены: ими пользуются существующие
сессии; они не были реализацией удалённого инструмента. Тест дедлайна перенесён без
изменения проверяемого поведения в tests/test_fan_deadline.py.

Новый dynamic-workflows.md подключён к orchestrator, sub-orchestrator, full-cycle.
Он даёт пример Python, запуск через серверный background job, модельный маршрут,
место результатов, проверку partial, восстановление и границы одноразовых вызовов.
Сессионный worker остаётся для диалога и управляемого мержа. Общие соседние правила
не переписывались.

В wf_run исправлены два обнаруженных препятствия: неявные verify/escalate теперь
выбирают Luna; CLI принимает --repo и сохраняет его в resume. Ранее вызов установленного
runner из другого проекта создавал writable-worktree в Orchestra, независимо от проекта
workflow. Использован уже существующий workspace_repo интерфейс, новый движок не добавлен.

Исходный research удалён из checkout при исторической консолидации; просмотрен через
`git show ba5e3823:.orchestra/tasks/dynwf/research.md`. Он подтверждает решение от 01.09:
вариант A — внешний runner через background job, а не движок в сервере. Исполняемого
freeze-флага нет. Frozen acceptance tests в tests/test_wf_run.py не изменялись.
Старый 20-ticket pilot не запускался: нынешний согласованный живой критерий — два агента.

## Живое доказательство

Серверная задача bg-119a4c2d46, workflow: live_workflow.py, stdout: live-1.log,
manifest: live-manifest.json, журнал: live-journal.jsonl (копии исходных файлов без правок).
Реальные subscription Codex CLI, `--ephemeral --ignore-rules --ignore-user-config`, Luna.
Два dispatched идут до первого attempt_finished; оба завершились успешно с первой попытки.
Ответы: 173×29 = 5017; 211×37 = 7807. complete=true, dispatched_calls=2.
Общее время по записанным интервалам: 6.790386 с; перекрытие agent()-вызовов: 5.377952 с.
Каждый вызов получил 15 925 байт выбранных четырёх модулей, без полного сессионного префикса.
API-equivalent суммарно 0.00538368 USD; это не счёт и не замер подписочной квоты.

Проба намеренно арифметическая: tools=read, network=false, mcp=false с явным reason.
Она доказывает параллельный ephemeral CLI и сбор результата, но не живую запись файлов,
MCP-вызовы или автоматический мерж. Реальные изолированные git worktrees с параллельными
записями проверяет тест CLI с подставным provider adapter; provider CLI там не запускается.

## Проверки и ограничения

Первый набор: 80 passed, 1 failed. Единственная ошибка — существующий тест ссылался на
удалённый .orchestra/tasks/532/live_probe.py. Стенд извлечён из 5f8894ec в
tests/fixtures/mcp/tool_scoping_probe.py, переведён на новый каталог инструментов.
Он запускает настоящие stdio MCP-процессы, HTTP обслуживает локальная фикстура.

Удалён тест буквальной фразы отчётного промпта; проверка списков модулей переписана
на сверку с каноническим YAML. Удалена проверка количества Markdown-пунктов; проверки
доставки модулей сохранены. Новые тесты защищают недоступность удалённого MCP handler,
доставку workflow-модуля, маршрут по умолчанию и выбор целевого репозитория при запуске
и возобновлении. Без этих проверок агент мог бы снова читать недействующее руководство,
запускать запрещённую модель или писать в другой проект.

systemd user bus в окружении отсутствует, sudo запрещён no_new_privs. Вместо MemoryMax
использован ulimit -v 2097152 (лимит виртуальной памяти процесса, не общий cgroup-лимит),
nice=15; наборы запускаются последовательно. Полный pytest не запускался.

Внешнее модельное ревью не запрашивалось: по codex-debate оно необязательно; основной
риск проверяется реальным CLI-прогоном, stdio стендом и контрактными тестами.
Python-изменения требуют рестарта владельцем; Orchestra и сервисы не перезапускались.

Повтор stdio: 13 passed (tests-scoping.log). Абсолютный импорт записан в import-path.txt.

Read-only SELECT из turn_usage подтвердил обе успешные строки учёта с task_id=V-555
(live-usage.json). На каждый CLI: input_tokens=19428, output_tokens=42,
cache_read_tokens=6912. Это фактический input данного прогона, не оценка по размеру
модуля; сравнительный baseline с сессионными воркерами в этой задаче не измерялся.

Frozen workflow набор: `uv run --frozen python -m pytest tests/test_wf_run.py -q` —
40 passed (tests-workflow.log). Первичный routing набор включает новые контрактные
тесты, default pipeline, tool scoping и deadline (точные пути в tests-routing.log
и воспроизводимой команде ниже):
`uv run --frozen python -m pytest tests/test_dynamic_workflows.py tests/test_tool_scoping.py tests/test_fan_deadline.py tests/test_default_pipeline.py -q`.
После исправления исторической фикстуры повторялся только изменённый scoping-набор.

Пять мутаций против тестов, закоммиченных в aed16be2: восстановление регистрации —
1 failed; отключение модуля — 3 failed; старый verify/escalate — 2 failed/1 passed;
потеря --repo на CLI — 1 failed; потеря --repo при resume — 1 failed. Скрипт
mutation_check.py восстанавливает файл в finally; полный вывод в mutations.log.
После восстановления `uv run --frozen python -m pytest tests/test_mcp_stdio.py tests/test_dynamic_workflows.py -q`
дал 127 passed (tests-mcp.log). `node --check app/static/js/chat.js` и `git diff --check` успешны.

Поиск по всему трекаемому репозиторию (search.txt): ноль активных упоминаний старого
инструмента. Остались 66 исторических строк в 16 сырых файлах .orchestra/tasks/515/raw
и доказательства этой задачи; исходные raw согласованно сохранены без переписывания.
Также выполнен rg --hidden по checkout с исключением .git и двух каталогов доказательств:
активных совпадений нет. Данные V-555 проверены app.secret_mask.mask_secrets перед коммитом.

Дополнительная живая проба со штатными tools/network/MCP (live_default_workflow.py)
первоначально остановилась до provider dispatch: --repo получил linked worktree,
а app.workspace.validate_repo_root принимает только primary Git root. Ошибка записана
в live-default.log; это ограничение явно внесено в модуль. Повтор успешно завершён с
--repo /home/kesha/orchestra. Рабочую ветку агента движок создаёт сам; родительский
репозиторий не редактируется. Новую поддержку linked-worktree roots не добавлял.

Штатная живая проба bg-f4ef247de0: 2/2 completed, complete=true, оба dispatch до первого
завершения, tools=all/network=true/mcp=true. Создание и уборка двух реальных worktrees
успешны, архивы результатов существуют, дочерних worktrees после завершения нет.
Общее время 10.809194 с; перекрытие agent()-вызовов 9.598777 с. Ответы снова 5017 и 7807.
API-equivalent 0.004114 USD. Доказательства: live-default-2.log, default-manifest.json,
default-journal.jsonl, default-usage.json. Эта проба не требовала от моделей реального
MCP-вызова или изменения файла; она проверяет запуск со штатными возможностями.
