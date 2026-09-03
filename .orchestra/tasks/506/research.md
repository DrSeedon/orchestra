# #506 — Antigravity CLI как пятый runtime Orchestra

Дата проверки: **2026-09-03**. Проверенная без авторизации версия: **Antigravity CLI 1.1.25**.
Код Orchestra в этой фазе не менялся.

## Вопрос

**Контекст.** Orchestra уже сводит Claude Code, Codex, Grok и собственный OpenRouter harness к
одному `BackendLike`-контракту. Пользователь предложил добавить официальный закрытый Go-бинарник
Antigravity CLI (`agy`) и просил отдельно проверить реальные GitHub-интеграции, а не только
маркетинговую документацию.

**Изменение под проверкой.** Пятый runtime должен запускать `agy` как управляемый subprocess,
передавать системный prompt и MCP-серверы Orchestra, стримить события, сохранять точную native
conversation identity, останавливаться и продолжаться после перезапуска.

**Baseline.** Не добавлять runtime и не расходовать Google quota.

**Решающий outcome.** Внедрение оправдано только при одновременном выполнении четырёх условий:

1. официальный машинный интерфейс покрывает `BackendLike` без PTY/скрейпинга приватной БД;
2. MCP Orchestra вызывается headlessly и восстанавливается предсказуемо;
3. авторизация и использование через Orchestra разрешены условиями сервиса;
4. лимит измерим настолько, чтобы routing не публиковал заведомо мёртвых workers.

## Гипотезы и фальсификаторы

### H1 — обычный backend поверх официального NDJSON достаточен

`agy` предоставляет prompt input, incremental events, terminal result, usage и exact conversation
ID, поэтому новый runtime по сложности ближе к `HarnessBackend`, чем к reverse-engineered ACP shim.

**Фальсификатор:** только TUI/PTY, отсутствие terminal event или exact resume, либо output требует
чтения приватных SQLite/protobuf файлов.

### H2 — техническая интеграция есть, но consumer-подписку использовать нельзя

Официальный CLI может быть технически управляемым, а Google OAuth/подписочный доступ при этом
может запрещать сторонний control plane вроде Orchestra.

**Фальсификатор:** актуальные Terms/FAQ прямо разрешают локальные wrappers официального `agy` или
дают документированный subscription-auth SDK/API для third-party applications.

### H3 — «бесплатен всем» означает лишь динамический небольшой baseline

Free и Google AI Plus получают доступ, но без опубликованных RPD/RPM; расход зависит от работы
агента и capacity, а не от числа пользовательских сообщений.

**Фальсификатор:** официальный документ публикует фиксированные requests/minute и requests/day для
consumer Antigravity и гарантирует срок действия этих значений.

## Короткий вывод

**One-shot adapter поверх `agy` технически доказан. Полноценный production runtime пока условен;
встраивать его с личным Antigravity login не стоит.**

- С 1.1.8 официальный `stream-json` даёт typed `init → step_update → result`; с 1.1.15 один
  процесс принимает последовательные user messages по stdin. Exact resume по
  `--conversation <id>` уже был живьём подтверждён в #249.[5][6][7][21]
- MCP поддерживает stdio и remote servers, конфиг сохраняется между процессами, а live #249
  вызвал workspace-local stdio tool. Но headless protocol не передаёт interactive approvals;
  открытые upstream issues дают historical/adjacent crash scenarios, а current 1.1.25 recovery
  local-stdio Orchestra server остаётся **UNVERIFIED**.[8][18][19][21]
- Главный blocker не код: текущие Terms и FAQ прямо называют доступ к Antigravity через стороннее
  ПО нарушением и допускают suspension/termination account. FAQ рекомендует Vertex или AI Studio
  API key; в Orchestra API keys запрещены проектным правилом.[14][15]
- Google не публикует consumer RPM/RPD. Free/Plus имеют weekly baseline; Pro/Ultra — 5-hour и
  weekly buckets; расход коррелирует с объёмом работы и может меняться по capacity. Исторический
  live batch #249 потратил 16.0045 п.п. неизвестного weekly tier за 13 коротких результатов — это
  около 81 такого результата на неделю, не универсальный request limit.[11][21]

Итого: **H1 PARTIAL, H2 CONFIRMED, H3 CONFIRMED.** One-shot transport и event parsing доказаны,
но current interrupt/retarget/MCP-crash recovery и combined persistent lifecycle не прогнаны.
Нужна не Phase 2, а изменение внешнего
условия: письменное разрешение Google для wrappers либо отдельное решение пользователя перейти на
API-key/Vertex route. Без этого backend превращает технически рабочую подписку в unsupported path с
риском блокировки.

## 1. Что требует Orchestra

Минимальный structural contract — `session_id`, `connect()`, `send()`, async `events()`,
`interrupt()` и `disconnect()`.[1] Runtime registry отдельно описывает event-stream mode,
mid-turn injection, reconnect, hibernate, process liveness, resume, retarget и subagents.[2]
Unified events должны как минимум дать final text, tool use/result, terminal `turn_end`, error и
status; live deltas можно публиковать как `stream`.[3][4]

| Требование Orchestra | Что даёт `agy` 1.1.25 | Вердикт |
|---|---|---|
| Запуск из нужного cwd/worktree | `--add-dir`, `--project`, обычный process cwd; #249 измерил раздельные side effects в двух worktree | **CONFIRMED** [5][21] |
| Системный prompt | Прямого `--system-prompt` нет; custom Markdown agent лежит в `.agents/agents/...` или `~/.gemini/config/agents/...`, выбирается `--agent` | **CONFIRMED, нужен materialization layer** [10] |
| Один prompt без TUI | `-p/--print/--prompt` | **CONFIRMED** [5][M2] |
| Долгоживущий процесс | `--input-format stream-json --output-format stream-json`; по stdin идут NDJSON user events | **CONFIRMED по official contract/help; authenticated live run не повторялся** [5][7][M2] |
| Streaming text | `step_update.text_delta` | **CONFIRMED** [5][21] |
| Tool use/result | `step_type=tool`, `tool_name`, `tool_info.parameters/output/error` | **CONFIRMED** [5][21] |
| Terminal event | Ровно один `result` на turn, status/response/error/usage | **CONFIRMED** [5][6][21] |
| Exact session identity | `conversation_id` в `init/result`; `--conversation <id>` | **CONFIRMED**, два одновременных exact-resume controls в #249 [5][21] |
| Process restart/resume | Новый process с `--conversation <id>`; config/state остаются в HOME | **CONFIRMED для one-process-per-turn**, комбинация resume + long-lived input не прогнана [5][21] |
| Mid-turn steer | Документация требует ждать `result`; `control_request/control_response` завершают stream с exit 2 | **НЕ ПОДДЕРЖИВАЕТСЯ**, сообщения надо queue после turn [5] |
| Interrupt | Documented `SIGINT → INTERRUPTED`; отдельного control RPC нет | **LIKELY**, signal path не прогонялся на authenticated turn [5] |
| Disconnect | В persistent input close stdin завершает current turn, отдаёт final `result` и process exits 0; аварийный путь остаётся signal/kill | **CONFIRMED как официальный contract**, current authenticated process cleanup не измерен [5] |
| Process liveness | `agy` — owned child process; PID/returncode даёт wrapper, vendor heartbeat RPC нет | **CONFIRMED на уровне OS wrapper**, semantic health требует events/watchdog [22][23][24] |
| Model retarget | `/model` недоступен в stream input; новый `--model` требует нового process, resume той же conversation через другой model не проверен | **НЕ ПОДДЕРЖИВАЕТСЯ IN-PROCESS / CROSS-MODEL UNTESTED** [5] |
| `AgentEvent.stream` + final `text` | `step_update.text_delta` даёт ephemeral delta; `result.response` — authoritative final text | **CONFIRMED mapping** [3][5][21] |
| `tool_use/tool_result` | `step_index/state/tool_info` дают start/completion, arguments, output/error; stable id придётся выводить из conversation+step | **CONFIRMED mapping**, derived ID — adapter contract [3][5][21] |
| `turn_end/status/error` | `result` всегда terminal и несёт status/error/usage; startup `init` даёт session status | **CONFIRMED mapping**, empty-SUCCESS guard обязателен [3][5][20][21] |
| Usage | Token counts есть; в multi-turn process usage cumulative, значит per-turn delta считает adapter | **CONFIRMED** [5] |
| Context occupancy/compact | Context percentage и manual compact RPC не опубликованы; generic summary→fresh-session path возможен | **GAP**, старый `agy help compact` в #249 дал unknown subcommand [21] |
| Model/effort | `--model <slug>`, `--effort low|medium|high`, unknown model fails non-zero | **CONFIRMED** [5][M2] |
| Native subagent lifecycle | `subagent_info` есть в output; управление из headless input не описано | **PARTIAL**, runtime capability оставлять false до отдельного canary [5] |
| Hibernation | One-shot adapter уже естественно не держит idle process; persistent adapter можно закрыть и resume по ID | **LIKELY**, зависит от выбранной Phase 2 архитектуры |

### Самый дешёвый технический путь

Для первого implementation slice достаточно **one process per turn**:

```text
agy --output-format stream-json --agent orchestra --model <slug> \
    --add-dir <worktree> [--conversation <exact-id>] -p <prompt>
```

Этот путь уже доказан #249 и несколькими независимыми wrappers. Новый long-lived stdin mode полезен
как следующая оптимизация startup latency, но добавляет управление persistent pipe и cumulative
usage; он не нужен, чтобы доказать полезность runtime.[5][21][22][23]

PTY/SQLite path для Orchestra не нужен. Он существует ради ACP UI и проксирования interactive
permission prompts, которых headless NDJSON намеренно не принимает.[24] Встраивать такую схему
означало бы зависеть от приватных protobuf полей и layout conversation DB при наличии официального
event stream.

## 2. Как `agy` встраивают другие

Дата в таблице — **последний commit именно файла с invocation/parser**, полученная через GitHub
Commits API 2026-09-03. Репозитории с недавним push, но устаревшим `agy` contract, не считаются
доказательством current capabilities.

| Проект | Реальный механизм | Последний commit файла | Что это доказывает / статус |
|---|---|---:|---|
| `SinanTufekci/agent-intern` | `subprocess.run` per turn, `--output-format json`, exact `--conversation`; watch mode парсит `init/step_update/result` | [2026-08-25, `server.py`](https://github.com/SinanTufekci/agent-intern/blob/f5ef57d60779f2619185636d8b7f7750fe764249/server.py#L1928-L2074) | **Recent structured-wrapper evidence** против 1.1.8+ contract, не live 1.1.25 canary. Есть version gating, hard timeout и defensive parsing.[22] |
| `ZEM17/dsh-subagent-agy` | Foreground JSON + exact conversation; background `stream-json`, parser text deltas/result и process-tree cancellation | [2026-08-16, `src/index.ts`](https://github.com/ZEM17/dsh-subagent-agy/blob/d520b9f690dbba9f8dafac09ebc79a5e1c5a8c8e/src/index.ts#L1247-L1370) | **Recent structured-wrapper evidence**, не 1.1.25 canary. Доказывает async-job pattern и собственный watchdog.[23] |
| `tksfjt1024/antigravity-cli-mcp-slim` | MCP server наружу, внутри один `agy --print ... --output-format json`; возвращает status, error, conversation_id, usage | [2026-08-22, `server.py`](https://github.com/tksfjt1024/antigravity-cli-mcp-slim/blob/3621b399b2a29635c2a0822d4b5cc0225d5ad038/src/antigravity_cli_mcp_slim/server.py#L57-L112) | **Recent structured-wrapper evidence**, не full runtime и не 1.1.25 canary; полезны failure guards.[24] |
| `shindgew/agy-acp` | Persistent interactive PTY, `--prompt-interactive`, polling private SQLite/protobuf steps, ACP translation, permission keystrokes | [2026-08-18, `src/agy/cli.ts`](https://github.com/shindgew/agy-acp/blob/54663f6ba56b2a93ededd8438373cfe9e71ff754/src/agy/cli.ts#L330-L470) | **Активный, но дорогой/brittle.** Нужен для rich ACP approvals; для Orchestra после 1.1.15 лишний.[25] |
| `AnEntrypoint/agentgui` | `agy --print <prompt> --dangerously-skip-permissions [--continue]`, каждая stdout line становится assistant text | [2026-08-09, `claude-runner-agents.js`](https://github.com/AnEntrypoint/agentgui/blob/78db2a894e0225c9c646e462daa3ba24cf07df63/lib/claude-runner-agents.js#L121-L142) | Репозиторий активен, **адаптер устарел**: утверждает, что нет stream-json/model/session id. Не current evidence.[26] |
| `Q00/ouroboros` | One-shot plain stdout, no resume, always permission bypass | [2026-08-24, `antigravity_cli_runtime.py`](https://github.com/Q00/ouroboros/blob/27fa0ebb92c1a4537caa2dc283cff318a5622509/src/ouroboros/orchestrator/antigravity_cli_runtime.py#L120-L168) | Репозиторий активен, **реализация stale**: файл после релиза 1.1.8 всё ещё пишет «нет output-format».[27] |
| `EstebanForge/pi-ask-antigravity` | Per-turn spawn; conversation ID ищет по появившемуся `.db` и process tree | [2026-08-14, `extensions/index.ts`](https://github.com/EstebanForge/pi-ask-antigravity/blob/875f8c73ddd54f85c97cbab31d5a65073055b4a5/extensions/index.ts#L1180-L1318) | **Активный, но stale discovery:** structured result уже отдавал точный ID; DB scan не нужен.[28] |
| `KyongSik-Yoon/antigravity-agy` | File-backed async jobs; plain stdout/stderr; `--continue`; secret-shaped env scrub; process-group timeout | [2026-07-15, `agy-companion.mjs`](https://github.com/KyongSik-Yoon/antigravity-agy/blob/dd29556bee223c64fec561676899baab7f522638/plugins/agy/scripts/agy-companion.mjs#L102-L165) | **Pre-1.1.8 legacy**, полезен только как operational pattern, не как parser reference.[29] |
| `TurkerYakup/mcp-server-google-antigravity` | MCP delegate с background job/polling; Windows PTY fallback; per-job `agy --print`, exact/fallback continue | [2026-07-14, `index.js`](https://github.com/TurkerYakup/mcp-server-google-antigravity/blob/5bb89ce89a505fdce1e751dac0b12f6bf6c3ae64/index.js#L600-L680) | **Pre-structured legacy**; async polling решает MCP timeout, но не даёт native runtime stream.[30] |
| `rhishi99/agy-headless-bridge` | POSIX PTY/ConPTY, ANSI/TUI cleanup, idle/hard timeout | [2026-07-02, `bridge.py`](https://github.com/rhishi99/agy-headless-bridge/blob/abe1de8349a68eabe3c37813437eaf89d4566bda/src/agy_headless_bridge/bridge.py#L236-L319) | Код старше двух месяцев и чинит pre-1.1.8 stdout bug; **не считать current evidence**.[31] |

**Общий результат GitHub-поиска:** production-shaped wrappers сходятся на прямом child process,
timeout/process-group kill, exact conversation ID и defensive output parsing. Ни один найденный
current wrapper не даёт более простой или более стабильный путь, чем официальный NDJSON. ACP/PTy
проекты добавляют слой только ради функций, которых headless protocol не имеет.

## 3. MCP

### Конфигурация

Официальный current contract:

- global: `~/.gemini/config/mcp_config.json`;
- workspace: `.agents/mcp_config.json`;
- local stdio: `command`, `args`, `env`, optional `cwd`;
- remote: `serverUrl`, optional `headers`/OAuth/Google ADC;
- disable controls: `disabled`, `disabledTools`.[8]

В `agy` нет `--mcp-config <path>`. Значит runtime должен либо materialize
`.agents/mcp_config.json` в worktree, либо дать каждому worker отдельный HOME с global config.
Второй вариант изолирует token, conversations, logs, settings и MCP secrets; сам 210 MB binary
можно держать общим.[8][21][M1]

Headless approvals по protocol вернуть в Orchestra нельзя: `control_request/control_response`
запрещены. Поэтому `mcp(orchestra/*)` должен быть заранее разрешён узкой rule в private
`settings.json`; `--dangerously-skip-permissions` открывает все tool calls и не нужен.[5][9]

### Перезапуск и отказ

Direct no-auth measurement 1.1.25:

```text
agy mcp add --env PROBE_VALUE=506 orchestra-probe /bin/false --probe-arg
Added MCP server "orchestra-probe" (stdio)

# отдельный второй процесс
agy mcp list
orchestra-probe  stdio  enabled  /bin/false --probe-arg
```

Файл сохранился как `~/.gemini/config/mcp_config.json` с `mcpServers` map. То есть **definition
переживает restart `agy`**.[M3] Live #249 дополнительно доказал не только discovery, но вызов
workspace-local stdio tool и его side effect.[21]

Операционная устойчивость current local-stdio path не проверена. Два соседних historical report
задают обязательные отрицательные canaries, но не доказывают дефект 1.1.25:

- issue #623 остаётся open, но описывает Antigravity 2.3.0 на Windows и remote HTTP через
  `mcp-remote`: там proxy child после EOF не respawn-ился до manual refresh/restart;[18]
- issue #657 остаётся open и обновлялся 2026-09-01, но тоже описывает Windows/scenario-specific
  startup: child, умерший при initialize, держал loop 300 секунд;[19]
- changelog содержит несколько MCP cleanup/path fixes, но не заявляет исправление respawn.[6]

Следствие для возможной реализации: readiness обязан проверять **живой Orchestra tool call**, а не
наличие config; каждый turn/process требует внешний watchdog; persistent process после MCP EOF надо
считать poisoned и пересоздавать.

## 4. Лимиты и авторизация

### Опубликованные числа

**Фиксированных consumer `requests/minute` и `requests/day` Google не публикует.** Current Plans
задаёт только формы окон:[11]

| Tier | Published window | Что происходит после baseline |
|---|---|---|
| Free и Google AI Plus | «meaningful» weekly quota; отдельного 5-hour bucket не заявлено | ждать weekly reset |
| Google AI Pro | 5-hour quota до weekly ceiling + более высокий weekly | ждать reset либо использовать купленные/promotional AI credits, если overages включены |
| Google AI Ultra | самый высокий 5-hour + weekly | то же, с более высоким baseline |

Расход «correlated with amount of work done by the agent», поэтому один user prompt не равен одной
quota unit; пределы могут меняться для capacity/stability.[11] Current Models page объединяет Free
и Google AI Plus в одну колонку доступности; значит Plus даёт доступ к CLI/model surface, но Plans
не ставит Plus рядом с Pro/Ultra по лимитам.[11][12]

Historical direct measurement #249 (Antigravity 1.1.12, неизвестный individual tier):

```text
13 successful gemini-3.6-flash-low terminal results
input_tokens=276577, output_tokens=3445, thinking_tokens=1546,
cache_read_tokens=256572, total_tokens=280022
Gemini weekly remaining: 1.0 -> 0.83995521068573
расход: 16.0045 percentage points
```

Нормализация ≈81 таких результатов/week — только порядок величины для того measured mix. Это не
RPD, не RPM и не переносится на Google AI Plus пользователя.[21]

`/usage`/`/quota` возвращает live per-account remaining buckets и с 1.1.12 исполняется как
read-only slash command без model turn. Если внешний policy blocker когда-либо снимется, admission
может использовать этот zero-token probe; hardcoded quota выдумывать нельзя.[6][21]

### Авторизация

- Consumer path: native keyring; по SSH — browser URL + code. Headless run использует cached
  credential.[5][13]
- Gemini API path: `modelProvider="gemini"` + `GEMINI_API_KEY`; это direct API, не Google AI
  Plus subscription.[13]
- Official Python SDK: API key или Vertex/ADC; subscription OAuth path не документирован.[17]

No-auth probe с isolated HOME не был fail-fast за 20 секунд: binary напечатал OAuth URL,
`Waiting for authentication (timeout 60s)` и был остановлен внешним `timeout` (`RC=124`). После
остановки stdout содержал structured `status=ERROR`, zero usage.[M2] Поэтому readiness не должен
полагаться только на обещание docs «authentication required вместо hanging»; нужен собственный
короткий process watchdog.

## 5. Terms, данные и риск закрытия

### Consumer login — блокирующий риск

Текущие Additional Terms запрещают использовать Service вместе с продуктами не от Google и прямо
называют доступ через third-party software/tools breach; возможны suspension или termination.[15]
FAQ повторяет это и как замену предлагает Vertex/AI Studio API key.[14]

Orchestra является сторонним control plane, даже если запускает неизменённый официальный binary.
Поэтому вывод #249 «официальный `agy` subprocess допустим, запрещено лишь извлекать token» теперь
**REFUTED**: Terms ограничивают способ доступа, а не только способ хранения credential.[14][15][21]

### Что уходит наружу

Terms говорят, что Google записывает и хранит user data, interaction data, related metadata и
feedback; эти Interactions используются для развития Google/Alphabet products and ML, и к ним
могут иметь доступ employees/contractors. В settings доступен opt-out использования данных, но
сам факт обработки Service traffic остаётся.[15]

**Inference из Terms и протокола, не перечисление гарантированно retained fields:** prompt,
выбранные фрагменты репозитория и те tool arguments/results, которые `agy` помещает в model
transcript, могут войти в широкую категорию Interactions. Сам stdio MCP server и его локальный
state исполняются на машине; Terms не доказывают, что Google получает каждый локальный MCP field.
Это не local-only model runtime, но exact retention payload остаётся нераскрытым.[5][8][15]

### Локальное состояние и неожиданные side effects

Unauthenticated 1.1.25 start в чистом isolated HOME создал **30 files / 106747 bytes** до login:
`settings/config`, installation ID, log, updater locks/status, summary SQLite, builtin skills,
cache и директории `brain/conversations/knowledge/crashes`.[M4] Authenticated #249 дополнительно
видел per-conversation DB/WAL, logs, `last_conversations.json` и scratch state.[21]

Тот же no-auth log показал три попытки скачать Playwright driver 1.57.0 с Azure CDN; все вернули
404.[M4] Значит даже pre-auth startup может создавать state и инициировать дополнительные downloads.
В production это требует private HOME, scrubbed environment и outbound-awareness.

### Change/closure risk

- Между release 1.1.8 (2026-07-28) и 1.1.25 (2026-09-03) вышло **18 releases за 37 дней**.[M5]
- 1.1.24 отдельно чинил hanging при piped stdout/stderr; 1.1.18 — false empty success; 1.1.15
  впервые добавил persistent stdin. Protocol уже менялся в местах, критичных для backend.[6][7]
- Auto-updater проверяет release в фоне с 15-minute debounce; его можно отключить только явным
  `AGY_CLI_DISABLE_AUTO_UPDATE=true`.[16]
- Issue #840 про `SUCCESS + empty response + zero usage` на JSON-heavy prompts остаётся open;
  текущий changelog заявляет родственный fix, но open issue не доказывает current resolution.[6][20]
- Пользователь уже зафиксировал исторический precedent: Gemini CLI consumer access закрыли через
  месяц после объявления. Для Antigravity нельзя честно вывести числовую probability, но Terms уже
  делают third-party consumer route unsupported **сегодня**, поэтому риск не гипотетический.

## 6. Во что обойдётся внедрение, если policy blocker исчезнет

### Кодовая поверхность

Current registry делает базовое подключение сравнительно прямым: новый backend реализует шесть
методов `BackendLike`, registry factory передаёт model/cwd/prompt/resume/MCP, а generic session loop
уже принимает per-turn events.[1][2][4]

Минимально затронуты:

- новый `app/backend_antigravity.py` — subprocess, NDJSON parser, signals, redaction, usage delta;
- `app/runtime_registry.py` — factory/capabilities/registration;
- `app/models.py` — namespaced model specs + provider metadata;
- `app/quota_gate.py`, `app/routes/system.py`, `app/session_turns.py` — две quota families,
  account snapshot и terminal classification;
- `app/session.py` — только те auth/quota/error seams, которые generic events не покрывают;
- private HOME/config materializer для agent prompt, settings и MCP;
- runtime and usage tests.

В repository уже лежат **4 skipped RED suites / 1495 lines** из #249:
`test_antigravity_runtime.py` (567), `test_antigravity_readiness.py` (447),
`test_antigravity_usage.py` (302), `test_antigravity_usage_frontend.py` (179).[M6] Это не готовый
oracle: test model list остановился на 3.6/3.5, не знает 3.7/3.8 и frozen под one-process-per-turn
1.1.12. Перед реализацией их нужно перепроверить и заново заморозить, а не просто снять skip.

Measured size аналогов: `backend_harness.py` 440 lines, `backend_grok.py` 1441,
`backend_codex.py` 2833.[M6] **Inference:** one-process Antigravity adapter должен быть ближе к
нижней половине этого диапазона, но per-worker HOME, MCP readiness и two-family quota добавляют
отдельную cross-cutting работу. Person-hours без Phase 2 plan и fresh RED tests не оцениваются.

### Ресурсы и эксплуатация

- Один общий 1.1.25 binary: **210436352 bytes**, stripped dynamically linked ELF.[M1]
- Private HOME нужен каждому concurrent worker; binary копировать не нужно. Рост authenticated
  conversation DB/logs не измерен на current version.
- Process RSS/CPU current authenticated turn не измерялись: login и расход чужой quota запрещены.
- Версию надо pin-ить и отключить self-update, иначе 18 releases/37 days меняют protocol под живым
  backend.[6][16][M5]
- Consumer subscription не создаёт прямого API invoice, но её usable pool непрозрачен; Pro/Ultra
  overages уже становятся credit spend по Gemini Enterprise Agent Platform pricing.[11]

## 7. Решение и следующий gate

### Сейчас

**Не переходить к Phase 2.** Технический spike больше не нужен для ответа «можно ли»: можно.
Нельзя безопасно использовать именно оплаченный/бесплатный consumer Antigravity login внутри
Orchestra по текущим Terms.[14][15]

### Что должно измениться, чтобы решение стало положительным

Достаточно одного из двух policy conditions:

1. Google письменно разрешает local wrappers, которые запускают официальный `agy`; либо
2. пользователь отдельно меняет правило «никаких API keys» и выбирает official SDK/CLI API-key
   или Vertex route с понятным billing owner.

После этого нужен один bounded live gate на собственном разрешённом account:

1. pinned `agy` version + disabled auto-update;
2. isolated HOME + worktree `--add-dir` в одном invocation;
3. exact resume после process restart;
4. Orchestra MCP canary до и после принудительного MCP child crash;
5. one persistent two-turn stdin session и external SIGINT;
6. `/usage` до/после 3–5 preregistered representative tasks.

Без policy change этот gate только жжёт quota и создаёт account risk, поэтому сейчас не запускается.

## Confidence по атомарным findings

| Finding | Confidence | Основание |
|---|---|---|
| `agy` имеет официальный machine-readable event stream | **CONFIRMED** | primary docs + current binary help + prior live stream [5][6][21][M2] |
| Один process принимает несколько последовательных turns | **CONFIRMED как contract** | primary docs/release + current help; no current authenticated run [5][7][M2] |
| Exact resume пригоден для Orchestra | **CONFIRMED** | primary docs + two-conversation live control #249 [5][21] |
| Полный production lifecycle Orchestra доказан | **PARTIAL / UNVERIFIED** | one-shot path proven; current persistent interrupt/retarget/MCP-crash recovery not run [5][18][19][21] |
| Mid-turn injection/control RPC отсутствует | **CONFIRMED** | primary protocol rejects control messages [5] |
| stdio MCP tool можно вызвать | **CONFIRMED** | primary config + live side-effect #249 [8][21] |
| MCP definition переживает restart process | **CONFIRMED** | 1.1.25 add + second-process list [M3] |
| MCP child автоматически восстанавливается после EOF | **UNVERIFIED на 1.1.25 local stdio** | #623 — adjacent older Windows/mcp-remote report, не current proof [18] |
| Consumer RPM/RPD известны | **REFUTED** | official Plans gives dynamic work-correlated windows, no counts [11] |
| Google AI Plus получает 5-hour Pro window | **REFUTED по current docs** | Plus попадает в «not Pro/Ultra» weekly group [11][12] |
| Consumer login разрешён third-party wrapper-у | **REFUTED** | explicit Terms + FAQ [14][15] |
| API-key/Vertex route существует | **CONFIRMED** | official CLI auth + official SDK docs [13][17] |
| Runtime стоит реализовывать сейчас | **REFUTED** | Terms blocker + project no-API-key rule |

## Counter-evidence и конфликты

- Official headless docs называют no-auth non-TTY path fail-fast, но isolated `setsid` probe всё
  ещё ждал OAuth после 20 seconds и объявил 60-second timeout. В production нужен watchdog.[5][M2]
- Official changelog заявляет fix false empty success в 1.1.18, но issue #840 остаётся open;
  defensive `empty response + zero usage = error` всё ещё нужен.[6][20]
- Plans отдельно обещает Ultra access к third-party models, а Models table ставит Claude/GPT
  checkmarks всем tier. Availability и quota entitlement нельзя выводить друг из друга.[11][12]
- Open issue #71 сообщает discovered-but-not-invocable remote MCP, но live #249 на 1.1.12 вызвал
  local stdio MCP и получил side effect. Для Orchestra local stdio path подтверждён; remote issue
  не переносится на него.[21][32]
- Старые wrappers подтверждают demand и operational patterns, но plain stdout/PTY/SQLite не
  доказывают current interface. Current proof берётся из official protocol и recent structured
  wrappers.[5][22][23][24]
- #249 считал официальный subprocess допустимым consumer route. Current Terms/FAQ формулируют
  запрет шире и отзывают этот вывод.[14][15][21]

## Review decision gate

- Изменённые artifacts: `docs/tasks/506/research.md`, новый topic `docs/kb/antigravity-runtime.md`,
  index `docs/kb/README.md`; consumers — будущие agents и пользовательский architecture decision.
- Author metadata: `model=gpt-5.6-sol`, `backend_type=codex`, role `full-cycle` — read from live
  `/api/sessions` record 2026-09-03, не выведено из имени.
- AC: GitHub integration table с file/date; Orchestra-vs-AGY contract; MCP lifecycle; quota
  windows/numbers; auth/data/closure risks; explicit go/no-go and missing gate.
- Mechanical checks: every GitHub row has pinned file link + commit date; every factual conclusion
  has opened primary source, code, task evidence or reproduced measurement; KB contract checker
  runs after topic update.
- Risk floor: external protocol + auth/Terms + secrets → high-risk. Canonical route is Sol, но
  отдельного Sol approval нет. По `codex-debate` используется один permitted Luna pass; если он не
  состоится, итог маркируется `Review: none — Codex unavailable/Sol not authorized`.

**Review outcome.** Luna round 1 нашёл два blocking overclaim: full-runtime compatibility и перенос
старых Windows/MCP reports на current local-stdio path. Оба исправлены и проверены в разрешённом
round 2; итог `APPROVED for Phase 1 research review`, новых findings нет. Completed-verdict evidence:
reviewer процитировал существующую строку «Полноценный production runtime пока условен;»;
артефакт — `docs/tasks/506/review-luna-research.md`. Первая фраза round 1 «Independent Luna review
was not run» противоречит metadata `reviewer_model=gpt-5.6-luna`, содержательным findings и
background completion; она не использована как verdict.

## Пробы и скачанные файлы

Все записи были только под `/tmp/agy-research-506.8ExvoM`, с отдельными `HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`. Ничего не ставилось в систему, пользовательские
`~/.config`, `~/.codex`, `~/.grok` не читались и не менялись. Login не завершался, account data не
вводились, model inference не выполнялся.

### Official binary

1. Скачан как файл, не `curl | bash`:
   `https://antigravity.google/cli/install.sh` → 7354 bytes,
   SHA-256 `ee1ea43ce4e9e56356c4ab6dad907ef357ae4bdfcaadb682735909fb57c9c640`.
2. Скрипт прочитан, затем запущен с scratch `HOME` и explicit `--dir`.
3. Manifest сообщил 1.1.25 и installer проверил payload SHA-512 до copy.
4. Получен `/tmp/.../bin/agy`: 210436352 bytes,
   SHA-256 `e552463e7cd479e342cfec3487f7b2de048b89548df74c610e3a58d1c2c9735b`.
5. Выполнены только `--version`, `--help`, `mcp --help/list/add`, unauthenticated headless probe.

### Source snapshots, только чтение

Через GitHub codeload скачаны и распакованы:

```text
agent-intern.tar.gz                    926826 bytes
agentgui.tar.gz                       1084208 bytes
agy-acp.tar.gz                         304491 bytes
agy-headless-bridge.tar.gz              34714 bytes
dsh-subagent-agy.tar.gz                 35413 bytes
mcp-server-google-antigravity.tar.gz    29299 bytes
ouroboros.tar.gz                      17198389 bytes
pi-ask-antigravity.tar.gz               54898 bytes
```

Отдельно shallow-cloned в тот же scratch HOME:

```text
KyongSik-Yoon/antigravity-agy       HEAD c9945c0ebf016762352e39d8efb089fcb7739035
tksfjt1024/antigravity-cli-mcp-slim HEAD 3621b399b2a29635c2a0822d4b5cc0225d5ad038
```

Ни один third-party package/build/test не исполнялся.

## Measurements

### M1 — binary artifact

```text
agy --version -> 1.1.25
size=210436352 bytes
sha256=e552463e7cd479e342cfec3487f7b2de048b89548df74c610e3a58d1c2c9735b
ELF 64-bit LSB pie, x86-64, stripped, dynamically linked
```

### M2 — current flags и unauthenticated behavior

`agy --help` показал `--input-format text|stream-json`, `--output-format
text|json|stream-json`, `--conversation`, `--agent`, `--model`, `--effort`, `--sandbox`,
`--print-timeout` и `mcp` subcommand.

```text
timeout 20s setsid agy -p 'Reply with exactly NOAUTH' --output-format stream-json </dev/null
RC=124
stdout result.status=ERROR, error="authentication failed or timed out", total_tokens=0
stderr: Waiting for authentication (timeout 60s)
```

### M3 — MCP persistence

Первый process `agy mcp add ...` записал 212-byte global config; второй process `agy mcp list`
прочитал server с точным command/arg и status `enabled`.

### M4 — pre-auth state/network

Чистый isolated HOME после no-auth run: 30 files, 106747 bytes. Log: telemetry propagation skipped
без login; три HTTPS попытки Playwright driver download завершились 404.

### M5 — release velocity

GitHub Releases API, interval 2026-07-28..2026-09-03:

```text
count=18
first=1.1.8 @ 2026-07-28T00:59:10Z
last=1.1.25 @ 2026-09-03T02:30:18Z
```

### M6 — local implementation surface

```text
existing skipped Antigravity tests: 567 + 447 + 302 + 179 = 1495 lines
backend_harness.py=440, backend_grok.py=1441, backend_codex.py=2833 lines
```

## Источники

1. `app/backend_protocol.py:8-16` — structural backend contract.
2. `app/runtime_registry.py:29-54,109-123,317-389` — build context and runtime capabilities.
3. `app/events.py:27-46` — unified event vocabulary.
4. `app/session.py:824-870,2236-2425` — backend construction and per-turn event consumer.
5. [Google: Headless mode](https://antigravity.google/docs/cli/headless/).
6. [Official Antigravity CLI changelog, pinned 1.1.25 tree](https://github.com/google-antigravity/antigravity-cli/blob/7e1316ca775dc3805aac13b2db5cd37d89d5aae8/CHANGELOG.md#L1-L148).
7. [Official release 1.1.15 — persistent stdin](https://github.com/google-antigravity/antigravity-cli/releases/tag/1.1.15).
8. [Google: MCP configuration](https://antigravity.google/docs/mcp).
9. [Google: CLI permissions](https://antigravity.google/docs/cli/permissions/).
10. [Google: custom agents](https://antigravity.google/docs/cli/commands/agents/).
11. [Google: Antigravity plans and quota windows](https://antigravity.google/docs/plans).
12. [Google: Antigravity models by tier](https://antigravity.google/docs/models).
13. [Google: CLI installation and authentication](https://antigravity.google/docs/cli/install/).
14. [Google: Antigravity FAQ, third-party access](https://antigravity.google/docs/faq/).
15. [Google Antigravity Additional Terms](https://antigravity.google/terms).
16. [Google: CLI troubleshooting and disabling auto-update](https://antigravity.google/docs/cli/troubleshooting).
17. [Official Antigravity SDK](https://github.com/google-antigravity/antigravity-sdk-python).
18. [Upstream issue #623 — MCP child not respawned](https://github.com/google-antigravity/antigravity-cli/issues/623).
19. [Upstream issue #657 — MCP startup five-minute freeze](https://github.com/google-antigravity/antigravity-cli/issues/657).
20. [Upstream issue #840 — empty SUCCESS](https://github.com/google-antigravity/antigravity-cli/issues/840).
21. `docs/tasks/249/research.md` — live 1.1.12 OAuth/quota/stream/tools/MCP/resume/isolation measurements.
22. [agent-intern `server.py`](https://github.com/SinanTufekci/agent-intern/blob/f5ef57d60779f2619185636d8b7f7750fe764249/server.py#L1928-L2074).
23. [dsh-subagent-agy `src/index.ts`](https://github.com/ZEM17/dsh-subagent-agy/blob/d520b9f690dbba9f8dafac09ebc79a5e1c5a8c8e/src/index.ts#L1247-L1370).
24. [antigravity-cli-mcp-slim `server.py`](https://github.com/tksfjt1024/antigravity-cli-mcp-slim/blob/3621b399b2a29635c2a0822d4b5cc0225d5ad038/src/antigravity_cli_mcp_slim/server.py#L57-L112).
25. [agy-acp PTY/DB adapter](https://github.com/shindgew/agy-acp/blob/54663f6ba56b2a93ededd8438373cfe9e71ff754/src/agy/cli.ts#L330-L470).
26. [agentgui legacy direct adapter](https://github.com/AnEntrypoint/agentgui/blob/78db2a894e0225c9c646e462daa3ba24cf07df63/lib/claude-runner-agents.js#L121-L142).
27. [Ouroboros legacy adapter](https://github.com/Q00/ouroboros/blob/27fa0ebb92c1a4537caa2dc283cff318a5622509/src/ouroboros/orchestrator/antigravity_cli_runtime.py#L120-L168).
28. [pi-ask-antigravity DB-discovery adapter](https://github.com/EstebanForge/pi-ask-antigravity/blob/875f8c73ddd54f85c97cbab31d5a65073055b4a5/extensions/index.ts#L1180-L1318).
29. [antigravity-agy companion](https://github.com/KyongSik-Yoon/antigravity-agy/blob/dd29556bee223c64fec561676899baab7f522638/plugins/agy/scripts/agy-companion.mjs#L102-L165).
30. [mcp-server-google-antigravity](https://github.com/TurkerYakup/mcp-server-google-antigravity/blob/5bb89ce89a505fdce1e751dac0b12f6bf6c3ae64/index.js#L600-L680).
31. [agy-headless-bridge PTY workaround](https://github.com/rhishi99/agy-headless-bridge/blob/abe1de8349a68eabe3c37813437eaf89d4566bda/src/agy_headless_bridge/bridge.py#L236-L319).
32. [Upstream issue #71 — remote MCP discovered but not invocable](https://github.com/google-antigravity/antigravity-cli/issues/71).
