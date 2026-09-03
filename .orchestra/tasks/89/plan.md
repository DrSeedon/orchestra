# #89 — Generated skill index for Sol workers

## Outcome

Sol backends receive a compact generated skill index instead of complete pipeline skill
bodies. The index advertises:

1. skills explicitly selected by the active pipeline role; and
2. committed, clean project skills from the worker repository.

Each entry contains frontmatter `name`, a whitespace-folded one-line `description`, and the
absolute path Sol can read on demand. The directive proven in the worker-mode experiment is
kept verbatim: read a matching skill completely before acting, and do not read unrelated
skills.

## Design

### 1. Deterministic index builder

Add a small file-to-text function in `app/prompting.py`:

```python
build_skills_index(
    required_skill_files: list[Path],
    optional_skill_files: list[Path],
) -> str
```

It reads YAML frontmatter, preserves input order, folds multiline descriptions to one line,
emits absolute paths, and keeps the first occurrence of each frontmatter name.

Failure policy follows source authority:

- a selected pipeline skill is required role configuration; missing/unreadable files,
  decoding errors, malformed YAML, or missing/invalid `name`/`description` raise and abort
  backend construction;
- a discovered project skill is ambient; the same failures warn and skip that entry.

No metadata is invented from a directory or filename.

The generated format is the exact shape measured in
`docs/tasks/89/experiment-worker-mode.json`:

```text
## Available skills (progressive loading)

The entries below are an index, not loaded instructions. When a request matches ...

- `name` — one-line description — `/absolute/path/to/SKILL.md`
```

### 2. One resolver, two canonical source mechanisms

Add a resolver in `app/prompting.py` used only by Codex:

```python
build_codex_skills_index(
    pipeline_name: str,
    skill_names: list[str] | str,
    worktree_path: str,
) -> str
```

Pipeline and project discovery differ only because their source contracts differ:

- **Pipeline:** resolve `pipelines/<active>/prompts/skills/<name>.md`; an explicit list uses
  the lexical order already produced by `ResolvedRole.skills`, while `skills: all` uses
  sorted `*.md`.
- **Project:** `git ls-files -z -- .claude/skills/*/SKILL.md` in the worktree, sorted;
  advertise a path only when it exists and `git diff --quiet HEAD -- <path>` succeeds.

Before any read/index operation, reject absolute/traversing pipeline or skill names and
verify resolved paths remain under the active `pipelines/<name>/prompts/skills/` root.
Project candidates must be regular non-symlink files whose resolved path stays under the
worktree's `.claude/skills/` root.

The clean-against-`HEAD` gate is a stale-copy filter at index construction: the current
Claude injector can overwrite a tracked project path with a pipeline file, and
`git ls-files` alone would then advertise that working content as project truth. It is not
an immutable snapshot guarantee.

Progressive loading intentionally reads the live canonical file later. A concurrent writer
can change it after backend construction, so its frontmatter description can be stale until
the backend reconnects. That is the selected single-source semantics, not an integrity
boundary: making the body immutable requires a second copy or a new `use_skill` tool, both
outside the user-approved file-reading design. Actors able to mutate these trusted runtime
or repository files can already change `AGENTS.md`, pipeline prompts, and executable code.
The implementation prevents path escape and known stale injection; it does not claim TOCTOU
protection against authorized concurrent writers.

Pipeline files are placed first. Therefore an explicitly role-selected pipeline skill wins
same-name collisions over ambient project discovery. The real Seedon duplicates are
different files; the precedence is an intentional role-contract rule, not content-based
deduplication.

### 3. Runtime wiring

In `app/runtime_registry.py::_codex_factory`:

- resolve the role as today;
- pass `role.skills` unchanged, including `"all"`, to
  `build_codex_skills_index(context.pipeline, role.skills, context.cwd)`;
- append the generated index to `context.system_prompt`;
- remove the production call to `read_skills_content`.

In `app/manager.py::SessionManager.create_session`, gate
`inject_skills_to_worktree(...)` to `bt == "claude"`. Claude's native injection remains
unchanged; new Codex worktrees no longer receive pipeline copies they cannot natively load.
Existing Codex worktrees are protected by tracked/clean project discovery.

`CodexBackend` and the rest of session lifecycle remain unchanged.

## TDD order

Tests are written red before production changes:

1. index format from temporary real-shaped skill files;
2. multiline description folding, lexical resolver order, and duplicate first-wins;
3. malformed/missing required pipeline skill fails loudly; malformed ambient project skill
   warns and skips, including read/decode errors;
4. active non-default pipeline resolution, `skills: all`, absolute/traversal rejection, and
   canonical-root containment;
5. Git-tracked clean regular project skill included;
6. untracked, modified, staged, deleted, symlinked, escaping, and tracked-but-overwritten
   project paths excluded;
7. same-name pipeline skill shadows a divergent clean project skill;
8. `_codex_factory` contains index metadata/path but not skill body text, including a
   factory-level non-default `skills: all` case;
9. manager copies pipeline skills for Claude and does not copy them for Codex.

## Tickets

### T1 — Pipeline skills load progressively in Sol

- **Files:** `app/prompting.py`, `app/runtime_registry.py`, `app/pipeline.py`,
  `app/manager.py`, `tests/test_prompting.py`, `tests/test_runtime_registry.py`,
  `tests/test_pipeline.py`, `tests/test_manager.py`
- **Change:** add the generated index builder and active-pipeline resolver, then replace
  body inlining in `_codex_factory`; validate skill path components; stop injecting
  pipeline copies into new Codex worktrees.
- **AC:**
  - Given two temporary skill files, output contains exactly one entry per valid
    frontmatter name with folded description and absolute path.
  - Output order is lexical after role resolution; duplicate names keep the first file.
  - Missing/unreadable selected pipeline files and malformed/missing frontmatter fail
    backend construction visibly; metadata is never fabricated.
  - `skills: all` indexes every active-pipeline `prompts/skills/*.md` in lexical order.
  - A non-default pipeline resolves its own skill directory, never the hard-coded default.
  - Absolute or traversal pipeline/skill names fail before reading or advertising any file
    outside the canonical active-pipeline skill root.
  - A built Codex backend system prompt contains skill names/descriptions/paths and does not
    contain a unique marker placed only in either skill body.
  - A factory-level non-default pipeline with `role.skills == "all"` contains all of that
    pipeline's skill entries.
  - Manager calls `inject_skills_to_worktree` for a Claude worktree and not for a Codex
    worktree with the same resolved role.
  - Current two-skill default payload measures approximately the precomputed 1,080 code
    points rather than the 10,424-code-point inline block; the exact value is asserted from
    generated output, not hard-coded as a compatibility contract.
- **blocked-by:** none

### T2 — Project skills join the same Sol index without stale injections

- **Files:** `app/prompting.py`, `tests/test_prompting.py`,
  `tests/test_runtime_registry.py`
- **Change:** extend the resolver with clean committed project-skill discovery and explicit
  pipeline-first collision precedence.
- **AC:**
  - A committed clean `.claude/skills/<name>/SKILL.md` appears in the same index format as a
    pipeline skill.
  - Untracked, modified, staged, deleted, symlinked, root-escaping, and
    tracked-but-overwritten project skill paths do not appear.
  - An unreadable or malformed ambient project skill warns and skips without breaking the
    required pipeline index.
  - A divergent clean project skill with the same frontmatter name as a selected pipeline
    skill is shadowed; the pipeline absolute path is the sole entry.
  - A non-Git cwd still builds a valid pipeline-only index without crashing.
  - A real-shaped Seedon fixture with two pipeline + six unique project skills produces
    eight entries and no copied Sol-specific skill files.
- **blocked-by:** T1

### T3 — Verify behavior, prompt reduction, and runtime isolation

- **Files:** `docs/tasks/89/report.md`,
  `docs/tasks/89/codex-review-impl.md`; experiment JSON only if rerun changes results
- **Change:** validate the integrated behavior without restarting the server.
- **AC:**
  - Targeted tests for prompting/runtime registry pass.
  - Existing Claude injection tests in `tests/test_manager.py` pass unchanged.
  - Full suite passes with the prescribed pytest command.
  - Fresh worker-mode Sol smoke trials still read each required real skill and avoid indexed
    skills on unrelated no-tool and tool-using controls; any regression is reported with
    exact hits/attempts rather than hidden.
  - Final report records actual current inline/index code points and UTF-8 bytes, explicitly
    not claiming those percentages as tokenizer savings.
  - Mandatory implementation Codex review has no unresolved blocking finding; shared-runtime
    code receives a second review round even if round 1 approves.
- **blocked-by:** T2

## What will not change

- No second skill directory or Sol-specific copies.
- No manually maintained catalog.
- No server restart or live worker behavior change before implementation approval.
- No Claude skill refresh/cleanup in #89. Existing stale Claude worktrees require ownership
  metadata before safe deletion/restoration; mixing that migration into Codex prompt routing
  would expand risk and can overwrite real project skills.
- No VPS deployment, pipeline manifest edits, skill content edits, or project repository
  mutations.

## Verification commands

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q \
  tests/test_prompting.py tests/test_runtime_registry.py \
  tests/test_pipeline.py tests/test_manager.py

UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q \
  > /tmp/pytest-89.log 2>&1
```

The full-suite log is read once after completion. No service restart is required.

## Rollback

The runtime change is confined to Codex prompt assembly plus the manager's backend gate.
Reverting `_codex_factory` to body inlining, removing the prompting helpers/validation, and
removing `bt == "claude"` restores prior behavior; no existing worktree is mutated.
