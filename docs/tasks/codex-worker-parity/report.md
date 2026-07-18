# Claude ↔ Codex workers: runtime parity report

Дата проверки: 2026-07-18. Проверены локальный код Orchestra, production-логи,
Claude Agent SDK 0.2.114, Claude Code 2.1.197, Codex CLI и сгенерированная этой
версией Codex CLI 0.144.5 JSON Schema `codex app-server`.

## Результат

Главный разрыв закрыт: Codex worker больше не обязан ждать конца хода, чтобы
получить новое сообщение. Backend переведён с одноразового `codex exec --json`
на persistent `codex app-server`; первое сообщение вызывает `turn/start`, а
сообщение во время работы — `turn/steer` с precondition по активному turn id.

Живой smoke:

```text
initial:  Run `sleep 2`, then answer exactly: BASE
steering: Append STEERED to the final answer
result:   BASE STEERED
turn:     completed
```

То есть это нативный same-turn steering Codex, а не очередь Orchestra.

Старый subprocess backend передавал `-m` только при создании thread, но не при
`codex exec resume`. Поэтому смена глобального `model` в `~/.codex/config.toml`
могла неожиданно возобновить worker другой моделью. Persistent adapter задаёт
модель явно и при resume, и на каждом новом turn.

## Сравнение фактических контрактов

| Контракт | Claude worker | Codex worker после изменения |
|---|---|---|
| Transport | Persistent `ClaudeSDKClient` + Claude CLI | Persistent JSON-RPC/JSONL `codex app-server` |
| Conversation | SDK session id | App-server thread id |
| Model selection | Explicit SDK model per session | Explicit model on `thread/start`, `thread/resume` and every `turn/start`; native Codex global default cannot leak into managed workers |
| Новый ход | `query()` | `turn/start` |
| Сообщение во время хода | SDK inject через stdin | `turn/steer(expectedTurnId=...)` |
| Когда сообщение всё же ставится в очередь | Compact, transport error | Compact, non-steerable/settling turn, protocol error |
| Resume | Локальный Claude transcript по session id | `thread/resume` по Codex thread id |
| Потерянный локальный transcript | Раньше вечный `connect exit 1`; теперь fresh session + bounded handoff из DB-логов | Resume error остаётся видимым; Codex rollout/thread не подменяется молча |
| Процесс | Persistent, умеет hibernate/reconnect | Persistent app-server; hibernate пока не включён |
| Web | Нативные WebSearch/WebFetch Claude | Нативный Codex WebSearch принудительно `live`; события видны в UI |
| Shell/files | Claude Code tools | Codex command/file-change items |
| Images/dynamic tools | Через доступные Claude/MCP tools | App-server image view/generation и dynamic tool items поддержаны адаптером |
| Skills | Claude settings + role skills в worktree | Codex skills + role skill content в developer instructions |
| MCP managed worker | Полный worker-specific merge | Явный `enabled=true` + полный allowlist; глобальный read-only больше не протекает |
| MCP обычного Codex | Раньше Orchestra была disabled | 13 read-only tools; mutations скрыты клиентом и самим MCP server |
| Native subagents у worker | Claude Task/Agent, Task* telemetry | Codex collaboration items, telemetry отображается как subagent |
| Native subagents у orchestrator | Заблокированы; делегирование через Orchestra | `features.multi_agent=false`; делегирование через tracked Orchestra workers |
| Reasoning | Thinking blocks | Финальный reasoning summary; agent text стримится дельтами |
| Context/usage | SDK usage events | App-server token usage; rollout остаётся fail-soft fallback |
| Network failure | SDK error + fresh transport retry | Typed Codex errors → `server_error` → fresh app-server/thread resume retry |
| Approvals | Auto-approve с явными blocked tools | `approvalPolicy=never`, `danger-full-access`; неожиданный client request отклоняется, а не зависает |

## MCP policy

Обычный native Codex получает только:

```text
test_lock_status
list_agents
list_orchestrators
get_worker_logs
list_jobs
check_conflict
worker_wip
get_worker_info
task_list
task_get
payment_status
bg_list
search_memory
```

`spawn_worker`, `send_message`, `kill_worker`, изменения задач/платежей,
background jobs и остальные mutations ему не экспонируются. Ограничение
двойное:

1. `enabled_tools` в глобальном Codex config.
2. `ORCHESTRA_ACCESS_MODE=read-only` удаляет mutations из server tool registry.

Managed worker получает server mode `full` и явный allowlist всех 35 Orchestra
tools. Проверка итогового Codex config показала `enabled: true`, 35 tools и
stdio transport.

## Что произошло с упавшими Sol workers

Это не лимит и не модельная ошибка:

```text
13:15:23  contabo tunnel died; SSH channels: Connection timed out
13:15–18  новый Orchestra tunnel не мог занять :12343: Address already in use
13:17     Codex WebSocket retries закончились, включился HTTPS fallback
13:17–19  HTTPS получил TLS unexpected EOF / decode errors
13:19:37  impl-codex-limits, research-sol-models, research-precompact → idle
13:20:02  research-codex-orchestration → idle
13:20:43  :12343 снова поднялся
```

Одновременно Orchestra и user-systemd управляли частью SSH forwards. Новый
startup-контракт Orchestra принимает уже занятый локальный forward как
externally managed и не убивает/не пересоздаёт его. Собственный Contabo forward
остаётся под Orchestra. Это убирает restart war; upstream VPS всё ещё может
оборваться, но typed retry теперь переживает обычное короткое восстановление.

## Sensar orchestrator

Запись Orchestra сохранила Claude session id и метрику `311412/1000000`, но
соответствующего локального Claude JSONL transcript больше нет. Поэтому две
попытки resume завершались до первого turn одинаковым CLI `exit 1`. Контрольный
fresh connect с той же моделью и cwd прошёл, значит модель, auth и текущий proxy
исправны.

После применения к running service backend:

1. Архивирует протухший session id в `session_id_history`.
2. Начинает новую нативную Claude session.
3. Передаёт до 32k последних user/assistant логов Orchestra.
4. Сбрасывает старый UI context percentage.

Полные 311k, hidden reasoning, cache и незаписанные tool state восстановить
нельзя: локальный первичный transcript удалён. Логи дают содержательный handoff,
но это не побитовое продолжение старой Claude session.

## Frontend

Dashboard теперь отдельно показывает:

- жёлтый `Codex reconnecting` с причиной transport error;
- голубой `Message steered into the current Codex turn`;
- встроенный `WebSearch`;
- Codex collaboration как обычные раскрываемые subagent cards;
- финальные command/MCP results и reasoning summary.

Headless Chromium подтвердил все четыре блока и ноль JavaScript errors.
`networkidle` для dashboard неприменим из-за долгоживущих SSE/polling
соединений, поэтому smoke ждёт `domcontentloaded`, `#chat` и короткую
стабилизацию DOM.

## Оставшиеся ограничения

1. `codex app-server` — официальный deep-integration interface, но его CLI
   subcommand всё ещё помечен experimental. Адаптер проверен против схемы
   установленной версии; upgrade Codex требует regression smoke.
2. Live command-output deltas пока не рисуются посимвольно. Вызов виден сразу,
   агрегированный stdout/stderr — после item completion.
3. App-server client не реализует интерактивные approvals и MCP elicitation:
   autonomous worker работает с `never`; неожиданный server request получает
   явный JSON-RPC error.
4. `danger-full-access` необходим текущему worktree/git/MCP workflow, но git
   worktree не является security sandbox. Codex и Claude workers всё ещё
   доверенные локальные процессы с доступом пользователя.
5. Активный proxy остаётся единым значением из `.env`. Скрытого hot-switch между
   странами нет; восстановление выполняют SSH tunnel restart и backend retry.
6. Изменения backend/runtime/tunnel требуют явного restart `orchestra.service`.
   В рамках этой работы сервис не перезапускался.

Официальный протокол: [Codex App Server](https://developers.openai.com/codex/app-server).
