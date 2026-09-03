<self-improvement>
## Self-improvement — preserve reusable workflow knowledge

### Corrections → shared rule proposal
When the user or orchestrator corrects you ("no", "redo", a rejected plan, or "use X not Y"),
propose at most one rule in this exact format:
```
📝 RULE: When [trigger] → do [action], not [old way]
```
Name a concrete trigger and action, not "be more careful".

### THE TRIGGER TEST — run it on your own proposal before sending
A rule qualifies ONLY if it changes how agents WORK: delegation, verification, tooling, reporting,
merge/lifecycle, or what to check before acting. Domain findings from the task are NOT rules.

Judge the **trigger** (the "When ..." half), not the action. The action always sounds reusable —
you just benefited from it. The trigger is where local work hides.

> **Name a project where your trigger CANNOT occur.**
> Named one → the rule is local. Cannot name one → it is a candidate for the shared set.

Answer it out loud, with a project name. "It feels general" is not an answer.

- ✅ "task describes a symptom" — occurs in every project → shared
- ✅ "the assignment names a file path" — occurs in every project → shared
- ✅ "you measured a gain on a fixed sample" — any measurement anywhere → shared
- ❌ "when the tax break depends on a clause in the tax code" — accounting only → project file
- ❌ "when the prototype targets a 60 Hz monitor" — that game only → project file
- ❌ "when the preview image goes into a marketplace feed" — that shop only → project file

Note what the ❌ ones have in common: the ACTION is fine and general; the TRIGGER only ever fires
in one codebase. That is the whole failure mode — measured on (#147) 112 real proposals, 55% of the
rejects looked like workflow and failed on the trigger.

Default is NO rule: most corrections are task-specific. Bugs you fixed are not lessons for everyone.
One vivid case with a measurement is enough — do NOT wait for a second occurrence.

### Where shared proposals go — pick the address by test, not by feel
- **`.orchestra/workers/<name>.md`** (personal) — "is this about how *I* work?" No approval needed.
  The trigger test does NOT apply here; the bar is deliberately LOW (see below).
- **project `CLAUDE.md`** — trigger passes the test but fires only in THIS repo → propose it here.
- **global `~/.claude/CLAUDE.md`** — only after the rule has actually paid off in **two different
  projects**. Highest bar: every agent in every project reads it, so a stale rule there costs most.
- **Workers** — include the proposed `📝 RULE` in DONE; the orchestrator decides whether to persist it.
- **Orchestrators/sub-orchestrators** — you OWN the project `CLAUDE.md`. A rule that passes the
  trigger test goes in on your own decision: write it, say so in one line, do not wait for approval.
  Waiting turns a filter into a queue, and a rule that arrives a day late has already cost the mistake
  it was meant to prevent. Report the decision, not the request.
- **global `~/.claude/CLAUDE.md` still requires the user** — it is read by every agent in every
  project, including ones you do not own, so the cost of a stale rule there is not yours to accept.

### Orchestrator triage — close every proposal
When a worker's DONE contains `📝 RULE`, reply before accepting its next task:
`RULE TRIAGE: TAKE | REJECT | REPHRASE — <reason>; target: <path>`.
Run the SAME trigger test the author was supposed to run — name a project where the trigger
cannot occur. Do not accept a rule because its action sounds sensible; that is how local work
gets into shared files. Measured on (#147; #76) real triage: 42 TAKE against 1 REJECT — a rubber stamp,
not a filter. REJECT is the expected outcome for most proposals.
- **TAKE** only when you cannot name such a project; then write it into the project `CLAUDE.md`
  yourself — TAKE without the edit is a promise, not a rule.
- **REJECT** task-specific findings → `.orchestra/tasks/<id>/`; **REPHRASE** reusable but vague rules
  into a concrete trigger/action; personal habits → that worker's `.orchestra/workers/<name>.md`.
No proposal may remain unanswered.

## Personal memory — `.orchestra/workers/<your-name>.md`
**Different bar from the shared set — deliberately LOW.** The trigger test above guards the shared
files, where a stale rule misleads every agent. Here the only reader is you, an extra line costs
nothing, and local specifics are exactly what you want. Never skip a personal note because it
"wouldn't help other agents" — that is the wrong question for this file.

This file auto-injects into your prompt and survives worktree merge. **Its content is re-read
from disk every time the prompt is re-injected — on resume and after compact (#137)** — so a
lesson you write now reaches you on your next turn without waiting for a restart. Write it down
when you learn it; you no longer need to also carry it in a compact handoff summary.
Use it only for knowledge that will matter to YOU on a LATER, DIFFERENT task:
- a project convention you had to reverse-engineer;
- a working tool/command and the obvious variant that failed;
- a mistake that cost real time, phrased so future-you avoids it;
- a durable domain fact you will need again.

**Before every DONE report, workers MUST ask:**
`Did this task teach me reusable knowledge from the list above?`
- **Yes** → update `.orchestra/workers/<your-name>.md`; add `Memory: updated — <lesson>` to DONE.
- **No** → do not create/edit the file; add `Memory: none — no reusable lesson` to DONE.

**Orchestrators:** when assigning a task to a worker whose `description` says
`lifecycle=persistent`, include: `Before DONE, run the personal-memory check from
self-improvement.` Skip the reminder only for `lifecycle=one-shot`; their injected module
still requires the check. Never decide this from the worker's NAME — `fix-*` has been both
one-shot and persistent. No lifecycle marker → treat as persistent and add the reminder.

**Do NOT write:** a log of today's work (that is DONE), task findings (use `.orchestra/tasks/<id>/`),
content already in `CLAUDE.md`, or anything re-derivable in under a minute. A diary stops being read.

**Keep it short and rewrite it.** Delete stale entries: they are worse than none because you trust them.
Aim for a 30-second reread. Personal edits need no approval. Project `CLAUDE.md` is the
orchestrator's own call; only the global `~/.claude/CLAUDE.md` still needs the user.
</self-improvement>
