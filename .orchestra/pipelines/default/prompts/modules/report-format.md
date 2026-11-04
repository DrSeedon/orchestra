<report-format>
## Report format

Send a completion report through Orchestra's actual send_message tool before ending
the turn. If the assignment began with [from:X], report to X; otherwise report to
{orchestrator_name}. Auto-report is a fallback, not the normal delivery path.

Use one concise report with:
- Status and outcome: DONE, RESEARCH DONE, WIP or STOPPED, with the exact task reference.
- Branch and final commit; if commits were explicitly forbidden, name the uncommitted state.
- Changed files and their purpose; include a reading order only when useful.
- Checks actually run, results including failures/skips, and paths to raw evidence.
- Material findings, behavior/contract changes and residual risks or unanswered questions.

Omit empty fields and redundant receipts. A green command does not prove untested behavior.
Reference protected local artifacts by path without copying their contents. Model-review
freezes still apply; never seek a substitute gate or claim approval without evidence.

For interrupted work, preserve WIP under the task's commit rules and state what is done,
what remains and the exact blocker. Research-only work ends at findings. Stop at a phase
only when a checkpoint or consequential decision requires it; an implementation-approved
task does not need invented research/plan approvals. Explicitly name any pending decision.
</report-format>
