# V-1242 — откуда берётся usage T3/MultiCode и кто что видит

**DONE · research-only · 2026-11-02.** Учёт здесь имеет несколько независимых источников. Orchestra передаёт задания и identity в T3; CLI/SDK предоставляют usage metadata; upstream T3 документирует чтение сохранённой истории для API-equivalent оценок; подписочные лимиты идут отдельным каналом. **Ни имя каталога, ни локальные `$0` не доказывают расход или приватность.** Корпоративная реализация MultiCode и её фактические ACL в исследование не поступали.

Обозначения: **код** — проверенный путь предоставленного source bundle; **документ** — первичный upstream документ, не проверка установленной версии; **unknown** — недостаточно источников. Точные файлы, SHA-256, ссылки и покрытие — в [source-index.md](source-index.md). Непубличные аккаунты, usage rows, desktop/Hub bundles и результаты V-1239/V-1241 не запрашивались.

## 1. Что Orchestra действительно передаёт и получает

Путь: `HubBackend → MultiCodeClient → HTTP MCP → T3 project/thread/run`; отдельно `HubWorkspace → SSH → рабочие файлы`. Это два транспорта, а не один JSON с кодом проекта.

| Шаг | Исходящие поля / данные | Что используется из ответа | Доказательство |
| --- | --- | --- | --- |
| Подготовка файлов | Выбранные tracked и untracked-not-ignored файлы; owned paths, корневые служебные файлы, ограничения размеров и фильтр секретов; tar передаётся через SSH | Manifest `relative path → SHA-256`, remote workspace | C3: `plan_upload`, `_under`, `write_tar`; C1: `_provision` |
| MCP transport | `initialize`: `protocolVersion`, пустые `capabilities`, `clientInfo{name,version}`; затем `tools/call{name,arguments}`. HTTP авторизация Bearer, отдельный `Mcp-Session-Id` | JSON-RPC id/result/error; `structuredContent` либо JSON/text content | C2: `_post`, `initialize`, `tool_call` |
| Регистрация проекта | `t3_project_create`: `title`, `workspaceRoot=remote_dir` | `id → state.project_id` | C1: 694–702 |
| Выбор runtime | `instanceId`, `model`; при заданном effort — `options` с ключом, найденным в capabilities | `providers[].providerInstanceId`, `models[].id`, `options[].id/type/options` | C1: 305–332 |
| Новый thread | `t3_thread_launch`: `title`, `projectId`, `message`, `runtimeMode`, `modelSelection` | `threadId → state.thread_id`; обязательный `runId` | C1: 761–797 |
| Продолжение | При необходимости `t3_thread_configure{threadId,modelSelection}`; `t3_thread_send{threadId,message,mode}` | Обязательный новый `runId`; рабочий thread сохраняется | C1: 761–783 |
| Наблюдение | `t3_thread_wait{threadId,runId,timeoutMs}`; `t3_thread_read{threadId,view,limit,maxCharsPerItem,afterPosition}` | `status`, `timedOut`; timeline items, `hasMore`, recent runs; ответ выбирается по `runId` | C1: 799–886; C4 |

**Identity не взаимозаменяемы.** `WorkspaceState` сохраняет `ws_id`, `worktree`, `remote_dir`, `project_id`, `thread_id`, manifests и activity cursor (C3: 1155–1204). `HubBackend.session_id` возвращает `ws_id`, не provider account и не T3 thread. Видимый title — `hub-<worker name>` либо fallback; сам код называет его только меткой (C1: 285–286, 732–736). Путь `workspaceRoot` передаётся явно: узнавать его из названия папки серверу не требуется. Прембула задания также может содержать имя работника, родителя, scope, ветку и номер задачи (C1: 78–104).

В проверенных start/create payload нет provider account receipt или поля с фактическим списанием квоты. Однако сервер получает авторизованный запрос и может связывать его со своей identity. **Неизвестно**, как корпоративный сервер выбирает аккаунт пула и связывает OAuth subject, run, workspace и организацию. `instanceId` выбирает адаптер; он сам по себе не устанавливает, чей аккаунт обслужил запрос. MCP transport session также не равна беседе.

`message` содержит текст задания. Для длинного текста `_wire_message` помещает полное сообщение в рабочую копию и отправляет инструкцию прочитать файл (C1: 738–759). Это перенос содержимого, а не гарантия его отсутствия в transcript. Timeline переводится в сообщения, reasoning, команды/вывод, file changes и dynamic tool input/output (C4: 35–112). Чтение ограничивается страницами и длиной item: возвращённое Orchestra не обязательно является полной историей T3.

## 2. Пять слоёв учёта

| Слой | Подтверждено | Чего из этого нельзя заключить |
| --- | --- | --- |
| **T3 run events** | Код Orchestra читает статусы и timeline по thread/run. Доступный metadata contract `t3_thread_read` обещает durable state и пагинированную историю; `t3_project_list` — проекты текущего environment. Это заявленный интерфейс, не выполненные здесь вызовы. | Run completed не означает известный token count, provider receipt или установленный объём подписочного списания. |
| **Claude/Codex CLI/SDK metadata** | Claude native backend читает `ResultMessage.session_id/uuid/usage/total_cost_usd/duration_ms/duration_api_ms`, учитывает assistant usage (C10). Официальный SDK описывает итоговое сообщение с usage/cost [A1](source-index.md#a1). Codex native backend принимает `thread/tokenUsage/updated`, хранит total/last; при завершении считает дельту относительно baseline и цену по таблице (C9). Официальный app-server документирует отдельное usage notification [O1](source-index.md#o1). | Эти native backends не являются путём HubBackend. Поддержка такого события Codex не доказывает, что MultiCode передаёт его Orchestra. SDK cost не равен счёту подписки. |
| **Локальный Orchestra `turn_usage`** | Hub `_turn_end` сам создаёт UUID, нулевой aggregate, `cost_usd=0`, `billing_mode=free`, `cost_unaccounted=False`, `provider_source_records=[]`; context — unknown с прямой причиной «hub does not report token usage to the broker» (C1: 1109–1140). `handle_turn_end` пишет данные с Orchestra `session_id=s.id`, scope/task/runtime/model; DB сохраняет `source_records_json` (C6–C8). | Здесь нет provider receipts для Hub. Ноль — значение адаптера, не измеренный бесплатный расход. Имя DB-функции «provider-identified» не превращает брокерский UUID в provider receipt. |
| **Subscription counters** | Orchestra имеет отдельный клиент сводки relay limits: windows `used_pct/resets_at/window_minutes`, `checked_at`, количество доступных/unknown аккаунтов (C5). Upstream T3 документирует Limits отдельно от истории [T1](source-index.md#t1). | Реальный источник корпоративных counters, свежесть и attribution конкретного хода не проверялись. Сводный процент нельзя автоматически разложить на проекты или пересчитать из API-долларов. Live feed исследует V-1241. |
| **Frontend API-estimate aggregation** | Upstream T3 Usage объединяет историю CLI из подключённых environments и оценивает API-equivalent стоимость; полнота зависит от сохранённой истории. Это прямо описано первичным документом [T1](source-index.md#t1). Orchestra отдельно агрегирует свою `turn_usage` и legacy logs (C12). | Код frontend/backend корпоративного MultiCode отсутствует. Его joins, dedup, тарифы и полный охват — unknown. Orchestra `usage_analytics.py` не является MultiCode frontend. |

Граница доказательства: HubBackend **не переносит** usage/receipts в локальную запись. Из этого не следует, что сервер T3/MultiCode ничего не хранит или никогда не возвращает дополнительные usage-поля: полный фактический ответ здесь не снимался, серверная реализация не исследовалась.

**Ответ на «сканируют код или CLI сами сохраняют usage»: это разные действия.** Код Orchestra сканирует дерево **для передачи файлов** (C3). Native Codex fallback читает `event_msg/token_count` из rollout, а импорт Claude history — `assistant.message.usage` из JSONL, с `cwd` либо именем родительского каталога как project label (C9: 241–358, 2697–2731; C11: 14–72). Это чтение записанных метаданных, не вычисление токенов по количеству файлов/строк кода и не требование к языковой модели вручную вести бухгалтерию.

Upstream T3 документирует историю настроенных аккаунтов, включая disabled; общие history directories считаются один раз. Некоторые вспомогательные генерации отсутствуют, когда CLI не сохраняет историю. Usage и Limits имеют разный охват; Limits также объединяет доступные аккаунты [T1](source-index.md#t1). Следовательно, история может быть шире списка T3 threads и одновременно неполнее провайдерского учёта. Перенос этого вывода на установленный корпоративный fork без версии был бы гипотезой.

В Claude официально различаются локальная долларовая оценка по токенам и авторитетный billing; для подписчика session cost не является его подписочным счётом [A2](source-index.md#a2). Формулы взвешивания корпоративного пула и фактические проценты здесь **не измерены**.

## 3. Privacy: содержимое, роли и границы

«Организация» у provider, доступ к environment T3 и Linux-пользователь — три разные системы прав. Таблица не утверждает, какие роли реально выданы конкретным людям.

| Данные | Что точно попадает в известный путь | Org admin | Обычный teammate | Процесс того же OS user | Право / где проверяется / статус |
| --- | --- | --- | --- | --- | --- |
| **Project names** | T3 получает `title`, `projectId`; title может содержать имя worker | Доступ через корпоративный MultiCode неизвестен; provider admin role сама по себе не доказывает чтение T3 проектов | Членство в компании само по себе такого доступа не доказывает; нужна соответствующая авторизация environment | Может прочитать локально сохранённую metadata при доступе к файлам | C1–C3 — факт передачи. T3 environment sessions/scopes — документ T2; реальные grants — не проверено |
| **Folder names / paths** | `workspaceRoot=remote_dir`; scope может оказаться в prompt; CLI history может хранить `cwd` | Название организации не доказывает доступ к файловой системе | Доступ зависит от environment/file permissions, а не просто от общей подписки | Проверяются search/read permissions, namespaces и дополнительные ограничения | C1, C3, C11 — код; T3 `filesystem:read` — документ T3; Linux DAC — L1. Фактические ACL — unknown |
| **File content** | Выбранные файлы реально загружаются; прочитанное агентом может попасть в model request/tool output | Администратор provider analytics не обязательно имеет host filesystem access; отдельные audit/compliance права требуют проверки | Авторизованный filesystem client либо показанный в shared thread фрагмент может дать доступ | При разрешении OS может читать файлы; project boundary сама по себе не sandbox | C3 — код; T2/T3/T4 — документы. Доступ конкретного коллеги к этой копии не проверен |
| **Chat / transcripts** | Prompt уходит в T3; Orchestra получает timeline/reply. Native adapters знают CLI usage/transcript форматы | Analytics и audit — разные права/поверхности; наличие цифр не доказывает доступ ко всем чатам | Upstream guest link даёт историю одного thread, включая показанные в нём данные; без такого grant общая видимость не доказана | При доступе к локальному transcript/хранилищу может читать его независимо от UI роли | C1/C4/C9/C11 — код; T4 и O3 — документы. MultiCode retention/export/tenant ACL — unknown |
| **Numeric account usage** | Local `turn_usage`; отдельно relay windows; в самих Hub turn records receipts пусты | Provider dashboards предусматривают org analytics для разрешённых ролей; это не вывод из имени каталога | OpenAI Member не является admin, но отдельная analytics роль возможна. Claude доступ зависит от продукта/permission; нельзя обещать «только admins» для API Console | Может прочесть доступные локальные сводки; это не даёт автоматически remote admin role | C5–C8 — код; O2/O4 и A3 — документы. Кто видит корпоративный Usage, поля и точность — не проверено |

Для upstream T3 авторизацию определяют выданные environment sessions/scopes; client label/device metadata не дают прав. Документ указывает серверные проверки RPC scopes и MCP access/runtime ceiling; projects названы организационными границами, не файловыми sandbox [T2](source-index.md#t2). Метаданные инструментов этой сессии описывают чтение проектов/threads **в environment**, но не устанавливают tenant-wide доступ коллег. Не выполнялись ни list/read чужих проектов, ни проверка прав аккаунтов.

OpenAI отделяет workspace roles от локальных разрешений и прав подключённых систем; Analytics Viewer может читать analytics, Member не имеет административных прав [O4](source-index.md#o4). Claude Team/Enterprise analytics доступны Admin/Owner, а API Console проверяет `UsageView`, доступный также некоторым другим ролям [A3](source-index.md#a3). Наличие общей корпоративной подписки не устанавливает ни полную приватность, ни полную открытость всех сессий.

## 4. Штатные privacy/settings — что подтверждено

| Механизм | Первичный источник и граница действия |
| --- | --- |
| Settings на устройстве и сервере | Upstream различает device preferences и server/environment/project settings. Архивирование проекта убирает его из pickers, сохраняя threads, files и settings: это организация интерфейса, не ACL и не прекращение расхода [T5](source-index.md#t5). |
| Guest sharing и permissions | Документированы ограниченный доступ к одному thread и отдельные environment/file permissions [T2–T4](source-index.md#t2). Это основания управлять содержимым, но не свидетельство текущих grants. |
| Product telemetry privacy | Документ T3 отделяет product events от содержимого бесед: перечисляет usage metadata и исключает prompts/responses/file contents из этих событий. Наличие штатного privacy opt-out описано, но он не рассматривается здесь как способ исключить оплаченный расход из корпоративного учёта; ничего не менялось [T6](source-index.md#t6). |
| Exclude local projects | В прочитанных первичных Usage, Project settings, Remote access и Telemetry **не найден подтверждённый механизм project-level privacy exclusion для корпоративного MultiCode**. Это ограниченный отрицательный результат поиска, не доказательство отсутствия функции. Фильтры Usage существуют, но фильтрация представления не доказывает запрет серверного чтения или прекращение provider accounting [T1](source-index.md#t1). |
| Минимум файлов в broker upload | Owned paths и фильтры upload ограничивают передаваемое содержимое (C3). Они не обещают скрыть авторизованные запросы или расход пула. Реальные настройки не менялись. |

Публичная T3 Privacy Policy распространяется на описанные в ней Services, отдельно от выбранных providers/environments. Она не является договором о приватности неизвестного корпоративного fork [T7](source-index.md#t7). По документу нельзя обещать владельцу, что коллеги не увидят проекты или что организация видит всё.

## 5. Допустимые варианты — только предложения

| Вариант | Цена/ограничение | Что проверить перед решением |
| --- | --- | --- |
| Уточнить документированные корпоративные роли и поля Usage | Время владельца политики; платные вызовы не нужны | Версия MultiCode, scope admin/member, спецификация полей/retention и принадлежность пула; без чужих чатов, usage rows и имён |
| Разделить права на содержимое и доступ к числам | Настройка и поддержка ACL; общая квота остаётся учитываемой | Документированный scope read-only/guest, кто вправе давать grants, проверка владельцем на синтетическом материале |
| Отдельная личная учётка/пул в разрешённом личном окружении | Возможна отдельная подписка/инфраструктура; сумма не установлена | Политика работодателя, допустимость личной работы, действительно отдельный billing owner и content boundary. Никаких новых входов, покупок или переключений здесь |

Выгода этих вариантов, экономия токенов, производительность и денежный эффект — **не измерено**: сравнения до/после не проводились. Решение об архитектуре остаётся владельцу. Способов скрыть общий расход, менять identity для attribution, удалять аудит, отключать collectors ради неучтённого использования или обходить auth не разрабатывалось.

## 6. Проверка, риски и предел завершения

- Выполнено: статическое чтение 13 ключевых исходных файлов; прослежены upload/create/start/resume/read/accounting, поля metadata/DB, native usage и документированные upstream границы. SHA-256 этих файлов зафиксированы в source index. Публичные T3 документы закреплены на commit `0847a448fdca5a688720050ca706cbbd37e6347e`; соответствие установленной версии неизвестно. У Orchestra bundle нет `.git`, поэтому его commit SHA не установлен.
- Учтены старые данные/recovery: `WorkspaceState` сохраняет identity при resume; Codex использует cumulative baseline; Claude history importer выполняет upsert по message id и сохраняет ранее импортированное при отсутствии файлов (C3/C9/C11). Проверено чтением кода, не исполнением. Это запрещает считать смену папки или исчезновение файла надёжной границей учёта.
- Риск качества данных зафиксирован здесь: Hub нули и `free/cost_unaccounted=False` выглядят учтённой стоимостью без provider evidence; local UUID не обеспечивает доказанную дедупликацию по T3/provider run. Практическое влияние и воспроизводимость не измерялись; код не исправлялся. Статус завершения run также не доказывает отсутствие затрат при failed/interrupted.
- Не выполнялись app import, pytest, SDK/CLI/account/model probes, обращения к usage/limits API, операции с рабочими БД/сервисами/remote, генерации, новые worker/review, сайт или публикация. Зависимости и uv не понадобились. Smoke/e2e и проверка настоящих ACL не заявляются; для исследования без изменения программы они не запускались.
- Публичный результат ограничен `report.md` и `source-index.md`: без raw выгрузок, абсолютных host/user paths, секретов и чужих полных текстов. Проверка: **13/13 SHA-256 источников — OK**; поиск чувствительных форм (host/user paths, private keys, характерные token/Bearer/URL credentials) — **PASS, совпадений нет**; состав каталога — ровно **2 файла**. Это проверка артефактов, не аудит неизвестного серверного кода. Commit/push не выполнялись; импорт/commit — брокер после завершения хода.

**DONE:** исследование и карта источников готовы. **Unknown:** корпоративный collector/aggregation implementation, реальные права коллег/администраторов, deployed version, фактический account attribution и списания конкретных сессий. Эти неизвестные нельзя заполнять выводом из папок, нулевых долларов или публичной документации другой версии.
