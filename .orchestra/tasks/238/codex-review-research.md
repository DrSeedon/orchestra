## Summary

The central recommendation—platform-enforced acceptance—is directionally sound, and the transaction-order and repository-evidence claims survive review. However, the write-scope conclusion is overstated, and §0 uses an incorrect peak plus unsupported inferences to reject wholesale reuse. Recommendation 1 also omits necessary runtime plumbing and path-semantics work, making its cost estimate unreliable.

## Findings

[suggestion] `docs/tasks/238/research.md:174` — §2.2’s load-bearing claim is too broad and, under the requested falsifier, does not survive. LoopX has a production admission path that consumes each todo’s `required_write_scopes`, rejects non-read-only lanes with missing or disallowed scopes, and excludes them from executable child lanes. In `loopx/control_plane/quota/task_orchestration_admission.py:339-350`, the decisive line is verbatim:

> `reasons.append("write_scope_not_allowed")`

`build_adaptive_task_orchestration_contract` then separates blocked lanes from eligible lanes, and only eligible lanes become executable child briefs. This is not tool-level confinement of an arbitrary `Edit`/`Write`, so the valuable narrower conclusion remains: LoopX does not compare an actual tool `file_path` against the per-todo scopes. Rewrite “NOTHING gates a file write” as “no tool-level file-write hook enforces the per-todo scopes”; also remove the claim that lease conflict/planning are their only production consumers.

[suggestion] `docs/tasks/238/research.md:26` — The reported “peak 131 on 2026-08-09” is not the repository peak. Re-running the stated aggregation gives 208 commits on 2026-07-04, 183 on 2026-06-21, and 131 only as the August 9 value. The 1,773 files, 705,210 Python lines, 4,322 commits, and 4,139/4,322 dominant-author count reproduce correctly.

[suggestion] `docs/tasks/238/research.md:45` — Neither commit velocity nor concentrated authorship proves that the code was “written by agents under LoopX itself,” and aggregate core size does not prove that “no module can be taken wholesale.” The document itself identifies a relatively isolated 1,492-line Claude integration immediately afterward. Rejecting wholesale adoption may still be reasonable, but it requires dependency/coupling evidence for candidate modules—not repository-wide LOC and an unverified authorship inference.

[suggestion] `docs/tasks/238/research.md:426` — Recommendation 1 substantially understates its integration surface. The existing hook factory receives only a Bash classifier (`app/backend_claude.py:377,604`); `ClaudeBackend` is not supplied `owned_dirs`, while those values currently live on `AgentSession` and in manager/database state. Enforcing them therefore requires an explicit session→backend authority path, reconnection/resume behavior, and normalization of tool paths relative to the worktree. “~50–70 lines in backend_claude.py” omits the main ownership-data plumbing and risks implementing a hook that cannot know the authoritative scope.

[suggestion] `docs/tasks/238/research.md:426` — The stated exceptions do not close the principal accidental-corruption failure mode cleanly. Unconditionally allowing `docs/tasks/<id>/` and `docs/workers/<name>.md` must bind `<id>` and `<name>` to the current session; otherwise every worker gains write access to every task report or personal-memory file. The recommendation also needs to account for absolute paths, relative paths, `..`, symlinks, and worktree-vs-repository roots before its safety claim and size estimate are credible.

[suggestion] `docs/tasks/238/research.md:448` — Recommendation 2 closes false reports about an exit code, but not acceptance of the delivered state as currently phrased. Running the command on a child’s final `DONE` validates the child worktree before squash merge; it does not prove that the resulting content reached `main`, survived merge conflict resolution, or passes in the integration state. The document should explicitly scope the guarantee to “validated child worktree,” or require a distinct post-merge acceptance point. Also, suppressing stdout/stderr as LoopX does would leave Orchestra with an exit code but poor diagnostic evidence; that behavior should not be copied unquestioned.

[question] `docs/tasks/238/research.md:454` — The $0.87 saving is not demonstrated by the proposed mechanism. Platform execution avoids a model wake only if the parent currently wakes solely to rerun the command and no subsequent interpretation/repair routing is needed. A failed or inconclusive command still needs agent work, while a successful subprocess is computational cost rather than subscription-token cost. Is there a measured count of parent turns eliminated specifically by automatic acceptance, rather than the cost of one generic parent wake?

## Verdict

CHANGES REQUESTED. Claims 2(b), 3, and 4 are supported: no CLI argument accepts a ready-made repository-evidence blob; settlement performs real ordered callbacks after validation; and the Claude/Codex handoff packet explicitly reports `writes_state: False` and `launches_runtime: False`. But §2.2 must distinguish task-admission enforcement from tool-level path enforcement, §0 needs correction and stronger reasoning, and both recommendations need their actual guarantee and integration cost narrowed before this research is ready to drive a plan.

> ⚠ Codex usage unaccounted: OperationalError: table turn_usage has no column named cost_unaccounted

## Round (2026-08-13T04:36:07Z)

## Re-review status

1. §2.2 admission/tool distinction — FIXED.  
2. §0 peak commit count — FIXED.  
3. §0 authorship inference — FIXED.  
4. §0 rejection of wholesale module reuse — STILL BROKEN.  
5. Recommendation 1 integration cost/plumbing — FIXED.  
6. Recommendation 1 session-bound exceptions/path handling — FIXED.  
7. Recommendation 2 guarantee, diagnostics, and cost claim — FIXED.

## New findings

[suggestion] `docs/tasks/238/research.md:57` — The revised evidence proves that `claude_goal_mode/` cannot be transplanted wholesale without LoopX’s CLI and domain model. It does not prove the broader conclusions “Вырезать можно только сам приём” and “Их код целиком, любым куском” in §7. Calling this plugin “the most isolated candidate” is also unsupported by the documented analysis of a 2,484-file repository. Narrow the conclusion to the candidate actually inspected: do not take `claude_goal_mode/` wholesale; no conclusion was established for every other module.

[suggestion] `docs/tasks/238/research.md:201` — “На допуске мы с ними симметричны” overstates equivalence. LoopX checks that a todo’s declared scopes are contained in the goal boundary; Orchestra checks that two live workers’ declared directories do not overlap. Both are pre-execution admission checks based on declarations, but they enforce different invariants. Describe them as analogous gates, not symmetric ones.

## Verdict

CHANGES REQUESTED, limited to the two scope overstatements above. The substantive corrections are otherwise complete, including this appropriately narrowed guarantee:

> `Прогон на финальном DONE ребёнка доказывает **зелень в worktree ребёнка до squash-мержа**, и только это.`

> ⚠ Codex usage unaccounted: OperationalError: table turn_usage has no column named cost_unaccounted
