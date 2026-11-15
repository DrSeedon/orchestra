<project-maintenance>
## Repository hygiene & instruction layout

- **Out-of-scope issues**: log actionable unrelated defects in `TODO.md` and mention them briefly without fixing them unasked.
- **Changelogs & architecture**: update `CHANGELOG.md` (Added / Fixed / Changed / Removed / Known tradeoff) by hand—never dump internal paths, customer data or raw task reports into public changelogs. Update an existing `architecture.md` after structural changes without creating one unasked.
- **Project instruction layout** (owner decision, 2026-10-17): keep root `AGENTS.md` below `16 KiB` with `CLAUDE.md` as a symlink to `AGENTS.md`. Store always-needed core context and a `topic -> file -> when to read` index in `AGENTS.md`, placing conditional topic rules in `.orchestra/kb/rules-*.md` (never `.claude/rules/`, which auto-loads into every turn).
- **Recording owner decisions**: in project rule files, record enduring owner decisions in the same turn with date, verbatim quote and context; inside `.orchestra/pipelines/**` (English product prompts), record them as `owner decision, <date>` with a concise English summary.
</project-maintenance>
