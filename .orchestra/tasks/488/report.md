# #488 — repository-owned review calibration

## Decision

`codex_review` reads `.orchestra/project-context.toml` from the pinned base revision, not from the
worker's current filesystem. The calibration changes severity, so letting the reviewed branch supply
it would let the subject lower its own review risk. A legitimate context edit becomes active after
it reaches the base branch; until then the review intentionally uses the last accepted calibration.

The repository identity is the parent of `git rev-parse --git-common-dir`. `SCOPE` and
`git rev-parse --show-toplevel` are not used for ownership: the former can name the parent project of
a cross-repository worker, and the latter names the linked worktree rather than the shared project.

## Contract

- Six non-empty, single-line TOML strings plus `schema_version = 1` are accepted; missing, extra,
  malformed, multiline, or wrong-version data produce an explicit `UNKNOWN` project block.
- Missing/invalid data never blocks review. The warning and provenance are recorded in the
  background-job receipt, and the warning is returned to the caller.
- Caller text is a separate task-calibration section. Actual `PROJECT CONTEXT` headings and all six
  reserved field lines, including blockquote, numbered-list, task-list, and heading forms, are
  quarantined before prompt construction; ordinary instructions mentioning those words survive.
- Receipt provenance includes repository identity, pinned source revision, source digest, reviewed
  `HEAD`, and request time.

## Rollout boundary

The prompt owners are intentionally unchanged in this branch. Their contract may be updated only
after the merged loader succeeds through a fresh live MCP process; changing them earlier would make
the mandatory review workflow refer to behavior that is not yet live.

## Mutation evidence

Every mutation used a committed test, restored `app/mcp_stdio.py` from a temporary copy, touched the
restored file, and reran the same test green. Counts below are for the named production marker before
mutation and after restore.

| Seam | Marker before/after | Mutant RC | Restored RC |
|---|---:|---:|---:|
| reviewed cwd instead of foreign parent scope | 1 / 1 | 1 | 0 |
| pinned base revision instead of reviewed worker `HEAD` | 1 / 1 | 1 | 0 |
| caller project-field quarantine | 1 / 1 | 1 | 0 |
| missing-file explicit `UNKNOWN` prompt | 1 / 1 | 1 | 0 |
| missing-file warning in receipt | 1 / 1 | 1 | 0 |
| blockquote/numbered Markdown quarantine | 1 / 1 | 1 | 0 |
| legitimate instruction mentioning `PROJECT CONTEXT` survives | 1 / 1 | 1 | 0 |
| implementation receipt uses already-pinned worker head | 1 / 1 | 1 | 0 |
| invalid-but-readable source retains its digest | 1 / 1 | 1 | 0 |
| complete Markdown context-heading syntax | 1 / 1 | 1 | 0 |

## Review round 1

Sol returned a substantive review in `.orchestra/tasks/488/codex-review-impl.md`; the outer job was
classified failed by the execution-evidence finalizer, but the model response is complete and counts
as round 1. Four findings were accepted and fixed: Markdown-container bypass of reserved fields,
overbroad removal of legitimate instructions mentioning the feature, a second `HEAD` resolution in
implementation provenance, and an empty digest for invalid-but-readable TOML.

Round 2 returned `APPROVED` with one non-blocking suggestion: recognize closing emphasis after the
colon and closing ATX hashes on context headings. The suggestion was accepted and test-covered; it
does not authorize another review round. Both review jobs were falsely classified `blind` because
the reviewed diff contains the literal `bwrap:` and `app/bg_jobs.py::_blind_review_error` searches
quoted source text as though it were a tool failure. The complete two-round model output remains in
the review artifact, and the platform defect was reported separately.

## Verification

- Baseline selector from #449: `5 passed, 12 deselected`.
- Focused review/receipt regression set: `56 passed`.
- `git diff --check` and `python -m py_compile app/mcp_stdio.py tests/test_project_context_review_488.py`: passed.
- Fresh-process loader probe: `status=loaded`, repository resolved to the Git common-dir parent,
  64-character digest, and the repository-owned Users value present.
- README table guard is already red outside this task's files: `anchor app/review_coverage.py:89
  points at nothing`; #488 did not modify that owner or README.
