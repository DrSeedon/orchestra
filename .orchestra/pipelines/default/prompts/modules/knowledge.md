<knowledge>
## Project memory — all roles

The project KB is `.orchestra/kb/`; its README indexes topics. These are working notes for
agents to search, not a transcript and not a second instruction hierarchy.

### Retrieve only what the task needs

Use the topic index in your prompt, then `rg -n -i -F -e '<symbol>' -e '<symptom>' .orchestra/kb`.
Choose exact identifiers, error text, commands or distinctive Russian/English terms; do not
search the whole question as one literal. Read the matching heading and nearby paragraphs.
Check the current code/config for changing runtime facts. Task evidence and archived notes
are historical sources, not current instructions. If the KB has no answer, search the relevant
`.orchestra/tasks/` paths or Git history (see `.orchestra/kb/history.md` when present); a failed search does not prove absence.
Skip memory lookup when the named code, command or live-state check already answers the task.
`search_memory`, if available, is an optional lexical shortcut, not a prerequisite.

### Write once, where the next agent will look

- Task result, verification, unresolved work and detailed evidence: the current task under
  `.orchestra/tasks/<id>/`. Update its existing report; do not create daily summaries or a
  second session chronicle for the same work. Before compaction, update unfinished task
  state only if it changed; no separate memory receipt or mandatory ceremony.
- Personal observation: `.orchestra/workers/<your-name>.md`. Keep only useful notes specific
  to your work; link to existing project knowledge instead of copying it. No note is required
  when nothing new was learned. Notes are included in your prompt, so keep them short and
  move long investigations into the task evidence.
- Shared reusable conclusion: update the relevant KB topic when the task calls for maintaining
  project knowledge, or when a verified finding changes an existing entry. Ordinary work and
  research do not require a KB addition. Unchecked promotion candidates stay in personal notes
  or the task until a knowledge-maintenance task verifies them. Shared policy changes still
  require the instruction owner's authorization.

Write plain Markdown in short, self-contained sections. Put exact search terms naturally in
headings/text; preserve decisive conditions, negations and version/scope qualifications.
No mandatory fact IDs, status headings, anchor fields, link types, approval receipts, gap
sections or single-line records. Use a normal source link and a date when freshness matters.
Replace an obsolete current explanation instead of appending another correction underneath.
Keep a useful rejected approach with its reason, clearly marked historical; preserve its
original evidence in task files or a pinned reachable Git snapshot when consolidating. Do not delete raw evidence merely
because a summary exists. Do not duplicate a finding across topics: link to its owner.
A new topic is justified by a distinct recurring question, not a task number; list it once
in `.orchestra/kb/README.md` as `- [name](topic.md) — description with search terms`.
Check that changed source links open. Never publish secrets from private runtime logs.
</knowledge>
