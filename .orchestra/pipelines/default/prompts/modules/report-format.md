<report-format>
## Report format

Send your completion report explicitly via `send_message` (to `X` if assigned with `[from:X]`, otherwise to `{orchestrator_name}`) rather than relying on turn-end auto-report:
- **Outcome**: `DONE`, `RESEARCH DONE`, `WIP` or `STOPPED` + exact task reference.
- **Git state**: branch and `HEAD` commit SHA (or authorized uncommitted diff summary).
- **Changes**: touched files and what changed.
- **Verification**: exact checks run, pass/fail/skip counts and raw evidence paths under `.orchestra/tasks/<id>/`.
- **Findings & risks**: key technical conclusions, contract impacts, residual unverified risks or concrete blockers.
</report-format>
