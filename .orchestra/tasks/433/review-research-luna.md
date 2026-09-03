<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Apparently Phase 1 still needed an autopsy before Phase 2 could touch a column 😏

## Summary

The arithmetic is correct: the listed rows sum to 181 and the roll-up is consistent. However, several “CONFIRMED” conclusions are overstated. Read-only checks found 29 send sites and 2 direct transactional writers within the allowed seams; no files were changed and no tests were run. Luna was unavailable, so no substitute or Sol review was run.

## Findings (blocking/suggestion/question)

No blocking findings.

1. **suggestion:** [research.md:83](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/research.md:83>) — F5 misses runtime prefix consumers in `app/session.py:1195-1198` and `app/limit_wake.py:59-65,569-576`; these inspect `[system] Retrying...` and `[system wake:...]` in log content. Updating only dashboard/TG/RAG leaves the “no runtime provenance parsing” AC unmet.

2. **suggestion:** [research.md:43](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/research.md:43>) — The 181-row mapping does not document known producers `[system wake:...]`, `[Cron command matched]` (`app/bg_jobs.py:819-822`), or raw voice transcription (`app/routes/tg.py:107-110`). Prove these contribute zero rows to the frozen cohort or add explicit migration rules; the correct sum alone does not prove complete classification.

3. **question:** [research.md:47](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/research.md:47>) — A receipt join plus non-empty `sender` does not prove `agent`: `InitialDeliveryRequest.sender` is caller-supplied, while direct deliveries distinguish `operator` from MCP through `source_principal` (`app/routes/sessions.py:749-756`). The migration needs an explicit trusted-principal rule, including operator-origin rows.

4. **question:** [research.md:18](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/research.md:18>) — Current UI behavior proves that agent names are displayed, but the supplied AC requires explicit labels, not exact agent/job identity. Category-plus-sender should be presented as a compatibility choice unless preserving exact sender names is made an explicit requirement.

5. **question:** [research.md:109](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/research.md:109>) — The artifact correctly notes that mailbox delivery can combine senders, but the recommended invariant still uses scalar `origin` and `sender`. Define whether multi-origin batches are split, represented as arrays, or forced to `unknown`; otherwise one log row cannot satisfy “right bubble only `origin=user`”.

## Verdict

Needs work. No blocking crash, corruption, or security finding, but F2/F5/H3 should not remain marked confirmed until these gaps are resolved.

Evidence quote: “A missing field can never fall back to `user`.”

The spreadsheet math is wearing a tie, but the mailbox still cannot say who wrote the blank envelope.
