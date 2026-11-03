# V-1242 — короткий индекс источников

Дата чтения: 2026-11-02 UTC. Только предоставленный безопасный source bundle, metadata contract инструментов текущей сессии и публичные первичные документы. Git metadata в bundle отсутствует; upstream Orchestra commit не установлен. Ниже **SHA-256 файлов**, не Git commit. Читались указанные функции/участки, не заявляется построчный аудит файлов целиком.

## Orchestra source bundle

| ID | Файл и покрытие | SHA-256 |
| --- | --- | --- |
| C1 | `app/backend_hub.py`: 78–104 preamble; 245–332 identity/selection; 653–886 provision/start/read; 1109–1140 accounting | `a1a1d650dc70bcd1faa524f50599df734f7318fcaae6f35bb9402f14477ab803` |
| C2 | `app/multicode_client.py`: 1–184 transport/handshake/tools; 186–270 helper run/followup/reply | `3c26debcb42c9dfc1211f8a53244cc00999249cc01fa871985c0c577aa4a8e54` |
| C3 | `app/hub_workspace.py`: 105–151 options/scope; 285–295 candidates; 370–454 selection; 471–485 tar; 1155–1204 state | `720536234b7f54227173c2861aa974bf6c35dcae0fb9c5038696564315b8f315` |
| C4 | `app/hub_activity.py`: 1–125 timeline translator | `c85e016aa2ddb48ad53f279f43d2919304b5609035ba95fe38e14a5f52d82a5e` |
| C5 | `app/hub_pool.py`: 1–210 relay summary contract; без выполнения fetch | `a3026b7cc17ac63c85d0479cfe52fcffdd68c79ca7a79638320afd6ea2146507` |
| C6 | `app/session_turns.py`: 440–528 metadata → DB | `482d2afd4f9bb2e401758c39dc40935116f8b86bd43f9b3e26ffafcd0cc6a7f5` |
| C7 | `app/schema.sql`: 550–593 turn/history schema | `0f04c693f8c0dcb5157c150930308822c7f9d8e18d1f0137039428dc4a07400d` |
| C8 | `app/db.py`: 2562–2688 turn_usage_add | `33d5c1d3330bc1d520bfa4b485e159ef6facd9a2d316fb2b6c2c26eb71552a5d` |
| C9 | `app/backend_codex.py`: 241–375 rollout/delta; 1676–1685 token notification; 1860–1871 dispatch; 2388–2478 completion; 2697–2731 fallback | `3aef3de42c1fa89bdf370e963c44ab7b34127d37ce20e831fcdeb9b743c4a446` |
| C10 | `app/backend_claude.py`: 1705–1946 result conversion; 1977–2024 assistant usage | `11f75ef1aa10097bf45d39a476ee89634f9e03ac096340f0dc500bc67cdbe119` |
| C11 | `app/claude_history_usage.py`: 1–121 history import/aggregation | `48dfacdfc0b43df52164042ed9f9caa866d44acdcc777551f42e84148d9d5936` |
| C12 | `app/usage_analytics.py`: 1–100 observed-turn sources; 141–168 daily aggregation | `d02d6193b1968057ca2a461bce5d1595957c093a459107f89477b4ed98bf5a35` |
| C13 | `app/usage_contract.py`: 1–185 aggregate/current-context semantics | `7fcb10d4e6d5f7f76ca6c96fbcf1f6510a04715d498b5b4cde463d19c2f44956` |

Дополнительно просмотрены README (публичный upstream `DrSeedon/orchestra`), `.gitignore`, точечные grep callers/schema. Это не provenance текущего commit. По metadata contract прочитаны описания `t3_project_create/list/read`, `t3_thread_launch/read/send/wait`, scope environment и runtime restrictions; эти инструменты **не вызывались**. Контракт инъецирован сессией, версии/SHA серверной реализации нет.

## Первичные документы T3

Публичный upstream: `pingdotgg/t3code`. Commit SHA получен read-only через публичный GitHub API `repos/pingdotgg/t3code/commits/main`; дальнейшие ссылки закреплены на `0847a448fdca5a688720050ca706cbbd37e6347e`. Документы не отождествляются с корпоративным fork. Implementation по ссылкам из документов не аудировалась.

### T1

[Usage and limits](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/user/usage.md): сохранённая история, API-estimate, отдельные Limits, ограничения покрытия и фильтры представления.

### T2

[Environment authentication](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/internals/environment-auth.md): sessions/scopes, серверная авторизация, MCP ceiling, environment/filesystem boundary.

### T3

[Remote access](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/user/remote-access.md): permissions текущего маршрута, отдельные file scopes.

### T4

[Guest links](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/user/guest-links.md): содержимое одного предоставленного thread и предел доступа гостя.

### T5

[Settings and project overrides](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/user/project-settings.md): device/server settings, archive semantics. Прочитаны целевой текст и поиск privacy/exclude/usage.

### T6

[Product usage data](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/user/telemetry.md): product event metadata и privacy boundary. Также открыт [Managed policy](https://github.com/pingdotgg/t3code/blob/0847a448fdca5a688720050ca706cbbd37e6347e/docs/user/managed-policy.md); ничего не применялось.

### T7

[T3 Code Privacy Policy](https://www.t33.codes/privacy-policy), effective/updated 2026-10-06: scope Services, connected environments/providers. Это изменяемая web-страница, не закреплённая версия deployment.

## SDK/provider/OS документы

Это изменяемые официальные страницы, просмотренные 2026-11-02; Git SHA и соответствие установленным CLI **не установлены**.

### A1

[Claude Agent SDK TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript#sdkresultmessage): итоговый `SDKResultMessage`. Исходный официальный URL `platform.claude.com/docs/en/agent-sdk/typescript` перенаправил сюда. Схема документа сопоставлена с потребителем Python SDK в C10; это не проверка установленного SDK.

### A2

[Claude Code: Manage costs effectively](https://code.claude.com/docs/en/costs#using-the-usage-command): session cost estimate и отличие от подписочного billing.

### A3

[Claude Code: Track team usage with analytics](https://code.claude.com/docs/en/analytics): Team/Enterprise admin/owner; API Console `UsageView`; разные продуктовые права.

### O1

[Codex App Server](https://learn.chatgpt.com/docs/app-server#events): thread/turn/item lifecycle и `thread/tokenUsage/updated`.

### O2

[Usage Insights](https://learn.chatgpt.com/docs/enterprise/usage-insights): доступ к analytics зависит от workspace permissions/features; показатели имеют разный scope.

### O3

[Governance](https://learn.chatgpt.com/docs/enterprise/governance): различие analytics, reporting и audit/compliance; не универсальная гарантия export локальной истории.

### O4

[Roles and workspace permissions](https://learn.chatgpt.com/docs/enterprise/roles-and-workspace-permissions): Member/Admin/Owner/Analytics Viewer и независимые границы подключённых систем.

### L1

[Linux man-pages: path_resolution(7)](https://man7.org/linux/man-pages/man7/path_resolution.7.html): directory search permissions, UID/DAC и namespace boundary. Не проводилась инспекция реальных файлов/пользователей хаба.

## Ограничения получения

Поисковые сниппеты, Reddit, обзоры и сторонние зеркала не использованы как доказательства. Два обращения к `.md` вариантам OpenAI страниц получили `400 Unsupported content-type: text/markdown`; HTML оригиналы успешно прочитаны. Один exploratory grep затронул отсутствующий `app/provider_timing.py`; из этого не делалось выводов. Клонирования, приватных endpoints и публикации не было. Весь публичный состав результата — этот индекс и соседний отчёт; сырые документы не копировались.
