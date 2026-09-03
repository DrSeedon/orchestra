## Summary

Naturally, the proposed cure preserves the starvation condition it diagnoses—just with tidier state. 😏

The audit’s core diagnosis is mostly sound:

- Conclusions 1–4 are confirmed, although the media race affects only voice and video-note reservations.
- Conclusion 5 is not correct as specified: the coalesced lane still permits indefinite telemetry starvation.
- Conclusion 6 overstates missing review evidence; there is a concrete media-plan review artifact.
- The focused suite passes: `56 passed`.
- The 3.05-second limiter is consistent with Telegram’s documented 20-messages-per-minute group limit ([Telegram Bots FAQ](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)).

## Findings

### blocking: Guarantee eventual service for the coalesced tool lane

**Location:** [research.md:290](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:290)

The proposed digest is sent “only when no reliable item is waiting,” so a continuous reliable stream still postpones it forever—the exact strict-priority starvation used to refute H1. Coalescing bounds memory but does not make tool activity visible. Specify a bounded fairness rule or maximum telemetry age, and add a test proving eventual digest delivery while reliable traffic continues.

### blocking: Remove `ensure_topics()` from the existing-stream critical path

**Location:** [research.md:308](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:308)

The plan backgrounds status synchronization but does not explicitly move existing stream startup ahead of `ensure_topics()`. Its sequential `create_forum_topic()` calls have no hard timeout, so a hung create can still prevent every configured stream from starting and preserve the same permanent log-loss window. Start streams for already-configured topics first; create missing topics separately under a deadline and start each idempotently after creation.

### suggestion: Limit the generation-race claim to reserved handlers

**Location:** [research.md:164](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:164)

Only `handle_voice()` and `handle_video_note()` call `_register_media()` and later `_resolve_media()`. Photo, document, video, audio, and sticker handlers await their work and then call `_send_to_agent()`, so they cannot reuse a stale reservation index. They may have a separate ordering problem under slow downloads, but they do not share this corruption mechanism.

### suggestion: Test stale resolution against a new media generation

**Location:** [research.md:318](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:318)

The reproduction covers stale media overwriting new text, but `_resolve_media()` also decrements `pending_media` unconditionally. If the next generation contains media and is already `WAITING_MEDIA`, an old resolver can reduce its counter to zero, flush it prematurely, and discard its real completion. The TDD case should use old voice/video-note followed by new media; “late photo completion” cannot exercise this reservation path.

### suggestion: Qualify runtime topic-status isolation

**Location:** [research.md:187](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:187)

The hotfix correctly removes global queue starvation, but startup is not the only remaining delay. `stream_logs()` still awaits `_update_topic_status()` before processing each first text/tool after a state change, so a stalled primary plus mirror can delay that agent’s reply by up to roughly ten seconds. State that global delivery is isolated while the originating stream remains synchronously gated, and ensure the background-status plan covers runtime calls too.

### suggestion: Correct the media review-coverage classification

**Location:** [research.md:245](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:245)

The “no review artifact” classification has a counterexample: [docs/tg-media/CODEX_REVIEW.md:1](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tg-media/CODEX_REVIEW.md:1) was committed in `5026801`, is an ancestor of `1e39c47`, and reviews the media/voice implementation plan with seven blockers. It does not review the later `d01e750` generation state machine, so split the row into reviewed plan context versus unreviewed implementation/state-machine changes.

### suggestion: Recalibrate the proposed P0 labels

**Location:** [research.md:284](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:284)

The experiments establish real reliability defects, but not P0 severity under this project’s definition. The current priority queue protects important replies; the demonstrated queue impact is unbounded telemetry state and delayed tool visibility, without an observed OOM or continuing text outage. Startup loss is serious but restricted to restart/creation windows. Both are P1 work unless production evidence shows a current sustained delivery outage.

### suggestion: Include debounce tasks in lifecycle ownership

**Location:** [research.md:137](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:137)

The lifecycle audit identifies untracked stream tasks but misses `_BufState.debounce_task`, also created outside `_tasks`. `stop_bridge()` neither cancels these timers nor clears `_buffers`; stopping during the 5–30 second inbound window can therefore lose the batch against `_manager=None` or deliver stale input through a newly started manager. Add inbound-buffer stop/start ownership to the lifecycle plan and tests.

## Verdict

**❌ Needs revision — high confidence.**

The audit correctly finds the current queue, startup, stream-ownership, image-result, and media-generation defects. It is not ready to approve as a Phase 2 plan because the proposed tool lane reproduces starvation, topic creation can remain on the startup critical path, and two factual classifications need correction.

A starvation fix that waits forever for a quiet moment is rather like fixing the Telegram outage by hoping Telegram gets bored first.

## Round (2026-07-25T12:04:43Z)

## Re-review status

Naturally, the “uncommitted diff” is already committed. 😏 The worktree is clean, so I reviewed `c887a5d` against `41d6b67`; it exactly matches the author notes.

| Prior finding | Status |
|---|---|
| Eventual telemetry service | **FIXED** — forced service at 15 seconds plus continuous-traffic AC |
| `ensure_topics()` startup gate | **FIXED** — configured streams start first; creation is separately bounded |
| Media-handler scope | **FIXED** — limited to voice/video-note |
| Stale resolver against new media | **FIXED** — overwrite and `pending_media` corruption are covered |
| Runtime status qualification | **STILL BROKEN** — the body is corrected, but [research.md:304](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:304) still says startup is the only remaining finding |
| Review-coverage classification | **STILL BROKEN** — the row is corrected, but [research.md:409](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:409) still broadly claims artifact absence for all listed commits |
| P0 severity inflation | **FIXED** — recalibrated to P1-A/P1-B |
| Debounce lifecycle ownership | **FIXED** — stop policy and tests are now explicit |

## New findings

### blocking: Bound the forced telemetry API call itself

**Location:** [research.md:322](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:322)

The scheduler bounds when telemetry starts, but not how long its Bot API call may occupy the shared dispatcher. A stalled digest send can still delay reliable FIFO far beyond the claimed single 3.05-second slot; the later deadline requirement covers only important calls. Require a hard telemetry attempt deadline and an AC with a never-returning digest followed by reliable text.

### suggestion: Define fairness across multiple overdue topics

**Location:** [research.md:318](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/polish-tg/docs/tasks/polish-tg/research.md:318)

Ten digests can reach 15 seconds simultaneously, but only one can consume the next slot. Therefore 15 seconds cannot be a per-digest maximum while also returning to reliable FIFO after every digest. Define oldest-first scheduling and the actual bound as a function of active topics, then test multiple overdue topics under continuous reliable traffic.

## Verdict

**❌ NEEDS REVISION.**

All prior blocking findings are resolved, but the new missing telemetry-call deadline can still recreate a shared-delivery stall. No code changed, and `git diff --check` is clean.

The scheduler now owns a watch; unfortunately, the network call still owns the snooze button.

## Round (2026-07-25T12:07:40Z)

## Re-review status

Naturally, Round 3 is committed too. 😏 The worktree is clean; reviewed `c887a5d..c544854`.

| Prior finding | Status |
|---|---|
| Indefinite telemetry starvation | **FIXED** |
| `ensure_topics()` startup gate | **FIXED** |
| Media race handler scope | **FIXED** |
| Stale resolver decrementing new generation | **FIXED** |
| Runtime status-delay wording | **FIXED** |
| Review-coverage overstatement | **FIXED** |
| P0 severity inflation | **FIXED** |
| Debounce lifecycle ownership | **FIXED** |
| Unbounded telemetry API call | **FIXED** — hard 2-second, single-attempt deadline |
| Multi-topic fairness | **FIXED** — eligibility, weighted share, ordering, capacity bound, and AC are explicit |

## New findings

None. The fairness policy, failure bound, startup ordering, lifecycle ownership, and acceptance criteria are internally consistent at the Phase 1 level.

## Verdict

**✅ APPROVED.**

No remaining load-bearing Phase 1 error found. Documentation-only diff passes `git diff --check`; no implementation was demanded or reviewed.

The scheduler finally owns both a watch and an alarm—civilization survives.
