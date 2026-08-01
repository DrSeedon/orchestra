# #116 — план: видимая свежесть состояния агента, RAG и MCP ошибок

Дата: 2026-08-01. Это Phase 2: production code не изменён. Основание и raw
measurements — `docs/tasks/116/research.md`.

## Решение

В задаче нет одной «системы синхронизации». Есть три независимые границы, каждая
с собственным признаком истины:

1. **Prompt state:** перед следующим fresh turn сравнить current component hashes с
   hashes, доказанно применёнными backend-ом. Расхождение сначала становится
   видимым; higher-priority content не считается доставленным через user-tail.
2. **MCP calls:** transport/domain failure превращается в один typed envelope на
   общей HTTP/MCP boundary. Partial success остаётся domain result, optional failure
   — явным warning.
3. **RAG:** search показывает, к какому проверенному source generation относится
   индекс. Недоказанная свежесть означает `unknown/stale`, не `fresh`.

Тикеты ниже вертикальны: каждый даёт проверяемое end-to-end поведение и может быть
отклонён без поглощения остальных. Исключения — явно указанные `blocked-by`.

## 1. Prompt-state contract

### 1.1 Компоненты и priority

Authoritative components фиксированы и называются одинаково в DB, logs, API и
tests:

| Component | Current source | Что считается applied | Delivery |
|---|---|---|---|
| `role_prompt` | resolved `pipeline + role` prompt, после worker placeholders, с сохранённым custom suffix | prompt, с которым backend успешно connected/resumed | authoritative reconnect |
| `worker_memory` | canonical `name.md → role.md`, включая удаление файла как новое пустое значение | exact `<worker-memory>` body в connected system/developer prompt | authoritative reconnect |
| `project_rules` | worktree `CLAUDE.md`; для Codex — managed `AGENTS.md` mirror этого source | bytes, прочитанные при успешном backend connect | authoritative reconnect |
| `skill_catalog` | resolved role catalog + canonical skill metadata/managed bytes | verified materialized catalog при connect | #94 exact-set sync, затем authoritative reconnect |

Hash format: SHA-256 с version/component prefix и deterministic path ordering. Hash
покрывает bytes и membership; mtime не является истиной. Dynamic worker list,
progress, current time и другие volatile blocks в digest не входят.

Low-priority payload — отдельный класс, но сегодня такого mutable source нет.
Поэтому generic `deliver_delta()` и prose-classifier не добавляются. Bounded
freshness warning использует существующий user-message prefix и **никогда** не
двигает authoritative applied hash. Если позже появится явно типизированный
append-only factual source, он получит отдельный ticket и `tail_delivered_hash`, а
не будет переиспользовать authoritative state.

### 1.2 Persisted state и migration

Добавить additive table, изолированную от частых whole-row `save_session()`:

```text
session_prompt_state
  session_id PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE
  observed_hashes JSON object
  applied_hashes JSON object
  compatibility_components JSON array
  updated_at
```

Отсутствующий key в `applied_hashes` означает `legacy_unknown`, а не «равен
current». Existing rows мигрируются lazy при первом fresh send:

- старый `template_hash` используется только как detector `known_stale`, если он
  отличается от пересчитанного legacy hash. Даже при совпадении `role_prompt`
  остаётся `legacy_unknown`: старый digest не покрывал modules/memory/skills и не
  является новым component SHA;
- новый applied SHA никогда не seed-ится из current source. Persisted prompt нужен
  лишь для реконструкции custom suffix и диагностики legacy состояния;
- `worker_memory` восстанавливается только из фактического persisted
  `<worker-memory>`; отсутствие блока означает historical empty memory, но до
  verified refresh component остаётся compatibility, а не strict applied;
- `project_rules` и `skill_catalog` остаются `legacy_unknown`, потому что exact
  model-loaded bytes не записывались;
- legacy unknown/known-stale component попадает в compatibility mode: каждый turn
  получает bounded warning agent+parent, applied hash не меняется;
- новый component/session становится strict только после successful initial connect
  или verified authoritative refresh.

Для новой либо ещё не подключённой session applied hashes записываются только после
успешного initial backend connect. Failed connect не создаёт «applied» baseline.

Compatibility — rollout, не вечный silent fallback. Strict mismatch не начинает
turn. Failed send/reconnect, compact и user-tail warning не меняют applied hashes.

### 1.3 Next-send decision

После #93 detector работает внутри central `SessionManager.send`, под тем же session
lock, после `needs_switch` gate и только для fresh IDLE/WAITING delivery:

```text
compute current hashes off-loop
  → load persisted applied hashes
  → match: no payload, no DB write
  → legacy unknown/stale: log + bounded warning in turn + response metadata
  → strict stale: log + typed stale_state response, AgentSession.send not called
```

RUNNING steer/queue не refresh-ит и не consumes pending mismatch. Следующий fresh
turn пересчитывает его. Compact также ничего не отмечает delivered.

Successful send route добавляет optional:

```json
{
  "ok": true,
  "freshness": {
    "state": "fresh|legacy_unknown|stale",
    "components": ["project_rules"],
    "action": "none|compatibility_warning|authoritative_refresh"
  }
}
```

Strict failure возвращает HTTP 409 с `code=stale_state`, тем же component list и
`retryable=false`. MCP `send_message` печатает warning/error; dashboard получает
его через существующие status logs, frontend в #116 не меняется.

## 2. Codex provider probe

Same-thread authoritative refresh для Codex не считается существующим, пока не
пройдёт live provider probe. Проба использует temp cwd, current Codex app-server и
случайные non-secret tokens:

1. Start thread с developer instruction `Reply exactly ALPHA_<nonce>`; отправить
   нейтральный одинаковый user prompt и получить exact ALPHA.
2. Disconnect app-server, resume **тот же thread id** с неизменным ALPHA; тот же
   prompt обязан снова дать ALPHA. Это continuity control.
3. Ещё раз disconnect/resume тот же thread id с `BETA_<nonce>`; тот же prompt обязан
   дать exact BETA, без BETA в user input.
4. Повторить полный sequence на втором independent thread. Сохранить только selected
   JSON-RPC fields, thread ids, answers и usage/cache counters; credentials/stdout с
   auth data не писать.

Verdict задан до запуска:

- **PASS:** 2/2 sequences держат same thread id, controls отвечают ALPHA, changed
  resumes отвечают BETA. Codex branch authoritative reload разрешается.
- **FAIL:** provider возвращает старую instruction хотя бы в одном clean sequence.
  Same-thread refresh не реализуется; detector остаётся видимым, strict session
  требует explicit new Codex thread/session recreation.
- **INCONCLUSIVE:** transport/quota/non-exact response. Повторных обходов нет;
  product ведёт себя как FAIL до новой отдельно одобренной пробы.

Request-shape unit test не может превратить FAIL/INCONCLUSIVE в PASS.

## 3. MCP error contract и совместимость с #115

Canonical envelope:

```json
{
  "code": "transport_timeout|connect_error|http_429|http_5xx|invalid_response|domain_error",
  "message": "non-empty human text",
  "status": 429,
  "retryable": false,
  "request_id": "client-or-server-id",
  "retry_after_seconds": 24,
  "outcome_unknown": true,
  "details": {}
}
```

`status` — HTTP status или null. Пустой `str(exception)` заменяется class name.
Response request id берётся из structured body/header, иначе остаётся client id,
который `_api` отправляет в header. Это ещё не end-to-end tracing: server-side echo/
logging остаётся отдельным follow-up.

Общий MCP shape согласован напрямую с `research-merge` (#115):

```text
structuredContent = {result: <domain DTO|null>, error: <envelope|null>}
```

- transport failure: `result=null`, envelope, `isError=true`;
- #115 `PARTIAL`: full merge DTO, `isError=false`; failed stage содержит typed
  detail/DTO.error;
- #115 `FAILED|UNKNOWN`: full merge DTO **не теряется**, top-level error дублирует
  DTO.error, `isError=true`; `UNKNOWN` имеет `outcome_unknown=true`;
- #115 сохраняет `operation_id`, commit point, OIDs и next action. #116 не меняет
  merge mechanics/idempotency;
- #115 T1 будет `blocked-by #116-T5` и использует этот serializer, второго формата
  не создаёт.

Mutating timeout по умолчанию `retryable=false, outcome_unknown=true`; GET может
быть retryable на known transient failure. Idempotency-aware retryability задаёт
domain operation (#115), а не угадывает generic HTTP wrapper.

## 4. RAG freshness contract

### 4.1 Additive state без rebuild

Не поднимать `SCHEMA_VERSION`: current mismatch path destructive drop-ает 456 MB
index. `rag_service.initialize()` до открытия RO connection выполняет O(1)
`CREATE TABLE IF NOT EXISTS`:

```text
rag_state
  project PRIMARY KEY
  indexed_head
  indexed_manifest
  trusted BOOLEAN
  state = unindexed|indexing|fresh_at_head|stale_at_head|
          working_tree_unverified|error|unknown
  started_at
  indexed_at
  last_error
```

Future destructive index migration обязана сбросить `trusted=false`; старый
watermark не переживает rebuild как fresh.

### 4.2 Fail-closed write path

`backfill_files(project, root)`:

1. До первой mutation commit-ит `state=indexing, trusted=false`. Failure прерывает
   scan, старый index не меняется.
2. Scan считает deterministic manifest фактически прочитанных `(path, content)`;
   read/stat/UTF-8 skip фиксируется как incomplete.
3. После scan повторный source pass считает exact manifest с тем же include/exclude
   contract, проверяет RAG-relevant Git dirty state и неизменный HEAD.
4. Только `no skips + same actual/source manifest + clean relevant tree + same HEAD`
   записывает `indexed_head/indexed_manifest/trusted=true`.
5. Mismatch/dirty даёт `working_tree_unverified`; exception — `error`. Если final
   state write упала, предварительный `trusted=false` остаётся.

Per-file commits остаются: во время scan search видит `indexing`, а не ложный fresh.
Manifest verification добавляет backfill-only `0.43–4.06 s` на все 11 scopes;
embedding/backfill занимает минуты.

### 4.3 Read path и API

Search читает hits + `rag_state`/covered namespace list в одном SQLite RO snapshot.
Затем проверяет live Git HEAD; HEAD error → `unknown`, mismatch → `stale_at_head`.
Cross-project response включает **все namespaces реально охваченного DB query**,
даже zero-hit stale project, и coverage marker.

API shape additive:

```json
{
  "results": [],
  "freshness": {
    "basis": "git_head",
    "files": {
      "state": "stale_at_head",
      "source_head": "...",
      "indexed_head": "...",
      "trusted": false,
      "checked_at": "..."
    },
    "logs": {"state": "not_tracked"}
  },
  "freshness_by_project": {},
  "coverage": {"mode": "indexed_namespaces", "complete": true}
}
```

`fresh_at_head` не обещает dirty working-tree freshness; это написано в `basis`.
MCP `search_memory` всегда печатает freshness header **до** hits/no-hits. Log index
generation пока явно `not_tracked`, а не молча fresh.

### 4.4 #113 overlap

#113-T1 со сменой batch size снят после quality A/B: смешанный индекс с batch
64/16 менял ranking, поэтому `EMBED_BATCH` остаётся **64**. T6/T7 не используют
размер batch как freshness/scheduling input и не меняют эту константу.

Текущая реализация #113 всё ещё меняет `app/rag.py`; это file-level sequencing, а
не функциональная зависимость. T6 стартует только после DONE-сигнала #113 от
оркестратора, затем ребейзится и держится вне чужих hunks. Новый module только ради
разведения merge не добавляется.

## Tickets

### T1 — Component hashes и видимый next-send detector

- **Outcome:** система и sender до fresh turn видят
  `fresh/stale/legacy_unknown`; target agent также видит compatibility warning, но
  strict rejection не запускает его backend. User-tail не masquerade-ится как
  authoritative delivery.
- **Files:** `app/db.py`, `app/prompting.py`, `app/manager.py`, `app/session.py`,
  `app/routes/sessions.py`, `app/mcp_stdio.py`, `tests/test_db.py`,
  `tests/test_manager.py`, `tests/test_session.py`, `tests/test_api.py`,
  `tests/test_mcp_stdio.py`.
- **Dependency:** **depends on #93**; specifically its T4 central
  `SessionManager.send`/session lock. **Independent of #94/#113/#115.** Rebase after
  #93; do not edit manager/route concurrently with `audit-worktree`.
- **Price:** **1–1.5 days**.
- **Risk:** medium — shared delivery path and legacy rollout; false strict baseline
  could block live sessions.
- **AC:**
  - additive DB migration preserves all existing sessions and cascading delete
    removes state; malformed JSON fails visible, not current-as-default;
  - old template hash can prove `known_stale` but never becomes the new applied SHA,
    even when equal; persisted memory is diagnostic/compatibility only;
    `project_rules`/skills are unknown and current source is never seeded as applied;
  - new session records applied hashes component-wise only after each component is
    verified at successful initial connect; failed connect records none, and
    `skill_catalog` remains compatibility-only until T4;
  - next IDLE/WAITING send computes four component hashes; match adds 0 model tokens
    and no DB write/message bytes;
  - 54/81-style template mismatch and absent/changed/deleted memory become visible
    on the next send; compatibility response/warning names components;
  - strict mismatch returns 409 `stale_state`, logs status and never calls
    `AgentSession.send`/backend;
  - RUNNING steer/queue and compact do not consume mismatch; next fresh send sees it;
  - old full `_current_prompt` user-copy no longer advances `template_hash` or
    `system_prompt`; bounded warning is ≤150 estimated tokens;
  - route/MCP successful response preserves old `ok/parent_name` and appends
    freshness warning; callers ignoring new field still work;
  - tests cover Claude and Codex, custom prompt suffix, empty/deleted memory, tracked
    project skill vs untracked managed skill, missing worktree and hash read error.
- **blocked-by:** #93.

### T2 — Codex same-thread developer-instruction provider probe

- **Outcome:** binary PASS/FAIL/INCONCLUSIVE decision artifact gates Codex branch;
  no product workaround is inferred from schema.
- **Files:** no production files; selected evidence and verdict go to
  `docs/tasks/116/codex-provider-probe.md`; temp probe stays in `/tmp`.
- **Dependency:** **independent of #93/#94/#113/#115**.
- **Price:** **0.25–0.5 day**, six short model turns (two 3-step sequences).
- **Risk:** low product risk; quota/transport can make result inconclusive.
- **AC:**
  - protocol above runs on two independent threads with exact same-thread ids;
  - verdict uses predeclared PASS/FAIL/INCONCLUSIVE thresholds;
  - BETA never appears in user input; selected request fields prove it was sent only
    as `developerInstructions` on `thread/resume`;
  - no credential, auth path or full transcript is persisted;
  - `codex-provider-probe.md` records app-server/CLI versions, selected JSON-RPC
    fields, exact answers, same-thread checks and the predeclared verdict;
  - FAIL/INCONCLUSIVE leaves Codex authoritative refresh disabled; T3's Codex
    fallback owns the runtime `new_thread_required` action, not this documentation
    spike and not a user-tail workaround.
- **blocked-by:** none.

### T3 — Authoritative refresh для prompt, memory и project rules

- **Outcome:** next-send mismatch reload-ит authoritative content с тем же native id
  where proven; failure starts no turn and never advances applied hash.
- **Files:** `app/manager.py`, `app/session.py`, `app/runtime_registry.py`,
  `app/backend_claude.py`, conditional Codex tests in `tests/test_backend_codex.py`,
  `tests/test_backend_claude.py`, `tests/test_runtime_registry.py`,
  `tests/test_session.py`, `tests/test_manager.py`, `tests/test_api.py`.
- **Dependency:** **depends on T1 and #93**. Claude branch independent of #94.
  Codex branch additionally requires **T2=PASS**. Independent of #113/#115.
- **Price:** **1–2 days**.
- **Risk:** medium — backend lifecycle and one-time cache cold fill; wrong resume mode
  can lose context or falsely mark current.
- **AC:**
  - introduce a prompt-refresh mode distinct from existing `force_fresh` (which
    intentionally drops resume id); refresh preserves exact Claude UUID/Codex thread;
  - Claude resume sends current append-system-prompt and direct contract is covered;
    Codex same-thread branch exists only on T2 PASS;
  - current custom suffix survives template rebuild; changed/deleted worker memory
    replaces old system block rather than appending a contradictory user note;
  - AGENTS sync completes before Codex connect; source/materialized mismatch or sync
    error prevents applied update;
  - connect failure leaves old applied hashes, returns typed `stale_state`, starts no
    turn and is retryable only by an explicit later send/reconnect action;
  - only successfully refreshed components leave compatibility mode/become strict;
    unresolved skill component remains warning-only until T4;
  - hash match never disconnects backend; changed prompt causes exactly one reconnect
    and one accepted user turn;
  - measured cache fields are logged in report; no claim that cold fill is free.
- **blocked-by:** T1, #93; Codex path: T2 PASS.

### T4 — Skill-catalog refresh bridge after #94

- **Outcome:** #94 materializes the exact managed set; #116 detects generation change,
  triggers T3 reconnect and only then marks skill catalog applied.
- **Files:** after #94 rebase, call its public exact-set helper from
  `app/manager.py`/`app/session.py`; hash/catalog helpers in `app/prompting.py`;
  focused manager/session/prompting tests. **Do not edit `app/workspace.py` or
  duplicate #94 copy/prune/slug code.**
- **Dependency:** **depends on T1, T3, #93 and #94**. Codex same-thread reconnect
  additionally requires **T2=PASS**; on FAIL/INCONCLUSIVE the catalog stays visibly
  stale with T3's `new_thread_required` action. Independent of #113/#115.
- **Price:** **0.5–1 day** after #94 lands.
- **Risk:** medium — ownership boundary between managed and tracked project skills;
  accidental prune is data loss.
- **AC:**
  - #116 computes catalog hash itself; #94 is not assumed to persist/provide one;
  - exact-set helper success + byte verification precedes backend reconnect;
  - missing/old managed skill and untracked managed orphan from the live census are
    corrected; tracked project-owned skill is preserved and represented once;
  - sync/reconnect failure leaves skill hash stale/visible and does not mark applied;
  - unchanged catalog performs no file writes and no reconnect;
  - #94 slug hash/path behavior and arbitrary non-managed snapshots are untouched.
- **blocked-by:** T1, T3, #93, #94.

### T5 — Typed MCP HTTP failures with partial-result compatibility

- **Outcome:** every decision-relevant MCP failure has non-empty human text and
  machine-readable `{result,error}`; #115 reuses the same contract.
- **Files:** `app/mcp_stdio.py`, `tests/test_mcp_stdio.py`,
  `tests/test_mcp_codex_review.py` only where protocol fixture is shared.
- **Dependency:** **independent of #93/#94/#113/#115**. It is a prerequisite consumed
  by **#115 T1**, not the reverse.
- **Price:** **2–3 days**; server-wide request-id logging would be a separate follow-up.
- **Risk:** medium — 34 tools change from success-shaped strings to MCP errors;
  unsafe retry classification is the main risk.
- **AC:**
  - `_api` raises one `ApiToolError` for timeout/connect, unsupported method,
    4xx/5xx JSON/text, non-JSON 2xx and 2xx top-level `{error}`;
  - one local FastMCP server subclass overrides the central `call_tool` boundary,
    walks the preserved exception cause and returns `CallToolResult` with non-empty
    text, canonical `{result,error}` and correct `isError`; tools do not get 34 local
    serializers/decorators;
  - 429 preserves status, Retry-After and request id; empty `ReadTimeout` message
    contains `ReadTimeout`; response body is capped/sanitized in details;
  - mutating timeout is `retryable=false,outcome_unknown=true`; transient GET is
    retryable; generic wrapper never declares a POST safe from status alone;
  - `spawn_worker` initial-delivery known rejection vs unknown outcome have distinct
    next action; unknown does not recommend resend and preserves worker mapping;
  - optional role icons degrade `list_agents` with explicit warning; `report_bug`
    cannot report success on error; `send_file` uses central adapter;
  - protocol tests assert `isError` and structuredContent, not only direct function
    strings;
  - serializer tests with an arbitrary synthetic domain DTO prove non-null `result`
    survives both `isError=false` and `isError=true`; #115 owns assertions for its
    PARTIAL/FAILED/UNKNOWN merge DTO.
- **blocked-by:** none.

### T6 — Fail-closed RAG watermark visible in API and MCP

- **Outcome:** search never silently labels an unverified/mixed/post-merge file index
  fresh; stale zero-hit projects remain visible.
- **Files:** `app/rag.py` outside constants block, `app/rag_service.py`,
  `app/routes/memory.py`, `app/mcp_stdio.py`, `tests/test_rag.py`, route tests in
  `tests/test_api.py`, `tests/test_mcp_stdio.py`.
- **Dependency:** **independent of #93/#94/#113/#115**. Distant-hunk coordination
  with #113 is recorded in §4.4.
- **Price:** **1.5–2 days**.
- **Risk:** medium — SQLite/Git/filesystem race and accidental destructive schema
  migration; false fresh is worse than false stale.
- **AC:**
  - live v1 DB fixture with sentinel file/vector rows gains `rag_state` without
    version bump, drop or re-embed; future destructive migration invalidates trust;
  - invalidation write failure calls no `index_file/delete_file`; successful
    invalidation is committed before first mutation;
  - clean temp Git repo backfill records matching head/manifest/trusted; next commit
    before backfill returns `stale_at_head` even if scheduler never ran;
  - dirty/reverted-during-scan, HEAD change, Unicode/read/stat skip and injected
    final-write failure never return fresh; final-write failure leaves trusted=false;
  - barrier search during backfill reads hits+state from one RO snapshot and returns
    either old trusted snapshot or indexing/untrusted, never mixed claim;
  - cross-project zero-hit stale namespace appears in `freshness_by_project` and
    coverage enumerates every searched DB namespace;
  - empty/no-hit search still returns freshness; non-Git/missing project is unknown;
  - API labels file basis and logs `not_tracked`; MCP prints header before results or
    “no matches”;
  - current `EMBED_BATCH=64` remains unchanged and existing retrieval ranking/content
    tests pass.
- **blocked-by:** none.

### T7 — Retained/coalesced RAG backfill scheduler

- **Outcome:** merge-triggered backfill has retained task, readiness, coalescing and
  observable completion; merge response never waits minutes for embeddings.
- **Files:** `app/rag_service.py`, one post-merge call in
  `app/routes/sessions.py` after #93 sequencing, `tests/test_rag_service.py`,
  route test in `tests/test_api.py`.
- **Dependency:** **depends on T6 and #93-T2** for route edit sequencing. Independent
  of #94/#113. Exact route ownership/order is **#93-T2 → #116-T7 → #115-T1**:
  #116 owns the only scheduler route hunk, #115 only consumes its result.
- **Price:** **0.5–1 day**.
- **Risk:** low–medium — lost dirty bit or duplicate runner; restart still loses an
  in-memory pending task, but T6 keeps that state visibly stale.
- **AC:**
  - `rag_service.is_ready()` requires enabled + successful initialize;
    disabled/failed init does not schedule and logs/returns explicit not-ready;
  - scheduler holds a strong task reference per normalized scope; start/end/duration/
    exception are logged and reflected by T6 state;
  - two or more schedules during one scan set a dirty bit and produce current scan +
    exactly one follow-up scan; one scope has no parallel writers;
  - schedules for different scopes share the existing single write executor but
    retain independent pending bits;
  - task exception is observed, removed from registry and does not suppress a later
    schedule; synchronous service teardown cancels wrapper tasks, consumes their
    exceptions and clears retained refs without claiming that an already running
    executor function was stopped;
  - successful merge response returns before a barrier-blocked backfill completes;
    route calls only `schedule_backfill`, not raw `create_task`;
  - route tests prove exact raw statuses `accepted|coalesced|not_ready`; accepted and
    coalesced mean live retained-scheduler acceptance, not a persisted queue or
    post-restart guarantee.
- **blocked-by:** T6, #93-T2. #115-T1 is blocked by both T5 and T7.

**#115 handoff, not T7 AC:** #115 maps the raw statuses to
`ACCEPTED|COALESCED|NOT_READY`. `NOT_READY` becomes
`PARTIAL/RAG_NOT_READY`, keeps its gate and exposes `FINALIZE_SAME_OPERATION`;
reconcile remains an awaited one-shot `backfill_scope()` recovery path, without a
second scheduler/helper.

## Recommended Phase 3 order

Priority from the task, not file convenience:

1. **T1 detector** after #93 — knowledge before delivery.
2. **T2 probe** — can run independently while T1 waits for #93.
3. **T3 authoritative prompt/memory/rules refresh**; Codex branch only on PASS.
4. **T4 skills bridge** only after untouched #94 A/B task lands.
5. **T5 typed MCP errors** — independent and may land immediately; #115 then consumes
   the contract.
6. **T6 RAG watermark** — functionally independent, but starts only after the
   orchestrator reports #113 DONE; preserve `EMBED_BATCH=64`.
7. **T7 scheduler** after T6/#93-T2; then #115-T1 consumes its route result.

Acceptance can be selective:

- reject T4 → prompt/memory refresh remains valid; skills stay visibly stale;
- reject/FAIL T2 Codex probe → Claude refresh remains valid; Codex reports
  `new_thread_required`;
- reject T7 → RAG remains fail-closed/visible, current trigger remains weak;
- reject T5 → prompt/RAG plans still apply, but #115 must wait rather than fork the
  error format.

## Verification

After each accepted ticket:

1. Its exact pytest subset from AC + `git diff --check`.
2. For T1/T3, read-only replay against all live session rows from a copied DB:
   component classification counts must reproduce research lower bounds; no live DB
   or worktree write.
3. For T5, direct `_api` matrix plus real MCP protocol `CallToolRequest` assertions.
4. For T6/T7, temp Git repos and temp SQLite only; no live reindex.
5. Shared-runtime final diff gets Codex implementation review; fix blocking findings
   in the same review session.
6. Acquire Orchestra test lock and run full suite once after the approved set:
   `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.

No service restart, live DB migration, worktree sync, RAG reindex or deployment
without separate user command.

## Codex plan review

Обязательный review завершён в `docs/tasks/116/codex-review-plan.md`:

- первый широкий запуск истёк по 10-minute limit, но прямой protocol probe доказал,
  что local FastMCP subclass boundary возвращает `CallToolResult` с
  `isError=true` и structured `{result,error}`;
- resume потерял target context и честно отказался оценивать невидимый план; этот
  раунд не использовался как verdict;
- fresh plan-only round: **APPROVED**, blocking issues не найдено. Шесть suggestions
  внесены: точная видимость strict rejection, component-wise initial hashes,
  документационный характер T2, Codex gate в T4 и удаление циклических #115 AC из
  T5/T7.

## Boundaries / non-goals

- #93 owns lifecycle locks, manager central send, worktree switching and merge route
  state machine. #116 rebases after it; no concurrent edits.
- #94 owns exact-set skill copy/prune and slug hash. #116 computes delivery hash and
  timing only.
- #113-T1 batch-size change is cancelled; `EMBED_BATCH=64` remains source truth.
  Active #113 `app/rag.py` work lands first; #116 preserves it and does not make
  watermark/scheduler behavior depend on batch size.
- #115 owns merge idempotency, commit point, recovery and domain DTO. #116 owns the
  reusable HTTP/MCP error envelope/adapter plus the single T7 scheduler route hunk.
  Sequencing: #93-T2 → #116-T7 → #115-T1; #115 reconcile calls existing
  `backfill_scope()` synchronously and does not fork the scheduler.
- No changes to `app/workspace.py`, `app/tg_bridge.py`, `pipelines/`,
  `app/static/js/app.js`, Serena, frontend or merge mechanics.
- No generic state-sync framework, filesystem watcher, every-turn full prompt,
  automatic Codex new-thread handoff or atomic whole-RAG-index swap.
