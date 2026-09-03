## Summary

Предпосылка об автоматической кросс-проектной сборке Claude MCP не подтверждается. Путь конкретен и безопасен относительно scope: `_load_scope_mcp_servers(context.scope)` читает только текущий проект; user-level MCP загружаются только при `role.mcp_servers == "all"`; `mcp_servers_custom` добавляются явно через `_make_mcp_config`. T5 корректно закрывает единственный найденный fail-open дефолт.

Однако план пока имеет четыре блокирующих проблемы: T4 не определяет стабильную идентичность `CODEX_HOME` и перенос subscription-auth; правило маски не покрывает заявленные типы секретов; T6 с `EnvironmentFile` не убирает значения из итогового argv.

## Findings

blocking: docs/tasks/224/plan.md:157 — новый `CODEX_HOME` должен быть «стабилен по session_id», но при первом запуске `CodexBackend` ещё не имеет Codex thread id: он появляется только после `thread/start`, тогда как `CODEX_HOME` нужен до запуска процесса. Конструктор не получает Orchestra session id, а список файлов T4 ограничен `backend_codex.py` → определить стабильный ключ до старта и передать его через `BackendBuildContext`/factory либо явно спроектировать и протестировать атомарную миграцию initial home после получения thread id; добавить тест «первый connect → disconnect → новый backend с resume id использует тот же home и находит rollout».

blocking: docs/tasks/224/plan.md:146 — пустой изолированный `CODEX_HOME` отделяет процесс не только от глобальных MCP, но и от subscription-auth/state в базовом Codex home. План переносит лишь `project_doc_max_bytes`; тесты вообще не запускают Codex и потому примут конфиг, с которым app-server не авторизуется → явно сохранить доступ к subscription-auth без копирования глобального `config.toml`/MCP и добавить connect-level проверку с изолированным home. Не переносить реальные credential values в committed fixture.

blocking: docs/tasks/224/plan.md:72 — алфавит значения `[A-Za-z0-9_\-.+/]` несовместим с явными классами `DATABASE_URL`, `CONNECTION_STRING`, `DSN`, `COOKIE` и `PRIVATE_KEY`: реальные URL/DSN содержат `:`, `@`, `%`, `?`, `&`, `=`, cookies — `;`/`=`, base64 часто заканчивается `=`. Реализация может замаскировать только префикс и оставить хвост либо не сработать вовсе → специфицировать безопасные границы отдельно для quoted JSON/env/shell форм и добавить параметризованные RED-тесты для каждого суффикса, каждого явного имени, Bearer/Basic, PEM, порога 11/12 и значений с URL/cookie/base64-пунктуацией. Сейчас единственный положительный oracle проверяет только quoted `INTERNAL_TOKEN` из простого алфавита.

blocking: docs/tasks/224/plan.md:184 — `EnvironmentFile` скрывает значение из текста unit-файла, но не гарантирует его отсутствие в `/proc/<pid>/cmdline`: если `telegram-bot-api` принимает API ID/hash как CLI-флаги, systemd или shell в итоге всё равно передаст раскрытые значения в argv процесса. Более того, текущий тест запрещраняет даже `--api-id=$TELEGRAM_API_ID`, но не доказывает, что запущенный бинарник получит параметры и останется без секрета → определить реально поддерживаемый файловый/env-интерфейс бинарника либо безопасный launcher/API; acceptance должна проверять живой cmdline и успешный старт. Если бинарник принимает креды только argv, T6 в заявленной форме невыполним.

suggestion: tests/test_mcp_config_isolation.py:108 — T3/T4 не являются полноценными оракулами сохранности MCP. T3 проверяет один сервер и одно поле, T4 лишь ищет название секции; `test_t4_foreign_global_servers_not_copied` даже не подсовывает базовый конфиг с иностранными секциями, поэтому пройдёт при полном игнорировании base config. Живая тройка из плана полезна, но не committed acceptance test → добавить round-trip точного множества stdio и URL серверов со всеми `args`, `env`, `enabled_tools`; подложить base config с иностранным MCP, `[projects.*]` и `project_doc_max_bytes`; проверить, что переносится только разрешённый scalar и все ожидаемые инструменты реально доступны.

suggestion: docs/tasks/224/plan.md:141 — ссылка на удаление Claude-файла «на `_disconnect_backend`» неточна: у `ClaudeBackend` есть `disconnect()`, а `_disconnect_backend` принадлежит session-слою. Текущие тесты также не проверяют каталог 700, расположение вне worktree/`/tmp`, lifetime, cleanup и повторный `_make_client`; последний сейчас вызывается тестами несколько раз и может плодить осиротевшие файлы → назначить владельцем lifecycle `ClaudeBackend.disconnect()` и покрыть эти свойства тестом.

suggestion: tests/test_secret_mask.py:81 — два изначально GREEN companion-теста легитимны как negative regression guards и не скрывают проблему сами по себе. Недостаёт именно позитивной матрицы правила. Для `LiveBroker.publish` также стоит проверить, что исходный payload не мутируется неожиданно либо явно закрепить мутацию как контракт; существующие `tests/test_live_broker.py` сравнивают только доставленные dict.

suggestion: docs/tasks/224/plan.md:85 — кроме уже названных model context и split SSE chunks, остаются: значения с пунктуацией вне заданного алфавита, секреты без распознаваемого имени ключа, закодированные/экранированные представления и секреты в других полях payload/log metadata. Для текущего штатного контракта `add_log(content)` + `LiveBroker.publish(payload["content"])` других очевидных текстовых маршрутов к DB/dashboard/RAG не видно, но утверждение «только два ограничения» пока делать нельзя из-за этих format/field bypass.

suggestion: docs/tasks/224/plan.md:168 — инвертируемая строка 252 не единственный существующий контракт T4: соседние тесты 250–254 ожидают, что command/args/enabled/enabled_tools возвращаются из `_mcp_config_args()`. Если метод после переноса отвечает только за безопасные argv overrides, их можно сохранить; если он станет пустым, потребуется осознанно переписать весь этот тест на проверку `config.toml`, а не только env assertion. Также нужен regression test `_build_env()["CODEX_HOME"]`, поскольку без него connect может создать правильный файл, но запустить процесс на общем home.

## Verdict

План требует доработки перед реализацией. Claude-premise и T5 обоснованы, а T1/T2 имеют правильные швы, но T4 и T6 сейчас способны сломать runtime или не устранить argv-утечку, а acceptance tests допускают тихую потерю MCP-инструментов.

## Round (2026-08-12T11:01:27Z)

## Re-review status

- Prior finding 1 — FIXED in design: `ORCHESTRA_SESSION_ID` exists before Codex starts and can provide stable identity.
- Prior finding 2 — FIXED in design: the live run validates subscription auth through an `auth.json` symlink.
- Prior finding 3 — FIXED: form-based boundaries and threshold coverage replace the invalid character class.
- Prior finding 4 — FIXED in design: omitting both API flags and using their documented environment defaults removes the values from argv.

`git diff` is empty; the reviewed revision is already committed as `4bd344c1`, not currently uncommitted.

## New findings

blocking: tests/test_tg_bot_api_unit.py:24 — the T6 oracle still does not enforce the revised AC. Its regex permits a bare `--api-id` or `--api-hash` at end-of-line, and the runbook test does not require either post-install command. An artifact that crashes on a missing flag argument can therefore pass all four tests → assert `--api-id` and `--api-hash` are absent as tokens/substrings altogether, and assert the runbook contains both the exact argv check with expected zero and `systemctl is-active`.

blocking: docs/tasks/224/plan.md:197 — the stable identity argument trusts flattened `mcp_env`, but `_codex_factory` constructs that mapping from every configured server, while `_make_mcp_config` appends caller-supplied custom servers after `orchestra`. A custom server can therefore supply the same key name and override the trusted Orchestra value. Depending on path construction, this can merge two agents’ homes or influence the target path → derive the identity specifically from `self._mcp_servers["orchestra"]["env"]["ORCHESTRA_SESSION_ID"]`, validate it as the expected session-id format, fail loudly when absent, and add collision plus traversal tests.

suggestion: tests/test_mcp_config_isolation.py:245 — the auth test accepts either a symlink or any non-empty regular file, contradicting the plan’s “только симлинк” requirement. A copied stale credential passes → require `is_symlink()`, resolve it to the base home’s `auth.json`, and verify the isolated home remains private.

suggestion: docs/tasks/224/plan.md:89 — the written key rule lists `DSN` only as an explicit name, while the matrix requires `SENTRY_DSN` to match. Following the specification literally fails its own test → state that explicit entries also match underscore/hyphen-delimited suffixes, or list `SENTRY_DSN` explicitly.

suggestion: tests/test_mcp_config_isolation.py:167 — T4 still lacks the claimed exact stdio+HTTP round-trip oracle. It checks only that the Orchestra section exists; an implementation can omit its `env`, `args`, or enabled tools and pass the committed tests. The manual live acceptance should catch total tool loss, but the tests permit the regression → add a T4 exact parsed-TOML comparison analogous to `test_t3_every_server_and_field_survives_the_move`, including stdio, HTTP, environment and enabled tools.

## Verdict

Not approved: two blocking oracle/trust-boundary holes remain. The overall T3/T4 live acceptance prevents silent total MCP loss, but T4’s committed tests still do not independently prove tool preservation.

## Round 2
