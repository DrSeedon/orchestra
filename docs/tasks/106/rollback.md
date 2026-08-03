# #106 — rollback for the `COMPACT_PROMPT` swap

Compaction is a **hot path**: this prompt fires for every Claude-backend agent in
every project. Rollback must be possible without reading the research.

**Change commit: `f796a08`** (squash в main; `8b5392d` — до-squash SHA воркера, из `main` НЕ достижим) — `app/session.py`, `COMPACT_PROMPT` replaced with
the `hot_state_ledger` bundle. Codex sessions are unaffected (they take
`_compact_codex_context()`).

## Fastest rollback

```bash
git revert --no-edit f796a08   # ВНИМАНИЕ: после f796a08 были правки той же зоны (#126 и др.) — revert даёт конфликт, разрешать вручную
sudo systemctl restart orchestra
```

Reverts the prompt and the four contract tests together, leaving no half state.
No migration, no schema change, no persisted data depends on this — the prompt is
read fresh on every `compact()` call.

**Restart is required.** `app/session.py` lives in memory under systemd; the
running process keeps the old prompt until restarted. Active turns are
interrupted by the restart.

## Partial rollback (keep the tests, restore old behaviour)

If you want the old prompt but not the test revert, restore just the block:

```bash
git show f796a08^:app/session.py > /tmp/old_session.py
# copy the _ORCH_PRESAVE + COMPACT_PROMPT block (was around line 1184-1206)
```

Then delete `TestCompactPromptContract` from `tests/test_session.py`, since those
four tests assert the new prompt's properties and will fail against the old one.

## What to watch for in live use

The measured wins and their failure signatures:

| Property | Expected after change | Regression looks like |
|---|---|---|
| Last 3 user messages preserved verbatim | exact commands/paths/numbers survive | next session asks for something just stated |
| Repeated compaction (G3) | recent recall holds | context degrades after 2-3 compactions |
| Handoff size | ~2.0 KB median, 38.6% of old | handoffs balloon back past ~5 KB |
| Unrelated writes | 0 | agents creating CLAUDE.md / TODO.md / BUGS.md at compact |
| File-action claims | evidence-backed only | "I read X" / "no files were read" without tool events |

**Most likely regression, and it is a behaviour change, not a bug:** the old
prompt ordered orchestrators to write CLAUDE.md, TODO.md and BUGS.md before every
compaction (`_ORCH_PRESAVE`). The new one forbids creating notes solely for
compaction. That preamble was **never part of the tested candidate** and it
contradicts the candidate's first rule; keeping both would have shipped an
untested hybrid.

Consequence: **orchestrators no longer auto-persist session notes at compact.**
This is deliberate — it is the mechanism behind 218 → 0 unrelated writes — but if
you relied on that automatic write, durable notes must now be written explicitly
during the session, not at compaction. The candidate still promotes a durable
fact when the conversation names an existing canonical path and the exact fact.

If that loss matters more than the write-sprawl it caused, that is a product
decision, not a defect — raise it rather than reverting silently.

## Known gap between what was measured and what shipped

**Read this before trusting the +75.66 pp recent-recall number in production.**

In the experiment the prompt ended with:

> "The runtime will append a redacted raw user tail and a deterministic tool/file
> ledger after your text; do not copy or infer those records."

That was true *there*: `run_evaluation.py` called `compose_handoff()`, which
mechanically appended the verbatim last-three user messages, the tool ledger and
the measured file diff after the model's output. **The 100% recent recall was
produced by that appender, not by the model.**

Production has no such post-processor — `compact()` concatenates the model's own
text and nothing else. Shipping that sentence verbatim would have promised the
next session a block that never arrives. It was therefore replaced with:

> "Preserve the last three user messages verbatim, including exact commands,
> paths, numbers, and error strings."

This asks the model to do by instruction what the harness did by construction.
Every other rule ships byte-identical to the tested candidate.

**Consequence:** the gates measuring recent recall (G1, and the recent half of
G8) were achieved with a deterministic guarantee that production does not yet
have. The other measured wins — bounded promotion (218 → 0 writes), size
(−61.4%), evidence-backed file claims (8 → 0 flags), critical-anchor and pending
recall — come from prompt text that shipped unchanged and are unaffected.

Closing this properly means porting `compose_handoff()` into `compact()` so the
tail and ledger are appended deterministically rather than requested. That is a
code change beyond the approved scope of this task and was **not** done here.
Until it exists, treat recent-recall in production as prompt-dependent and watch
the first regression signature in the table above.

## Evidence behind the change

`docs/tasks/106/q6/report.md`. Seven of eight gates PASS on 126 outputs across 21
newly authored fixtures; G7 UNDECIDED pending the second judge (Codex, from
2026-08-08). Full-suite state at the change: **1452 passed, 27 skipped**.
