# V-995 — "Prompt is too long" at displayed 93% context (katya-work-orchestrator)

## Incident state
Failure 09:40:16Z; auto compaction began 09:40:51Z (context 99%, 986709 tokens). It is an agentic (tool-using) compaction: at 09:47Z the CLI transcript showed 56 calls since 09:42, prompt 314K tokens and growing steadily, so it was healthy, not stuck. At the time of this report the compaction had not finished; I did not touch the session. The owner's queued messages (09:40 "Скинь разбор платформ", 09:42 voice) sit in `_pending_messages` ("message queued (compact in progress)") and are flushed by compact().

## Root cause (measured)
Source: Claude CLI transcript `~/.claude/projects/-home-kesha-katya-work/30839354-….jsonl` plus `logs` in data/orchestra.db.
1. API-reported size of the last request before the failure (09:23:18): 934,259 tokens (input+cache_read+cache_create) = 93.4% of 1M. The displayed 93% was correct.
2. The next send (09:40:16) was not a 4-line message. `app/session.py` (~l.1407–1462) prepends the **entire refreshed system prompt** to the first message after a session (re)start (`_prompt_injected` is False at process start, after compaction, model change): the transcript entry is 95,135 chars ("[Orchestra platform note: refreshed context …]<platform>…"). On top of it the CLI re-attached its `instructions` attachment (CLAUDE.md files) in the same request. CLI-estimated total afterwards: 986,709; real API count was above 1,000,000 → "Prompt is too long".
3. Nothing in our accounting looked at this: the critical threshold (95%) compares the percentage of the previous measurement, and a 93% session has no headroom for a ~50–70K injection.
4. Second defect found on the way: for Claude the context is "deferred" (measured by `_refresh_context_from_api` after the turn), but `schedule_compaction_on_success` was only passed for *unknown* context, so the turn-end compaction decision always used the previous turn's number (lag of one turn; a 30-call turn at 09:01 grew 877K→911K inside one turn).

## Fix (behavioural tests: tests/test_context_overflow_v995.py, red without the change)
- `injection_overflows_context` + guard in `AgentSession.send`: Claude, auto-compact on, idle, no durable delivery; if `total_tokens + (message + pending prompt injection)/2 bytes-per-token + 4% of the window ≥ window` the message is queued, `_overflow_compact` runs `compact()` and flushes. Later messages join the queue; a guard compaction that did not change the token count does not retrigger (no loop).
- Turn end now re-runs the compaction decision after the refresh for deferred contexts.
Limits: the 4% reserve and bytes/2 are heuristics calibrated on this single incident (~66K unaccounted tokens); the CLI attachment size is not measured, only covered by the reserve. Does not help when compaction itself cannot run (e.g. subscription limit) — then the message is sent after the failed compaction, as before.
Checks: `uv run --frozen python -m pytest tests/test_context_overflow_v995.py tests/test_session.py tests/test_compact_pending_ack_467.py tests/test_compact_pending_rollback_467.py tests/test_compact_gate_438.py tests/test_limit_wake.py -q` → 298 passed.

## Q3: does changing a temp rule / agent memory rewrite the prompt cache of every running agent?
No. Running Claude sessions keep the system prompt the CLI was started with (a resumed session sets no system prompt); changes reach an agent only as text prepended to a user message, once per (re)start/compaction/model change (`_prompt_injected`), so they are appended at the tail. Measured in the same transcript: first call after the 08:38 restart — cache_read 782,880 (prefix intact), cache_create 62,948 (1h); the call after "prompt updated" at 09:02 — cache_read 877,917, cache_create 33,910. So the cost of a prompt change is ~34K (prompt) to ~63K (prompt + re-attached instructions + new work) tokens of 1h cache write per agent on its next restart, not a ~1M rewrite: at Opus 5.5 list input $4/M with 1h write ≈2× → roughly $0.3–0.5 per agent. A full ~1M rewrite (~$8) happens only when the 1h cache has expired, which is independent of rule changes. Temp rules also do not reach an already-injected running session until its next restart (so "from next turn" in the tool text is optimistic).

## Restart
Python changes (`app/session.py`, `app/session_turns.py`) → restart needed after merge. I did not restart anything.
