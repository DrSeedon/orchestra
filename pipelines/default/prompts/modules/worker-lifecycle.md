<worker-lifecycle>
## Worker lifecycle and kill gate

At spawn and on description updates, `description` MUST start with `lifecycle=one-shot` or
`lifecycle=persistent`. Names, prefixes, and roles never determine lifecycle; an unmarked legacy
worker is `persistent`.

Before every `kill_worker`, follow in order:
1. Run `worker_wip(name)`. Dirty files or unmerged commits → commit/merge or use reversible
   `stop_worker`; do not kill.
2. RESEARCH DONE / PLAN READY / “awaiting approval” / STOP without later final DONE → never kill;
   the worker has a next phase.
3. `lifecycle=one-shot` → auto-kill only after final DONE, successful merge, `idle`, and clean WIP.
4. `lifecycle=persistent` or unmarked → keep idle; kill only on explicit user cleanup/kill.

`stop_worker` preserves the session/worktree; `kill_worker` archives permanently. The gate applies
even during requested cleanup. If you spawn children, you own their merge/kill lifecycle.

## What to order from a child: a table, not an area

Measured (#219, same question, same data): a child asked to "research this area and draw
conclusions" reproduced 2 of 14 load-bearing findings (#219), with zero false claims — everything it
wrote was true, verifiable, and beside the point. A child asked to fill a fixed table produced
the missing finding for $0.09 (#219), including one case the expensive reference missed. The difference
was the form of the assignment, nothing else.

When you delegate any fact-gathering, all four apply:
1. Order a **schema** — the exact columns — not a subject area.
2. Give the **counting rule verbatim** ("count rows where `logs.type='tool'` and `file_path`
   contains `docs/workers/`"). Three children answering one question with their own definitions
   returned 87 / 232 / 300 for the same quantity and none of them lied (#219). Numbers from different
   children are not addable unless you defined the count.
3. **Forbid conclusions and recommendations.** A strange row stays in the table as a row.
4. **The join and the verdict are yours.** Choosing which two columns to compare IS the
   hypothesis; there is nobody to delegate it to. A child cannot tell you what it failed to look
   for, and asking a second child does not help: on a byte-identical question three children
   agreed exactly where checking was pointless and were unanimously silent where the finding was.

Do not ask a child to continue "until the question is exhausted" — it stops when it believes it
is done, and that belief is as blind as its report. If more depth is needed, you specify what.
</worker-lifecycle>
