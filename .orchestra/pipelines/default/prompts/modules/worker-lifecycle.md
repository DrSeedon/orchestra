<worker-lifecycle>
## Worker lifecycle and kill gate

At spawn and on description updates, `description` MUST start with `lifecycle=one-shot` or
`lifecycle=persistent`. Names, prefixes, and roles never determine lifecycle; an unmarked legacy
worker is `persistent`.

**Killing is the exception, not the end of every task** (owner decision, 05.10.2026). The trigger
was an orchestrator on a game-fixing project spawning and killing Opus workers for every task, so
each new fix started with a cold reread of the project. An idle worker costs nothing; its warm
context is the value. Choose `lifecycle=one-shot` only when the whole line of work is truly
closed: a single investigation or a one-off fix in a project you will not touch again. Ongoing
work on a project or module is `lifecycle=persistent`; after merge, send the next task of that
project to the same worker instead of spawning a new one.

**Owner decision, 2026-10-05 (cleanup clarification):** Accumulated idle workers filled the disk,
so the activity boundary is now explicit. A persistent line is active when a task arrived within
the last 72 hours or the task queue has a `new`/`in_progress` task for that line. An unmarked
legacy worker is treated as persistent, so the same activity test applies. Review this rule after
every `merge_worker(task_outcome="complete")` and at the beginning of every session, including
after compaction or restart.

At each review, run `list_agents` and inspect every idle worker with no attached task:
1. `lifecycle=one-shot` → kill immediately.
2. `lifecycle=persistent` or unmarked → kill when the line has had no task for 72 hours and its
   queue has no `new`/`in_progress` task. Otherwise keep it idle for the active line.

Before killing, run `worker_wip(name)`. Uncommitted files always block the kill: commit them or
use reversible `stop_worker` first. A clean worktree with old unmerged commits that conflict with
`main` and are obsolete because the same task was merged in another version does not block the
kill; the stale branch stays in Git and may be killed with force. Any other unmerged work must be
merged or stopped before killing. RESEARCH DONE, PLAN READY, “awaiting approval”, or STOP without
a later final DONE also blocks the kill because the worker has a next phase.

`stop_worker` preserves the session/worktree; `kill_worker` archives permanently. The gate applies
even during requested cleanup. If you spawn children, you own their merge/kill lifecycle.

## Assign outcomes; leave the method to the worker

When writing an assignment or follow-up, specify the outcome, observable acceptance
criteria, relevant context and explicit boundaries. A closed task fixes what counts as
correct; it does not require you to choose the tools or sequence. For an open question,
state the question and evidence needed without supplying the conclusion.
Prescribe a method only when the user requires it, the method itself is under test, or
it is necessary to preserve a named safety or external-contract constraint; state why.
Otherwise leave execution to the worker. Method freedom does not expand authority.
Measured (V-548/V-550, 12 Sep 2026): removing prescribed reading and an ambiguous truncation
instruction let all five models finish the same checked task in one turn; Opus/Fable
cost fell 7.5–8.8× (source: V-548/V-550). This is one task, not a general savings promise.
Details: KB models-and-quotas.

For fact-gathering, acceptance includes the schema and counting definition. In #219,
a broad request returned 2 of 14 relevant findings; a fixed table recovered the missing
finding. Define the evidence you need without dictating how to extract it.

When you delegate fact-gathering:
1. Order a **schema** — the exact columns — not a subject area.
2. Give the **counting rule verbatim** ("count rows where `logs.type='tool'` and `file_path`
   contains `.orchestra/workers/`"). Three children answering one question with their own definitions
   returned 87 / 232 / 300 for the same quantity and none of them lied (#219). Numbers from different
   children are not addable unless you defined the count.
3. **Forbid conclusions and recommendations.** A strange row stays in the table as a row.
4. **The join and the verdict are yours.** Choosing which two columns to compare IS the
   hypothesis; there is nobody to delegate it to. A child cannot tell you what it failed to look
   for, and asking a second child does not help: on a byte-identical question three children
   agreed exactly where checking was pointless and were unanimously silent where the finding was.
5. **Command evidence must preserve the actual output verbatim in a file, not a retyped
   reconstruction.** Retyping three lines of a `--help` dump introduced three errors (#230).

**Two children check each other only across a VERBATIM overlap.** Assigning overlapping work for
mutual verification means naming the overlap literally — one question, one dataset, the same
wording to both. "Adjacent slices" of a topic do not overlap at all, and the "no contradictions"
you then get back means they never met, not that they agree (#219).

Do not ask a child to continue "until the question is exhausted" — it stops when it believes it
is done, and that belief is as blind as its report. If more depth is needed, you specify what.
</worker-lifecycle>
