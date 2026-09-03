# #470 — Archestra.AI: маркетинг против кода

**Дата:** 03.09.2026. **Фаза:** 1 (ресёрч). Прод-код не тронут.

## Question (Step 0)

- **Контекст:** `archestra-ai/archestra` — чужая опенсорсная «Enterprise AI Platform», лендинг
  `https://archestra.ai` обещает девять механизмов.
- **Проверяемое утверждение:** каждый пункт лендинга существует в репозитории как код.
- **Базис сравнения:** отсутствие реализации (заявка без кода) — то, что мы уже ловили в #345,
  где 11 из 11 названных артефактов не существовали ни в одном коммите.
- **Измеримый исход:** для каждого пункта — `путь:строка` в репозитории на зафиксированном
  коммите, либо доказанное отсутствие (греп по всему дереву даёт ноль).

## Что именно проверялось (снимок предмета)

Репозиторий склонирован **blobless** (`git clone --filter=blob:none`) в
`/mnt/data/tmp/archestra-470/archestra` — вне рабочего дерева Orchestra, чужой код в наш
репозиторий не копировался и не устанавливался. `docker run` с монтированием `docker.sock` не
запускался ни разу; всё ниже получено чтением исходников и read-only вызовами GitHub/Docker Hub API.

- HEAD на момент проверки: `c0f30875ee0e2b935fb5bb511e9edcc1e45dd412` (Thu Sep 3 16:30:20 2026 +0000,
  `ci: trigger website deploys via workflow_dispatch instead of Vercel deploy hook (#7651)`).
- Отслеживаемых файлов: **7 544** (`git ls-files | wc -l`).
- Все пути ниже — **относительно чужого репозитория**, не нашего. Наш префикс для проверки:
  `/mnt/data/tmp/archestra-470/archestra/`.

Дословный текст лендинга сохранён в `landing.txt` того же каталога (получен `curl` + снятие тегов,
не пересказом `WebFetch` — по правилу «дословная формулировка тянется из сырого исходника»).

## Зрелость проекта (одни и те же числа для всех строк таблицы)

| величина | значение | источник |
|---|---|---|
| первый коммит | `66f0cc2d` — 2025-07-15 13:56:54 +0100, Matvey Kuk, «License» | `git log --reverse` |
| второй коммит | 2025-07-16, Joey Orlando, «basic tauri app» — проект начинался как десктоп на Tauri | `git log --reverse` |
| коммитов всего | 5 960 | `git rev-list --count HEAD` |
| коммитов за 30 дней | 495 | `git log --since=2026-08-04 --oneline \| wc -l` |
| уникальных авторских e-mail | 89 | `git log --format='%ae' \| sort -u \| wc -l` |
| контрибьюторов по GitHub API | 80 | `gh api repos/.../contributors?anon=1 --paginate` |
| звёзд / форков | 4 243 / 1 189 | `gh api repos/archestra-ai/archestra` |
| релизов (тегов) | 320; последний `platform-v1.3.48` 2026-09-03 | `gh api .../releases --paginate` |
| частота релизов | 35 релизов `platform-*` за август 2026 ≈ **один в день** | тот же вывод |
| открытых issues | **24** (не 44: `open_issues_count` в API считает вместе с PR) | `search/issues q=…is:issue+is:open` |
| issues всего / PR всего | 839 / 6 747 | `search/issues` |
| образ | `archestra/platform:latest` существует, manifest HTTP 200, теги от `0.0.2` до текущих | Docker Hub registry API, read-only |

## Лицензия (одна на все строки таблицы)

- **Router:** `LICENSE.md:1-24` — «This repository is dual-licensed… first matching rule wins».
  Default — `AGPL-3.0-only` (`LICENSE_AGPL`); Enterprise — `LicenseRef-Archestra-Enterprise`
  (`LICENSE_ENTERPRISE`).
- **Как помечается Enterprise:** (1) SPDX-заголовок первой строкой файла; (2) регион
  `SPDX-SnippetBegin … SPDX-SnippetEnd` внутри AGPL-файла; (3) имя `*.ee.{ts,tsx,…}` или каталог `ee/`.
- **Замер по дереву:** файлов, где встречается `LicenseRef-Archestra-Enterprise` — **212**; из них
  целиком Enterprise (SPDX первой строкой) — **136**; файлов с врезками — **76**, самих врезок —
  **381**; файлов по конвенции `*.ee.*` — **94**; каталогов `ee/` — **0**.
- **Важно для ячейки «есть ли закрытые enterprise-куски»:** закрытых нет — весь Enterprise-код
  **лежит в репозитории** и читается (`platform/backend/src/secrets-manager/vault.ee.ts` 321 строка,
  `platform/backend/src/auth/idp.ee.ts` 517, `platform/backend/src/k8s/mcp-server-runtime/hibernation.ee.ts` 826).
  Ограничена не доступность, а **право использования в проде**.
- **Small Team Clause** (`LICENSE_ENTERPRISE:26-32`): прод без платной лицензии разрешён, пока
  пользователей во всей компании **меньше 30**; «user» там определён широко — любой, кто
  provisioned/invited/able to access (`:31-32`).
- **Рантайм-гейт:** `platform/backend/src/enterprise-tier.ts:7` — `SMALL_TEAM_THRESHOLD = 30`;
  `:57-63` — `isCoreActive() = config.enterpriseFeatures.core || isSmallTeam()`, то же для
  `isKnowledgeBaseActive()`. Лицензия — это **переменная окружения**, не подписанный ключ.

## Таблица: механизм → реализация

Столбцы «лицензия» и «зрелость» вынесены в разделы выше — они одинаковы для всех строк; в таблице
остаётся только то, что по строкам различается, плюс лицензионная пометка Enterprise/AGPL.

### 01 · Agentic Chat
- **Дословно:** «People sign in with **SSO** — Entra ID, Okta, any OIDC provider. Every tool call
  runs under that person's own identity. No shared service accounts.»
- **Реализован:** **частично.**
  - SSO есть: плагин `@better-auth/sso` подключается в `platform/backend/src/auth/better-auth.ts:275`
    (`...(ssoConfig ? [sso(ssoConfig)] : [])`), конфиг приходит из `auth/idp.ee.ts:19` (`export const ssoConfig`).
  - Идентичность на вызов тула: режим разрешения кредов — enum
    `platform/backend/src/types/enterprise-managed-credentials.ts:6-10`: `static | dynamic | enterprise_managed`,
    колонка `credential_resolution_mode` в `database/schemas/agent-tool.ts:23`.
  - **«No shared service accounts» опровергается их же документацией и схемой:** режим `static`
    и есть общий аккаунт, а `docs/pages/platform-mcp-gateway.md:161` говорит дословно
    «on behalf of the user by default, or **one shared account** when the server is configured that way».
- **Где принуждается:** код (middleware Fastify + модель кредов), не промпт.
- **Зависимости:** Postgres; внешний OIDC/SAML IdP; для OBO — Entra.
- **Лицензия:** **Enterprise.** `auth/idp.ee.ts:1` — SPDX Enterprise; сверх того рантайм-гейт
  `platform/backend/src/middleware.ts:44-50` отдаёт **403 «SSO is an enterprise feature»**, пока
  `enterpriseTier.isCoreActive()` ложно. Бесплатно — только под Small Team (<30 пользователей).

### 02 · Apps & Skills
- **Дословно:** «A **skill** is a folder with instructions and scripts. Same format Claude Code and
  Codex use… **Apps** render real UI inside the conversation… Making one team- or org-wide is a
  reviewed promotion step.»
- **Реализован:** **да** для формата скилла и рантайма приложений; «reviewed promotion» — да,
  как sharing/marketplace-поток.
  - Формат: `platform/backend/src/skills/parser.ts:42` — `SKILL_MANIFEST_FILENAME = "SKILL.md"`;
    `:9-18` — фронтматтер `name`, `description`, `allowed-tools` (тот же контракт, что у Claude Code);
    `:58` — «SKILL.md must start with a YAML frontmatter block».
  - Импорт из GitHub: `platform/backend/src/skills/github-import.ts`; маркетплейс — `skills/marketplace/`.
  - Apps: Rust-крейт `platform/archestra-rs/app-runtime-core/` (1 748 строк, `app_html.rs`,
    `envelope.rs`, `app_html_lint.rs`), TS-обвязка `backend/src/services/apps/app-runtime-native.ts`.
  - Миграция из Claude Code: отдельный каталог `migration-kit/` — но это **сам по себе агентский
    скилл** (`migration-kit/README.md:11`: «It ships as a Skill (`migrate-to-archestra`) for your
    favorite coding agent… the model owns the judgment calls»), то есть перенос принуждается
    **промптом**, а не детерминированным конвертером.
- **Где принуждается:** код (парсер, рантайм) + **промпт** для миграции.
- **Зависимости:** Postgres; для исполнения кода в скиллах — sandbox-рантайм (см. 04).
- **Лицензия:** AGPL.

### 03 · Projects
- **Дословно:** «Sharing follows the platform's **permission model**, re-checked on every file operation.»
- **Реализован:** **да, дословно.**
  `platform/backend/src/skills-sandbox/project-file-scope.ts:19-23` — комментарий владельца:
  «The caller's project access is re-checked here on EVERY use, not only at chat creation… **Fails
  CLOSED**»; функция `resolveProjectFileScope` (`:24`) вызывается каждым тулом, трогающим файлы.
- **Где принуждается:** код (запрос к `ProjectShareModel` на каждой файловой операции).
- **Зависимости:** Postgres; объектное хранилище (`skills-sandbox/object-store.ts`).
- **Лицензия:** AGPL.

### 04 · Agent Runtime
- **Дословно:** «Agents run server-side, in **sandboxed containers** with their own filesystem…
  A run starts from a schedule, **an email**, or **a webhook**… **Per-user execution and cost limits**.»
- **Реализован:** **да.**
  - Песочница: Rust `platform/archestra-rs/sandbox-core/` (4 093 строки), единственный бэкенд —
    **Dagger** (`src/backends/dagger.rs`, 1 845 строк).
  - K8s-манифесты раннера: `platform/backend/src/k8s/runner-runtime/manifests.ts:248` (ресурсные
    лимиты), `:257` (`securityContext: { allowPrivilegeEscalation: false }`), сетевые политики —
    `k8s/runner-runtime/network-policy.ts`.
  - Триггеры: `routes/incoming-email.ts`, `routes/schedule-trigger.ts`, вебхуки/A2A — `routes/a2a/`,
    расписания — `services/scheduled-run-conversation.ts`.
  - Лимиты: `models/limit.ts` (проверка по сущностям `user`/`team`/`agent`/`virtual key`,
    `:911-1015`), дефолты на среду — `models/environment-default-user-limit.ts`.
- **Где принуждается:** код.
- **Зависимости:** **Kubernetes обязателен.** `platform/backend/src/config.ts:1941-1944` —
  `isCodeRuntimeEnabled` требует либо явный `runnerHost`, либо `k8sConfigured` (kubeconfig или
  in-cluster). Квикстарт это не отменяет, а прячет: в образ **вкомпилирован KinD**
  (`platform/Dockerfile:7` `ARG KIND_VERSION=v0.31.0`, `:34` сборка из исходников
  `kubernetes-sigs/kind`) плюс Dagger Engine (`:160`, `:577`), поэтому команда с лендинга монтирует
  `/var/run/docker.sock`. Плюс Postgres (в квикстарте — внутри контейнера, `docker/supervisord/postgres.conf:3`).
- **Лицензия:** AGPL для ядра; спящий режим MCP-подов и prepull образов — Enterprise
  (`k8s/mcp-server-runtime/hibernation.ee.ts:499`, `image-prepuller.ee.ts:1308`, оба через `isCoreActive()`).

### 05 · MCP Orchestrator
- **Дословно:** «**MCP servers** run as containers **in your own Kubernetes**… Anyone can submit a
  server; security reviews and approves it. Promotion from dev to staging to production is a human
  gate. Each **environment** has its own credentials and network egress policy.»
- **Реализован:** **частично.**
  - K8s-рантайм MCP-серверов: каталог `platform/backend/src/k8s/mcp-server-runtime/`
    (deployment, hibernation, image-prepuller, `network-policy.ts:14` —
    имя политики `mcp-egress-<deployment>`).
  - Среды: `models/environment.ts:14-28` — поля `namespace`, `networkPolicy`, `restricted`,
    `validationRegex`, `trustedImageRegistries`. Это ровно «свои креды и egress-политика на среду».
  - **Одобрение существует, но оно уже не «security review», а гейт доверенного реестра образов:**
    `routes/internal-mcp-catalog.ts:1540` («=== Image approval (trusted-image-registry gate) ==='),
    `:1543` `GET /api/internal_mcp_catalog/pending-image-approval`, `:1565` `POST …/:id/approve`,
    `:1349-1364` — правка каталога на недоверенный образ **удерживает** установку до одобрения
    администратора вместо авто-переустановки.
  - **Конвейера «dev → staging → prod» как объекта в коде я не нашёл:** среды — плоский список строк
    в одной таблице без отношения «следующая среда» и без операции promote. Греп `promote|promotion`
    по `models routes services` даёт совпадения только в несвязанных местах (agent, knowledge-file,
    connection-setup). Промоушен — это административное действие человека в UI, а не машина состояний.
- **Где принуждается:** код (K8s + гейт реестра образов); последовательность сред — организационная.
- **Зависимости:** Kubernetes, Postgres, реестр образов.
- **Лицензия:** AGPL; гибернация/prepull — Enterprise.

### 06 · RAG с ACL источника
- **Дословно:** «Documents are indexed together with their ACLs. A query returns only what that user
  could already open in the source system. Embeddings sit in **pgvector**, in your own Postgres.»
- **Реализован:** **да, с оговоркой по лицензии.**
  - pgvector: `platform/backend/src/database/schemas/kb-chunk.ts:21` — колонка `vector(${dimensions})`,
    рядом `:77` `tsvector("search_vector")` (гибрид «вектор + лексика», как у нас).
  - ACL-токены: `knowledge-base/acl-tokens.ts` — `user_email:<email>`, `buildGroupToken` →
    `group:<connectorType>_<groupId>` (`:28-33`), `buildContainerToken` → `container:<connectorId>:<key>`;
    токены сравниваются **как строки, никогда не парсятся** (`:41-42`), и обе стороны обязаны
    нормализовать e-mail одинаково (`:15-21`).
  - Синхронизация ACL из источника: `knowledge-base/source-access-control.ts`.
- **Где принуждается:** код (SQL-фильтр по токенам на запросе).
- **Зависимости:** Postgres с pgvector; коннекторы к Confluence/Jira/дискам; провайдер эмбеддингов.
- **Лицензия:** **Enterprise + бета-флаг.** `acl-tokens.ts:1` — SPDX Enterprise;
  `source-access-control.ts:133-147` — `isAutoSyncPermissionsActive() = config.kb.autoSyncPermissionsEnabled
  && enterpriseTier.isKnowledgeBaseActive()`, а `:171` возвращает 403
  «Auto-sync-permissions connectors require an enterprise license». Строка `:130-131`:
  фича прямо названа бетой (`ARCHESTRA_KNOWLEDGE_BASE_AUTO_SYNC_PERMISSIONS_ENABLED`).

### 07 · LLM & MCP Proxies
- **Дословно:** «One **OpenAI-compatible endpoint**… Users get virtual keys; real provider keys never
  leave the vault… The **MCP gateway** handles… dynamic client registration, on-behalf-of token
  exchange. Tools load on demand: a 70-tool Jira server costs ~600 context tokens, not ~60,000.»
- **Реализован:** **да**, кроме числа (разбор — ниже, отдельным разделом).
  - Прокси: `routes/proxy/llm-proxy-handler.ts` (~2 200+ строк), адаптеры под провайдеров в
    `routes/proxy/adapters/`.
  - Виртуальные ключи: `models/virtual-api-key.ts`, маршруты `routes/virtual-api-key/`,
    заголовок `routes/proxy/utils/headers/virtual-key.ts`.
  - Vault: `secrets-manager/vault.ee.ts`, `vault-client.ee.ts`, `readonly-vault.ee.ts` — **Enterprise**.
    Дефолт для AGPL-сборки — секреты в Postgres (`secrets-manager/db.ts`), то есть формулировка
    «real provider keys never leave the vault» верна только на платной ветке.
  - DCR: `routes/oauth-server.ts`, `routes/oauth.ts`. OBO: `services/identity-providers/enterprise-managed/
    exchange-strategies/entra-obo-strategy.ts:49` — `requested_token_use: "on_behalf_of"`, плюс
    RFC 8693 (`exchange-strategies/rfc8693-token-exchange`); файл помечен SPDX Enterprise первой строкой.
- **Где принуждается:** код (прокси + gateway).
- **Зависимости:** Postgres; для vault — HashiCorp Vault (`dev/docker-compose.vault.ee.yml`).
- **Лицензия:** ядро AGPL, vault и enterprise-managed OAuth — Enterprise.

### 08 · Security & Guardrails («tainted conversation»)
См. отдельный разбор ниже. Кратко: **реализован, принуждается кодом на прокси и на MCP-gateway**,
но «список тулов-эксфильтраторов» устроен не так, как читается с лендинга.

### 09 · Observability & Cost Tracking
- **Дословно:** «Every request is traced… Every trace is attributed to a person, a team, and an
  agent. Traces **export over OpenTelemetry**… **Budgets and per-user limits**.»
- **Реализован:** **да.**
  - OTel настоящий, не «поддержка на словах»: `platform/backend/package.json:100-110` — `@opentelemetry/sdk-node`,
    `exporter-trace-otlp-http`, `exporter-logs-otlp-http`, `auto-instrumentations-node`, `semantic-conventions`.
  - Атрибуция: `observability/tracing/mcp.ts:89-96` — `ATTR_GENAI_AGENT_ID`, `ATTR_GENAI_AGENT_NAME`,
    `setAgentAttributes`, `setTeamAttributes`; сам файл ссылается на семконвенции gen-ai (`:39`).
  - Готовый стенд: `platform/dev/docker-compose.observability.yml` — tempo, loki, otel-collector,
    prometheus, grafana.
  - Бюджеты/лимиты: `models/limit.ts` (см. 04).
  - RUM-экспортер — Enterprise (`observability/rum/exporter.ee.ts`).
- **Где принуждается:** код.
- **Зависимости:** OTLP-приёмник (Grafana/Splunk/коллектор), Postgres.
- **Лицензия:** ядро AGPL, RUM — Enterprise.

---

## Разбор 1 — «Tainted conversation»: где именно шов принуждения

**Дословная заявка:** «When a tool call returns sensitive data, the conversation is marked tainted.
**Tools that could leak it switch off** — email, web requests — for the rest of that conversation.
**Enforced at the proxy, deterministically. Not requested in a system prompt.** You define the
configuration.»

### Слово «tainted» в коде отсутствует — и это не придирка, а способ найти механизм

`rg -i taint` по всему дереву не даёт ни одного файла реализации (только тексты вроде
`platform-deployment.md` и чужие README в каталоге MCP-серверов). Внутреннее имя другое:
**`contextIsTrusted` / `unsafeContextBoundary`**. Владельцы:
`platform/backend/src/guardrails/trusted-data.ts` (747 строк) и
`platform/backend/src/models/tool-invocation-policy.ts` (806 строк).

### Как помечается разговор

`evaluateIfContextIsTrusted` (`guardrails/trusted-data.ts:95`) — чистая функция над историей
сообщений запроса. Она:

1. Собирает все tool-calls из `messages` (`:182-219`). Вызов через обёртку `run_tool`
   **разворачивается на целевой тул** (`:191-203`), иначе политика цели никогда бы не сработала —
   это прямая связка с прогрессивной загрузкой тулов из разбора 2.
2. Bulk-оценивает их политиками результата: `TrustedDataPolicyModel.evaluateBulk` (`:244`).
3. Исходы на результат тула (`:309-465`):
   - `isBlocked` → содержимое заменяется уведомлением, контекст грязный (`:324-341`);
   - `shouldSanitizeWithDualLlm` → результат прогоняется через **Dual LLM**-субагента
     (`agents/subagents/dual-llm`), модель видит только сводку, контекст остаётся чистым
     (`:342-464`); при отказе анализа — **fail closed**, весь запрос падает 502
     (`:427-451`, класс `DualLlmSanitizationError` на `:47`);
   - иначе `mark_as_untrusted` → контекст грязный (`:467-476`).
4. **Отсутствие политики = грязно** (`:292-307`: «Tool not found - treat as untrusted») и
   **неразрешимая обёртка `run_tool` = грязно** (`:276-287`).
5. Первая точка загрязнения запоминается как `unsafeContextBoundary` и **не перезаписывается
   позже** (`:299-305`, `unsafeContextBoundary ??=`). Тип — `platform/backend/src/types/interaction-guardrails.ts:25-38`,
   причины — `:3-8`: `agent_configured_untrusted`, `inherited_from_parent`,
   `tool_result_marked_untrusted`, `tool_result_blocked`.

### Где «список тулов-эксфильтраторов»

**Статического списка нет вовсе.** Ни «email», ни «web request» в коде не перечислены. Вместо
списка — **строки в БД на каждый тул**, две таблицы: `tool_invocation_policies` (можно ли звать) и
`trusted_data_policies` (как трактовать результат).

Дефолт — **fail closed для всего**: `models/tool.ts:537-561`, `createDefaultPolicies`, каждый
новосозданный тул получает `block_when_context_is_untrusted` на вызов и `mark_as_untrusted` на
результат; организация может сменить дефолт (`models/tool.ts:570-582`,
`defaultDiscoveredToolInvocationPolicy` / `defaultDiscoveredToolResultPolicy`), но хардкод-фолбэк
именно закрытый.

Классификация «какой тул опасен» делается **LLM-субагентом**, а не человеком и не эвристикой:
`agents/subagents/policy-configuration.ts:48` (`PolicyConfigurationService`), запускается при
обнаружении тула, если включён флаг организации — `models/tool.ts:4164`
(`!config.autoConfigureOnToolDiscovery` → выход), и вручную из `routes/agent-tool.ts:544`.
Системный промпт этого субагента виден в `database/seed.ts:1221` (легаси-версия, оставленная для
авто-апгрейда пристроенных промптов): «Analyze this MCP tool and determine security policies…
"block_always": Never invoke automatically (writes data, executes code, **sends data externally**)».
То есть **решение** о том, что тул — эксфильтратор, принимает модель; **принуждение** после этого
детерминированное.

### Где принуждается — четыре шва, все в коде

| шов | файл:строка | что делает |
|---|---|---|
| LLM-прокси, потоковый ответ | `routes/proxy/llm-proxy-handler.ts:1733` | оценивает tool-calls модели ПОСЛЕ стрима, до отдачи клиенту |
| LLM-прокси, непотоковый | `routes/proxy/llm-proxy-handler.ts:2198` | то же на не-SSE пути |
| MCP-gateway (исполнение) | `routes/mcp-gateway/utils.ts:799` | `evaluateSingleMcpToolInvocationPolicy` перед реальным вызовом тула |
| встроенный диспетчер `run_tool` | `archestra-mcp-server/run-tool.ts:457` | тот же гейт для тула, вызванного через обёртку |
| предвыполнение в чате | `agents/context-trust.ts:13-52` | второй, независимый расчёт доверия прямо перед исполнением тула (`sanitizeCacheOnly: true`) |

Решение принимает `ToolInvocationPolicyModel.evaluateBatch`
(`models/tool-invocation-policy.ts:536-663`). Действия: `block_always`,
`block_when_context_is_untrusted`, `allow_when_context_is_untrusted`, `require_approval`.
Специфичные политики (с условиями) перекрывают дефолтную (`:550-614`), а **при полном отсутствии
политики и грязном контексте — блок** (`:654-659`).

### То, ради чего это смотрелось: запрет по СОДЕРЖИМОМУ аргументов

`models/tool-invocation-policy.ts:375-414`, `evaluateInputCondition`: значение достаётся из
аргументов тула по пути (`get(input, key)`, lodash-style) и сравнивается операторами
`endsWith | startsWith | contains | notContains | equal | notEqual | regex`. Условия на контекст
(`key.startsWith("context.")`) — отдельной веткой (`:562-569`).

Это ровно тот шов, которого у нас нет: у нас замерено (#228), что запрет по содержимому аргументов
через `can_use_tool` **не принуждается вовсе** — колбэк на `Bash(run_in_background=true)` был вызван
0 раз, и правило пришлось переносить в хук `PreToolUse`. У Archestra аналогичное правило —
строка в Postgres, вычисляемая сервером на пути исполнения, а не текст в промпте. Их собственная
документация это подтверждает и распространяет на обёртку: `docs/pages/platform-mcp-gateway.md:163` —
«`run_tool` does not bypass input conditions, team conditions, untrusted-context rules, or
approval-required rules».

### Границы механизма (то, что лендинг не говорит)

1. **Состояние «грязно» не хранится на сессии — оно пересчитывается из истории каждого запроса.**
   `llm-proxy-handler.ts:966-969` берёт `requestAdapter.getMessages()`, и именно этот массив уходит
   в `evaluateIfContextIsTrusted` (`:1013`). Внешний клиент (Claude Code, curl), который пришлёт
   историю без «грязного» tool-result, получит чистый контекст. Липкого серверного флага на сессию
   для внешних клиентов нет; для чата история серверная, поэтому там свойство держится.
2. **Наследование через делегирование — по HTTP-заголовку.** `llm-proxy-handler.ts:333-338`:
   `inheritedContextUntrusted = <заголовок UNTRUSTED_CONTEXT_HEADER> === "true"`. Это внутренний
   контракт между их же компонентами, а не подписанное утверждение.
3. **Отказ терминален и это осознанный компромисс, задокументированный в коде.**
   `guardrails/tool-invocation.ts:352-398`, функция `refusalWouldStrandTheCaller`: на LLM-прокси
   вызов необъявленного тула **не** отклоняют, потому что отказ обрывает ход и «with nobody watching
   it is fatal… an unattended run simply stops, with no error, no exit and nothing to retry». На
   gateway отказ сохраняется. То есть строгость сознательно разная на двух швах.
4. **Проверяемость.** Юнит-тестов у трёх владельцев: `guardrails/trusted-data.test.ts` — 44,
   `models/tool-invocation-policy.test.ts` — 59, `guardrails/tool-invocation.test.ts` — 25 (итого 128
   по `rg -c "^\s*(test|it)\("`), плюс `routes/proxy/llm-proxy-handler.gateway-guardrails.test.ts`.
   E2E-файл `platform/e2e-tests/tests/tool-guardrails.spec.ts` при этом содержит **один** тест, и он
   про подписи в UI, а не про блокировку.

---

## Разбор 2 — Ленивая загрузка тулов и происхождение чисел «~600 против ~60 000»

### Механизм существует и называется «Progressive tool loading»

- **Переключатель:** `platform/backend/src/types/agent.ts:58` —
  `ToolExposureModeSchema = z.enum(["full", "search_and_run_only"])`.
- **Фильтр выдачи `tools/list`:** `routes/mcp-gateway/utils.ts:2314`, `filterExposedTools` — в режиме
  `search_and_run_only` наверху остаются только мета-тулы, тулы управления задачей и «всегда
  открытые», всё остальное прячется за пару `search_tools` / `run_tool` (`:2322-2342`).
- **Поиск:** `archestra-mcp-server/search-tools.ts:187` — описание тула; два режима
  (`:60`): `keyword` (ранжирование по имени, описанию, именам и описаниям аргументов) и `regex`
  (по имени/заголовку/описанию). Реализация ранжирования — `rankCandidatesByKeyword` /
  `rankCandidatesByRegex` (`:285-289`, `:829`). **Эмбеддингов здесь нет** — чистая лексика,
  как и у нас.
- **Компактность выдачи:** возвращаются «exact tool names plus compact input summaries» (`:187`),
  скелет схемы строит `archestra-mcp-server/tool-args-skeleton.ts` (136 строк).
- **Исполнение:** `run_tool` (`archestra-mcp-server/run-tool.ts`), и он **не обходит гейты** —
  политика проверяется на `:457`.
- **Связка с guardrails:** `guardrails/trusted-data.ts:191-203` разворачивает `run_tool` на целевой
  тул, иначе обёртка «авто-доверялась» бы как встроенный тул.
- **Документация:** `docs/pages/platform-mcp-gateway.md:152` («turn on **Progressive tool loading**…
  This keeps the initial tool list small»), `:161` (в режиме Auto `tools/list` возвращает только эти
  два тула, сколько бы тулов пользователю ни было доступно).

### Откуда взяты «~600 против ~60 000»

**Ниоткуда, что можно проверить.** Проверка, а не впечатление:

- `rg -F '60,000'` по всему дереву (без каталога `mcp-catalog/`, где лежат чужие README) — **0 совпадений**.
- `rg -F '60000'` — совпадения есть, но все посторонние: таймауты в `config.ts`, `platform-deployment.md`,
  тестовые данные в `ai-labs/`.
- `rg -i '70 tools|70-tool'` — **0 совпадений**.
- В самой документации по gateway числа нет вообще: там только качественное «keeps the initial tool
  list small» и «too large or noisy».
- Страница их собственных замеров `docs/pages/platform-performance-benchmarks.md` меряет **другое**
  (латентность 30–50 мс, 155 req/s, Dual LLM 2–3 с на раунд) и про токены тулов не говорит ни слова;
  `lastUpdated: 2025-10-15`, то есть почти год назад.
- Каталог `platform/benchmarks/` содержит только нагрузочный стенд (`run-benchmark.sh`,
  `setup-gcp-benchmark.sh`, один payload `test-payloads/chat-with-tools.json`) — воспроизводимого
  замера токенов там нет.
- Числа нет и в блоге: `grep -c '60,000'` — `blog.html: 0`, `landing.html: 1`. То есть строка живёт
  ровно в одном месте — на лендинге.

**Что при этом в платформе есть:** рантайм-измеритель контекста по категориям, включая схемы тулов —
`routes/chat/context-window-breakdown.ts:3` («tokens the system prompt, **tool schemas**,
conversation messages, tool results»), `:57-63` сериализует каждое определение тула и считает
токены, `:300` — `serializeToolForEstimate`. Токенизаторы настоящие: `backend/src/tokenizers/`
(`tiktoken.ts`, `anthropic.ts`). То есть **инструмент для честного замера у них есть, а сам замер не
опубликован**; «~600 / ~60 000» — оценка порядка, не результат прогона.

### Что из этого сравнимо с нашим подходом

- Форма совпадает: два мета-тула + лексический поиск по каталогу + компактный скелет схемы.
- Отличие в том, где живёт каталог: у них это строки в Postgres с RBAC и политиками, поэтому
  `search_tools` в режиме Auto отдаёт «весь корпус, доступный этому пользователю», а гейт стоит
  на исполнении, а не на выдаче.
- Цена, которую они платят и не называют: минимум один дополнительный round-trip модели
  (`search_tools` → `run_tool`) на каждый незнакомый тул, плюс риск, что лексический ранкер не
  найдёт нужное — их собственное описание тула прямо инструктирует модель переформулировать запрос
  (`search-tools.ts:45`: «If nothing fits, reformulate with different keywords and search again
  rather than settling for a poor match»), то есть качество поиска частично переложено на промпт.

---

## Confidence по находкам

| находка | уверенность | основание |
|---|---|---|
| Дуальная лицензия AGPL + Enterprise, enterprise-код лежит в репозитории | **CONFIRMED** | прочитан `LICENSE.md`, посчитаны файлы двумя независимыми признаками (SPDX и `*.ee.*`) |
| SSO гейтится лицензией в рантайме (403 под <30 юзеров бесплатно) | **CONFIRMED** | `middleware.ts:44-50` + `enterprise-tier.ts:57` прочитаны целиком |
| «Tainted conversation» принуждается кодом на 4+ швах, включая условия на содержимое аргументов | **CONFIRMED** | прочитаны обе модели политик и все точки вызова, найденные грепом по имени функции |
| Статического списка тулов-эксфильтраторов нет; классификация — LLM-субагент, дефолт fail-closed | **CONFIRMED** | `models/tool.ts:537-561`, `agents/subagents/policy-configuration.ts`, промпт в `seed.ts:1221` |
| Состояние «грязно» пересчитывается из истории запроса, а не хранится на сессии | **LIKELY** | прочитан путь прокси от `getMessages()` до `evaluateIfContextIsTrusted`; не проверено живым запросом (платформу не поднимали намеренно) |
| Прогрессивная загрузка тулов реализована (лексический поиск + `run_tool`) | **CONFIRMED** | прочитаны фильтр выдачи, тул поиска и диспетчер |
| Чисел «~600 / ~60 000» в репозитории и блоге нет | **CONFIRMED** | четыре независимых грепа по дереву + `grep -c` по сохранённым HTML лендинга и блога |
| «Promotion dev→staging→prod» как машины состояний в коде нет | **LIKELY** | греп по `promote|promotion` в `models/routes/services` пуст по смыслу; модель среды не содержит связи «следующая среда». Не исключено, что это делается лейблами (`entity-labels`), которые я не разбирал |
| K8s обязателен для рантайма кода/агентов | **CONFIRMED** | `config.ts:1941-1944` + вкомпилированный KinD в `Dockerfile:7,34` |

## Counter-evidence и то, что играет против моих выводов

- **Против «числа выдуманы»:** число могло быть посчитано вручную по реальному Jira-MCP и просто не
  закоммичено. Это правдоподобно: 70 тулов × ~850 токенов на определение действительно дают ~60 K, и
  порядок величины у нас сходится с собственным опытом. Моё утверждение узкое и именно такое:
  **в репозитории и в блоге замера нет**, а не «число неверно».
- **Против «taint пересчитывается и потому обходится»:** у них есть второй, независимый расчёт
  доверия прямо перед исполнением тула (`agents/context-trust.ts:13`), и на gateway набор тулов —
  это назначенные агенту тулы, а не заявленный клиентом список (`guardrails/tool-invocation.ts:389-392`).
  То есть даже клиент с подчищенной историей упирается в RBAC и в политики на исполнении;
  «обходится» относится к вычислению признака грязноты, а не ко всей защите.
- **Против «SSO платный»:** Small Team Clause делает его бесплатным до 30 человек во всей компании,
  а `isCoreActive()` истинно и при поднятом env-флаге, который никем не проверяется криптографически.
- **Против «одобрение — только про образы»:** я грепал по `approv` и по `promote`; поток «submit →
  security review» может быть реализован под другими словами (`request`, `pending`, `draft`) или
  жить целиком во фронтенде. Помечено как пробел.

## Затронутые файлы (для возможной Фазы 2 у нас)

Их код мы не копируем. Наши файлы, которых касались бы выводы, если задача когда-нибудь пойдёт
дальше ресёрча: `.orchestra/pipelines/default/prompts/` (правила про запреты по аргументам),
`app/mcp_stdio.py` (наши тулы), `.orchestra/kb/agent-guardrails.md`, `.orchestra/kb/token-efficiency.md`.

## Риски и грабли, на которые наткнулся по дороге

- `rg -rn` — это **не** «recursive + line numbers»: `-r` это `--replace`, и вывод молча заменяется
  строкой «n». Один греп в этой задаче так и соврал, пока я не перечитал вывод.
- Каталог `mcp-catalog/data/mcp-evaluations/*.json` — это дампы чужих README; любой греп по общим
  словам вытаскивает оттуда мегабайты. Все счётные грепы здесь сделаны с `--glob '!mcp-catalog/**'`.
- `open_issues_count` в GitHub API **включает pull requests**: 44 против настоящих 24 открытых issue.

## Review

- **Route:** `none — Codex unavailable`. Предмет — fact extraction / проза (маршрут 5 гейта в
  `codex-debate`), обязательный первый шаг там — механические проверки полноты. Model-review не
  запускался: оркестратор в постановке зафиксировал пул Codex на 93% (выше нашего потолка) и прямо
  запретил брать Sol и Luna в этот ход. Замену ревьюеру не поднимал — это предписанный исход, а не долг.
- **Механическая проверка полноты (она же гейт):** каждый `путь:строка`, названный в этом файле,
  разрешён в реальный файл чужого репозитория, и фактический текст строки напечатан рядом.
  Результат: `TOTAL upstream anchors checked=105 ok=105 failed=0`. Артефакт —
  `.orchestra/tasks/470/anchor-check.txt` (там же напечатан снимок коммита, к которому привязаны
  все ссылки).
- **Что эта проверка НЕ доказывает:** что моя интерпретация строки верна. Она доказывает только,
  что ссылка не выдумана и указывает на существующий код — то есть закрывает ровно тот класс
  дефекта, ради которого правило заведено (#345).

## Sources

Все ссылки открыты в этой сессии.

1. `https://archestra.ai` — лендинг, сохранён как `/mnt/data/tmp/archestra-470/landing.html` (78 716 байт,
   HTTP 200) и распакован в `landing.txt`; цитаты выше — дословно оттуда.
2. `https://archestra.ai/blog` — индекс блога, `/mnt/data/tmp/archestra-470/blog.html` (234 919 байт, HTTP 200).
3. `github.com/archestra-ai/archestra` на коммите `c0f30875` — исходники, blobless-клон.
4. `gh api repos/archestra-ai/archestra`, `.../releases`, `.../contributors`, `search/issues` — метаданные.
5. Docker Hub registry API, `repository:archestra/platform:pull` — существование образа (manifest 200).
