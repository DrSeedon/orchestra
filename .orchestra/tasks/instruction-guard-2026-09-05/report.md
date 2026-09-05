# Identical root rules and generated topic directory

User requested byte-identical CLAUDE.md/AGENTS.md and a brief directory of every KB topic
inside both files. This supersedes the earlier CLAUDE import adapter.

- AGENTS.md is edited; --sync assembles its topic block from kb/README.md and regenerates
  the identical CLAUDE.md copy. Topic files remain on demand, never imported wholesale.
- The inventory covers Markdown topics under kb, excluding the root README. Every topic
  must be indexed once with a description; broken, duplicate and missing entries fail.
- Existing CI runs pytest, including the repository-source test which calls the read-only
  checker. It rejects byte drift, an outdated directory, empty/oversized files and imports.
- Size limit applies to EACH CLI's copy (<16 KiB), not the sum of duplicate files on disk.
  The final size is about 15.5 KB each; a new topic cannot be silently omitted to fit.
- Existing projects without a directory in their root rules retain the README fallback.
  No other project's instructions, runtime services or credentials were changed.

162 focused tests passed; the expanded run including pipeline delivery passed 372 tests.
Negative cases include one-sided edits, equally oversized UTF-8 copies, missing
topics, stale descriptions, broken references, duplicate entries and invalid markers.
Failed sync does not mutate either root file during validation; an unchanged sync is a no-op.
The README checker reuses the same implementation instead of another limit/import rule.

The check enforces structure, completeness and size, not semantic correctness of arbitrary
new rules. Human/task review is still needed; agents are told not to add reports, incident
logs, changing quota percentages or one-off workarounds to the root instructions.
This is a repository/CI contract, not a gate on starting Codex or existing agents.

GitHub rejected an attempted workflow-file update because the OAuth token lacks workflow
scope. The final branch makes no workflow change: automatic checking uses the existing
pytest CI entry point. No extra permissions or alternate credentials were used.
