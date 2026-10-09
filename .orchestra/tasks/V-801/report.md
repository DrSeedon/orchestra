# V-801 — что из InditexTech полезно Orchestra

Срез GitHub API и README: 2026-10-09 UTC. Запрос `GET /orgs/InditexTech/repos?per_page=100&type=public&sort=full_name` вернул 40 публичных репозиториев. Для каждой строки проверен README (у `spring-cloud-stream` — README.adoc); последний коммит получен из `GET /repos/InditexTech/<repo>/commits?per_page=1`, звёзды и SPDX-метка лицензии — из ответа репозитория. Число звёзд и даты подвижны. GitHub `NOASSERTION` означает, что API не определил SPDX-лицензию; `—` означает, что API не показал лицензию. Это GitHub-определение лицензии репозитория; у README нескольких проектов отдельно указан CC-BY, что не заменяет лицензию кода. Описание ниже передаёт проверенное README/назначение исходников, а не текст поста.

Внешние репозитории клонированы в `/tmp/V-801-*` только для чтения. Просмотрены исходники `cerbia`, `kumoss`, `ag-ui`, `mcp-teams-server`, `mcp-server-simulator-ios-idb`, `weavejs`. Ничего из них не запускалось; пакеты не ставились; платных вызовов не было. В Orchestra меняется только этот отчёт.

## Все 40 репозиториев

| Репозиторий | Что делает (README/код) | Лицензия | Последний коммит (UTC) | ⭐ | Агенты / LLM / MCP |
|---|---|---:|---:|---:|:---:|
| [.github](https://github.com/InditexTech/.github) | Публичный профиль организации и workflow проверки CLA | — | 2026-10-08 | 2 | нет |
| [ag-ui](https://github.com/InditexTech/ag-ui) | Форк протокола событий для связи AI-агента с пользовательским интерфейсом; содержит типы событий и SDK | MIT | 2026-05-14 | 0 | да |
| [android-test](https://github.com/InditexTech/android-test) | Форк AndroidX Test и поддержки Bazel для instrumented-тестов Android | Apache-2.0 | 2025-11-03 | 0 | нет |
| [cerbia](https://github.com/InditexTech/cerbia) | Python-набор сканеров и security gates для проверки входов/выходов AI-пайплайнов | Apache-2.0 | 2026-10-06 | 23 | да |
| [CucumberSwift](https://github.com/InditexTech/CucumberSwift) | Swift-реализация Cucumber для BDD-сценариев на iOS, tvOS и macOS | MIT | 2025-05-15 | 1 | нет |
| [devworkspace-operator](https://github.com/InditexTech/devworkspace-operator) | Kubernetes-оператор, управляющий DevWorkspace-ресурсами и рабочими пространствами разработки | Apache-2.0 | 2026-06-03 | 0 | нет |
| [docouture](https://github.com/InditexTech/docouture) | Antora-тема и CLI для создания и запуска сайтов документации | NOASSERTION | 2026-10-01 | 7 | нет |
| [ff4j](https://github.com/InditexTech/ff4j) | Форк FF4J: feature flags, properties и аудит для Java-приложений | Apache-2.0 | 2026-09-29 | 1 | нет |
| [foss](https://github.com/InditexTech/foss) | Манифест и шаблоны Inditex Tech для публикации FOSS-проектов | CC-BY-SA-4.0 | 2026-09-29 | 6 | нет |
| [gh-actions](https://github.com/InditexTech/gh-actions) | Переиспользуемые GitHub Actions для проверяемой публикации Python/npm/Maven-пакетов | — | 2026-09-30 | 3 | нет |
| [gh-sherpa](https://github.com/InditexTech/gh-sherpa) | Расширение GitHub CLI для создания веток и pull request, связанных с задачами GitHub/Jira | Apache-2.0 | 2026-10-05 | 91 | нет |
| [go-ci-testing](https://github.com/InditexTech/go-ci-testing) | Небольшой Go-проект-образец для проверки корпоративного CI-профиля | Apache-2.0 | 2026-10-03 | 2 | нет |
| [grafana](https://github.com/InditexTech/grafana) | Форк платформы Grafana для метрик, логов, трассировок и dashboard | AGPL-3.0 | 2026-06-29 | 0 | нет |
| [hoppscotch](https://github.com/InditexTech/hoppscotch) | Форк Hoppscotch — клиент и рабочее место для разработки и проверки API | MIT | 2026-07-30 | 0 | нет |
| [k8s-overcommit-operator](https://github.com/InditexTech/k8s-overcommit-operator) | Kubernetes-оператор для управления overcommit ресурсов pod-ов | Apache-2.0 | 2026-10-09 | 131 | нет |
| [kafka-go](https://github.com/InditexTech/kafka-go) | Форк Go-клиента Kafka для чтения и записи сообщений | MIT | 2026-06-11 | 0 | нет |
| [karatetools-oss](https://github.com/InditexTech/karatetools-oss) | Java/Maven-инструменты для генерации Karate-тестов и моков из OpenAPI и запуска тестовых наборов | Apache-2.0 | 2026-10-08 | 31 | нет |
| [kumoss](https://github.com/InditexTech/kumoss) | Сервис, который через AI-агентов строит, проверяет на политиках, открывает PR и применяет Terraform-совместимый IaC | Apache-2.0 | 2026-10-09 | 69 | да |
| [maven-enforcer](https://github.com/InditexTech/maven-enforcer) | Форк Maven Enforcer Plugin для правил и проверок Maven-сборки | Apache-2.0 | 2026-09-29 | 1 | нет |
| [mavencentral-ci-testing](https://github.com/InditexTech/mavencentral-ci-testing) | Образец и интеграционные проверки публикации Java-библиотек в Maven Central | Apache-2.0 | 2026-10-05 | 2 | нет |
| [mcp-server-simulator-ios-idb](https://github.com/InditexTech/mcp-server-simulator-ios-idb) | MCP-сервер: переводит текстовые инструкции в действия `idb` для iOS Simulator (UI, приложения, скриншоты, логи и др.) | Apache-2.0 | 2026-10-01 | 328 | да |
| [mcp-teams-server](https://github.com/InditexTech/mcp-teams-server) | MCP-сервер Microsoft Teams: чтение каналов/тредов, публикация и ответы, упоминания участников | Apache-2.0 | 2026-10-02 | 432 | да |
| [micrometer](https://github.com/InditexTech/micrometer) | Форк фасада прикладных метрик Micrometer | Apache-2.0 | 2026-09-09 | 0 | нет |
| [npmjs-ci-testing](https://github.com/InditexTech/npmjs-ci-testing) | Canary-проект для end-to-end проверки корпоративных npm CI, release и publish workflow | Apache-2.0 | 2026-10-05 | 3 | нет |
| [openapi-generator](https://github.com/InditexTech/openapi-generator) | Форк OpenAPI Generator для генерации SDK, серверных заглушек и документации | Apache-2.0 | 2026-10-02 | 1 | нет |
| [provider-ceph](https://github.com/InditexTech/provider-ceph) | Crossplane provider, который управляет S3 bucket-ами в Ceph и других совместимых хранилищах | Apache-2.0 | 2026-09-03 | 5 | нет |
| [pypi-ci-testing](https://github.com/InditexTech/pypi-ci-testing) | Canary-проект для проверки корпоративного Python CI-профиля и публикации | Apache-2.0 | 2026-10-02 | 3 | нет |
| [redkey-operator](https://github.com/InditexTech/redkey-operator) | Kubernetes-оператор для управления Redkey/Redis-кластерами | Apache-2.0 | 2026-10-02 | 20 | нет |
| [redkey-robin](https://github.com/InditexTech/redkey-robin) | Runtime-компонент Redkey: Redis orchestration, health supervision и метрики | Apache-2.0 | 2026-10-02 | 9 | нет |
| [scenes](https://github.com/InditexTech/scenes) | Форк Grafana Scenes для создания интерактивных Grafana-приложений | Apache-2.0 | 2026-06-26 | 0 | нет |
| [scs-outbox](https://github.com/InditexTech/scs-outbox) | Библиотека transactional outbox для Spring Cloud Stream с JDBC/MongoDB | Apache-2.0 | 2026-09-23 | 31 | нет |
| [spring-cloud-stream](https://github.com/InditexTech/spring-cloud-stream) | Форк Spring Cloud Stream: event-driven приложения и биндинги к Kafka/RabbitMQ | Apache-2.0 | 2026-10-01 | 1 | нет |
| [swagger-ui-plugin-diff-highlight](https://github.com/InditexTech/swagger-ui-plugin-diff-highlight) | Плагин Swagger UI, визуально помечающий добавленные/изменённые/удалённые части OpenAPI diff | Apache-2.0 | 2026-10-09 | 12 | нет |
| [weavejs](https://github.com/InditexTech/weavejs) | Headless TypeScript-фреймворк для совместного редактирования Canvas-приложений на базе Konva/Yjs | Apache-2.0 | 2026-10-05 | 230 | нет |
| [weavejs-backend](https://github.com/InditexTech/weavejs-backend) | Пример сервера Weave.js на Express, Yjs и Azure Web PubSub | Apache-2.0 | 2026-10-05 | 11 | нет |
| [weavejs-frontend](https://github.com/InditexTech/weavejs-frontend) | Демонстрационный UI Weave.js на TanStack Start, Shadcn и Tailwind | Apache-2.0 | 2026-10-05 | 13 | нет |
| [xk6-grpcresolver](https://github.com/InditexTech/xk6-grpcresolver) | Расширение k6, которое разрешает gRPC hostname в реплики и отслеживает обновления | AGPL-3.0 | 2026-10-05 | 16 | нет |
| [xk6-jsonparser](https://github.com/InditexTech/xk6-jsonparser) | Расширение k6 для JSON marshal/unmarshal через sonic | AGPL-3.0 | 2026-10-05 | 15 | нет |
| [xk6-sftp](https://github.com/InditexTech/xk6-sftp) | Расширение k6 для SFTP-действий в сценариях нагрузочного тестирования | AGPL-3.0 | 2026-10-05 | 16 | нет |
| [xk6-smb](https://github.com/InditexTech/xk6-smb) | Расширение k6 для SMB-операций в нагрузочных сценариях | AGPL-3.0 | 2026-09-29 | 15 | нет |

## Подробно о проектах, связанных с агентами/LLM/MCP

В этой выборке к теме непосредственно относятся пять репозиториев с пометкой «да» в таблице. Weave.js разобран отдельно, так как он был назван в посте, хотя в его исходниках это общий real-time Canvas-фреймворк, а не агентный/LLM/MCP-инструмент.

### MCP Teams Server — полезная готовая интеграция при наличии Teams-сценария

[`src/mcp_teams_server/__init__.py`](https://github.com/InditexTech/mcp-teams-server/blob/main/src/mcp_teams_server/__init__.py) регистрирует шесть MCP-инструментов: старт треда, отправка сообщения/ответа, чтение треда, листинг тредов, поиск участника по имени и листинг участников (строки 105–215). Реализация в [`teams.py`](https://github.com/InditexTech/mcp-teams-server/blob/main/src/mcp_teams_server/teams.py) использует Microsoft Agents SDK и Microsoft Graph; пагинационные cursors проверяются на ожидаемый `graph.microsoft.com` путь конкретной команды/канала (строки 95–117), а mention сопоставляется с участником канала (около 140–180). Нужны Entra app ID/secret, tenant и team/channel IDs; транспорт по умолчанию stdio, также заявлены streamable HTTP и legacy SSE ([README](https://github.com/InditexTech/mcp-teams-server/blob/main/README.md), разделы Teams configuration/Usage).

У Orchestra уже есть generic MCP stdio lifecycle, регистрация и вызов произвольных MCP tools: [app/harness/mcp.py:172](../../../app/harness/mcp.py#L172), [app/harness/mcp.py:202](../../../app/harness/mcp.py#L202), [app/harness/mcp.py:244](../../../app/harness/mcp.py#L244). Конфиг MCP для сессий формируется в [app/manager.py:329](../../../app/manager.py#L329) и далее. Своего Microsoft Teams bridge в этих точках и в `app/` не найдено; Telegram bridge — другой внешний канал и не заменяет Teams.

**Вердикт: брать только как подключаемый внешний MCP-сервер, если у команды есть реальные рабочие треды в Teams.** Не копировать его код в Orchestra: Apache-2.0 допускает кодовое использование с соблюдением лицензии/NOTICE, но тут MCP-подключение уже является штатным extension point. Оценка на конфигурацию, проверку списка tools и запуск в существующем MCP-контуре: около 0.5–1 инженерного дня плюс настройка Azure/Entra и права Teams у владельца tenant. Это не добавляет безопасного управления публикациями само по себе — модель получает инструменты отправки сообщений; доступ нужно ограничивать нужными каналами и аккаунтом.

### MCP iOS Simulator — инструмент для разработки iOS-продуктов, не платформенной задачи Orchestra

Сервер регистрирует один основной MCP tool `process-instruction` ([`src/mcp/mcp-server.ts`](https://github.com/InditexTech/mcp-server-simulator-ios-idb/blob/main/src/mcp/mcp-server.ts)); строка передаётся в `MCPOrchestrator`, [`NLParser`](https://github.com/InditexTech/mcp-server-simulator-ios-idb/blob/main/src/parser/NLParser.ts) выбирает обработчик из реестра команд и нормализует/проверяет наличие параметров (`src/parser/commands/*`). Реальные действия уходят через [`IDBManager`](https://github.com/InditexTech/mcp-server-simulator-ios-idb/blob/main/src/idb/IDBManager.ts) к `idb`; среди command handlers есть управление симулятором и приложениями, UI/accessibility, capture и debug. Требуются macOS, Xcode Simulator, Node и `idb`/`idb-companion` ([README Requirements](https://github.com/InditexTech/mcp-server-simulator-ios-idb/blob/main/README.md)); это не универсальная симуляция GUI и не Android tool.

Orchestra может запускать внешние MCP tools по конфигурации ([app/harness/mcp.py:179](../../../app/harness/mcp.py#L179)), но в просмотренных runtime/tools нет интеграции с iOS Simulator и ни один описанный компонент платформы не требует iOS. **Вердикт: не брать в ядро.** Если появится проект, где агентам поручена проверка iOS UI, этот MCP можно подключить как отдельный инструмент на выделенной macOS-машине; ориентир 0.5–1 день конфигурации/проверки подключения, не считая подготовки Mac, Xcode и simulator images. Apache-2.0 не требует отказа от использования, но отдельное лицензирование сейчас несущественно: переносить код не нужно.

### Weave.js — интересный real-time canvas, но это новая продуктовая возможность

README и исходники показывают библиотеку для совместно редактируемого Canvas: Konva-объекты и Yjs CRDT-представление синхронизируются между браузерами; `weavejs-backend` и `weavejs-frontend` — именно showcase, не обязательные части ядра. README предупреждает о короткой истории использования в production и незрелости документации для open-source DX. **Агентов, LLM или MCP в механизме нет.**

В Orchestra есть dashboard и текстовые/live chat события, но просмотренный UI/событийный путь (`app/events.py:110–130`, `app/routes/sessions.py:711`) не содержит совместной Canvas-модели; прямого аналога CRDT-доски нет. Это не ускоряет текущие мультиагентные сценарии без отдельного решения строить визуальное совместное рабочее пространство. **Вердикт: не брать сейчас.** Если такой интерфейс будет выбран как новая фича, оценка интеграции библиотеки и backend/frontend/auth/state boundary — ориентировочно 1–3 инженерные недели; это уже отдельный архитектурный проект. Код Apache-2.0, но полный перенос потребовал бы также проверить LICENSE/NOTICE у зависимостей и showcase.

### Cerbia — security pipeline, а не фильтр опасных shell-команд

В исходниках Cerbia — отдельные Python packages `cerbia-core`, CLI и optional adapters. [`Runner`](https://github.com/InditexTech/cerbia/blob/main/packages/cerbia-core/src/cerbia/core/runner.py) загружает entries, последовательно прогоняет preprocessors, затем каждый entry передаёт в gate. [`SecurityGate`](https://github.com/InditexTech/cerbia/blob/main/packages/cerbia-core/src/cerbia/core/security_gate/_gate.py) вызывает конфигурируемые scanners, собирает typed findings, считает weighted score и применяет `fail_fast`/threshold; ошибки scanner по умолчанию закрывают gate. Есть сканеры prompt injection (multilingual regex categories с исключением defensive context, [реализация](https://github.com/InditexTech/cerbia/blob/main/packages/cerbia-core/src/cerbia/core/scanners/prompt_injection/_scanner.py)), PII, secrets, malicious URLs, URL allowlist, invisible text, XSS, canary и keywords, а также отдельные адаптеры Presidio/ProtectAI. [Конфигурация](https://github.com/InditexTech/cerbia/blob/main/packages/cerbia-core/src/cerbia/core/config.py) допускает подключение компонентов по fully qualified import path. Все пакеты в дереве имеют Apache-2.0 лицензии.

**Сравнение с текущей защитой Orchestra:**

- V-773 — узкий исполняемый guard перед Bash в Claude: токенизирует небольшой shell subset и запрещает классы опасных команд (`rm -r`, `find -delete`, опасный `xargs rm`, `shred`, destructive `git clean`, `chmod 777`, `curl | shell`, regex blowup и пр.); смотрит путь `rmdir -p` относительно workspace. Код: [app/backend_claude.py:183](../../../app/backend_claude.py#L183), [app/backend_claude.py:354](../../../app/backend_claude.py#L354), [app/backend_claude.py:524](../../../app/backend_claude.py#L524). Hook подключается при `CLAUDE_BASH_HOOK_ENABLED=1` ([app/backend_claude.py:1083](../../../app/backend_claude.py#L1083)); эта конкретная защита не является универсальным сканером для содержимого prompt или всех runtime.
- Правила `safety.md` — текстовые инструкции модели о запретах, разрешении на разрушительные операции и проверке данных ([.orchestra/pipelines/default/prompts/modules/safety.md:1](../../pipelines/default/prompts/modules/safety.md#L1)); `app/prompting.py:182–213` добавляет выбранные role modules к prompt. Это guidance модели, а не content scanner.
- Есть и структурные проверки доступа: read-only reviewer не может вызвать изменяющий tool ([app/harness/loop.py:371](../../../app/harness/loop.py#L371)); disabled tools валидируются как точные имена [app/tool_scoping.py:7](../../../app/tool_scoping.py#L7). Quota gate регулирует доступ к model lanes, не безопасность входного текста.

Следовательно, Cerbia не является заменой V-773: оно не парсит shell грамматику и не доказывает, что конкретная Bash-команда безопасна. V-773 не находит prompt injection/PII в произвольном сообщении и не сканирует каждый tool result. Применение Cerbia к каждой реплике потенциально добавит regex-based false positives и новый внешний dependency/runtime без локальной оценки на данных Orchestra. **Вердикт: не брать пакет/сканеры как готовый обязательный gate.** Полезная идея — конфигурируемый scanner pipeline с typed findings, явной политикой ошибок и отдельными проверками разных границ (вход модели, внешние tool outputs, исходящий контент). Для решения, нужен ли такой слой, потребуется отдельный узкий пилот с заранее заданными сценариями и ложноположительной частотой; оценка пилота около 1–2 дней, production-встраивание после результата — несколько дней. В рамках текущего исследования изменений не предлагаю.

### Kumoss — агентная система для управления IaC

`README.md` и код описывают полноценный сервис: пользовательская инфраструктурная заявка проходит через сессии, workspace/repository tools, генерацию Terraform-compatible HCL и review на корпоративные политики; затем система создаёт PR, а apply блокируется до ручного разрешения для неподходящих/high-impact изменений. В репозитории разнесены API/core, IaC-сервис, authorization, notifications (включая Slack) и web client. Это вертикальный IaC-продукт с Docker Compose и собственными контрактами, а не библиотека агентов или общий MCP server.

Orchestra управляет созданием сессий/runtime и admission ([app/manager.py:583](../../../app/manager.py#L583)); у неё есть dynamic workflow для агентных задач ([app/mcp_stdio.py:3162](../../../app/mcp_stdio.py#L3162)), но это не управление Terraform-планами или IaC apply. **Вердикт: не брать.** Извлекаемого механизма для заявленной платформенной функции здесь нет; перенос означал бы принятие нового продуктового домена и отдельной архитектуры. Оценка переноса продуктовой части — несколько инженерных недель и отдельная эксплуатационная конфигурация, поэтому в текущем отчёте это не предлагается.

### AG-UI — стандарт событий для агентного UI, но локально уже есть свой event contract

Проверенный форк содержит [AG-UI event types и SDK](https://github.com/InditexTech/ag-ui/blob/main/sdks/python/ag_ui/core/events.py), а не отдельный orchestration runtime. Типы включают начало/фрагменты/конец сообщений и tool calls, lifecycle run/step/error, state snapshot/delta, activity events и interrupts ([схема событий](https://github.com/InditexTech/ag-ui/blob/main/docs/concepts/events.mdx)).

Orchestra уже выдаёт SSE в dashboard ([app/routes/sessions.py:711](../../../app/routes/sessions.py#L711)) и внутренний единый `AgentEvent` с `text`, `tool_use`, `tool_result`, `turn_end`, provider limit и subagent lifecycle ([app/events.py:110](../../../app/events.py#L110)). AG-UI не «добавит SSE», но дал бы совместимый внешний schema contract для другого AG-UI frontend/client. Сейчас такого потребителя в задаче нет, а переход означал бы миграцию внешнего event contract и адаптацию типов. **Вердикт: не брать сейчас; уже есть внутренняя событийная модель и поток, стандарта AG-UI нет.** Если появится конкретный frontend/интеграция, разумная цена — отдельный adapter к текущим событиям (порядка 2–5 дней, зависит от покрытия events); миграция внутреннего contract не оправдана. SDK MIT, но это форк с нулём звёзд и последним коммитом в мае; оценивать upstream/актуальную спецификацию отдельно перед выбором.

## Ответ про Cerbia и фильтры

Cerbia проверяет содержимое на угрозы для LLM и может собирать несколько сканеров в configurable gate. V-773 классифицирует команды, которые агент собирается выполнить через Bash. Это разные границы угроз и разные данные. Промпт безопасности просит агента соблюдать правила, а V-773 способен отказать до исполнения команд в подключённом Claude hook; ни промпт, ни V-773 сами по себе не сканируют пользовательское сообщение на prompt injection. Сейчас у Orchestra не найдено общего сканера prompt/tool-output; найденные hard gates в основном ограничивают инструменты, runtime/quota, пути и операции. Ценность Cerbia возможна только как отдельный эксперимент над входами/выходами модели, не как замена V-773.

## Итоговые вердикты

1. **MCP Teams Server — потенциально брать через существующий MCP extension point**, если Teams станет рабочим каналом. Наиболее прямое использование, минимальный перенос.
2. **MCP iOS Simulator — не брать в платформенное ядро**; подключать как project-local tool только для iOS-разработки.
3. **Weave.js — не брать сейчас**: совместная доска — новая UI-возможность, текущего требующего её процесса нет.
4. **Cerbia — не брать как готовый обязательный guard**; идея раздельного fail-closed scanner pipeline заслуживает отдельного пилота, если появится конкретный prompt/tool-output threat requirement.
5. **Kumoss — не брать**: отдельный продукт управления IaC.
6. **AG-UI — не брать сейчас**: полезен только при требовании совместимости с внешним AG-UI клиентом, при этом локальные события уже есть.

Остальные 34 проекта по README — инфраструктурные библиотеки/операторы, dev tooling, документация, тестовые образцы и CI governance. У них не выявлено прямого агенто-LLM-MCP-механизма для названных компонентов Orchestra. Это классификация по текущей платформе, а не оценка качества проектов.
