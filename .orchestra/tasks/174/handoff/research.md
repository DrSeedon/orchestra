# #174 — self-switch runtime handoff: research slice

## Measurement contract (written before reading the snapshot)

The measurement target is the current implementation of `AgentSession._build_runtime_handoff()` at `app/session.py:2056-2093`, called for an ordinary runtime switch with `exclude_latest_user=""`.

Selection rule for one real long session: from a SQLite online backup of the live database, select the session with the greatest sum of trimmed eligible `user_message` + `text` content characters (using the same platform-note exclusion as metric 1) among sessions having at least 120 persisted log rows. This optimizes for conversation history rather than base64/tool noise. Ties break by `sessions.id` ascending.

Metrics, fixed before querying rows:

1. **Full semantic source**: all non-empty, trimmed `user_message` and `text` rows in ascending log-id order, excluding `user_message` content beginning `[Orchestra platform note:`. Report rows and content characters.
2. **120-row query loss**: full semantic-source rows/chars older than the newest 120 persisted rows, because `get_logs(id, limit=120)` limits all log types before handoff filtering.
3. **Per-row cap loss**: characters removed by `content[:6000]` among semantic rows that reach the newest-120 window.
4. **32,000-character budget loss**: capped semantic block characters (`label + ":\n" + content`) not emitted after reverse-newest traversal reaches the budget. Separately report full blocks and the one optional partial block.
5. **Retained payload**: eligible semantic rows represented at least partly, their source-content characters represented, final handoff characters (including labels/separators), and percentages against full semantic source.
6. **Boundary integrity**: whether the optional partial block begins at its label, a line boundary, and a word boundary; identify the source log id and exact cut offset. A partial block counts as one partly retained row, not a fully retained row.
7. **Tool omission**: counts and content characters for `tool` and `tool_result` in the full session and newest-120 window; all are omitted by the label allowlist. Inspect omitted rows adjacent to retained semantic rows and state a concrete lost fact/action, without reproducing secrets.

Character counts are Python Unicode code points, matching `len()` and slicing in production, not UTF-8 bytes. Percentages use unrounded counts and are displayed to two decimals.

If the primary session falsifies H4 by fitting inside the formatter budget, a supplemental boundary witness will be selected, before its rows are inspected, as the session with at least 120 logs and the greatest sum of per-row-capped eligible content characters in its newest 120 rows (ties by session id). It does not replace the primary loss measurement; it only tests the production cut branch on real data.

## Hypotheses and falsifiers (before measurement)

- **H1:** A running agent cannot currently change its own runtime through `change_worker_model`; the route returns conflict while `status == RUNNING`. Falsifier: an invocation path that transitions the live session despite `RUNNING`, or defers the change until the turn boundary.
- **H2:** The current guard is deadlock-safe precisely because it checks status before `_disconnect_backend()`. Falsifier: any reachable running-self path that awaits disconnect of the backend/MCP process servicing the same tool request.
- **H3:** Handoff loses most long-session evidence before the 32k formatter because the newest-120 query counts tools/status/thinking. Falsifier: at least 50% of full semantic characters survive, or query-window loss is smaller than formatter loss.
- **H4:** At least one emitted oldest boundary is cut inside content because the formatter appends `block[-remaining:]`. Falsifier: the selected session fits without a partial block, or the partial suffix starts on a label/line/word boundary.
- **H5:** Tool omission removes reproducibility-critical evidence even when the nearby assistant conclusion survives. Falsifier: the newest-120 window contains no tool/tool-result rows, or every omitted result is fully restated with equivalent detail in retained user/assistant text.

## Result in one sentence

A running agent can call the model-change MCP tool on itself, but a real runtime change is deliberately rejected with HTTP 409 before any disconnect or mutation; therefore self-switch is currently safe only as a failed/no-op request, not as a supported operation. Removing that guard would be unsafe because the synchronous request would tear down the CLI/MCP process that still must receive the tool result, while turn finalizers can concurrently mark idle, flush queued messages, and schedule hibernation.

## Sources and control-flow trace

Code was read at commit `47949781c9595ecf6fd1dc8f8c88f4d1665b5873` (`2026-08-10T10:35:36+02:00`, `#173: #173: fix prompt P0 defects`). Relevant history:

```text
$ git log --oneline -S"_build_runtime_handoff" main -- app/session.py
8012d5d fix: snapshot Codex context for runtime handoff
3c7de7d feat: add persistent Codex worker runtime

$ git log --oneline -S"cannot change model while running" main -- app/session.py
871f850 refactor: make agent runtimes provider-agnostic
ec71ffc wip: auto-save before worker spawn
```

The current path is:

1. Every full-access worker receives `change_worker_model(name, model)`. The tool accepts an arbitrary name, so `name == WORKER_NAME` is allowed by its input contract. It synchronously POSTs `/api/sessions/{name}/change-model` with a default 30-second HTTP timeout (`app/mcp_stdio.py:449-474,1215-1223`). The callable tool was also present in this worker's live tool registry.
2. The route resolves a loaded session and directly awaits `found.change_model(new_model)`; it does not take `SessionManager.get_session_lock()` (`app/routes/sessions.py:606-621`). That manager lock serializes message delivery and branch auto-switch only (`app/manager.py:936-950`).
3. `AgentSession.send()` takes `_lifecycle_lock` only while submitting/steering the message, creates the per-turn listener, then releases the lock in `finally` (`app/session.py:820-858,1018-1024`). The lock is therefore free during the model's ongoing turn and its MCP tool calls. The model-change route can acquire it; there is no lock deadlock before the status check.
4. `change_model()` holds `_lifecycle_lock`, rejects compaction, and `_change_model_locked()` checks same-model first, then rejects a different model while `status == RUNNING` (`app/session.py:2095-2106`). Thus a same-model self-call returns success/no-op even while running; a runtime-changing self-call returns `{"ok": false, "error": "cannot change model while running"}` and the route maps it to HTTP 409.
5. The MCP HTTP client converts that 409 into a structured tool error (`app/mcp_stdio.py:476-490` plus `_response_error`). The old runtime remains alive and can consume the tool result and continue the turn. No handoff, status log, native-session reset, disconnect, persistence, queue entry, or wakeup is performed.
6. There is no deferred switch intent. On normal `turn_end`, `TurnManager.finish_turn_status()` sets `IDLE` or `WAITING`, persists, and publishes completion; post-turn actions then notify scope idle, auto-report, flush `_pending_messages`, or hibernate (`app/session_turns.py:455-499`). None retries a rejected model change.

### Why simply deleting the RUNNING guard is unsafe

The successful idle path builds/stores handoff, logs the change, then awaits `_disconnect_backend()` while still holding `_lifecycle_lock`; only afterwards does it clear native session state, mutate `model/backend_type`, persist, and return the HTTP response (`app/session.py:2108-2158`). All built-in runtime disconnects terminate the execution substrate:

- Claude awaits `ClaudeSDKClient.disconnect()` (`app/backend_claude.py:320-326`).
- Codex interrupts an active turn, stops the scoped/direct app-server process, and fails outstanding requests during finalization (`app/backend_codex.py:691-725`).
- Grok interrupts and terminates/kills its ACP process (`app/backend_grok.py:502-529`).
- OpenCode aborts, closes SSE/HTTP, and terminates/kills its daemon (`app/backend_opencode.py:610-638`).

For a self-call, that same runtime owns the MCP subprocess awaiting the route response. Disconnecting before the HTTP/tool result has travelled back to the model creates a circular lifecycle dependency: the control request needs the old runtime alive to finish, while the control handler is killing it before replying. A mere `create_task()` after forming the HTTP response is not sufficient evidence of delivery—the old process may be killed before it consumes and records the MCP result. The reliable boundary visible in current architecture is the runtime's terminal `turn_end`, after the result has been consumed.

Forced mid-turn disconnect also activates competing finalizers. The per-turn listener catches cancellation and, in `finally`, changes `RUNNING → IDLE`, persists, and either spawns `_flush_pending()` or schedules hibernation (`app/session.py:1212-1236`). Its done callback publishes turn completion when no longer running (`app/session.py:1469-1491`). `_flush_pending()` waits 300 ms, takes the same lifecycle lock, changes status back to `RUNNING`, and submits through whichever backend/model is current when it wins the lock (`app/session.py:1358-1467`). A message-delivery race is serialized, but a model switch that loses to flush is rejected again; there is no priority or durable switch-before-wake ordering.

Therefore a safe self-switch needs two phases: acknowledge/persist intent while the old runtime is alive, let that turn reach its terminal boundary, then have a server-owned task acquire the lifecycle lock, recheck state, switch, persist the new runtime, and only then wake/send through it. The ordinary message queue is not a substitute for the control intent because it has different ordering and failure semantics.

## Empirical status/lock probe

No live session was mutated. An isolated `AgentSession` was put in `RUNNING` with a mock backend:

```text
$ uv run python - <<'PY'
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from app.session import AgentSession, AgentStatus

async def main():
    s = AgentSession(id='probe', name='self', scope='/probe', cwd='/tmp',
        model='claude-sonnet-5[1m]', system_prompt='probe',
        created_at=datetime.now(timezone.utc))
    backend = AsyncMock()
    backend.disconnect = AsyncMock()
    s._backend = backend
    s.status = AgentStatus.RUNNING
    result = await s.change_model('gpt-5.6-sol')
    print('result=', result)
    print('model=', s.model, 'runtime=', s.backend_type,
          'backend_same=', s._backend is backend)
    print('disconnect_awaits=', backend.disconnect.await_count,
          'lock_locked=', s._lifecycle_lock.locked())

asyncio.run(main())
PY
result= {'ok': False, 'error': 'cannot change model while running'}
model= claude-sonnet-5[1m] runtime= claude backend_same= True
disconnect_awaits= 0 lock_locked= False
```

Existing focused tests were then run unchanged:

```text
$ uv run pytest -q \
  tests/test_session.py::TestRuntimeCapabilities::test_cross_runtime_model_switch_resets_native_session_and_builds_handoff \
  tests/test_session.py::TestRuntimeCapabilities::test_runtime_handoff_is_one_shot_user_message_context \
  tests/test_mcp_quota_gate.py::test_change_model_is_control_action_even_when_target_bucket_blocked
...                                                                      [100%]
3 passed in 8.31s
```

These cover idle cross-runtime reset/handoff, one-shot handoff delivery, and quota-gate bypass for the control action. There is no repository test for a self-invoked runtime change or deferred switch after turn end.

## `_build_runtime_handoff()` behavior

The builder first drains asynchronous log writes, then calls `get_logs(session_id, limit=120)`. `get_logs()` selects the newest 120 rows of **all types** and only then returns them oldest-first (`app/db.py:1101-1118`). The builder:

- permits only `user_message → User` and `text → Assistant`;
- drops empty content and platform-note-prefixed messages;
- caps each retained content at its first 6,000 characters;
- walks newest to oldest under a nominal 32,000-character block budget;
- on overflow, may keep the **suffix** of the oldest block when more than 200 characters remain, then stops;
- reverses selected blocks back to chronological order (`app/session.py:2056-2093`).

The `total` counter excludes the `\n\n` separators inserted by the final join, so 32,000 is not a strict final-output bound. The latent overflow is `2 × (represented_blocks - 1)` characters.

Call sites differ materially:

- Missing Claude native transcript: builder with `exclude_latest_user` (`app/session.py:955-963`).
- Native Codex compact without a provider summary: builder fallback (`app/session.py:1626`).
- Model/runtime change: if the runtime changes and `last_summary` is non-empty, the builder is bypassed in favor of `_bounded_summary(last_summary)`; otherwise the builder runs (`app/session.py:2115-2119`). `_bounded_summary` is 4,000 characters (`app/session.py:182,268-275`).

Counter-evidence against treating the measurement below as every switch's actual payload: the selected live row had `last_summary=4000`, `runtime_handoff=4000`, and a final status log `model change: gpt-5.6-sol (codex) → claude-opus-5[1m] (claude)`. That real switch used the 4k summary branch. The measurement is the exact result the current builder produces over the same real session when it is selected (for example, no summary or missing-native-transcript paths).

## Live SQLite measurement

The authoritative snapshot was captured at `2026-08-11T07:29:53.160995+00:00`. Source was opened with SQLite URI `mode=ro` and copied with `sqlite3.Connection.backup()` into an in-memory database. No `cp`, live write, or session mutation occurred. Snapshot size: 91 sessions, 54,914 logs.

Selection produced real session `seedon-orchestrator`, id `09b75a6c-c93f-45ea-b2f4-6728851a1bbd`, scope `/home/kesha/projects/seedon`, status `idle`, with 7,251 log rows. It had the largest exact eligible semantic history: 1,284 rows / 1,760,169 characters.

### Exact numbers

| Stage | Rows represented | Content characters represented | Loss at stage |
|---|---:|---:|---:|
| Full eligible user/assistant source | 1,284 | 1,760,169 | — |
| Newest 120 persisted rows, after type filter | 24 | 24,830 | 1,260 rows / 1,735,339 chars lost to query window |
| Per-row 6,000 cap | 24 | 15,163 | 9,667 chars lost (one 15,667-char user row became 6,000) |
| Nominal 32k formatter | 24 full, 0 partial | 15,163 | 0 content chars lost at budget |
| Final handoff with labels/separators | 24 | 15,163 payload; 15,433 total | 270 framing chars added |

Retained against full semantic source: **24/1,284 rows = 1.87%** and **15,163/1,760,169 content chars = 0.86%**. Total semantic loss is **1,745,006 chars = 99.14%**. Query-window loss alone is 98.59% of the full source and 99.45% of all dropped semantic characters; the nominal 32k budget was not the active limiter.

The newest-120 window spanned log ids 54,693–54,933 and contained:

| Type | Rows | Share of window |
|---|---:|---:|
| `tool` | 38 | 31.67% |
| `tool_result` | 38 | 31.67% |
| `status` | 20 | 16.67% |
| `text` | 16 | 13.33% |
| `user_message` | 8 | 6.67% |

Thus tools alone consumed 76/120 = **63.33%** of the row window before being discarded. Semantic rows were only 20.00% of the window.

### Boundary cutting

There were two distinct boundary results:

1. **Formatter suffix cut: absent in all real sessions in this snapshot.** The selected session emitted 24 full blocks; its internal block counter was 15,387 and the final join was 15,433 (46 separator characters). The supplemental selection across every session with at least 120 logs found zero sessions entering the partial-block branch. The maximum recent capped semantic payload was `dev-lead`: 21,907 content chars, 28 full blocks, 22,189 final handoff. This falsifies H4 on current real data.
2. **120-row boundary cuts conversational structure.** The first selected row was status id 54,693. The immediately preceding row 54,692 was the user's question; the first retained semantic row 54,694 was its assistant answer. The handoff therefore opens with an orphan answer whose question was cut solely by the all-types row limit. The boundary is an event boundary, not a user/assistant turn boundary.

The suffix branch remains a latent integrity risk: `blocks.append(block[-remaining:])` can remove the `User:`/`Assistant:` label and the beginning of the oldest included content, starting mid-line or mid-word. No claim of observed live cutting is made because the falsifier fired.

### Omitted tools/results and concrete impact

All `tool` and `tool_result` rows are omitted by design:

- Full selected session: 4,646 rows / 10,463,792 characters (`tool` 2,338; `tool_result` 2,308).
- Newest-120 window: 76 rows / 196,335 characters (`tool` 38; `tool_result` 38).
- Recent omitted tool evidence was 12.95 times the retained semantic payload by characters.

Concrete consequences visible in adjacent rows:

- Assistant log 54,792 retained the conclusion that a lead arrived for query “установка бота на сайт,” through a specific auto-target/group/ad combination. Raw evidence logs 54,787 (site event/UTM), 54,789 (keyword list), and 54,791 (ad list) are omitted. A new runtime receives the conclusion but cannot reproduce which raw ids/fields established it or distinguish manual keyword from auto-targeting without rerunning external reads.
- Assistant log 54,863 retained “all 9 ads lead to `/`” and the summarized URL pattern. Tool call 54,861 and 5,434-character result 54,862 containing the nine ad records are omitted. The handoff cannot audit the universal “all 9” claim or recover individual ad ids/links.
- Tool result 54,712 and later result 54,802 each contained 20,000 characters of search-query data; both vanish. Only selected conclusions survive, so future analysis of false positives or a different grouping must repeat paid/external queries.
- User log 54,822 is retained only as its first 6,000 of 15,667 characters. The initial question survives, but 9,667 characters of the supplied Yandex Direct screen/state are irrecoverable from the builder even though the row itself is counted as retained.

The adjacency evidence was read from the same kind of online backup with:

```sql
SELECT id, ts, type, length(trim(content)), substr(replace(trim(content), char(10), ' ↵ '), 1, 220)
FROM logs
WHERE session_id = '09b75a6c-c93f-45ea-b2f4-6728851a1bbd'
  AND id BETWEEN 54685 AND 54865
ORDER BY id;
```

The summary-branch counter-evidence was obtained from the backup with:

```sql
SELECT name, model, backend_type, length(last_summary), length(runtime_handoff), status
FROM sessions WHERE id = '09b75a6c-c93f-45ea-b2f4-6728851a1bbd';
-- seedon-orchestrator | claude-opus-5[1m] | claude | 4000 | 4000 | idle
```

## Hypothesis outcomes and counter-evidence

- **H1 confirmed:** a different-model self-call while running returns 409; no deferred transition exists. Same-model is counter-evidence to an overbroad “all self-calls fail” statement: it succeeds as a no-op because equality is checked first.
- **H2 confirmed for current code:** the guard fires before handoff/log/disconnect/mutation, and the probe observed zero disconnect awaits. This does not prove a future forced self-switch safe; backend teardown evidence points the other way.
- **H3 confirmed strongly:** only 0.86% of full semantic characters survived; query-window loss (1,735,339 chars) dwarfed per-row-cap loss (9,667) and formatter-budget loss (0).
- **H4 falsified on live data:** no partial block in the selected session or any eligible session. Counter-evidence still shows a real turn-structure cut at the 120-row boundary and a latent suffix-cut branch in code.
- **H5 confirmed:** 76 recent tool rows / 196,335 chars were omitted, including exact campaign/ad/query evidence needed to reproduce retained claims.

## Exact measurement command

This is the command used for the authoritative numbers (Python code-point lengths intentionally mirror production):

```bash
python3 - <<'PY'
import sqlite3, datetime, collections, json
src = sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro', uri=True)
db = sqlite3.connect(':memory:')
src.backup(db)
src.close()
db.row_factory = sqlite3.Row
labels = {'user_message': 'User', 'text': 'Assistant'}
def content(r): return str(r['content'] or '').strip()
def eligible(r):
    c = content(r)
    return r['type'] in labels and bool(c) and not (
        r['type'] == 'user_message' and c.startswith('[Orchestra platform note:'))
def rows_for(sid):
    return [dict(r) for r in db.execute(
        'SELECT id, ts, type, content FROM logs WHERE session_id=? ORDER BY id', (sid,))]
def format_window(rows):
    blocks=[]; total=0; partial=None
    for r in reversed(rows[-120:]):
        if not eligible(r): continue
        capped=content(r)[:6000]; block=f"{labels[r['type']]}:\n{capped}"
        if total + len(block) > 32000:
            remaining=32000-total
            if remaining > 200:
                cut=len(block)-remaining
                partial={'id':r['id'],'cut':cut,'remaining':remaining,
                         'line_boundary':cut == 0 or block[cut-1] == '\n',
                         'word_boundary':cut == 0 or block[cut-1].isspace() or block[cut].isspace()}
                blocks.append((r, block[-remaining:], False, cut, block, capped))
            break
        blocks.append((r, block, True, 0, block, capped)); total += len(block)
    represented=0
    for r, emitted, full, cut, block, capped in blocks:
        prefix=len(labels[r['type']])+2
        represented += len(capped) if full else max(0, len(block)-max(cut,prefix))
    handoff='\n\n'.join(x[1] for x in reversed(blocks))
    return {'eligible_capped_chars':sum(len(content(r)[:6000]) for r in rows[-120:] if eligible(r)),
            'represented_content_chars':represented,'handoff_chars':len(handoff),
            'full_blocks':sum(x[2] for x in blocks),'partial_blocks':sum(not x[2] for x in blocks),
            'counter':total,'separator_chars':2*max(0,len(blocks)-1),'partial':partial}
stats=[]; cache={}
for s in db.execute('SELECT id,name,scope,status FROM sessions ORDER BY id'):
    rs=rows_for(s['id']); cache[s['id']]=rs
    if len(rs) < 120: continue
    sem=[r for r in rs if eligible(r)]
    stats.append((sum(len(content(r)) for r in sem), s['id'], dict(s), len(rs), len(sem)))
stats.sort(key=lambda x:(-x[0],x[1]))
sem_chars,sid,sess,log_count,sem_count=stats[0]; rows=cache[sid]; window=rows[-120:]
full=[r for r in rows if eligible(r)]; win=[r for r in window if eligible(r)]; fm=format_window(rows)
def tools(rs):
    ts=[r for r in rs if r['type'] in ('tool','tool_result')]
    return {'rows':len(ts),'chars':sum(len(content(r)) for r in ts),'types':dict(collections.Counter(r['type'] for r in ts))}
bound=[]
for _, sid2, sess2, nlogs2, _ in stats:
    m=format_window(cache[sid2]); bound.append((m['eligible_capped_chars'],sid2,sess2,nlogs2,m))
bound.sort(key=lambda x:(-x[0],x[1]))
out={
 'snapshot_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'snapshot_sessions':db.execute('SELECT count(*) FROM sessions').fetchone()[0],
 'snapshot_logs':db.execute('SELECT count(*) FROM logs').fetchone()[0],
 'selected':{**sess,'log_rows':log_count,'semantic_rows':sem_count,'semantic_chars':sem_chars},
 'window_ids':[window[0]['id'],window[-1]['id']],
 'window_types':dict(collections.Counter(r['type'] for r in window)),
 'semantic_window':{'rows':len(win),'chars':sum(len(content(r)) for r in win)},
 'query_loss':{'rows':len(full)-len(win),'chars':sum(len(content(r)) for r in full)-sum(len(content(r)) for r in win)},
 'per_row_cap_loss_chars':sum(len(content(r))-len(content(r)[:6000]) for r in win),
 'formatter':fm, 'tools_full':tools(rows), 'tools_window':tools(window),
 'boundary_max':{'session':bound[0][2],'log_rows':bound[0][3],**bound[0][4]},
 'sessions_with_partial':sum(x[4]['partial'] is not None for x in bound),
}
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```
