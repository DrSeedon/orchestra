## Summary

Naturally, the five-minute delay is easy; deciding which task still owns the Telegram edit is where the fun begins 😏

The overall design is sound, with no blocking contradictions:

- A distinct `cron_command` is safer than extending `cron`. Existing validation accepts extra cron fields but ignores them during dispatch, whereas an old server rejects an unknown type.
- Limiting `timeout_seconds=0` to recurring/watch jobs—`cron`, `cron_command`, `file`, `command`, and `ssh`—is correct. `timer` and `run` should retain bounded lifetimes.
- Preserving immediate running state, delaying only idle, and removing the startup cache eviction are consistent with the current paths.
- The no-wall-clock testing approach is appropriate.

Within the permitted sources, DB type constraints and restart restoration cannot be independently verified; the planned persistence/restore tests therefore remain necessary.

## Findings (blocking/suggestion/question)

### suggestion: Route stream-log running through the cancellation path

[plan.md:63](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:63) requires every new running signal to cancel pending idle, but the current stream path calls `_schedule_topic_status(..., True)` directly for text/tool logs at [tg_bridge.py:2291](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/tg_bridge.py:2291). The test AC covers only an “interactive running signal,” so an implementation could fix the session hook and leave this independent path bypassing cancellation. Require either the stream path to use the common running helper or `_schedule_topic_status(True)` itself to cancel idle ownership, with a deterministic stream-path test.

### suggestion: Close the idle-owner-to-status-worker handoff race

The plan only cancels idle-delay owners during deletion and rename at [plan.md:68](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:68). Once the delay owner calls `_schedule_topic_status`, the actual edit belongs to a separate `_topic_status_tasks` task at [tg_bridge.py:1848](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/tg_bridge.py:1848); cancelling the now-finished delay owner cannot stop that edit. Keep the delay owner alive by awaiting the returned status task, or cancel/await both registries and clear desired state before deleting or renaming. Add a test that releases the delay, blocks inside `edit_forum_topic`, then deletes or renames the topic.

### suggestion: Make subprocess cleanup runner-owned

“Terminate through the existing `_procs` lifecycle” at [plan.md:46](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:46) is underspecified. The current command watcher removes the process from `_procs` in an inner `finally` at [bg_jobs.py:469](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/bg_jobs.py:469), then its outer cancellation handler returns without killing it at [bg_jobs.py:487](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/bg_jobs.py:487). The new recurring runner should retain a local process reference and kill it in an outer `finally`, using identity-safe registry removal. Exercise cancellation while `communicate()` is blocked, not only between fires.

### question: Define timeout and non-zero-exit semantics

The research requires timeout and non-zero exit to remain observable at [research.md:153](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/research.md:153), but the plan only specifies a 30-second cap and `last_output` update at [plan.md:41](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:41). Specify whether matching output from a non-zero process wakes the agent, and require timeout to kill the process, leave the recurring job active, record an explicit timeout marker, and avoid waking on empty output. Otherwise two reasonable implementations will produce different alert behavior.

### suggestion: Make the zero-Telegram-edit boundary assertion non-vacuous

The T1 file scope at [plan.md:107](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:107) contains only background-job/MCP tests, while `bg_jobs` never calls `edit_forum_topic` directly. Merely installing a bot mock and asserting zero edits would prove nothing beyond module separation. Wire the mocked session’s `send` boundary to the real topic-running hook, or phrase the AC causally as “no topic edit attributable to the four fires.” Absolute zero edits cannot be guaranteed in a live scope because startup synchronization and unrelated stream logs are independent edit sources.

## Verdict

**Approve with revisions.** The selected contract and timeout scope are correct, and there are no blocking plan contradictions. Tighten the two ownership handoffs, cover the stream-running bypass, and define process-result semantics before implementation.

Otherwise the debounce merely hands a live Telegram edit from one registry to another and declares it cancelled.

## Round (2026-07-29T04:55:17Z)

One timeout, two mutually exclusive promises—efficient specification work 😏

## Re-review status

`git diff` is empty because the revised documents are untracked; I reviewed their current contents directly.

1. **RESOLVED — stream-log running bypass.** [plan.md:74](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:74) makes direct `_schedule_topic_status(..., True)` cancel delayed idle, with explicit coverage at [plan.md:162](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:162).

2. **RESOLVED — lifecycle handoff race.** Delay and edit remain in one `_topic_status_tasks` owner at [plan.md:71](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:71). Existing lifecycle cleanup pops, cancels, and awaits that owner at [tg_bridge.py:1530](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/app/tg_bridge.py:1530); deletion and rename invoke it before mutation.

3. **RESOLVED — subprocess ownership.** Runner-local reference, outer cleanup, and identity-safe `_procs` removal are specified at [plan.md:43](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:43), with blocked-`communicate()` cancellation coverage at [plan.md:147](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:147).

4. **STILL OPEN — timeout wake semantics.** See the blocking contradiction below.

5. **RESOLVED — non-vacuous Telegram boundary.** The separate #99 test wires fake `session.send` to the real scheduler and proves both no-match silence and forced-match edit at [plan.md:126](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:126).

## New findings

**blocking — Resolve timeout output semantics.** [plan.md:46](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:46) says regex is the sole wake condition, which implies a timed-out process with partial matching output wakes. But [plan.md:139](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:139) says timeout does not wake. Specify one rule—author notes suggest “completed processes use regex; timed-out invocations never wake regardless of partial output”—and test timeout after emitting matching output.

No further contradiction was found in the single-registry design or scoped territory.

## Verdict

**NOT APPROVED** until the timeout-with-matching-output contradiction is resolved. Everything else from Round 1 is adequately addressed.

## Round 2

The timeout path currently has one process and two rulebooks; Telegram will inevitably pick the inconvenient one.

## Round (2026-07-29T04:56:26Z)

The timeout has finally chosen one legal system 😏

## Re-review status

**Prior blocker: RESOLVED (FIXED).**

Exact agreement now exists across:

- Completed-process semantics: regex decides wake at [plan.md:46](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:46).
- Timeout exception: never wakes, including matching partial output, at [plan.md:49](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:49).
- Explicit acceptance test at [plan.md:141](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/plan.md:141).
- Matching research conclusion at [research.md:155](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-topic-flicker/docs/tasks/99/research.md:155).

`git diff` remains empty because both artifacts are untracked; their current contents were reviewed directly.

## New findings

None.

## Verdict

**APPROVED.** No blocking contradiction or open question remains. Implementation can begin.

## Round 3

Three rounds later, the timed-out process is finally forbidden from ringing the bell on its way out.
