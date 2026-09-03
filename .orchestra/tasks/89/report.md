# Task #89 — Generated skill index for Sol workers

## Outcome

Sol/Codex workers now receive a live generated skill index instead of pipeline
skill bodies. Each entry contains the frontmatter name, normalized one-line
description, and canonical source path, followed by a directive to read only a
matching skill before acting.

The same builder combines:

- configured pipeline skills from `pipelines/<pipeline>/prompts/skills/`;
- clean, committed project skills from `.claude/skills/*/SKILL.md`.

Pipeline entries are required and fail backend construction on missing,
unreadable, malformed, traversing, or symlinked files. Ambient project entries
warn and skip when dirty, missing, malformed, symlinked, cyclic, or outside the
canonical root. Pipeline entries win duplicate frontmatter names.

Claude behavior is preserved: `SessionManager` still copies configured skills
into `.claude/skills/` for Claude worktrees, while Codex worktrees no longer
receive those copies. Synchronizing already-created Claude worktrees remains
out of scope; changing that lifecycle would mutate active worktrees and is
separate from the Codex prompt contract.

## Tickets

- **T1 complete — Pipeline skills load progressively in Sol.**
  Pipeline/skill components are validated, `skills: all` works through the
  runtime factory, bodies are absent from the prompt, and Claude-only copying is
  covered by regression tests.
- **T2 complete — Project skills join the same Sol index.**
  Discovery uses tracked live files, excludes non-HEAD state and symlinks, and
  applies deterministic pipeline precedence.
- **T3 complete — Verify behavior, prompt reduction, and runtime isolation.**
  The experiment builds the real Codex backend through
  `app.runtime_registry.build_backend`, records raw tool commands, and measures
  both triggering and idle behavior.

## Changed files

- `app/manager.py` (+1/-1): keep native skill injection Claude-only.
- `app/pipeline.py` (+32/-0): reject unsafe pipeline and skill components.
- `app/prompting.py` (+163/-19): generate the live index, discover committed
  project skills, enforce source-specific failures, remove body inlining.
- `app/runtime_registry.py` (+11/-4): attach the generated index to Codex with a
  stable prompt boundary.
- `tests/test_manager.py` (+11/-3), `tests/test_pipeline.py` (+29/-0),
  `tests/test_prompting.py` (+378/-0), `tests/test_runtime_registry.py`
  (+66/-0): TDD and regressions for the contracts above.
- `docs/tasks/89/experiment_skill_index.py` (+159/-71): assembled-system
  measurement harness.
- `docs/tasks/89/experiment-assembled-system.json` (+538/-0): final raw results,
  source paths, hashes, commands, and measurements.

## Measurements

Final run: `2026-07-26T11:06:07Z`, model `gpt-5.6-sol`, worker mode, real
`app.runtime_registry.build_backend("codex")`, 17 fresh sessions:

| Metric | Result |
|---|---:|
| Required skill read | **9/9** |
| Control false read | **0/8** |
| Any extra indexed skill read | **0/17** |
| Subagent use | **0/17** |

The positives were three attempts each for the project skills
`bobik-generate`, `direct-banner`, and pipeline skill `html-artifacts`. Controls
included two short questions and two ordinary repository-reading tasks, each
repeated twice.

Serialized payload size from the same source files:

| Payload | Unicode chars | UTF-8 bytes | Reduction vs inline |
|---|---:|---:|---:|
| Previous two-skill body inline | 10,424 | 13,741 | baseline |
| Generated two-skill pipeline index | 1,080 | 1,263 | 89.64% chars / 90.81% bytes |
| Generated Seedon index, 8 entries | 3,697 | 5,055 | 64.53% chars / 63.21% bytes |

These are serialized character/byte measurements, not tokenizer cost estimates.
The task's earlier 13,289-character figure was not reproduced by the current
source snapshot; the reproducible current baseline is recorded with source
hashes in the JSON artifact.

## Verification

- Targeted shared-runtime modules after review fixes:
  `208 passed in 3.86s`.
- Final full suite:
  `979 passed, 20 skipped in 93.02s`.
- Codex implementation review, two rounds:
  round 1 found four issues (pipeline symlinks, multiline names, ambient symlink
  cycles, and missing prompt separation); all received regression tests and
  fixes. Round 2: **APPROVE**, all prior findings fixed, no new blockers.
- Server was not restarted.

## Risks and reusable lesson

- Project discovery intentionally advertises only files matching committed
  `HEAD`; an authorized edit after index construction can still change the live
  file before Sol reads it. This is the approved live-source tradeoff and avoids
  a second skill copy.
- Read detection must recognize both absolute paths and paths relative to the
  backend working directory. The first classifier undercounted five successful
  reads because Bash used relative paths; the final harness fixes this and the
  final 17-session run was executed from scratch with the corrected classifier.
- `0/8` controls is evidence for these controls, not a universal false-read-rate
  guarantee. The raw prompts and commands remain in the JSON for replication.
