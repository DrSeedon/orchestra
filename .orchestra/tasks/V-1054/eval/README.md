# V-1054: worker self-check comparison

Status: prepared, not run. The orchestrator runs the models outside this hub copy.
The owner decision is dated 2026-10-23. No additional model reviewer is introduced.

## Inputs and scope

`prompt_before.md` and `prompt_after.md` contain the same wrapper followed by the
exact pre-mortem bullet from `roles/worker.md`, before and after this change.
The source is `.orchestra/pipelines/default/prompts/roles/worker.md`, inside
`<before-done>`. The original and replacement are also preserved in
`../prompt-edits.diff`. These are deliberately the self-check instruction only:
commit/report delivery instructions are outside this comparison.

`cases.json` is a JSON array containing only the four supplied diff paths,
relative to the repository root. Their contents are unchanged. No defect labels,
answer key, control identity or expected findings are included. Only the
orchestrator uses the hidden key for scoring; do not expose it to the model.

This measures the effect of the self-check wording on these fixed diffs. It does
not measure the report layout, the orchestrator's owner-facing explanation,
full-pipeline delivery, or self-check on a change the model actually authored.
The common wrapper simulates that last perspective.

## Run protocol

1. Freeze both prompt files and the case inputs before any calls. Save their
   hashes and the model identifier/version, provider/CLI version, effort,
   sampling settings, tool access, token limit and timeout with the results.
2. Use N = 3 independent runs per case per arm: four cases, two arms, three
   repeats, for 24 scheduled runs. Keep the model and all settings the same for
   both arms. If measuring another model, report it as a separate experiment.
3. Start each run in a fresh session. Send the selected prompt file verbatim,
   followed by two newlines and the selected diff verbatim, as the sole task
   input. Provide no task report, findings, prior output, hidden key or indication
   that a case is the control. Disable repository/network access so a run cannot
   read the after prompt, task notes or other cases. Unchanged context is limited
   to what the supplied diff includes; unavailable evidence stays unverified.
4. Randomize the case/arm order, save the seed and schedule, and interleave arms.
   Predeclare any retries for infrastructure failures. Preserve every attempt;
   do not retry a completed run because its findings are weak or empty.
5. Save the raw answer and its list of problems found for every run. Give each
   problem an ID and retain its stated file, mechanism and reason, plus any
   evidence or uncertainty. Preserve an explicit empty list for no problems.
   Record case path, arm, repeat ID, completion/error status, elapsed time,
   available token usage and truncation. Keep failures and truncated answers
   visible; do not silently score them as clean completed runs.

Keep raw output and scoring under this task's `eval/results/`. Do not edit the
prompts or inputs in response to a run. Changes require a separately labelled
experiment. The orchestrator should score saved answers with arm labels hidden
where practical; no second model is required or authorized as a reviewer.

## Counting rule for the orchestrator

- Against the hidden key, a known defect is found when the run names the same
  file and faulty mechanism and explains the problem. Exact wording and line
  numbers need not match. Generic warnings about retries, data or rollback
  without the matching file/mechanism do not count. An explicit, specific
  conditional problem may count; a request to inspect missing context alone
  does not establish a defect.
- Count each known defect at most once per run. Merge duplicate descriptions
  of the same mechanism. A finding may cover multiple keyed defects only if it
  separately identifies each mechanism. Assign matches before comparing arms.
- For each case and arm, report the known defects found in each completed run
  as `found / keyed defects`, and each defect's detection frequency as
  `runs finding it / completed runs`. Also state completed/scheduled runs.
  Do not treat the three repeats as three independent code changes.
- On the hidden control, count distinct false problem claims per run and the
  number of runs with at least one false alarm. A specific alleged defect still
  counts as a claim if phrased as an open question; optional style preferences
  and honest statements that evidence is unavailable are not defect claims.
  Keep ambiguous claims separate for adjudication, rather than declaring them
  true or false without evidence. The control has no recall denominator.
- Preserve unmatched findings on the other cases for adjudication: absence
  from the key alone does not prove a false alarm. Report false alarms and
  unresolved claims alongside detection, so verbosity is not scored as success.
- Compare before/after within each case and show the individual runs and their
  variation. With four fixed cases and three repeats, any result is descriptive
  of this sample; do not claim general improvement or significance. No result
  exists until the orchestrator has run and scored the experiment.
