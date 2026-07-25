# Phase 1 audit — Telegram bridge delivery

Date: 2026-07-25  
Scope: `app/tg_bridge.py`, `tests/test_tg_bridge.py`, delivery-related history, `BUGS.md`, `TODO.md`.  
No production calls, service restart, or implementation changes were made.

## Question

- **Context:** one Telegram bot mirrors all agent activity into topics of one supergroup. The
  supergroup shares one `chat_id`, one local dispatcher, and Telegram's group quota.
- **Change under test:** the queue rewrite in `0c4c4c0` and the topic-metadata isolation hotfix
  `62cf9bc` / `a566371`.
- **Baseline:** the lock-and-shed implementation from `4fd6816`.
- **Outcome:** important text remains deliverable under bursts/failures; tool activity is visible
  without being able to starve text; queues and startup delays are bounded; lifecycle and media
  state cannot duplicate or corrupt delivery.

## Hypotheses and falsifiers

| Hypothesis | Falsifier | Result |
|---|---|---|
| H1: `0c4c4c0` preserves tools without endangering text because priority scheduling replaces shedding. | A low-priority tool can be postponed behind every later important item, or queue growth equals input growth. | **REFUTED** by deterministic measurements. |
| H2: `a566371` fully isolates cosmetic topic status from real delivery. | Status synchronization still delays startup/log processing, or a cosmetic request still uses the reliable retry queue. | **PARTIAL:** global retry-path isolation is correct; startup and the originating stream remain synchronously gated. |
| H3: the focused tests cover load-bearing concurrency/lifecycle states. | A deterministic race or duplicate-stream state is reproducible while all focused tests pass. | **REFUTED:** three such states reproduced; `56 passed`. |
| H4: the old broad `tg_bridge` split is necessary before reliability can be fixed. | The defects have surgical fixes with explicit state owners and tests. | **REFUTED:** do not revive the broad P5 split for this task. |

## Review of `0c4c4c0`

The commit changed only `app/tg_bridge.py` (`+207/-62`) and added **zero tests**. It replaced
per-chat locks plus shedding with a per-chat `asyncio.PriorityQueue`, a perpetual dispatcher,
and a split return contract: important calls await a Telegram result; non-important calls return
a pending `Future`/`Task`.

### [P1] Bound or coalesce the non-important queue

**File:** `app/tg_bridge.py:653` in `0c4c4c0`  
**Confidence:** 1.00

Every non-important tool, edit, and image is inserted with `put_nowait()` into an unbounded
`PriorityQueue`; its producer gets a future immediately and continues reading SQLite logs. When
arrival rate exceeds the 3.05-second group service rate, memory and delivery age grow without a
limit. Measured with a blocked dispatcher: 1,000 submissions produced queue size 1,000 and 1,000
pending futures. There is no maximum, TTL, coalescing, or backpressure.

### [P1] Prevent strict-priority starvation of tool activity

**File:** `app/tg_bridge.py:618` in `0c4c4c0`  
**Confidence:** 1.00

The queue key `(0 if important else 1, sequence, ...)` lets every later important call overtake
every earlier tool call. Three predeclared trials queued one tool followed by 5, 20, and 50
important calls; the tool ran after all 5/20/50 respectively. At the production interval, 50
slots imply at least 152.5 seconds before the tool, excluding API latency and retries. With a
continuous important stream, the delay has no finite bound.

### [P1] Do not report image success at enqueue time

**File:** `app/tg_bridge.py:669` and `app/tg_bridge.py:1258` in `0c4c4c0`  
**Confidence:** 0.96

The new non-important contract returns a future before Telegram delivery. `_send_diff_image()` and
`_send_result_image()` still return success based on rendered PNG bytes, so `stream_logs()` skips
the expandable text before the photo future has succeeded. A delayed, failed, or cancelled photo
therefore removes both representations. The commit adapted temp-file lifetime to the future but
did not adapt the caller's delivery-success contract.

### Retained hazard accepted without proof

`_tg_run_call()` performs all attempts and sleeps inside the single dispatcher. That behavior
predates `0c4c4c0` as "hold the per-chat lock through retries", but the queue rewrite retained it
without an absolute attempt/operation deadline and without reclassifying callers. Marking
`topic_status` important therefore let cosmetic `editForumTopic` calls monopolize the dispatcher;
the 2026-07-25 incident is the observed consequence. This is not solely introduced by
`0c4c4c0`, but a review of the rewrite should have blocked on the caller classification and a
slow-call test.

### Missing tests in the commit

No tests were added for:

- queue capacity or producer backpressure;
- starvation/fairness and maximum tool-delivery age;
- a slow/timeout call followed by real text;
- return-type compatibility (`Message` vs `Future`/`Task`);
- cancellation/reset while a call or entity fallback is pending;
- image/text fallback based on actual delivery;
- more than one topic sharing the same negative group `chat_id`.

The queue tests now present in `tests/test_tg_bridge.py` arrived with the later topic hotfix. They
verify one important call overtakes one tool and that two tools retain the interval; they do not
assert boundedness, fairness, delivery outcome, or lifecycle behavior.

## Current delivery-state map

### Outbound source and classification

Each `stream_logs(orch_name, thread_id)` polls its session's SQLite logs independently. All primary
topics use the same negative `group_id`, so they share one dispatcher and 3.05-second interval.
Mirrors have their own `chat_id` and dispatcher.

| Log/action | Primary policy | Mirror policy | Consequence |
|---|---|---|---|
| agent `text` | important, awaited, formatted UTF-16 chunks | important, awaited after primary | bounded retry, but a slow mirror stalls this session's next primary log |
| `user_message`, `error` | important | important | same |
| `send_message` tool | important | ordinary mirror path | user-visible inter-agent message is protected |
| other tool start/result | non-important future/task | non-important future/task | unbounded queued telemetry; strict-priority starvation |
| Edit/Write diff and result images | non-important future | no equivalent image path | text may be suppressed on enqueue rather than successful image delivery |
| `status`, `subagent_end`, worker-info pretty output | non-important | non-important | can be stale or starved |
| explicit `send_file_to_tg` | important, awaited | important, awaited after primary | file object is recreated per retry; mirror delay extends MCP call |
| topic running/idle icon | direct best-effort call after hotfix | direct best-effort call | no message-queue retry, hard 5-second attempt timeout |
| topic create/rename/delete | direct Bot API call | direct where applicable | outside delivery queue, but create/status sequencing can delay startup |

### Per-chat queue and retry state

- Queue owner: `_tg_call_queues[chat_id]`; dispatcher: `_tg_dispatch_tasks[chat_id]`.
- Priority: `0=important`, `1=non-important`; FIFO only inside a priority class via global sequence.
- Rate state: `_tg_last_send`, `_tg_flood_until`; interval `3.05s` for negative group IDs and
  `1.05s` otherwise.
- Important calls: 3 attempts. `RetryAfter` sets a chat flood deadline. Network/server failures
  retry after 1s/2s and are explicitly ambiguous (at-least-once, possible duplicate).
- Non-important calls: 1 attempt and fire-and-forget result.
- All attempts stamp `_tg_last_send` before the Bot API call.
- Reset cancels dispatchers, queued futures, and tracked entity/edit completion tasks.

The official Telegram FAQ currently says to avoid more than one message/second in one chat and
caps groups at 20 messages/minute [S1]. The 3.05-second group interval matches that documented
ceiling. Telegram documents `retry_after` as an optional response parameter, but does not provide
an idempotency key for `sendMessage` [S2].

### Topic and stream lifecycle

1. `start_bridge()` starts polling and schedules `_deferred_startup()`.
2. `_deferred_startup()` awaits `ensure_topics()`, then awaits
   `_sync_all_topic_statuses()`, then starts existing `stream_logs()` tasks.
3. `ensure_topics()` itself creates an untracked `stream_logs()` task for every newly created topic.
4. `topic_sync_loop()` calls `ensure_topics()` every 30 seconds.
5. `stop_bridge()` cancels only tasks stored in `_tasks`.

This produces two defects:

- A new topic at startup gets **two** stream tasks: one from `ensure_topics()` and one from
  `_deferred_startup()`. Deterministic experiment result:
  `new_topic_stream_starts=2 [('orch', 42), ('orch', 42)]`.
- The task created inside `ensure_topics()` is not stored in `_tasks`, so bridge stop does not own
  or cancel it.

Each stream initializes `last_id` to the newest existing log. Therefore anything generated while
startup is awaiting cosmetic status synchronization is skipped, not replayed when the stream
finally starts.

Inbound buffer timers are also outside lifecycle ownership: each `_BufState.debounce_task` is
created independently, while `stop_bridge()` neither cancels those tasks nor clears `_buffers`.
A stop/start during the 5–30-second inbound window can therefore run a stale timer against
`_manager=None` or a replacement manager.

### Inbound text/media/voice state

Inbound messages are grouped per session in `_BufState`:

`IDLE -> COLLECTING --5s debounce--> WAITING_MEDIA --all media ready or 30s--> IDLE`

The buffer lock protects `entries`, `pending_media`, phase, and debounce task, but a reserved media
slot is identified only by list index. After a 30-second timeout flush clears the list, a late
voice/video-note completion can reuse that index and overwrite an entry in the next generation.
Deterministic reproduction:

`next_batch_after_late_resolve=[('new-msg', 'OLD-VOICE')]`.

Voice additionally downloads/caches the OGA file, calls Deepgram, records the transcription cost,
and resolves the reserved batch slot. Only voice and video-note currently use
`_register_media()`/`_resolve_media()` and are affected by this generation-corruption mechanism.
Other media handlers await their work and then append through `_send_to_agent()`; they can reorder
under slow downloads, but they do not reuse a stale reservation index.

### UTF-16 and formatting

Markdown is converted before final size validation. `_formatted_chunks()` enforces the 4,096
UTF-16-unit limit and drops cross-chunk entities; focused tests cover table expansion and emoji
length. This part is **CONFIRMED healthy** at the unit level.

## Assessment of `a566371` / `62cf9bc`

The two hashes are equivalent source hotfixes on different branch ancestry.

**What is correct:**

- `topic_status` no longer enters `_tg_call_safe()` and is never marked important, so it cannot
  globally monopolize the per-chat message dispatcher.
- Each edit is one best-effort call with both `asyncio.timeout(5)` and Bot API
  `request_timeout=5`.
- failures are debug-only and do not update the status cache;
- snapshots fix `dictionary changed size during iteration`;
- the focused suite passes: `56 passed in 2.59s`.

**Remaining hole:**

`_sync_all_topic_statuses()` awaits each status sequentially before starting log streams. With a
2ms test timeout, measured elapsed time scaled linearly:

| statuses | elapsed | multiple of one timeout |
|---:|---:|---:|
| 5 | 0.0108s | 5.4x |
| 10 | 0.0215s | 10.7x |
| 25 | 0.0538s | 26.9x |

At the production 5-second cap, 25 primary topics can postpone stream startup by approximately
125 seconds; mirrors can double it. Since streams skip existing logs when they start, this is a
loss window. The runtime one-hour starvation path is fixed, but cosmetic startup work is still
sequenced ahead of real delivery.

Runtime callers are not fully asynchronous either. `stream_logs()` awaits
`_update_topic_status()` before processing each first text/tool after a state change. A stalled
primary plus mirror edit can therefore delay that originating stream by approximately 10 seconds,
although other primary streams and the global message dispatcher remain free.

No other cosmetic caller uses the reliable retry helper. Direct create/rename/delete topic calls
also stay outside it, although `ensure_topics()` remains a blocking prerequisite for all stream
startup.

## Other defects found

### [P1] Cosmetic startup can permanently skip replies

`_deferred_startup()` waits for all topic edits before creating stream tasks, while each stream
sets its cursor to the newest log. A Telegram slowdown during startup can therefore cause agent
replies generated in that window to be skipped forever.

### [P1] Stream ownership is non-idempotent

`ensure_topics()` and `_deferred_startup()` can start the same stream twice; runtime-created
streams are untracked and survive bridge stop. Duplicate streams independently read and send the
same future logs.

### [P2] Late voice/video-note completion corrupts the next batch

Confirmed above and already recorded in `TODO.md`. A generation token is required; list index
alone is not a stable reservation identity. A stale resolver also decrements `pending_media`
unconditionally, so it can prematurely flush a new media generation before that generation's real
completion arrives.

### [P2] Mirror failure blocks later primary logs for that agent

Primary text is sent first, then `stream_logs()` awaits the important mirror delivery. A slow
mirror queue/retry does not block other primary topics globally, but it does stop this session's
log poller from reaching its next primary message.

### [P2] Delivery has no queue-age observability

Logs report floods and final loss, but not queue length, oldest item age, coalesced tool count, or
per-class delivery latency. The system can therefore be functionally silent for a long time while
appearing merely busy.

### [P2] Runtime status edits synchronously gate the originating stream

The hotfix protects the global dispatcher, but each first text/tool after a state transition still
waits for primary and mirror status edits. Status updates should be deduplicated background work,
not a prerequisite for reading or sending the current log.

## Review-coverage audit

`git log --follow -- app/tg_bridge.py` contains 107 commits. Repository artifacts can positively
establish review context for changes such as `4fd6816` (TG delivery), `cf2721a` (TG three-bug
task), `3a7b76a/92159f2/e87a5fd` (ECS refactor), and task-review commits
`ae15f3b/9ddd1b8/e9b4e7f`.

For the following load-bearing commits, no dedicated `codex-review-*` artifact or task report
covering the TG change was found. This is an **artifact-based classification**: it proves missing
review evidence, not that no human ever glanced at the code.

### Current/surviving delivery behavior with no review artifact

| Area | Commits | Surviving responsibility |
|---|---|---|
| Initial bridge and stream lifecycle | `bd196e4`, `d16728e`, `2afbee9` | topic streams, startup ordering, task creation |
| Inbound debounce/media/voice implementation | `d01e750`, `1e39c47`, `3a72feb` | buffer state machine, media reservation, voice/media handlers; `docs/tg-media/CODEX_REVIEW.md` reviewed the earlier implementation plan, but no implementation/state-machine review artifact was found |
| Formatting/expandables/UTF-16 | `84a7911`, `9314dec`, `5f58966`, `080d349`, `1af9540`, `c36c51d`, `26d6d2a` | expandable contracts and split logic |
| Diff/result visibility | `2a123f6`, `ba30a98`, `745dece`, `07f9185`, `d3e33b0`, `a69165a` | image rendering and text-suppression decisions |
| Tool presentation | `bd01478`, `71ba69f`, `eb09bb0` | worker/tool and inter-agent message rendering |
| Topics and mirrors | `6a1b3c5`, `9f7dfee`, `c5f8c62`, `d5b6544`, `21c665e` | mirror topics, status edits, rename |
| Current queue/hotfix | `0c4c4c0`, `62cf9bc` / `a566371` | priority dispatcher and topic isolation |

### Superseded but historically unreviewed delivery rewrites

`8e84911` plus revert `9066c48`, `756938a`, `72d02fa`, `a02a977`, `b6e4838`,
`106a439`, and `ee6f61a`. They no longer own most current queue lines, so retro-reviewing them is
lower value than testing the surviving contracts above.

The archived `refactor-tg` branch contains no committed `docs/tasks/refactor-tg/` research or plan;
only the `TODO.md`/`CLAUDE.md` summary survives (`tg_bot/tg_stream/tg_render/tg_topics`). The branch
cannot serve as an auditable implementation plan.

The media row is deliberately narrower than “no review at all”: commit `5026801` contains a
Codex review of the media implementation plan with seven blockers. The later buffer generation
state machine and its implementation commits still have no discovered implementation review.

## Counter-evidence and healthy behavior

- The current 3.05-second interval matches Telegram's documented group ceiling.
- Per-chat state correctly makes all topics in one supergroup share the same limiter while
  independent mirror/private chats do not block each other.
- Important retry keeps the same `message_thread_id`, accounts failed attempts against the
  interval, recreates files, and logs ambiguous/final loss.
- Final UTF-16 chunking and topic preservation have focused tests.
- `a566371` removes the observed global cosmetic retry starvation. Remaining findings are startup
  sequencing and up to approximately 10 seconds of synchronous status delay in the originating
  stream, not the same one-hour queue lock.
- `56 passed` does not mean the current queue is broken in every ordinary case; the failures
  require burst, slow-startup, new-topic, or late-media states.

## Proposed polish order after approval

### P1-A — replace per-event tool queueing with bounded, fair coalescing

Keep one shared rate authority per `chat_id`, but give it two logical inputs:

1. reliable FIFO for agent/user/error/inter-agent text and explicit files; producers apply
   backpressure instead of unlimited `put_nowait`;
2. one coalesced pending tool digest per `(chat_id, thread_id, agent)`, updated in place;
3. reliable-first scheduling until telemetry reaches 15 seconds of age, then bounded weighted
   fairness: while overdue telemetry exists, at least one of every four eligible send slots goes
   to the oldest pending topic; topics with the same age are round-robin;
4. a hard 2-second, one-attempt deadline for telemetry Bot API calls. Timeout/failure releases the
   dispatcher and preserves textual fallback evidence; telemetry never enters the reliable retry
   path.

This is the third path between "drop every tool" and "mark every tool important". It preserves
activity during tool bursts, bounds memory by active topics rather than event count, and cannot
build an unbounded telemetry backlog. Fifteen seconds is the eligibility threshold, not an
impossible per-topic SLA: for `A` simultaneously overdue topics, healthy-network service is
oldest-first and bounded by the fixed 1-in-4 slot share (`15s + O(4*A*3.05s)`). The hard attempt
deadline bounds the extra delay a failed telemetry call can impose on reliable FIFO. A separate
independent dispatcher is rejected because two senders would violate the same Telegram group
quota.

TDD first:

- continuous important arrivals do not grow tool state beyond one coalesced entry per topic;
- multiple overdue topics are attempted oldest-first/round-robin with at least one telemetry slot
  per four eligible slots while reliable traffic continues;
- a 1,000-tool burst stays bounded and emits a digest containing count/latest activity;
- a never-returning telemetry call times out within 2 seconds, has no retry, and the following
  reliable text proceeds;
- failed image delivery retains/falls back to textual tool evidence;
- cancellation/reset resolves every waiter and cleans temp files.

### P1-B — make cosmetic/topic work unable to delay stream startup

- start exactly one tracked stream for every already-configured topic before both
  `ensure_topics()` and status synchronization;
- track stream tasks by agent/topic and make creation idempotent;
- create missing topics separately under a hard deadline and start each new stream idempotently
  only after its topic exists;
- run startup and runtime status synchronization as bounded background work, deduplicated per topic;
- keep create/rename/delete/status calls outside the reliable delivery retry path;
- own/cancel per-buffer debounce timers and clear or explicitly flush buffer state on stop;
- test existing/new-topic startup, stop/start, create/status timeout, buffer-timer, and mutation
  races.

### P1 — fix inbound media generation ownership

Add a monotonically increasing buffer generation/reservation token. A late completion for a
flushed generation becomes a logged no-op and cannot address the next list by index. TDD the
30-second timeout followed by (a) new text and (b) a new reserved voice/video-note, then complete
the stale old reservation. The stale resolver must neither overwrite content nor decrement the
new generation's `pending_media`.

### P1 — bound every real delivery operation and isolate mirrors

- hard per-attempt/total deadlines for important Bot API calls;
- retain the acknowledged at-least-once duplicate tradeoff;
- do not let an awaited mirror retry prevent the source stream from polling later primary logs;
- add queue length, oldest age, coalesced count, per-class latency, and final-loss metrics/logs.

### P2 — clean contracts, not the whole file

Normalize helper results to explicit `DeliveryResult`/status instead of returning a `Message` for
important calls and a `Future` for tools. Do not perform the old four-module `tg_bridge` split in
this task. If extraction helps testability, move only the delivery scheduler/state owner to one
small module; leave rendering, handlers, and topics in place.

## Verification artifacts

Focused suite:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_tg_bridge.py -q -p no:cacheprovider
56 passed in 2.59s
```

Queue experiment (predeclared criteria):

```text
n=5  tool position=6  important before tool=5
n=20 tool position=21 important before tool=20
n=50 tool position=51 important before tool=50
backlog submitted=1000 queue_size=1000 pending_futures=1000
```

Lifecycle/media experiments:

```text
status count 5/10/25 -> 5.4x/10.7x/26.9x one timeout
new_topic_stream_starts=2
next_batch_after_late_resolve=[('new-msg', 'OLD-VOICE')]
```

## Confidence summary

| Finding | Confidence | Evidence tier |
|---|---|---|
| unbounded queue and strict-priority starvation | **CONFIRMED** | direct code + three deterministic measurements |
| runtime topic-status retry isolation | **CONFIRMED** | source diff + focused slow-status test |
| startup status delay/loss window | **CONFIRMED** | direct code + three deterministic measurements |
| duplicate/untracked streams | **CONFIRMED** | direct deterministic reproduction |
| media generation race | **CONFIRMED** | direct deterministic reproduction + existing TODO |
| mirror stalls later source polling | **CONFIRMED from control flow** | primary source code, not timed against live Telegram |
| missing implementation review artifacts for the listed TG changes | **CONFIRMED with stated exception** | full `git log --follow` + repository-wide doc/hash search; media plan review `5026801` is acknowledged separately |

## Sources

1. **[S1] Primary official documentation:** Telegram, “Bots FAQ — My bot is hitting
   limits, how do I avoid this?”, opened 2026-07-25:
   https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
2. **[S2] Primary official specification:** Telegram Bot API, `ResponseParameters`,
   `message_thread_id`, and request semantics, opened 2026-07-25:
   https://core.telegram.org/bots/api
3. **[L1] Primary local source:** `app/tg_bridge.py` at branch
   `feat/mnt-data-projects-python-orchestra/polish-tg`.
4. **[L2] Primary local tests:** `tests/test_tg_bridge.py`; focused run recorded above.
5. **[L3] Primary local history:** `git log --follow -- app/tg_bridge.py`,
   `git show 0c4c4c0`, and `git blame` over the delivery/lifecycle ranges.
6. **[L4] Incident/task records:** `BUGS.md`, `TODO.md`,
   `docs/tasks/tg-message-delivery/`, and `docs/tasks/codex-review-value/research.md`.
