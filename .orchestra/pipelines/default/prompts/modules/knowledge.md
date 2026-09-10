<knowledge>
## Knowledge — one policy for every role

The KB stores findings that would be costly to rediscover: research results, non-obvious
external behavior, hard-to-find constraints, empirical comparisons, failed approaches and
why a non-obvious decision was made. It is not a description of the current repository.

Before adding a finding, ask: what would another capable agent otherwise have to investigate
or test again? Time spent alone is not evidence of value. Do not add general engineering
advice, a paraphrase of accessible documentation, function/file inventories, current settings,
status reports or a list of your edits. Read changing code/config directly. A code-related
entry belongs only when it preserves an expensive experiment, rejected alternative or design
reason that cannot be recovered by ordinary source reading.

### Find the relevant experience

Use the injected topic index, then search exact symbols, errors or distinctive terms:
`rg -n -i -F -e '<symbol>' -e '<symptom>' .orchestra/kb`.
Read the matching section with its conditions and evidence. Historical behavior is a hypothesis
for today's version, not a current guarantee. If necessary, follow sources in the task or
pinned Git history (`kb/history.md` when present). Skip lookup when the named code/command
already answers the question. `search_memory` is optional; an empty search proves little.

### Preserve the knowledge, not another transcript

Write a concise, self-contained explanation in ordinary Markdown. Retain the observation,
material conditions (version/environment/date when relevant), the unsuccessful attempts,
and the reason for the conclusion. Distinguish measured behavior from interpretation and
untested hypotheses. "Failed in this experiment" does not mean "never works".
Link to inspected evidence or a recorded experiment; do not make up missing provenance.
There is no required card, status vocabulary, fact ID, receipt, section count or line format.

Search for an existing entry first. Another confirmation extends its conditions/evidence;
a contradicting experiment qualifies or replaces the conclusion. Keep the decisive reason
for rejecting an approach. Do not append duplicate versions across topics. A new topic needs
a distinct recurring research question and one index line in `.orchestra/kb/README.md`:
`- [name](topic.md) — description with search terms`.

Verified reusable findings may update the KB within the authorized task. Unchecked candidates
stay in the task or short personal notes; neither automatic promotion nor a separate approval
receipt is required. New shared behavioral policy still needs the instruction owner's decision.

Task results, unfinished work and detailed evidence belong in the existing report under
`.orchestra/tasks/<id>/`. Personal observations belong in `.orchestra/workers/<your-name>.md`
only when useful and not already in the KB; these files are injected into your prompt, so
keep them short. No new finding means no memory entry. Research completion does not require
adding a KB line. Do not make daily summaries, compulsory pre-compaction chronicles or a
second record of the same result. Update changed unfinished task state in its existing place.
TODO contains actionable follow-ups, not every observation or declined idea.

Keep source evidence retrievable when consolidating: pinned reachable Git history may replace
old checkout copies after authorized, verified cleanup. A summary alone does not prove complete
extraction. Check changed links and never publish private credentials from the source material.
</knowledge>
