# V-1056 — quota gate / граница исполнения

Дата: 2026-10-23. Ветка результата платформы: `task-V-1056/fix-quota-gate-guard`.

## Статус: частичный результат, архитектурная развилка открыта

**Произвольный Python/CLI с доступом к нашим provider credentials не изолирован от
расходующего их runtime. Обход monkeypatch не закрыт этой правкой.** Добавление ещё
одного вызова `get_worker_admission()` в тот же интерпретатор, wrapper CLI, проверка
переменной окружения или запрос readiness из управляемого вызывающим кода не создают
обязательную границу. По условию задачи архитектуру изоляции здесь не строил.

Исправлено именование отказа: `QuotaGateError` для наших подписок и hub, а также
MCP-отказ Codex review теперь прямо называют `worker_quota_admission`. То же имя
попадает в `error.details.rule`. Сохранены `weekly_quota_blocked`, HTTP 429,
`retryable=false`, фактические числа/причины, hub-подсказки и политика пропуска `unknown`.
Это имя существующего правила допуска, а не новое ограничение модели.

Серверный `change_model` уже после успешного изменения вызывает
`quota_queue.release_waiting()`. Подмена этой логики не понадобилась. Добавлены
четыре pytest-регрессии: initial/direct × разрешённый hub/запрещённый Haiku; в
запрещённом случае проверяется сохранение ожидания и последующее восстановление той
же доставки без дубля. В тестах используются настоящие функции quota/hub decisions,
подменяются телеметрия, смена runtime и конечная отправка провайдеру. Сам код очереди
не был предоставлен в копию, а pytest здесь недоступен: полноценная проверка этой
матрицы ещё нужна на стороне оркестратора.

## Граница достоверности инвентаризации

В этой private copy есть только `scripts/wf_run.py`, `app/{quota_gate,hub_pool,
manager,session,mcp_stdio}.py`, часть routes и тесты. Здесь нет `.git`,
`scripts/wf_adapters.py`, `app/backend_{claude,codex,hub,harness}.py`,
`app/runtime_registry.py`, `app/harness/`, `app/claude_api_credits.py`,
`app/{quota_queue,initial_deliveries,message_deliveries,bg_jobs}.py`,
`app/models.py`, pipeline/prompts и полного перечня scripts. Отсутствующие файлы
не искал вне предоставленного каталога и не восстанавливал по догадке.

Таблица охватывает **все обнаруженные в предоставленном срезе семейства путей**.
Для отсутствующих реализаций есть ссылки из кода/тестов, но это не доказательство
полноты инвентаризации всей репозитории и не утверждение об их текущем содержимом.

## Инвентаризация путей

| Путь / источник | Где принимается решение сейчас | Можно ли вызывающему обойти его локальной подменой | Результат / ограничение |
|---|---|---|---|
| Создание воркера через сервер: `SessionManager._create_session_locked`, `app/manager.py` | При `planned_initial_turn` до task/session/worktree вызывается центральный admission; серверная роль оркестратора исключена по политике. Для hub отдельно `require_hub_capacity` | Подмена модуля в отдельном клиентском процессе сама по себе не меняет серверный модуль. Импорт manager в произвольный credential-bearing Python — другой, открытый путь ниже | Существующий серверный guard сохранён; имеющиеся тесты `test_quota_admission_e2e.py`. Новая обязательная граница не добавлялась |
| Direct/initial API delivery → manager → `AgentSession.preflight_delivery_admission` / `send`, `app/session.py` | Сервер читает свой admission; после await проверяет текущую модель, stop generation и срок решения под lifecycle lock. `send` проверяет заново перед началом нового хода | Клиентская подмена не меняет серверную функцию. Это не защищает прямой импорт session/backend в другом процессе | Существующая граница сохранена. WAITING_QUOTA является удержанием принятой доставки, а не потерей сообщения |
| Pending messages → `AgentSession._flush_pending`, `app/session.py` | Сервер повторяет admission для текущей модели, учитывает stop/model/expiry | Как выше, пока исполнение остаётся в сервере | Сохранено; не добавлял расходующий квоту повтор отправки |
| Hub workers → `get_worker_admission` → `hub_pool.hub_admission` / `require_hub_capacity`, `app/hub_pool.py` | Серверный снимок usable accounts по всему provider pool; неизвестная доступность предупреждает и пропускает по существующей политике | Прямой импорт hub/backend с собственным доступом к relay — открытый путь; сама низкоуровневая реализация backend не предоставлена | Admission и политика hub не менялись. Тесты отказа усилены проверкой имени правила |
| `change_worker_model` MCP → `POST /api/sessions/{name}/change-model`, `app/routes/sessions.py` | После успешного `changed=true` сервер запускает `quota_queue.release_waiting`; решение о доставке принимает очередь по модели из текущего состояния. Hub-target проверяется также в `AgentSession._change_model_locked` | Сама смена модели — разрешённое управление, а не разрешение нового хода на закрытом пуле | По доступному коду поведение уже корректно; добавлена матрица initial/direct, hub/Haiku, recovery. Исполнение pytest ещё требуется |
| `dynamic_workflow` MCP → сгенерированный bg `run` → `scripts/wf_run.py:WorkflowEngine.agent` → `_run_attempt` → `run_adapter` | В subscription-ветке readiness запрашивается из вызывающего Python; checker инъецируется конструктором. `_run_attempt` вызывает `self.adapter`; независимого запуска через сервер здесь нет | **Да**: вызывающий контролирует checker/adapter и может обратиться к адаптеру напрямую. `ORCHESTRA_URL` также контролируется его окружением | **Открытая архитектурная развилка**. Offline probe исполнил настоящий body `_run_attempt` с fake sink без admission. Никаких реальных вызовов |
| Workflow `billing='api_credit'`, тот же `WorkflowEngine.agent` | Явно отдельная разрешённая ветка: Claude-only; `credit_status().available`; subscription readiness намеренно пропускается | Локальные `credit_status`, billing, adapter подменяемы. Проверка остатка кредита не доказывает разрешение цели вызова | **Открытая развилка** для прямого запуска с ключом. Разрешённые explicit credit workflows сохранены, автоматический fallback на кредиты не добавлен |
| `scripts/wf_adapters.run_codex`, `run_claude`, `run_adapter`, `_run_process` | Исходник не предоставлен. Имена/сигнатуры и запуск CLI подтверждаются `tests/test_wf_run.py`; тесты credit-ветки проверяют mapping ключа в окружение Claude CLI | Нельзя заявить независимую границу по тестам; если это Python, запускающий credential-bearing CLI, добавление проверки только туда всё равно обходится напрямую | **Открытая развилка**; нужен полный source review на стороне оркестратора |
| Произвольный импорт `AgentSession._make_backend`, `_ensure_backend`, `runtime_registry.build_backend`; прямые `ClaudeBackend` / `CodexBackend` / SDK / native CLI | Session guard существует в нормальном server flow, но не является OS-ограничением на создание своего backend. Backend/registry/SDK transport исходники здесь отсутствуют | **Да при доступных credentials/credential directory/provider socket**: можно не вызывать Session.send вообще. Fresh Python с тем же UID не устраняет этот доступ | **Открытая развилка**, требуется разделение доверия и credentials; не строил |
| `codex_review` MCP → `_quota_refusal` → arbitrary shell command в `/api/bg/jobs`, `app/mcp_stdio.py` | Readiness серверный, но решение остановиться принято внутри MCP-процесса. `app/routes/bg.py:bg_job_create` проверяет receipt/proof/task/budget/artifact и payload replay, но не квотный допуск и не строит canonical provider argv | **Да**: `_quota_refusal`/shell command контролируются вызывающим; generic bg endpoint принимает команды и без review receipt | **Открытая развилка**. Исправлено только именование существующего MCP-отказа. Дополнительный server preflight без связывания runtime/команды и изоляции credentials не закрыл бы всё семейство |
| `bg_create` → bg `run`, `command`, `cron_command`, `ssh`; host-shell / subprocess из инструмента агента | Generic command runner не имеет обязательной typed модели/цели; cgroup ограничивает ресурсы, не provider credentials | **Да**, если в этой среде команда видит нашу авторизацию. Парсер shell-команды не может доказать отсутствие динамического Python, вложенного CLI или сетевого вызова | **Открытая развилка**. Не вводил блокировку произвольных shell-команд и не ломал сборки/проверки |
| `/api/bg/workflow-scheduler/acquire`, `app/routes/bg.py` | Только resource slot: request_id/run_id/label, cgroup и scheduling. Модель/биллинг не представлены | Slot не является разрешением вызова модели; его добавление/пропуск вызывающим не даёт изоляцию | Не выдавать за quota enforcement. Сохранено |
| `HarnessBackend` / `app.harness.llm.OpenRouterClient`; arbitrary import harness / probe scripts | Реализаций нет. `test_harness_production.py` фиксирует exact `:free`/`PAID_HARNESS_ROUTES`, отсутствие Anthropic fallback, отдельную авторизацию OpenRouter | In-process policy можно подменить при доступном API key; это не путь Claude/Codex subscriptions. Полный source inventory отсутствует | Отдельная внешняя авторизация и существующий allowlist сохранены; новые платные маршруты/вызовы не добавлены |
| Native SDK subagents / agentic compact audit / auxiliary evals | `session.py` строит backend и отдельные compact turns; `routes/subagent.py` читает telemetry/transcripts, не запускает модель. Низкоуровневые SDK hooks/eval scripts не предоставлены | Нельзя подтвердить отдельный server guard для всех SDK/eval вызовов без отсутствующего кода. Доступ к credentials остаётся общей развилкой | Требует продолжения инвентаризации; не вводил blanket gate на каждый CLI connect |
| Compaction: `_compaction_permit`, summary/audit/ack и native Codex compact, `app/session.py` | **Явное исключение V-640 в текущем коде**: quota gate не применяется к сжатию; есть lifecycle/stop/model checks и реальные provider limits | Исключение нельзя распространять на произвольный вызов из скрипта; его scope должен принадлежать broker | Легитимный путь сохранён. Автоматический глобальный CLI gate без purpose policy нарушил бы действующее решение |
| `routes/system.py:_fetch_codex_usage`, quota observation, hub relay limits | CLI app-server используется для `account/rateLimits/read`, а не для model completion; hub curl читает лимиты | Не считать каждый `create_subprocess_exec` расходом модели | Telemetry сохранена без quota gate, иначе получение самого решения можно заблокировать этим решением |

## Почему локальная дополнительная проверка не решает задачу

В представленном запуске сервер, worker tool subprocess и провайдерный CLI не
образуют подтверждённую границу прав. Произвольный код может не импортировать
`app.quota_gate`, импортировать адаптер отдельно, передать свой checker, вызвать
SDK/CLI напрямую либо отправить generic bg command. Он может подменить также
HTTP-клиент или адрес readiness. Наличие серверного `/api/usage/readiness` не
означает, что сервер владеет реальным provider launch.

Поэтому тест «ещё раз вызвали admission перед Popen» в одном Python не доказывает
требуемую неподменяемость. Положительный тест monkeypatch → отказ независимого
runtime сейчас нельзя честно предъявить для этих открытых путей. Изменений,
которые только создавали бы видимость такой защиты, не делал.

## Архитектурные варианты и цена

Предварительные оценки инженерного времени, а не обещание или API-счёт; после
полного source inventory и проверки текущих UID/credentials могут измениться.
Никакие из вариантов не реализованы, сервисы/credentials не менялись.

| Вариант | Что потребуется | Цена / предел |
|---|---|---|
| Fresh runtime с обязательным запросом серверу, из защищённой установки | Runtime не загружается из worker checkout; сервер связывает worker/task/model/purpose с решением, runtime отказывает при невозможности проверить решение | Ориентир 2–4 дня на ограниченный workflow path и тесты/recovery. Это закрывает только подконтрольный entrypoint: при доступе агента к raw CLI/credentials общий обход остаётся. Сам по себе не удовлетворяет всей задаче |
| Credential-owning broker и изоляция worker tools (предпочтительный для полной гарантии) | Отдельный UID/защищённая установка/credential directories; агентам недоступны ключи, подписочные credentials и authenticated provider sockets. Все provider launches исполняет broker; tools агента исполняются в среде без этой авторизации. Сервер владеет actor/task/model/purpose, включая owner-approved credits и разрешённые eval/compact exceptions; arbitrary bg commands не получают provider credentials | Ориентир 1–3 инженерные недели на Claude+Codex+workflow/harness, миграцию и adversarial/recovery/concurrency tests. Самая дорогая часть — SDK/CLI tools, обычно исполняемые тем же пользователем, что и credential-bearing runtime. Предусмотреть долгоживущий broker без контейнера на каждый ход |
| Считать локальный shell доверенным и оставить прямой CLI владельцу | Явно согласовать границу: сервер гарантирует свои API, произвольный код с credentials вне неё | Небольшая доработка документации, но **исходное требование о механическом запрете не выполнено**. Не принимать этот вариант молча |

Для полной приёмки broker дополнительно потребуются тесты с отсутствующей/просроченной
авторизацией, повтором/replay, конкурентной сменой модели, истечением решения,
рестартом очереди и остановкой, а также отрицательная попытка прямого CLI из worker
среды. Denial должен назвать существующее правило; утверждение о недоступности
credentials должно подтверждаться OS-тестом, а не prompt/ENV-флагом.

## Что проверено здесь

Попытка обязательного запуска:

```sh
uv run --frozen python -m pytest tests/test_quota_gate.py tests/test_hub_pool.py tests/test_mcp_quota_gate.py tests/test_quota_wait_queue.py -q
```

Код выхода 127. `/usr/local/lib/claude-hub/shims/uv` ответил:
`uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
В `/usr/bin/python3` (3.12.3) отсутствуют pytest, httpx, fastapi и dotenv; полноценные
app imports дополнительно невозможны из-за selective copy. Зависимости не ставил,
запуск на другую машину не переадресовывал.

Разрешённый task-specific fallback:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .orchestra/tasks/V-1056/offline_checks.py
```

**5 smoke checks прошли** (`offline-checks.log`). Скрипт извлекает AST production
definitions и исполняет их с явно заданными dependency fakes: отказ подписки/hub,
имя правила/формат, разрешающие состояния, MCP отказ, порядок re-evaluation после
смены модели и отсутствие вызова release после отказа/unchanged. Отдельный fake-sink
probe подтверждает открытый workflow dispatch, а не его защиту. Реальные model/API,
CLI, сеть и SQLite не вызываются. Это **не required pytest**, не проверка сборки
модулей и не проверка настоящей durable queue.

Три in-memory мутации каждого исходного определения выполнены без изменения
production-файлов:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .orchestra/tasks/V-1056/offline_checks.py mutate-rule
PYTHONDONTWRITEBYTECODE=1 python3 .orchestra/tasks/V-1056/offline_checks.py mutate-admission
PYTHONDONTWRITEBYTECODE=1 python3 .orchestra/tasks/V-1056/offline_checks.py mutate-release
```

Каждая завершилась кодом 1 с ожидаемыми assertion failures: неверное имя правила,
no-op `require_worker_admission`, удалённый вызов `release_waiting` соответственно.
Логи `mutation-{rule,admission,release}.log`. Это мутации **smoke checks**; мутационный
прогон новых pytest queue cases пока не выполнен.

Импортированный здесь `app` — namespace package: `app.__file__ is None`,
`app.__path__ = ['<hub-copy>/app']`.
Полноценный импорт `app.quota_gate` не выдаётся за состоявшийся; smoke использует
исходные определения из этого абсолютного каталога, не копию установленного app.

## Обязательные команды оркестратору в полном checkout

Выполнить последовательно с установленными проектными ограничениями ресурсов:

```sh
uv run --frozen python -c 'import app; from app import quota_gate; print(app.__file__); print(quota_gate.__file__)'
uv run --frozen python -m pytest tests/test_quota_gate.py tests/test_hub_pool.py tests/test_mcp_quota_gate.py tests/test_quota_wait_queue.py tests/test_quota_admission_e2e.py tests/test_change_model_unloaded.py -q
uv run --frozen python -m pytest tests/test_wf_run.py tests/test_dynamic_workflows.py tests/test_work_review_jobs.py -q
uv run --frozen python scripts/check_instruction_contract.py
uv run --frozen python scripts/run_tests.py
```

Перед утверждением широкой приёмки: повторить matrix tests с намеренно удалённым
server `release_waiting`, затем с принудительным разрешением `_admission_allows`
в запрещённом Haiku-плече и с принудительным отказом hub-плеча — все соответствующие
регрессии обязаны краснеть. Здесь эти pytest-прогоны не исполнены.

## Остаток / безопасность артефактов

Новые обязательные provider boundaries не внедрены; полная инвентаризация и
изоляция arbitrary credential-bearing execution открыты. Имя правила исправлено,
а корректный существующий путь смены модели зафиксирован тестами, ожидающими
полного прогона. CHANGELOG прямо помечает результат частичным.

Никакого git commit/push/clone, установки зависимостей, обращения к credentials,
реального provider call, развёртывания или рестарта не выполнял. Root instructions
не менялись. Артефакты содержат только синтетические данные/ошибки тестов и пути
этой копии, без выгрузок рабочих логов/секретов. Публикационный scanner отсутствует
в срезе; его проверку должен выполнить штатный merge/publish gate оркестратора.
Syntax/AST и отсутствие trailing whitespace проверены для всех семи изменённых
Python-файлов. Spot check артефактов на формы private key, provider/GitHub/AWS keys
находок не дал; это не замена штатному scanner. `.git` отсутствует, поэтому вместо
`git diff` просмотрены изменённые участки файлов. Результат — `verification.txt`.
