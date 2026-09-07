# #532 — отключение Orchestra tools по роли и воркеру

Реализация начата на main `7e9ad9dd7e0160c7385c84a3122a6ad9cde55924`; затем включён main `25570312` со снятием особого статуса search_memory. Автор по live metadata сессии `ad8dc5ea-4fb8-4d9e-9260-fa5666d4ed76`: `gpt-6-astra`, Codex runtime.

## Контракт и выбор границы

Роль: `.orchestra/pipelines/<name>/pipeline.yaml`, `roles.<role>.disabled_tools: [run_fan]`. В default запрет задан у orchestrator и sub-orchestrator; full-cycle его не имеет.

Воркер: `spawn_worker(..., disabled_tools=["get_worker_info"])`, HTTP `POST /api/sessions` с тем же полем. Поле сохраняется в `sessions.disabled_tools` как JSON-массив, показывается в session API, переносится через hydrate/resume и пересборку MCP identity. Старые строки получают `[]` миграцией. Граница создания выбрана, чтобы политика существовала до первого подключения агента и переживала рестарт; отдельного изменяющего тула и гонки с уже начатым вызовом нет. Ограничение роли и воркера объединяются, worker не может отменить role ban. Неизвестные синтаксически корректные имена разрешены как предварительная настройка; пробелы, имена с точками/дефисами и некорректные структуры не являются шаблонами. Следует указывать короткое точное имя, например `run_fan`.

MCP каталог остаётся неизменным. Агент видит инструмент и получает при попытке вызова `isError=true`, код `tool_disabled`, имя тула/воркера/роли и понятную причину. Проверка стоит перед вызовом handler и проверкой его аргументов. Поэтому даже кешированная клиентская схема не обходит запрет. Это scoped tool availability, не защита от агента, исполняющего произвольный shell/HTTP в обход MCP. Сами обработчики инструментов, квоты, модели и runtime permission callbacks не менялись.

Политика фиксируется в env свежего MCP процесса. Hot-update не предоставляется: изменение pipeline требует перезагрузки backend-конфигурации (обычно рестарт Orchestra), действующий MCP процесс сам YAML не перечитывает. Расширение схемы spawn_worker новым параметром требует штатного обновления MCP схем у существующего клиента Codex; переключение disabled_tools не меняет сам каталог и не требует удаления кешированных инструментов. После мержа Python требует отдельного рестарта по команде владельца. Мержа и рестарта исполнитель не делал.

## Проверка и границы доказательства

AC: deny и allow на обоих уровнях, role run_fan matrix, сохранение worker-политики, понятный MCP error без side effects, однородный механизм без исключений. `search_memory` используется как обычный пример в тесте диспетчера, без проверки обязательного наличия в default.

`tests/test_tool_scoping.py`: реальный MCP protocol handler для матрицы ролей с детерминированным handler-sentinel; worker deny/allow; union; malformed-policy; SQLite persistence/old rows; spawn argument forwarding; fresh stdio stand. `tests/test_manager.py::test_worker_disabled_tools_survive_create_and_identity_refresh`: путь создания сессии, БД, refresh_identity.

Живая команда: `PYTHONPATH=. .venv/bin/python .orchestra/tasks/532/live_probe.py`. Артефакт `live-probe.log`: пять отдельных реальных stdio MCP процессов, конфигурация от AgentSession и production `_make_mcp_config`; локальный HTTP-сервер на случайном порту вместо production API. Worker deny: `isError=true`, 0 HTTP calls. Worker allow: `isError=false`, 1 HTTP call. Оба orchestrator role отвергают `run_fan` до проверки обязательных аргументов. Каталог во всех пяти процессах: 48. CLI/LLM-turn не запускался: stand проверяет настоящий транспорт MCP и результат диспетчеризации, не послушание модели.

Абсолютный импорт: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-tool-scoping/app/mcp_stdio.py`.

Первый focused run после исправления имени DB helper: `.venv/bin/python -m pytest tests/test_tool_scoping.py -q` → `11 passed in 6.07s` (`tests.log`). Позже добавлены spawn/stdio checks; финальный результат ниже.

Для широкой регрессии `systemd-run --user --scope -p MemoryMax=2G` не запустил тесты: `Failed to connect to bus: No medium found`. Повтор запущен с `nice -n 15`, ограничение виртуальной памяти `ulimit -v 2097152` вместо недоступного MemoryMax; тесты последовательные.

## Pre-mortem

Потеря поля при восстановлении или смене identity → запрет исчезает: поле проведено через обе реконструкции сессии и все четыре места сборки MCP. Старый процесс → старая политика: жизненный цикл описан явно. Синтаксически ошибочный JSON в БД/env → ошибка загрузки, а не тихое снятие запрета. Ошибка в имени корректного синтаксиса → не совпадёт ни с одним вызовом; оператор обязан использовать точное имя из каталога. Отказ не опирается на Claude can_use_tool, поэтому одинаково исполняется внутри сервера для любого MCP-клиента.

## Review decision

Поверхность высокого риска: MCP admission/dispatch, pipeline schema, session persistence, spawn API. Consumers: manager → runtime MCP env → mcp_stdio; SQLite save/hydrate/resume; Claude/Codex/прочие клиенты общего stdio. Независимого frozen oracle на всю новую фичу до реализации нет. По прямому заданию — ровно один Luna pass (`mode=implementation`, `model=gpt5.6luna`); Sol не авторизован. Квитанцию подписывает автор после проверки результата.


## Итог проверок перед review

Широкий прогон `.venv/bin/python -m pytest tests/test_tool_scoping.py tests/test_manager.py tests/test_mcp_stdio.py tests/test_pipeline.py tests/test_default_pipeline.py tests/test_mcp_config_isolation.py -q` дал `2 failed, 514 passed in 134.28s`: оба падения в старом TestBehaviourRulesLandedAtOwners требовали уже удалённую владельцем дословную фразу про веер. Согласно действующему правилу code-quality весь обнаруженный набор из 24 фиксированных фразовых проверок удалён (55 строк). Проверки сборки/изоляции модулей сохранены. Это единственное расширение файлов помимо самой фичи.

После удаления фразовых проверок и добавления новых MCP checks: `.venv/bin/python -m pytest tests/test_tool_scoping.py tests/test_default_pipeline.py -q` → `72 passed in 21.50s` (`final-focused.log`). Дополнительно тест миграции существующей БД со старой схемой: `.venv/bin/python -m pytest tests/test_tool_scoping.py::test_existing_database_migrates_worker_policy -q` → `1 passed in 6.41s` (`migration.log`). Успешные неизменённые manager/MCP/pipeline/config tests из широкого прогона повторно не запускались.

Мутации по закоммиченному `test_role_dispatch_both_arms`: `.venv/bin/python .orchestra/tasks/532/mutation_probe.py` временно снимает deny и запрещает всё; обе команды дают rc=1. После снятия deny краснеют обе запрещённые роли; при deny-everything краснеет full-cycle allow. Исходник восстанавливается в finally; сырой результат — `mutations.log`.

Memory: none — нового переиспользуемого личного знания, кроме контракта фичи, нет; контракт сохранён в KB agent-tools. Рестарт production по-прежнему необходим после мержа и не выполнялся.

Перед review также включён свежий main `4b4ac862` (исправление парсера review-verdict, файлы фичи не затронуты).

## Review result

Один авторский вызов `codex_review(mode="implementation", model="gpt5.6luna")` успел стартовать до срезанного рестартом хода; повторного заказа не было. Серверная квитанция `review-receipt:59771bab-d6e6-4ff3-894f-2655a4aa1ff5`: reviewer `gpt-5.6-luna`, status `completed`, verdict `Approve with the suggestion above.`. Reviewer процитировал строку `DISABLED_TOOLS = parse_disabled_tools(os.environ.get("ORCHESTRA_DISABLED_TOOLS", "[]"))`; цитата сверена с `app/mcp_stdio.py:51`. Дополнительно reviewer сообщил полный focused run → `73 passed in 19.20s` и успешный stdio stand. Фраза reviewer «Luna ... unavailable in the tool set» противоречит metadata и не используется как свидетельство доступности; реальную модель pass устанавливает серверная квитанция.

Blocking: 0. Suggestion: 1, восстановить удалённые ownership wording tests — отклонено: это набор фиксированных фраз, прямо запрещённый действующим code-quality; две проверки уже падали от легитимной правки владельца. Механические tests сборки и доставки модулей остаются. Вердикт принят, suggestion не принят; нового раунда нет.

`git diff main...HEAD --check` отмечает только пробелы/пустую строку в `mutations.log`: сохранён дословный pytest output красного контроля. Код и остальные артефакты без whitespace-ошибок. Проверка всех task artifacts через `app.secret_mask.mask_secrets` не нашла секретоподобных строк.

Квитанция подписана самим автором через `record_review_outcome(..., outcome="accepted")`; ответ сервера: `author_outcome=accepted`, `outcome_source=direct`. После возобновления включён текущий main `067679f3` (без конфликтов); затронутые им session/routes автоматически объединены, фича в diff относительно main не изменилась по смыслу. Проверка совместимости: `.venv/bin/python -m pytest tests/test_tool_scoping.py tests/test_default_pipeline.py tests/test_manager.py::test_worker_disabled_tools_survive_create_and_identity_refresh -q` → `74 passed in 18.22s`, `post-main.log`.

## Остаточный блокер допуска merge

После включения свежего main read-only `app.review_coverage.coverage_decision` против production receipt DB вернул `status=blocked`, `reason=review_receipt_missing`, target `067679f36e23f2496335beed07374a700b51d0f0`, worker `73dec600926b28dd71dd0dfe8954d6783d846bd7`. Подписанная квитанция покрывает target `4b4ac862` / worker `e8fa814e`; последующие изменения main в `app/session.py` и `app/routes/sessions.py` изменили конечные blob hashes, и gate не связывает старую квитанцию с новым снимком. Это не новый дефект фичи: интеграционные 74 tests зелёные. Ровно один pass выполнен, второй запрещён исходным заданием; фиктивная аттестация по несуществующим findings не выписывалась. Решение о дальнейшем покрытии запрошено у постановщика, gate не изменялся.

Второй Luna pass явно разрешён постановщиком после блокировки: первый снимок протух от интеграции чужого main (#515), не от findings или переделки фичи. Повтор ограничен собственным диффом #532; чужие изменения session/routes повторно не ревьюируются. Старое ограничение «ровно один» снято для этого случая.

## Round 2

Разрешённый второй Luna pass завершён: `ACK — no blocking, suggestion, or question findings.` Квитанция `review-receipt:1a6dbd25-a5db-434d-ba84-a86deae85869`, status completed, reviewer gpt-5.6-luna. Проверенная цитата из собственного кода: `details={"tool": name, "worker": WORKER_NAME, "role": ROLE},` находится в `app/mcp_stdio.py:234`. Reviewer проверял только дифф фичи против main 067679f3; чужие изменения #515 не ревьюировал повторно. Его focused command `...python -m pytest tests/test_tool_scoping.py tests/test_manager.py::test_worker_disabled_tools_survive_create_and_identity_refresh -q` → `15 passed in 17.43s`. Автор подписал квитанцию через `record_review_outcome(outcome="accepted")`. Blocking 0, suggestions 0, questions 0. Предыдущий блокер покрытия закрывается этой квитанцией; новых изменений production-кода после второго pass нет.

Финальная read-only проверка `coverage_decision` для main `067679f3` и HEAD `622b712d` вернула `status=satisfied`, `coverage_outcome=reviewed`, `author_outcome=accepted`, receipt `review-receipt:1a6dbd25-a5db-434d-ba84-a86deae85869`. Merge-блокер снят. Рабочее дерево чистое; merge и production restart остаются у постановщика/владельца.
