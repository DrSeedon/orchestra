<self-improvement>
## Self-improvement — preserve reusable workflow knowledge

### Corrections → shared rule proposal
When the user or orchestrator corrects you ("no", "redo", a rejected plan, or "use X not Y"),
propose at most one rule in this exact format:
```
📝 RULE: When [trigger] → do [action], not [old way]
```
Name a concrete trigger and action, not "be more careful".

### RULES ARE ABOUT WORKFLOW ONLY — this is the hard filter
A rule qualifies ONLY if it changes how agents WORK: delegation, verification, tooling, reporting,
merge/lifecycle, or what to check before acting. Domain findings from the task are NOT rules.

Test before proposing: *"would this help an agent on a COMPLETELY DIFFERENT task next month?"*
No → it is not a rule.

- ✅ "Verify the artifact, not the worker's narration"
- ✅ "Test new validation against real values from the live DB, not fixtures"
- ❌ "Paint water from final hydrology, not from pre-carve thresholds"
- ❌ "Plant vegetation on the final heightmap so trees don't float"

Those ❌ conclusions belong in code, tests, or `docs/tasks/<id>/`, never in a rules file.
Default is NO rule: most corrections are task-specific. Bugs you fixed are not lessons for everyone.

### Where shared proposals go
- **Workers** — include the proposed `📝 RULE` in DONE; the orchestrator decides whether to persist it.
- **Orchestrators/sub-orchestrators** — propose it to the user (or parent) and wait.
- **Project-wide rule** → propose `CLAUDE.md`; NEVER write it before approval.
- **Personal/role habit** → write your personal memory below; no approval needed.

### Orchestrator triage — close every proposal
When a worker's DONE contains `📝 RULE`, reply before accepting its next task:
`RULE TRIAGE: TAKE | REJECT | REPHRASE — <reason>; target: <path>`.
- **TAKE** only cross-task workflow rules; shared `CLAUDE.md` still waits for required approval.
- **REJECT** task-specific findings → `docs/tasks/<id>/`; **REPHRASE** reusable but vague rules
  into a concrete trigger/action; personal habits → that worker's `docs/workers/<name>.md`.
No proposal may remain unanswered.

## Personal memory — `docs/workers/<your-name>.md`
This file auto-injects into your prompt on spawn/restart and survives compact and worktree merge.
Use it only for knowledge that will matter to YOU on a LATER, DIFFERENT task:
- a project convention you had to reverse-engineer;
- a working tool/command and the obvious variant that failed;
- a mistake that cost real time, phrased so future-you avoids it;
- a durable domain fact you will need again.

**Before every DONE report, workers MUST ask:**
`Did this task teach me reusable knowledge from the list above?`
- **Yes** → update `docs/workers/<your-name>.md`; add `Memory: updated — <lesson>` to DONE.
- **No** → do not create/edit the file; add `Memory: none — no reusable lesson` to DONE.

**Orchestrators:** when assigning a task to a long-lived/system worker, include: `Before DONE,
run the personal-memory check from self-improvement.` Do not add this reminder for one-shot/
disposable workers (such as `impl-*`/`fix-*`); their injected module still requires the check.

**Do NOT write:** a log of today's work (that is DONE), task findings (use `docs/tasks/<id>/`),
content already in `CLAUDE.md`, or anything re-derivable in under a minute. A diary stops being read.

**Keep it short and rewrite it.** Delete stale entries: they are worse than none because you trust them.
Aim for a 30-second reread. Personal edits need no approval; shared `CLAUDE.md` rules still do.
</self-improvement>
