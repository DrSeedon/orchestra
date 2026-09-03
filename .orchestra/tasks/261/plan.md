# #261 — план: X-поиск как один фоновый Grok-тул

Дата: 2026-08-13. Фаза 2. Основание: одобренный `research.md`; реализации ещё нет.

## Цель и граница

Добавить `grok_x_search(question: str)`, который возвращается сразу, создаёт один `run` bg job на
Grok 4.5 и будит вызывающего после появления артефакта
`docs/tasks/<current-task-id>/grok-x-<run-id>.md`.

Успешный артефакт — не ответ модели. Это независимо собранный retriever report:

- canonical URL — из `publish.twitter.com/oembed`;
- timestamp — из X snowflake id;
- fragment — только из oEmbed HTML;
- provenance — тот же post id был входом completed native `x_thread_fetch`;
- model-authored summary, quote, suffix и raw answer не публикуются никогда.

Поток:

```text
grok_x_search(question)
  → credential + authenticated catalog + central fresh billing AVAILABLE
  → bg run (120 s)
  → atomic attempt claim
  → one Grok 4.5 turn
  → JSONL validator + oEmbed
  → atomic validated artifact
  → usage (nonfatal) + caller wakeup
```

Не входят: обязательная pipeline-фаза, Grok-worker, API-ключ, промпты ролей, свободный synthesis,
точный долларовый cap, provider-side X-call cap, изменение общего `BgJobManager`.

## Решения до реализации

### Fail-closed admission

`app/quota_gate.py` остаётся единственным владельцем admission-решения и versioned envelope.
Dedicated route делает свежий billing request на каждый вызов и передаёт observation/failure в
`evaluate_grok_x_admission()`; dashboard cache и route-код не классифицируют решение сами. Wire
contract использует общую v2-форму readiness:

```text
policy = grok-x-subscription-v1
wire_version = 2
decision_state = available | blocked | unknown
provider = grok; model = grok-4.5; threshold = 100
observed_at + valid_until обязательны
```

- weekly utilization `<100` → `available`;
- utilization `>=100` или billing HTTP 429 → `blocked` с reason `exhausted`;
- no credential, 401, network/timeout, malformed response → `unknown`.

Это не меняет worker policy: обычный `get_worker_admission(grok)` остаётся `not_applicable`, потому
что его 95%-резерв относится к спавну воркеров, а этот точечный spend разрешён до фактического
исчерпания по решению задачи. Разные thresholds и observation loaders живут в одном owner и одном
state vocabulary, а не в двух route-level политиках. Только `available` разрешает
`POST /api/bg/jobs`. Ошибочный отказ теряет один X-result и допускает поздний повтор; ошибочное
разрешение расходует пул и роняет фоновую доставку. Поэтому unknown и blocked блокируются до job,
`retryable=false`; endpoint сохраняет категорию причины, но никогда не возвращает credential/token.

### Принудительный запрет синтеза

JSON schema просит у модели только массив `post_urls` (1–5). Finalizer трактует весь model text
только как список кандидатов. В Markdown нет пути, который форматирует model summary или
`verbatim_text`: fragment строится из независимо полученного oEmbed response. Каждый опубликованный
decimal post id обязан буквально совпасть с `post_id` completed `x_thread_fetch`; факт любого
другого fetch не разрешает candidate. Невалидный кандидат отбрасывается; ноль независимо
подтверждённых постов означает nonzero failure и отсутствие success artifact. Больше шести
completed native X calls, любой completed non-X tool, неединственный/неуспешный terminal `end`,
не `grok-4.5-build` или `num_turns>1` отвергают весь результат до записи.

oEmbed `author_name`/`author_url` используются не как output: контракт наружу содержит только URL,
timestamp и fragment. oEmbed подтверждает источник, но его body остаётся недоверенным
пользовательским текстом. Каждая
строка fragment принудительно публикуется только внутри Markdown blockquote (`> `); ни heading,
HTML comment, fence, ни вложенный success marker из поста не могут стать структурой отчёта.

### Бюджет и replay

Предварительно принуждаются один agent turn и 120 секунд wall time. Число native X calls известно
только после хода: `>6` — integrity reject, а не обещание сэкономить уже сделанный расход.
Runtime `total_cost_usd_ticks` сохраняется как telemetry, но не называется billing truth.

Run state живёт в platform-owned persisted каталоге
`<orchestra-checkout>/data/grok-x-runs/<run-id>/`, заданном `GROK_X_RUN_ROOT`, а не в worktree
вызывающего проекта. Так вызов из scope, где `data/` tracked или не ignored, не пачкает чужой Git:

- `question.txt` (0600), `attempt.started` (0600, `O_CREAT|O_EXCL|O_NOFOLLOW`), `run.jsonl`,
  `run.stderr`;
- готовый файл считается переиспользуемым только с точным первым маркером
  `<!-- grok-x-validated:v1 -->`;
- marker без validated artifact → `attempt_outcome_unknown`, Grok второй раз не запускается;
- marker не удаляется после ошибки. Две параллельные команды могут пересечь ровно один atomic claim.

Так обычный `restore_from_db()` может переисполнить shell command, но повторный command не может
повторить provider spend.

## Изменения по файлам и символам

### `app/routes/system.py`

- `GrokBillingExhausted` сохраняет HTTP 429 как отдельную семантику.
- `_fetch_grok_usage()` различает 401, 429 и прочие ошибки.
- Новый `@router.get("/api/usage/grok-x-readiness") async def grok_x_readiness()` получает fresh
  observation/failure и делегирует решение + envelope в `app/quota_gate.py`; `_grok_usage_cache`
  остаётся dashboard-only.
- `tests/route_surface_snapshot.json` обновляется в том же implementation commit.

### `app/quota_gate.py`

- `evaluate_grok_x_admission()` и `grok_x_readiness_envelope()` — единственный owner state mapping,
  threshold=100, freshness и v2 wire для spend-tool; `worker-weekly-v1` и Grok
  `not_applicable` для обычного worker spawn не меняются.
- Используется общий vocabulary `available | blocked | unknown`; `exhausted` остаётся reason/error
  provenance, не несовместимым четвёртым state token.

### `app/grok_x_artifact.py` (новый)

- собирает ordered `type=text.data`, извлекает последний JSON object с `post_urls`;
- считает completed tool updates по native trace, проверяет terminal/model/turn budget;
- сверяет exact equality трёх id: candidate URL, completed `x_thread_fetch(post_id)` и canonical
  oEmbed URL; затем декодирует snowflake;
- извлекает только первый `<p>` из oEmbed HTML, HTML-unescape + whitespace normalization и
  Markdown-quoting каждой строки недоверенного fragment;
- атомарно пишет Markdown с success marker; существующий artifact не трогает при validation error;
- после artifact делает идемпотентный `turn_usage_add(runtime="grok", model="grok-4.5")` по terminal
  ticks/tokens и preflight quota sample. Accounting failure добавляет warning, но не уничтожает
  оплаченный validated result.

### `app/backend_grok.py`, `app/grok_x_runner.py` (новый)

- module-level `build_grok_env(mcp_env=None, is_orchestrator=False)` становится одним owner
  proxy stripping, telemetry hard-off и managed `GROK_HOME`; `GrokBackend._build_env()` делегирует
  ему без изменения worker semantics.
- `AttemptOutcomeUnknown`, `_claim_attempt()`, `build_grok_x_command()`, `_invoke_grok()`,
  `run_grok_x_once()` и `main(argv)` реализуют `O_CREAT|O_EXCL|O_NOFOLLOW` claim, один subprocess,
  tested command/env builders, CLI parse и вызов настоящего finalizer.
- argv пинит `grok-4.5`, high effort, `--max-turns 1`, no memory/plan/subagents, always approve,
  disabled web, disallowed code/filesystem/task tools, streaming JSONL и schema только с
  `post_urls`. Prompt читается из файла; вопрос не попадает в shell argv/SQLite job config.

### `app/mcp_stdio.py`

- `@mcp.tool() async def grok_x_search(question: str)` — единственный публичный аргумент;
  question после trim имеет 1–4000 символов, current task id обязан быть decimal.
- `_grok_x_catalog_preflight()` proxy-free и telemetry-hard-off вызывает `grok models` с 15 s
  timeout через общий `build_grok_env()`; нужны одновременно rc=0, literal logged-in banner и
  exact parsed model entry `grok-4.5` независимо от default model. `grok-4.50`, banner как часть
  diagnostic-строки и конфликт logged-in/logged-out не принимаются. Timeout имеет отдельный
  fail-closed `grok_catalog_timeout`. Каждый отказ запрещает job.
- После authenticated catalog вызывается `/api/usage/grok-x-readiness`; только exact policy +
  wire v2 + provider/model + fresh `available` продолжают путь; incompatible, expired, future и
  malformed envelope становятся `grok_quota_unknown` до job.
- MCP создаёт 0600 prompt file под platform-owned `GROK_X_RUN_ROOT`, а bg command получает только
  безопасно quoted paths и usage
  attribution. Job: `timeout_seconds=120`, `success_file`, exact success marker pattern, immutable
  caller routing через существующий bg route. `success_pattern` привязан к первому байту artifact,
  поэтому marker внутри недоверенного post fragment не проходит bg gate.
- Каждый path/attribution argv-аргумент проходит `shlex.quote`; round-trip обязан сохранять одним
  argv-значением пробелы, кавычки, `;` и `$()` из caller worktree без shell execution.
- Tool description и immediate result содержат `END YOUR TURN NOW`; full result читается из
  artifact, не из 3000-character notification tail.
- `grok_x_search` добавляется в `REDUCER_MCP_TOOLS`, но не в `READ_ONLY_MCP_TOOLS`. Так он доступен
  каждой production pipeline role (`reducer` либо `full`) без изменения read-only semantics.

### Tests

- новые `tests/test_grok_x_tool.py`, `tests/test_grok_x_artifact.py`,
  `tests/test_grok_x_runner.py` — frozen RED ниже;
- расширяются существующие `tests/test_backend_grok.py`, `tests/test_codex_usage.py` и route
  snapshot только для regression coverage общей env/usage проводки; frozen tests не меняются.

## Миграция, выкладка, риски

DB migration нет. Python route, MCP schema и новые модули требуют загрузки нового процесса:
Orchestra service restart для HTTP route и reconnect агентов для уже живущих MCP subprocess.
План не авторизует restart/deploy.

Риски и ближайшие проверки: oEmbed outage/protected/deleted post → fail without artifact; dynamic
catalog без 4.5 → fail before job; raw JSONL остаётся только в platform-owned ignored `data/`;
output path и run dir server-generated; question не появляется в command/DB; outer timeout убивает
process group, marker уже сохранён; notification failure не удаляет artifact; provider usage
остаётся estimate.

## Prompt handoff — владелец Orchestra-orchestrator

Промпты этот ticket не меняет. Дословная строка для отдельной вставки владельцем:

> Нужны мнения людей, реакция на событие или свежие обсуждения в X, которых нет в обычном веб-поиске → вызови `grok_x_search` и закончи ход.

## Tickets

### T1 — Fresh subscription admission

- Files: `app/quota_gate.py`, `app/routes/system.py`, `tests/route_surface_snapshot.json`,
  `tests/test_grok_x_tool.py` (frozen).
- Test: `uv run python -m pytest -q tests/test_grok_x_tool.py -k 'test_t1_'`
  — committed RED in `7bd8d41b`.
- AC: named command is green; `/api/usage/grok-x-readiness` makes a fresh classified billing read;
  `quota_gate.py` owns the standard v2 decision; cached available data cannot authorize
  missing/401/429/network/malformed state; real `_fetch_grok_usage` maps HTTP 429 to exhausted
  provenance before generic HTTP handling.
- blocked-by: none.

### T2 — Independently verified artifact

- Files: `app/grok_x_artifact.py`, `tests/test_grok_x_artifact.py` (frozen).
- Test: `uv run python -m pytest -q tests/test_grok_x_artifact.py` — committed RED in
  `7bd8d41b`.
- AC: named command is green; success artifact contains only canonical oEmbed identity/body and
  snowflake timestamp, never oEmbed author fields; candidate, completed fetch and canonical oEmbed
  ids are equal; model-authored sentinel text is absent; untrusted oEmbed lines remain quoted;
  exactly 6 X calls pass while >6, completed non-X,
  malformed terminal/model/turn and zero verified posts leave any prior artifact untouched; usage
  records `runtime=grok`, `model=grok-4.5`, correct tokens/cost and an idempotent event id; usage
  failure is visible but nonfatal after artifact.
- blocked-by: none.

### T3 — Crash-safe single-attempt runner

- Files: `app/backend_grok.py`, `app/grok_x_runner.py`, `tests/test_backend_grok.py`,
  `tests/test_grok_x_runner.py` (frozen).
- Test: `uv run python -m pytest -q tests/test_grok_x_runner.py` — committed RED in
  `7bd8d41b`.
- AC: named command is green; marker exists before spawn, survives failure, validated artifact is
  reusable, marker+no-valid-artifact refuses replay, claim uses
  `O_CREAT|O_EXCL|O_NOFOLLOW` mode `0600`, concurrent commands spawn exactly once, argv pins
  model/capabilities/turn budget, `_invoke_grok` uses those command/env builders, shared env keeps
  all telemetry/proxies closed.
- blocked-by: T2.

### T4 — Background MCP tool for every pipeline role

- Files: `app/mcp_stdio.py`, `tests/test_grok_x_tool.py` (frozen),
  `tests/test_mcp_stdio.py`, `tests/test_reducer_role.py`.
- Test: `uv run python -m pytest -q tests/test_grok_x_tool.py` — committed RED in
  `7bd8d41b`.
- AC: named command is green; schema has only required `question`; reducer and full can call while
  read-only cannot; catalog requires exact authenticated banner/4.5 entries under a 15 s timeout and
  every failure stops before job; unknown/blocked/incompatible/stale/future readiness never POST a
  job; available creates one 120 s job under the current decimal task, writes prompt mode 0600,
  keeps volatile state outside caller repo and question out of command, shell-quotes every path,
  declares a first-line success marker, returns `END YOUR TURN NOW`, and its emitted argv drives
  runner CLI → real finalizer → validated artifact. This whole-file command deliberately reruns T1
  at the final slice boundary.
- blocked-by: T1, T3.

## Frozen RED baseline

```text
T1 → exit 1, 2 failed, 13 deselected: AssertionError: T1 missing: subscription billing has no dedicated fresh Grok X admission contract
T2 → exit 1, 13 failed: AssertionError: T2 missing: no independent JSONL-to-validated-X-artifact finalizer
T3 → exit 1, 7 failed: AssertionError: T3 missing: no crash-safe single-attempt Grok X runner
T4 → exit 1, 27 failed: first T4 assertion is `T4 missing: no Grok X MCP tool is registered`
```

## Review resolution

Opus round 1 (`opus-review-plan.md`) returned NEEDS WORK. All three verdict groups were accepted
after checking the cited production seams:

1. Admission classification moved from the route-level design into `app/quota_gate.py`; the
   Grok-X threshold remains deliberately 100 while the existing worker-spawn Grok decision remains
   `not_applicable`. Both use versioned envelopes and the standard state vocabulary.
2. Frozen oracles now include mismatched fetched/candidate post ids and live catalog controls for
   banner, pinned 4.5, nonzero rc and pre-job refusal.
3. A T4 integration oracle executes the exact emitted argv through runner `main()` and the real
   finalizer; T3 separately proves `_invoke_grok` consumes the tested argv/env builders.

The nonblocking findings were also accepted where mechanically testable: exact-six boundary, all
terminal integrity rejects, real 429 mapping, syscall flags, platform-owned volatile state, exact
usage attribution/idempotency and quoted untrusted oEmbed content. First-round dissent remains in
the preserved review artifact.

Sol round 2 (`codex-review-plan.md`) confirmed those Opus groups materially closed, then found six
further blocking counterexamples. All were accepted and frozen before implementation: author
fields cannot leak; canonical oEmbed id must equal candidate/fetch; every readiness identity and
freshness field is checked; metacharacter paths round-trip through the stored shell command;
`question.txt` is mode 0600; catalog entries/banners are parsed exactly. Its timeout suggestion was
also accepted with an enforced 15 s timeout and pre-job failure. The final review round is reserved
for cross-family verification of these fixes; the executable-artifact ceiling is three rounds.
