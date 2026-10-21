# V-990 — checklist step time on bulk close

## Rule
In `save_checklist` (app/checklists.py), when the step that carried the open clock interval is closed in the same save together with other steps that have no measured time (`actual_seconds` NULL/0), that one interval (`now − active_since`) is split equally between the closing step and those unmeasured steps. Nothing is invented: the sum over the steps equals the interval that was really measured (test asserts total == measured active time). Equal split because nothing in the data says which step took longer; the estimate is not used (it would feed the estimate back into the measurement being analysed). Steps that already have measured time take no share; the step's earlier accumulated time is untouched. If no other step is unmeasured, or the current step merely moves on, behaviour is unchanged.

Marking: new column `checklist_step_metrics.distributed_seconds` (REAL, NULL = fully measured directly). It holds the part of `actual_seconds` that came from a split; added by `ensure_schema` (ALTER for existing DBs, also in the CREATE DDL). Analysis: `actual_seconds - COALESCE(distributed_seconds,0)` is directly measured time. Historical rows are not rewritten (the 718 old NULLs stay NULL; they cannot be recovered).

Not covered: steps closed across separate turns without ever being current stay NULL; a bulk close by a save that happens with no open interval (clock stopped) has nothing to split.

## Codex vs Claude clock
The clock is backend-independent: `AgentSession.__setattr__` (app/session.py:861) flips `set_clock` on `status`/`_compacting` changes, no `backend_type` branch. Live DB read-only: among completed steps with actual>0, median actual/wall (completed_at−created_at) is 1.00 Opus, 1.00 Sonnet, 1.00 Luna, 0.84 Sol — same clock behaviour. NULL share of completed steps: Opus 374/515, Sonnet 247/283, Luna 90/166, Sol 4/45 (Codex closes fewer in bulk). Luna/Sol small actuals are real short work (mean wall 264 s / 581 s per step) against inflated estimates, not a clock defect. No code defect found; a parametrized test pins that claude and codex sessions open/close the interval identically.

## Tests (tests/test_checklists_v858.py)
`uv run --frozen python -m pytest tests/test_checklists_v858.py -q` → 23 passed (app imported from this worktree). Mutation: disabling the split (`if False and unmeasured`) reddens `test_bulk_close_splits_measured_interval_and_marks_distributed`; restored → green. New: bulk close, single-step unchanged (no distributed mark), Claude/Codex clock path.

Restart needed: app/checklists.py changed (Python).
