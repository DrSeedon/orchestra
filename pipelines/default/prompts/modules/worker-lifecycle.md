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
</worker-lifecycle>
