<project-maintenance>
## Issues and project documentation

When you find a problem outside the current fix, record the actionable follow-up in the
project's TODO.md and mention it with the result when there is something to report.
This does not authorize fixing it or creating another task without the required approval.

If the project has CHANGELOG.md, update it with the change before commit/publication.
If it has none, create it for a substantial feature, refactoring or non-obvious fix.
Publication still requires its own authorization; a changelog obligation never requires a push.
Write entries by hand, never generate a public changelog from internal task reports: those
reports may contain paths, addresses, customer identities or other unpublished details.
Each entry states what changed, the technical substance with relevant symbols/files, and
the concrete triggering case. Record known tradeoffs and correct previous incomplete fixes
honestly. Omit linter noise, development-only changes and cosmetic style refactoring.
Use patch increments for fixes, minor increments for features, major for breaking changes;
sections are Added / Fixed / Changed / Removed / Known tradeoff / Reasoning.

An owner's decision that should outlive this conversation goes into the project's rules file
(AGENTS.md/CLAUDE.md) in the same turn: the date, his words verbatim and what prompted it, plus
one line of the resulting rule. Paraphrases get lost in compaction and handoffs; a dated quote
does not (seedon and katya-work, V-683, 03.10.2026). Keep undated rules in the rules file and
dated state in a separate state file with only current statuses; do not grow a chronicle there.
If the rule is already written, fix that entry instead of appending another version.

Update an existing architecture.md after significant changes to modules, structure or
dependencies. Do not create that document on your own.
</project-maintenance>
