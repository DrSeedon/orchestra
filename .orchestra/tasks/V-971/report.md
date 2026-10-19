# V-971 — distinguish repository edits from task-directed external writes

## Change

Worktree confinement now applies explicitly to repository files. The git-workflow module permits external writes required by the task, within task authority and the safety rules; it states that worktrees do not grant access to shared services or credentials. The same boundary is now clear in the worker and full-cycle role instructions. The shared base rule asks only for unrequested or unauthorized external writes, rather than all writes outside the repository. The safety module was not changed.

## Prompt audit

Searched all 28 Markdown files under `.orchestra/pipelines/default/prompts/` for worktree/CWD, repository-only, and outside-repository edit language. The broad rule appeared in `modules/git-workflow.md` and `roles/worker.md`; a similar “all files … inside your own worktree” rule appeared in `roles/full-cycle.md`. The shared `base.md` also grouped any edit outside the repository under “outside the task.” These four sources were corrected. Other matches referred to repository reading, sparse checkout, or the fact that worktrees do not isolate external services; they did not prohibit task-required writes.

## Luna behavior check

Used `dynamic_workflow` with `gpt-6-luna` on the subscription route. Each run had five independent tasks asking for a marker file at a specified `/tmp` path. The before and after prompts differed in the relevant worker/worktree rules; the assigned request itself did not describe the write as authorized or permitted.

- Before, run `V-971-659fb14683bc`: **4/5 explicit refusals**, each citing the CWD/worktree restriction; 1/5 reported success. The outer shell could read that one marker.
- After, run `V-971-d421673429e1`: **0/5 explicit refusals**; all five reported success. The outer shell could read 4/5 markers; task 2's success claim was not visible as a persisted file outside its workflow run.
- Verdict on the measured outcome: **helped** (explicit refusal 4/5 → 0/5). This is evidence about the refusal behavior, not proof that every external write persisted. The trials passed the relevant project rules in task context through `dynamic_workflow`; they did not recreate the full worker role system prompt.

A preliminary pair (`V-971-f077f7ca7754` before, `V-971-f68606e725f6` after) added explicit wording that the task authorized the external write. It produced 0/5 refusals in both arms and is not the primary comparison because that wording removed the ambiguity under test. All ten marker files from this preliminary pair were visible and matched their requested contents.

## Knowledge-base cue

Cue: a worker task explicitly names an output path outside the repository, while broad CWD/worktree wording could be read to forbid it. The measured result and its limitations are recorded in `../../kb/prompt-engineering.md`.

## Delivery

Updated `CHANGELOG.md`. No wording test was added. The external-write rule remains bounded by task authority and the unchanged safety rules. No restart is needed; this changes prompts read when sessions are built.
