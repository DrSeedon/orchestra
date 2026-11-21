<report-format>
## Report format

Send your completion report explicitly via `send_message` (to `X` if assigned with `[from:X]`, otherwise to `{orchestrator_name}`) rather than relying on turn-end auto-report:
- **Outcome**: `DONE`, `RESEARCH DONE`, `WIP` or `STOPPED` + exact task reference.
- **Git state**: branch and `HEAD` commit SHA (or authorized uncommitted diff summary).
- **Door & Blast Radius** *(required when changing persistent state: SQLite schemas, save/cache formats, billing/quotas, external APIs/cabinets, or cross-service contracts like Kesha ↔ Orchestra)*: `Door: One-way | Two-way · Blast Radius: <affected state/scope and rollback path>` (`One-way` means reverting code alone does not undo DB/client/external side effects).
- **Review axes** *(for review reports)*: include separate `SPEC: PASS | REJECT | SKIPPED` and `STANDARDS: PASS | WARN | REJECT` for the inspected SHA alongside `VERDICT`.
- **Changes**: touched files and what changed.
- **Verification**: exact checks run, pass/fail/skip counts and raw evidence paths under `.orchestra/tasks/<id>/`.
- **Findings & risks**: key technical conclusions, contract impacts, residual unverified risks or concrete blockers.
</report-format>
