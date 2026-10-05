---
name: codex-debate
description: "FROZEN by the owner on 2026-09-20: model review is disabled and the codex_review tool is not registered. Do not call it or seek a substitute."
# Previous description; restore together with the tool:
# description: "Optional executor-owned review: one focused second opinion, a server-enforced task budget, and advisory findings. Work is accepted by commit and tests, without outcome signatures or skip receipts."
---

# Review Routing

## Review decision gate — canonical policy

**Review is available but optional.** The `worker` or `full-cycle` executor chooses whether
independent checking would help. Orchestrators and sub-orchestrators do not launch model review
through this tool, the shell, or a substitute reviewer.

**Codex unavailable → do not review. Do not seek a substitute reviewer.** Run your own checks and
state clearly that no external opinion exists. Missing review is not a debt.

- The usual goal is one focused Luna pass through `codex_review(model="gpt5.6luna", ...)`;
  the server default is Luna. A second pass needs a specific material question, not a request
  for the word APPROVED.
- Astra is a separate additional run and requires the owner's explicit authorization for Astra.
  Approval of the task or of review in general is not that authorization.
- Do not assign Sol as reviewer: it has not been a route since 2026-09-06. Cost is not a reason
  either way: the 2026-09-10 measurement could not separate Sol and Astra's pool usage because
  three estimates swapped their order. Only Luna is consistently cheaper than both and is the
  standard reviewer.
- **The server budget is three attempts per task, including failed attempts.** The value belongs
  to `app/work_review.py::MAX_REVIEW_REQUESTS`. It is shared across task modes and executors;
  another report name, a new session, or transferring the work does not reset it.
- Only one review for a task runs at a time. On `review_in_progress`, wait for normal completion;
  do not create another output. On `review_budget_exhausted`, submit available evidence and list
  unknowns; do not rename the task to bypass the limit.

## Review work — an appendix to the result

**work-review-v2** applies to all assignments, including already started ones. Workflow:

1. Do the work, check readiness, and commit the result.
2. If useful, run `codex_review(mode="implementation", context=..., output=...)`. The tool pins
   the commit. `mode="review"` looks at an uncommitted diff, while `mode="exec"` reviews a
   specific file or plan; these modes do not prove implementation review.
3. Read the response and check its findings. Fix real defects and explain disagreements.
   **The author's position belongs in the ordinary report**, not as a separate merge gate.
4. Give the requester the final commit, check result, review path if any, and what changed after
   it. **No separate attestation or skip receipt is needed.**
5. The receiver reads `worker_wip` and calls `merge_worker(expected_head=..., acceptance_note=...,
   task_outcome=...)`. The note records the decision, including why external review was absent.
   The server accepts only an authorized orchestrator/owner, checks the same commit, and runs the
   prescribed tests. A full-cycle parent may accept its child into its own branch but cannot grant
   itself permission on main.

`worker_wip` shows all attempts, reports, the checked commit, and files changed after the last
code review. **Advisory does not mean APPROVED.** Do not present a completed process as proof of
correct code. If the report is missing or comparison is unavailable, say so; do not reconstruct
evidence from memory. Current-code checks and the receiver's decision matter more than the
reviewer's heading, Markdown formatting, or verdict mark.

`required=false` may return a size skip for a full diff of no more than 40 lines/3 files without
binary files. This is the tool response and needs no separate receipt. Do not call review merely
to obtain a skip; state the reason with the work result.

For follow-up, reuse the same output, mode, and model with `resume=true`. After launching, end
the turn or do independent work; the platform reports the outcome. Do not poll the job in a loop.
Do not create a new task for a new limit. If the agreed result itself changes, discuss scope with
the requester.

## Calibration and result

In `context`, give the goal, exact files/questions, and readiness criterion. The PROJECT CONTEXT
tool loads repository context itself. For a plan, state plainly that implementation does not yet
exist. Findings must be concrete and verifiable; argue with facts instead of launching another
agent. Save the report under `.orchestra/tasks/<id>/`. The final message only needs what was
checked, how, material fixes/disagreements, and remaining uncertainty.
