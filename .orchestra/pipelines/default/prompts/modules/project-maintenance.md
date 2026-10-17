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

An owner's decision that should outlive this conversation goes into the project's rules,
in the same turn, with the date, his words verbatim and what prompted it (a paraphrase gets
lost in compaction and handoffs; a dated quote does not). The exception is Orchestra's own
shared prompts (`.orchestra/pipelines/**`): they are public product text, so write them in
English and record an owner decision there as "owner decision, <date>" with an English summary
and reason, never as a verbatim quote. Keep undated rules in the rules files and dated state in
a separate state file with only current statuses; do not grow a chronicle there. If the rule is
already written, fix that entry instead of appending another version.

Structure of a project's rules (owner decision, 2026-10-17). The root file (CLAUDE.md /
AGENTS.md) is the core and holds what is needed always: the essence of the project (what it
does, for whom, the main structure), small rules that always apply and are not worth a file of
their own, and a registry of lines "topic → file → when to read". What is needed only
sometimes lives in topic Markdown files of the project, which agents read when the registry
line says so and extend when a rule changes. Keep them in a directory that runtimes do
not load by themselves (for example `.orchestra/kb/rules-*.md`) and never in `.claude/rules/`:
Claude Code loads every `.md` there into context, so the registry silently becomes a full load
(measured: an 18.5 KB core plus 171 KB in `.claude/rules/` put about 189 KB on every turn, and a
model with file tools disabled still knew a fact that existed only in a topic file). To check
the layout, ask a model without file tools for a fact that exists only in a topic file: it must
not know it, while a fact from the core it must. A new rule that is not always needed, or an
owner decision with its date and quote, goes into its topic file; the core gets one registry
line, or one line with the conclusion and a link. The core is sent on every turn of every
agent, so it has a size ceiling: 16 KiB, half of the 32 KiB at which the harness silently
truncates project instructions. When the core outgrows the ceiling, move content into topic
files; do not raise the ceiling. AGENTS.md and CLAUDE.md are one file and a symlink to it,
never two copies: Codex reads AGENTS.md, the Claude SDK reads CLAUDE.md, and the harness
prefers AGENTS.md, so a stale copy silently gives part of the agents old rules. Triggering
cases: one project's core, compressed to about 64 KB, grew back to about 139 KB; in three
projects of one installation AGENTS.md had drifted into a separate copy.

Update an existing architecture.md after significant changes to modules, structure or
dependencies. Do not create that document on your own.
</project-maintenance>
