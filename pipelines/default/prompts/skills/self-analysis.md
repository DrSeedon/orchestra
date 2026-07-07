---
name: self-analysis
description: "Per-task retrospective — after a substantial task, analyze what went wrong via root-cause, anchored to concrete signals (Codex verdict, test failure, retries, corrections). Writes docs/tasks/<id>/retro.md. Triggers: '/self-analysis', '/retro', 'do a retro', 'run a retrospective', 'analyze how that went', end of a gated task before DONE."
roles: [full-cycle]
integrations: []
---

# Self-Analysis — per-task retrospective

Deep post-task review: root-cause of mistakes + patterns of inefficiency, so the next task goes better.
This is NOT the reactive correction-capture (that's `self-improvement`). This runs on your OWN task artifacts.

## When to run
Invoke this **before your final DONE report**. Then **skip immediately** (write nothing) unless the task hit
**≥1 concrete signal** below. Trivial tasks produce no retro.

Signals (any one → run; none → skip):
- Codex review returned CRITICAL/HIGH, **or** a test run failed at any point during the task
- ~5+ files touched, **or** a long task (~10+ tool calls)
- The user corrected or rephrased the task mid-flight
- A single command was retried ≥3×
- Explicit `/self-analysis` or `/retro` — always runs, even with no signal

## How (the one hard rule)
**No signal ⇒ no entry.** Every "what went wrong" item MUST cite a concrete signal (a Codex finding, a failed
test, a retry count, a correction). Do NOT introspect open-endedly ("I could have been cleaner") — unanchored
self-critique makes things worse, not better. You are good at explaining a failure *once you have its location*;
you are bad at *inventing* failures. So: collect the signals first, then explain each one's root cause.

1. Collect the **Metrics** block from your own turn history (tool calls, retries, files ±, Codex/test verdicts, corrections).
2. For each signal, write: **signal → root cause → category** (process / correctness / rule-violation / scope).
3. Note what went well (only if a signal confirms it, e.g. "Codex caught the bug pre-commit").

## Output location (Tier-1, auto — allowed)
- `docs/tasks/<task-id>/retro.md`. No task-id ⇒ `docs/tasks/adhoc-retro-<YYYYMMDD-HHMM>.md`.
- `docs/workers/<your-name>.md` — append a lesson **only if** it derives from an anchored retro entry, is
  generalizable, and is directly actionable for you. n=1 weak observations stay in the retro, NOT in memory.
  Append/merge only — never overwrite, no secrets, one short line each.

## Proposals (Tier-2 — propose only, NEVER write)
Changes to `CLAUDE.md`, `pipelines/**` (base/modules/roles/skills), or `pipeline.yaml` go in the retro's
"Proposed changes" table as text and are surfaced in your DONE report. **You MUST NOT edit those files.**
Default row status = **"logged, not promoted"** — a single task is too little evidence to change fleet-wide
prompts. Mark "promote" only if the signal is severe (e.g. a Codex HIGH traced to a prompt cause) or the same
issue is already known to recur.

## Template
```markdown
# Retro — <task-id> (<short title>)

## Metrics
- Tool calls: N | Retries: N (<what>) | Turns: N | Files: N (+X/−Y)
- Codex: <verdict> | Tests: <result> | User corrections this task: N

## What went wrong (signal → root cause)
- **Signal:** <concrete signal>. **Root cause:** <why>. **Category:** <process|correctness|rule-violation|scope>.

## What went well (keep doing)
- <only signal-confirmed items>

## Proposed changes (Tier-2 — NOT applied, awaiting approval)
| Target | Change | Evidence | Status |
|---|---|---|---|
| <file> | <change> | <signal + n=1/recurs> | logged, not promoted |

## Written to worker memory (Tier-1 — applied)
- <lesson, or "none">
```
