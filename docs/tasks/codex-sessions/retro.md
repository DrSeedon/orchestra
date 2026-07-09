# Retro — codex-sessions

## Signal
6 Codex review rounds. Findings degraded from real bugs → intentional edge-cases, which is the
right shape, but rounds 1-3 caught bugs I should have caught in my own /tmp tests first.

## Root cause of the missed bugs
My initial /tmp verification tested the **happy path** (new + resume) and misread its output:
the resume test showed "1 Round match" and I read it as success — it was actually the `-o`
**overwrite** (Codex round 1). I verified the mechanic worked but not the *invariant* (history
preserved). Same for exit-code (didn't test jq-missing) and jq-parse (didn't test with the
polluted-stdout that the fallback path produces).

**Lesson:** when the feature's VALUE is an invariant ("history preserved", "exit code reflects
codex", "graceful degrade"), the test must assert the invariant, not just "the command ran".
A green run that doesn't check the invariant is a false negative.

## What worked
- Shell-side UUID capture (jq on JSONL) was the right architecture call from research — the bg
  job is detached, Python can't capture it. Confirmed by measurement before coding.
- Debate discipline: verified every Codex finding against code/measurement before applying;
  applied 5, reasoned 1 as intentional. No blind acceptance, no silent dismissal.

## Tier-2 proposal (for orchestrator)
📝 RULE: When a feature's value is an INVARIANT (history-preserving / exit-code-faithful /
graceful-degrade), the verification must assert that invariant explicitly (before-state vs
after-state, failure-injection), not just "the command exited 0". A run that doesn't test the
invariant is not evidence the invariant holds.
Suggested home: full-cycle.md Phase 3 self-verify, or CLAUDE.md PROCESS RULES.
