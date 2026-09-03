# #89 — Skill index for Sol workers

## Question

- **Context:** Orchestra builds a Codex/Sol backend in `app/runtime_registry.py`; the
  current adapter appends complete pipeline skill bodies to every Sol system prompt.
- **Change under test:** replace those bodies with a generated index containing the
  frontmatter name, one-line description, and canonical file path for both role-selected
  pipeline skills and committed project skills.
- **Baseline:** `read_skills_content(["html-artifacts", "codex-debate"])` in the current
  checkout.
- **Outcome:** (1) lower prompt size, (2) a fresh `gpt-5.6-sol` session reads the matching
  real skill before answering, and (3) a task with no matching skill does not read skills.

## Hypotheses considered

### H1 — A directive generated index is sufficient

Sol reads the matching skill because the index provides both a trigger-rich description
and an exact path.

- **Falsifier:** at least one clearly matching task fails to produce a command reading the
  expected skill file, or non-matching controls routinely read indexed skills.

### H2 — An index is insufficiently reliable

Sol ignores or over-eagerly traverses the index because Codex has no native project-skill
loader.

- **Falsifier:** repeated fresh sessions consistently read exactly the matching skill and
  natural controls produce no skill reads.

### H3 — Enumerating `.claude/skills/` directly is safe

All files in a worktree skill directory are current project skills.

- **Falsifier:** injected pipeline skills remain after their role assignment is removed.
  This is already observed in a live worker (`self-analysis`), and the code only injects on
  worktree creation.[3] H3 is therefore **REFUTED**.

## Findings

### F1 — Current Codex behavior always inlines complete pipeline skill bodies

`_codex_factory` resolves `role.skills`, calls `read_skills_content`, and appends the
returned block to `context.system_prompt`.[1][2] `read_skills_content` reads from the
hard-coded default pipeline skills directory and has no project-skill discovery.[1]

**Confidence: CONFIRMED** — primary source, direct call path.

### F2 — Current serialized prompt payload and projected index are materially different

The task reported a 13,289-character baseline. The current checkout measures:

| Payload | Unicode code points | UTF-8 bytes |
|---|---:|---:|
| Current two-skill inline block | 10,424 | 13,741 |
| Generated two-skill pipeline-only index | 1,080 | 1,263 |
| Generated Seedon index, 8 unique skills | 3,697 | 5,055 |
| Three-skill index used in the experiment | 1,775 | 2,524 |

For the same current-checkout metric, pipeline-only sessions save **89.6% of code points /
90.8% of UTF-8 bytes**. A Seedon full-cycle session gets six additional project skills and
still saves **64.5% / 63.2%** against the current two-body inline block.[M1]

The reported 13,289 and measured 10,424 are not silently treated as the same unit: Russian
text makes code-point and byte counts diverge, and the current UTF-8 measurement (13,741)
is closest to the reported number.

These are serialized-text measurements, not tokenizer measurements; they establish payload
reduction but not an exact token/cost reduction. The worker-mode result preserves every
selected source path and SHA-256, so the figures are reproducible against those inputs.[M1]

**Confidence: CONFIRMED** — direct measurements with source paths and hashes. The Seedon
number is the projected output of the candidate resolver, not production behavior yet.

### F3 — Sol followed the index on all tested matching requests

Pass/fail was fixed before running: a hit requires the expected absolute skill path to
appear in a Bash tool command; an extra read is any other indexed skill path.

| Scenario | Expected skill | Hits |
|---|---|---:|
| New Seedon mascot plan | `bobik-generate` | 3/3 |
| Yandex Direct banner plan | `direct-banner` | 3/3 |
| Re-readable interactive comparison | `html-artifacts` | 3/3 |
| **Total matching requests** | | **9/9** |

Every trial was a fresh independent `gpt-5.6-sol` **worker** session at `high` reasoning
effort with `is_orchestrator=False` in an isolated `/tmp` cwd. The index was generated from
the real frontmatter of two Seedon skills and the default pipeline `html-artifacts` skill.
Each observed `sed` range covered the full file (192, 82, and 67 lines respectively). No
trial spawned a native subagent.[M1][5]

**Confidence: LIKELY** — direct reproducible measurement, but only three unambiguous
trigger families and three repetitions each.

### F4 — Tested unrelated worker tasks did not traverse the index

Eight fresh worker-mode controls produced **0/8** indexed-skill reads:

- 4/8 were short no-tool questions (Python and Git);
- 4/8 explicitly read unrelated production/test files and issued 1–2 Bash commands each.

Across the nine matching turns there were **0/9 extra indexed-skill reads**. One
`direct-banner` turn additionally read that skill's own renderer scripts; this is workflow
loading, not an unrelated skill read.[M1]

**Confidence: LIKELY only for the tested controls** — direct target-runtime measurement,
but 0/8 still has a one-sided 95% upper false-read bound of about 31%, and four prompts were
repetitions. This is evidence against “reads everything every session,” not a universal
false-read guarantee.

### F5 — Pipeline and project sources require different discovery, not different copies

- Pipeline skills are selected explicitly by `ResolvedRole.skills` and live under
  `pipelines/<pipeline>/prompts/skills/<name>.md`.[4]
- Project skills live under the worker repository's
  `.claude/skills/<name>/SKILL.md` and are already checked out with the project branch.[5]
- `inject_skills_to_worktree` also copies pipeline skills into that same directory only at
  worktree creation.[1][3] Therefore a directory glob cannot distinguish committed project
  truth from stale injected files.

The safest single-source resolver is: canonical pipeline files from the active manifest +
project `SKILL.md` files that are both returned by `git ls-files` **and byte-equivalent to
`HEAD`** (`git diff --quiet HEAD -- <path>`). The second condition prevents a pipeline copy
that overwrote a tracked project path from being re-advertised as project truth after the
role stops selecting it. Missing, staged, or modified project skills are omitted with a
warning rather than indexing content that differs from the committed branch.

Deduplicate by frontmatter `name`, with the explicitly role-selected pipeline skill taking
precedence. This is an explicit contract, not an identity assumption: the real Seedon
`codex-debate` and `html-artifacts` project copies have different SHA-256 values from the
pipeline files. An explicit role assignment is narrower than ambient project discovery, so
it wins; the index still contains exactly one readable physical path per name.[M2]

**Confidence: CONFIRMED** for the source topology; **LIKELY** for precedence because the
repository has same-name `codex-debate`/`html-artifacts` copies, so any precedence rule is a
policy choice.

## Counter-evidence and limitations

1. The experiment proves behavior for clear trigger descriptions, not ambiguous requests.
   A larger post-implementation regression corpus would be needed to claim universal
   routing reliability.
2. In one `html-artifacts` trial Sol first attempted a relative pipeline path from `/tmp`,
   then immediately retried the exact absolute path and read it successfully.[M1] Exact
   paths reduce but do not eliminate model detours.
3. Half of the worker controls used repository reads, but none was a long implementation or
   review. The production index must retain the explicit “do not read unrelated skill
   files” directive, and implementation validation should add an end-to-end smoke test.
4. Project discovery intentionally excludes uncommitted, staged, modified, deleted, and
   ignored skills. “Project skill in the repository” means a readable worktree file equal
   to committed `HEAD`; a locally drafted skill is not advertised.
5. Claude's stale injected-skill lifecycle should **not** be changed in #89. Refresh/removal
   cannot safely delete stale injected files while pipeline and tracked project skills share
   the same directory and can share names. #89 can avoid the defect for Sol by indexing
   canonical/tracked sources. Claude synchronization needs a separate ownership marker or
   manifest and dedicated migration tests.

## Affected files and risks

- `app/prompting.py`
  - replace body inlining with a deterministic frontmatter index builder;
  - resolve active-pipeline skills and committed project skills;
  - preserve Claude injection unchanged.
- `app/runtime_registry.py`
  - append the generated index in `_codex_factory` instead of bodies.
- `app/pipeline.py`
  - reject absolute/traversing pipeline skill names before path construction.
- `app/manager.py`
  - keep native pipeline-skill injection for Claude, skip it for Codex worktrees.
- `tests/test_prompting.py` (new)
  - TDD for frontmatter parsing, deterministic output, missing metadata/files, deduplication,
    active-pipeline paths, project Git discovery, stale untracked exclusion, and a tracked
    path overwritten by pipeline injection.
- `tests/test_runtime_registry.py`
  - integration assertion that Codex receives the index and not a skill body.
- `tests/test_pipeline.py`, `tests/test_manager.py`
  - unsafe skill-name validation and backend-specific injection gating.

Primary risks: malformed frontmatter, duplicate names, non-Git cwd, deleted tracked files,
spaces in absolute paths, an active non-default pipeline, and accidentally changing Claude
behavior.

## Sources

1. **Primary source:** `app/prompting.py:168-206` — Claude injection and current body inlining.
2. **Primary source:** `app/runtime_registry.py:200-223` — Codex factory wiring.
3. **Primary source:** `app/manager.py:553-575` — injection occurs during worktree creation.
4. **Primary source:** `pipelines/default/pipeline.yaml:18-75` — role-selected pipeline skills.
5. **Primary sources:** real skill frontmatter in
   `/mnt/data/Projects/Python/seedon/.claude/skills/{bobik-generate,direct-banner}/SKILL.md`
   and `pipelines/default/prompts/skills/html-artifacts.md`.
6. **M1, direct measurement:** `docs/tasks/89/experiment-worker-mode.json` (9 positive + 8
   controls, source hashes and size measurements). Harness:
   `docs/tasks/89/experiment_skill_index.py`.
7. **M2, direct measurement:** `docs/tasks/89/experiment-size-measurements.json` records
   both winning and shadowed path/hash pairs for real Seedon duplicate names.
8. **Superseded pilot:** `docs/tasks/89/experiment-results.json` and
   `docs/tasks/89/experiment-controls-natural.json` used `is_orchestrator=True`; they are
   retained as raw history but are not evidence for F3/F4.

No external web sources were required; the question is about local runtime behavior and was
answered from primary code plus direct model measurements.
