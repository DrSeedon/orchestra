# #249 — Antigravity как четвёртый runtime Orchestra

Дата плана: **2026-08-13**. Исходная проверенная версия CLI: **1.1.12**.

## Решение и границы

Строим официальный `agy` subprocess runtime без API-ключа. Авторизация остаётся Google OAuth,
а backend не извлекает token для прямых запросов к Google: и inference, и `/quota`, и `models`
выполняет только официальный CLI.

Изоляция обязательна в двух независимых слоях:

1. каждый Orchestra session получает собственный `HOME` по доверенному
   `ORCHESTRA_SESSION_ID`; там живут cache, conversation DB/WAL, logs и scratch;
2. каждый `agy` turn получает `--add-dir <session.cwd>`, поэтому default workspace не уезжает
   в общий scratch. `--add-dir` задаёт workspace/tool-policy root, но не объявляется kernel
   sandbox: state/collision isolation обеспечивает именно private `HOME`.

Это namespace/collision isolation, а не adversarial credential isolation: все workers намеренно
работают под одним Unix user и разрешают `command(*)`, поэтому процесс с произвольной shell-командой
может адресно прочитать sibling HOME или canonical auth path. Это существующая trust boundary
Orchestra, не новое обещание #249. Настоящая защита от враждебного worker потребовала бы отдельного
Unix user/mount namespace или проверенного Antigravity sandbox; ни один из этих механизмов не
подтверждён Phase 1 и не подменяется словом «изоляция» в этом плане.

Операторская авторизация имеет один канонический source в
`data/antigravity-auth-home/.gemini/antigravity-cli/antigravity-oauth-token`. Перед turn token
атомарно копируется mode `0600` в private HOME, после завершения/interrupt удаляется. Копия не
symlink: CLI может обновлять token, и общий writable inode вернул бы гонку между workers. Рядом с
generation marker не хранится: generation равен `sha256` байтов token snapshot. Login валидируется
в staging без блокировки старого account, затем делает ровно один `os.replace` staged token в
canonical path. Поэтому crash оставляет либо целиком старый, либо целиком новый token, а generation
не может разойтись с credential. Новый login меняет вычисленный generation;
существующий Orchestra worker на следующем turn берёт новый token и начинает новый native
conversation вместо попытки возобновить ID другого Google account.

`app/static/**` и template не входят в backend-реализацию: frontend владеет T4 после #260.
Контракт уже согласован дословно и заморожен RED-тестом в этой ветке.

## Архитектура

### Runtime и модели

- Новый `app/backend_antigravity.py` реализует `BackendLike` как one-process-per-turn JSONL
  adapter; новый `app/antigravity_auth.py` владеет canonical path, atomic promotion и snapshot
  generation.
- Orchestra model ids namespaced как `antigravity/<raw-id>`, чтобы raw
  `claude-sonnet-4-6` не перехватил существующий alias на Claude runtime.
- Регистрируются все 11 IDs, возвращённые authenticated `models` на 1.1.12:
  `gemini-3.6-flash-{high,medium,low}`, `gemini-3.5-flash-{high,medium,low}`,
  `gemini-3.1-pro-{high,low}`, `claude-sonnet-4-6`,
  `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`.
- Явные aliases: `agy-flash` → `antigravity/gemini-3.6-flash-low`, `agy-pro` →
  `antigravity/gemini-3.1-pro-low`, `agy-sonnet`, `agy-opus`, `agy-gptoss`.
- Все модели получают консервативный Orchestra context cap `128_000`. Это внутренний ранний
  compact threshold, не заявление о provider window: exact per-model Antigravity limits CLI не
  отдал. Поднять cap можно отдельным measured change; завышать неизвестный предел нельзя.
- Provider/runtime metadata: runtime `antigravity`, provider `google-antigravity`, неизвестная
  цена остаётся `cost_unaccounted`; `$0.00` не выдумывается.
- Capabilities: `event_stream="per_turn"`, `mid_turn_inject=False`, `reconnect=False`,
  `hibernate=False`, `process_liveness=True`, `resume=True`,
  `resume_across_models=False`. Model encoded in persisted native conversation is not silently
  changed across raw model ids.

### Invocation and event contract

Каждый turn запускает pinned/supported `agy` с global flag до subcommand/prompt:

```text
agy --output-format stream-json --model <raw-id> --agent orchestra \
    --add-dir <cwd> [--conversation <exact-id>] -p <message>
```

`--dangerously-skip-permissions` не используется: upstream issue #36 показывает, что вместе с
sandbox он разрешает agent обойти sandbox. Private settings/custom-agent policy должны заранее
разрешить ровно `command(*)`, `read_file(*)`, `write_file(*)` и `mcp(*)` под
`permission.allow`. Custom agent frontmatter фиксирует `mainAgent: true`, `subagent: false`,
`inheritMcp: true`, `commandExecutionPolicy: always-proceed`; остальные native tool families не
разрешаются. Soft-denied tool остаётся видимой ошибкой, а не terminal SUCCESS. System prompt
доставляется через private
`~/.gemini/config/agents/orchestra/agent.md`, MCP — через private
`~/.gemini/config/mcp_config.json`; оба публикуются атомарно и mode `0600`. MCP secrets не попадают
в argv; raw vendor stderr redacted against all configured MCP env values before any log/event.

Parser:

- `init.conversation_id` и `result.conversation_id` обновляют exact native session id;
- `agent_response.text_delta` → ephemeral `stream`, terminal `result.response` → один persisted
  `text` без дублей;
- tool ACTIVE → `tool_use`; DONE/ERROR → `tool_result` с stable step-derived id и `is_error`;
- любой ERROR tool step делает terminal turn `ok=False`, даже если `result.status="SUCCESS"`;
- `result.usage` → `TurnUsage`; current-context semantics неизвестны, поэтому backend не
  вычисляет ложный `context_pct`;
- auth/eligibility/model/quota terminal failures классифицируются громко, не ретраятся как
  transient server errors, и всегда завершают turn.
- Native Antigravity subagent surface в этой версии не публикуется
  (`RuntimeCapabilities.subagents=False`): её event lifecycle живьём не проверялся. Orchestra
  delegation через `spawn_worker` остаётся обычным MCP tool use и этим флагом не выключается.

Manual compact использует существующий generic `AgentSession.compact()`:
summary turn → disconnect → `force_fresh=True` → summary preamble. Claude-specific subscription
guard применяется только к Claude runtime; Antigravity compact проверяет собственную readiness и
свою quota group.

### Readiness, account rotation and degradation

#249 не создаёт второй spawn gate. После merge #247 runtime регистрирует единственный
`RuntimeDefinition.readiness` callback; coordinator остаётся
`app/spawn_readiness.py::admit_planned_spawn()` в порядке route → runtime readiness → quota.

Antigravity readiness использует канонический auth HOME и одну singleflight probe:

1. exact CLI version/support check;
2. `agy --output-format json -p /quota` — `status=SUCCESS`, обе exact bucket ids и валидные поля;
3. `agy --output-format json models` — requested raw model присутствует;
4. нормализованный `/quota` snapshot кладётся в общий cache, чтобы quota stage и `/api/usage` не
   запускали второй CLI процесс.

Missing token, OAuth prompt, location/eligibility failure и отсутствие requested model дают
credential/catalog not-ready и отказывают **до** AgentSession/worktree/DB publication. Неизвестная
quota остаётся в политике #247 (quota exception fail-open с ERROR), но credential/catalog unknown
fail-closed. Первый `send` не повторяет admission.

Если account/token исчез после admission, backend выдаёт terminal `error` + `turn_end(ok=False,
model_error="credentials")`, оставляет worker видимым/idle и не делает retry storm. Оператор
повторяет login script; следующий turn того же Orchestra worker подхватывает новую generation.

### Quota contract

`/quota` имеет две независимые weekly группы и ни одна не выводится из другой:

- `gemini-weekly`: все `antigravity/gemini-*`;
- `3p-weekly`: `antigravity/claude-*` и `antigravity/gpt-oss-*`.

Backend `/api/usage` contract (согласован с frontend):

```json
{
  "antigravity": {
    "gemini-weekly": null,
    "3p-weekly": {
      "remaining_fraction": 0.17,
      "reset_time": "2026-08-20T07:47:15Z"
    }
  }
}
```

Оба exact key присутствуют всегда. Value — `null` либо object с finite
`remaining_fraction` в `[0,1]` и ISO-8601/null `reset_time`. Missing/malformed/unavailable никогда
не становится `0`. Для scheduler/history эти же данные нормализуются в два provider bucket
`antigravity_gemini` и `antigravity_3p` с `utilization=(1-remaining_fraction)*100`, weekly window
10080 minutes и одним observation timestamp. Existing 95% worker threshold применяется к
выбранной группе, не к max/sum двух групп.

### Account-change runbook

`scripts/antigravity-login.sh` — единственная operator entry point. Он:

1. создаёт staging HOME mode `0700`;
2. запускает официальный browser-code OAuth в controlling TTY без API key;
3. валидирует `models` и zero-token `/quota`;
4. только после двух SUCCESS одним `os.replace` публикует canonical token mode `0600`; generation
   вычисляется как `sha256` опубликованных bytes;
5. при любой ошибке сохраняет предыдущий canonical credential и удаляет staging HOME.

Документ `docs/antigravity-runtime.md` даёт копируемые команды от `ssh` до проверки `/api/usage`,
показывает cleanup derived worker copies и объясняет: существующие Orchestra workers не
пересобираются, но native conversation сменившего account worker начнётся fresh на следующем turn.

## Порядок интеграции и владение

- **External #247 T1:** должен быть merged до T3. До merge не редактировать
  `app/spawn_readiness.py`, `app/runtime_registry.py`, `app/manager.py`, `app/session.py` и #247
  tests одновременно с `prompt-engineer`.
- **External #260:** должен быть завершён до T4. Frontend владеет `app/static/js/utils.js`,
  `app/static/js/usage.js`, `app/static/css/style.css` и реализацией T4.
- Backend contract T2 фиксирован и не переименовывается frontend-слоем.
- Никаких live inference/benchmark через corporate account. Все Phase 3 tests используют fake
  `agy`; будущий собственный supported-region account требует отдельного минимального canary перед
  production enablement.

## Что не делаем

- не используем API key, Vertex project или прямой Google API;
- не встраиваем старый consumer `gemini-cli`;
- не используем `-c` (mutable last conversation) — только exact `--conversation <id>`;
- не делим HOME/token inode между workers;
- не переносим raw Antigravity vendor ids в существующие Claude/Codex aliases;
- не угадываем absolute weekly requests/tokens или dollar prices;
- не правим template: существующий `<div id="usage-bar">` достаточен;
- не включаем runtime в production model-routing до собственного account и minimal canary.

## Tickets

### RED freeze lineage

`227a376f3eb427cda3b22e516af3e4f681e4451b` is **SUPERSEDED**: Codex round 1 exposed
missing crash-atomic rotation, neighbor-process interrupt and stderr-redaction oracles. No Phase 3
implementation or replay used that freeze. The ticket fields below point to the replacement freeze.

`05f52e8ad2b819d8766ea6c18732c6ff1e4625eb` is also **SUPERSEDED before implementation**:
Phase 3 approval strengthened the stderr canary from a human-readable placeholder to a runtime
string matching `ya29\.[A-Za-z0-9_-]{40,}`. The current freeze is named in every ticket below.

### T1 — Один изолированный Antigravity worker от model route до terminal event

- Files: `app/backend_antigravity.py` (new), `app/antigravity_auth.py` (new),
  `app/runtime_registry.py`, `app/models.py`, `app/session.py`,
  `tests/test_antigravity_runtime.py` (frozen RED)
- Test: `uv run pytest -q tests/test_antigravity_runtime.py -k t1`
- RED commit: `e9f8c2726b18dec1ab26f18b51642d9ab56be8d9`
- RED assertion: `assert runtime is not None, "Antigravity runtime is not registered"`
- AC: named command is green; all 11 namespaced models and five aliases resolve exactly; raw
  `claude-sonnet-4-6` still resolves to Claude runtime; two concurrent fake turns receive distinct
  mode-0700 HOME paths and exact `--add-dir`; custom agent/settings/MCP files are atomic mode-0600;
  fake CLI writes a runtime-built `ya29.` token-shaped sentinel to stderr; that exact value is
  absent from argv and redacted from captured stderr/log/events;
  stream/text/tool/tool_result/usage/turn_end mapping is
  exact; a tool ERROR overrides terminal SUCCESS; exact resume uses `--conversation <id>` and
  never `-c`; interrupt kills only the owned process; private token copies are removed after exit;
  manual compact takes the generic summary→fresh path even when Claude quota is blocked
- blocked-by: external #247 T1 merged (shared `runtime_registry.py`/`session.py` ownership)

### T2 — Две quota groups от zero-token CLI до API, history и routing gate

- Files: `app/backend_antigravity.py`, `app/routes/system.py`, `app/quota_gate.py`,
  `tests/test_antigravity_usage.py` (frozen RED)
- Test: `uv run pytest -q tests/test_antigravity_usage.py`
- RED commit: `e9f8c2726b18dec1ab26f18b51642d9ab56be8d9`
- RED assertion: `assert callable(normalize), "Antigravity quota normalization is missing"`
- AC: named command is green; `/api/usage.antigravity` has exactly `gemini-weekly` then
  `3p-weekly`; `.62/.17` remain fractions at API boundary and normalize to independent 38%/83%
  weekly history buckets; missing/malformed/NaN/out-of-range data becomes null, never 0; cache is
  singleflight and preserves stale timestamp on failed refresh; quota gate maps Gemini vs
  Claude/GPT models to their exact group and applies 95% independently; unknown future
  Antigravity model fails closed; unavailable telemetry remains visibly unknown
- blocked-by: T1

### T3 — Штатная смена Google account и fail-loud spawn readiness

- Files: `scripts/antigravity-login.sh` (new), `docs/antigravity-runtime.md` (new),
  `app/antigravity_auth.py`, `app/backend_antigravity.py`, `app/runtime_registry.py`,
  `tests/test_antigravity_readiness.py` (frozen RED). `app/spawn_readiness.py`, `app/manager.py`
  and `tests/test_spawn_readiness.py` remain owned by #247; #249 consumes their merged public
  contract and adds no second gate.
- Test: `uv run pytest -q tests/test_antigravity_readiness.py`
- RED commit: `e9f8c2726b18dec1ab26f18b51642d9ab56be8d9`
- RED assertion: `assert script.is_file(), "account rotation entry point is missing"`
- AC: named command is green; fake successful login promotes one mode-0600 canonical token with
  exactly one `os.replace` only after `models` and `/quota` SUCCESS; generation is the `sha256` of
  the same token snapshot, so no crash window can pair different accounts; fake failed login leaves previous credential
  byte-identical and removes staging files; existing backend picks new generation on next turn,
  drops old native conversation id and requires no worker/worktree recreation; readiness
  rejects missing token, OAuth prompt, eligibility ERROR, unsupported CLI version and missing
  requested model before AgentSession/worktree/DB publication; one spawn performs one admission
  and first send does not repeat it; post-admission credential loss yields a visible terminal
  credentials error with no retry storm; runbook copied commands contain no API-key path and its
  verification step reads the exact two `/api/usage` keys
- Cross-contract regression AC after #247 merge:
  `uv run pytest -q tests/test_spawn_readiness.py -k 'missing_runtime_credentials_leave_no_session_or_worktree or initial_delivery_reuses_loud_fail_open_spawn_admission'`
  is green. The frozen #249 test proves the Antigravity callback returns credential/catalog
  not-ready; these two frozen #247 tests prove that any such result is refused before
  AgentSession/worktree/DB publication and is not admitted again on first send.
- blocked-by: T1, T2, external #247 T1 merged

### T4 — Две Antigravity полосы в persistent usage bar без возврата overflow

- Files: `app/static/js/utils.js`, `app/static/js/usage.js`, `app/static/css/style.css`,
  `tests/test_antigravity_usage_frontend.py` (frozen RED); owner: `frontend`, after #260
- Test: `uv run pytest -q tests/test_antigravity_usage_frontend.py`
- RED commit: `e9f8c2726b18dec1ab26f18b51642d9ab56be8d9`
- RED assertion: `assert measured["providers"] == ["claude", "codex", "grok", "antigravity"]`
- AC: named command is green; compact order Claude → Codex → Grok → Antigravity; inner order
  `gemini-weekly` → `3p-weekly`; fixture `.62/reset=A` and `.17/reset=B` renders two distinct
  blocks with 38%/83% and distinct countdowns in compact and hover/detail; null or missing key
  remains an explicit `нет данных`, never `0%`; deletion of either mapping or mapping both blocks
  to one payload fails the frozen test; at 1280/1440/1680/1920 every provider block exists,
  `#usage-info-btn.right <= viewport`, `#usage-bar.scrollWidth == clientWidth`, wrapping remains
  allowed, controls remain visible, and `$cost`/agent count stay absent from permanent bar
- blocked-by: T2, external #260 completed

## Phase 3 verification

Focused commands above run first per ticket. After all tickets:

```bash
uv run python -m pytest -q > /tmp/pytest-249.log 2>&1
```

Then read the log once, confirm `uv.lock` unchanged, run the frontend test at all four widths, and
perform secret-form scan over all new fixtures/docs (`ya29.`, `Bearer <25+>`, `AIza`, token-shaped
JSON). No live `agy` inference is part of acceptance. Production enablement is a separate operator
decision after login on an owned eligible account and one minimal canary.
