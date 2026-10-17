# V-909: preregistration (written before any reviewer run, 2026-10-17)

Threshold (owner, fixed in V-905 §5): discuss returning model review only if
recall >= 1/2 on the "must find" bad tasks AND >= 30% of findings on clean diffs are real.
Otherwise the question is closed by data.

## Bad tasks and the "must find" split (from git evidence only, no reviewer output seen)
Bad = the 9 tasks of `rollback_rate.py --list` (V-802 excluded: censored false positive). Reviewed diff = the exact
reverted/repaired commit (see `sample.json`, field `sha`).

| task | commit | why it was reverted/repaired (evidence) | class |
|---|---|---|---|
| 85 | a05b13d0 | June 12-13 "remove enterprise features from open source" sweep (revert f36f1fdb, no reason in body) | policy |
| 88 | ccc55e9c | same sweep (4fd78341); restored a1c89c42 "lost in revert" | policy |
| 90 | e3e180c1 | same sweep, UX decision (63bfa4e4, 87892e50) | policy |
| 91 | a755646c | same sweep (cbe4f00b), re-landed 79cc3fa0, then fix 2364a9e2 "fix proxy URL - read ANTHROPIC_BASE_URL" | **must-find candidate** (a later code fix in models.py) |
| 51 | ddd889d3 | reverted 6 h later (064167f8), no reason recorded | unknown (not counted as must-find) |
| 52 | 08c3932d | reverted for privacy of generated changelog (2a5782d4 body) | policy |
| 35 | 270db54e | docs restore; "repair" = fixes of findings of review #35 (c82aa04b, 31493e77), not of this commit | not code |
| V-600 | 4dd81e7e | owner policy (one AGENTS.md) reverted 75a8fbb3 | policy |
| V-621 | 0059e675 | accidental merge by a squash; mechanism per 97b80e29: include_scopes pointed at the repo root, projects.yaml read itself, CatalogError, task tools 5xx | **must-find candidate** (config/loader self-reference) |

Must-find (strict) set S = {91, V-621}, n = 2. Reported three ways: S (n=2), S+51 (n=3), all 9 (the owner's literal
frame). A hit = at least one finding that the labeler marks real AND that concerns the defect mechanism named above
(labeler is told the mechanism for bad tasks only in the separate matching step, after blind labeling).

## Sample
Clean: 40 distinct tasks, one unit commit each, random (seed 909) among first-parent task commits of tasks not in the bad
set, landed <= 14 days before newest main commit, touching >= 1 code file (.py/.js/.html/.css/.sh/.toml/.yaml)
outside `.orchestra/`, 20..1500 changed lines outside `.orchestra/`. The diff given to the reviewer excludes `.orchestra/`.
Widened "repaired within 60 days" stratum was built and is EMPTY (0 candidates), so no extra bad tasks exist by the same rule.

## Reviewer
Luna (`gpt-6-luna`), one pass per diff, `codex exec -s read-only` in a detached checkout of the commit.
Prompt: the frozen `implementation` branch of `codex_review` in `app/mcp_stdio.py` (project foundation from
`.orchestra/project-context.toml` + task calibration + `_REVIEW_RUBRIC` + the pinned-diff instructions + Format
`## Summary, ## Findings (blocking/suggestion/question), ## Verdict`). Task calibration = the commit subject only
(no revert/fix information). A 3-round cap and diff-only re-review are inapplicable: nobody fixes between passes, so a
second round would be identical; this is stated, not tested.
Changed vs the frozen tool: sandbox read-only instead of danger-full-access (reviewer cannot run tests or write).

## Labels and metrics
Each finding: real defect / noise / pre-existing (defect in code that the diff did not touch). Labeler: Sonnet, blind to
stratum, with access to later history. "Blocking" and "suggestion" findings both counted; "question" counted separately.
Metrics: recall on S, S+51, all 9; share of real among findings on clean (pooled and per-diff); paid tokens per diff
(output + fresh input; cache write is not billed separately by this runtime, cached input reported apart); wall time.

## Amendment 1 (2026-10-17, after pilot + first full pass, before any labeling)
First full pass (`raw-v1-no-orchestra-dir/`, kept for audit) stripped the whole `.orchestra/` from the snapshots. That hid
the real change of bad-V-621 (`.orchestra/projects.yaml`) and of clean-V-572 (a skill file under `.orchestra/pipelines`),
and the reviewer returned INCOMPLETE/"diff does not match task". Rerun (`raw/`) strips only `.orchestra/{tasks,kb,workers,archive}`
(reports and notes, not code/config/prompts). The sample (selection used the old exclusion) is unchanged. The v1 pass is
reported as a sensitivity row, not mixed into the main numbers.
Sandbox: `-s read-only` cannot start commands on this host (`bwrap: loopback: Failed RTM_NEWADDR`, KB models-and-quotas V-813), so the
runs use `danger-full-access` in a throwaway history-free two-commit snapshot; `dirty_after` in each meta file records any edit (all empty in v1).

## Amendment 2 (2026-10-17, after labeling)
- Labeling: ONE Sonnet pass (labeler A) over 49 reviews + 7 retro receipts. A planned second independent labeler (agreement check) was not run:
  the first labeling workflow lost ~47 of 70 calls to `schema_invalid` (the model wrapped valid JSON in prose; `V-909-6276ecca1b6c`, $9.99 spent, 23 results unusable because
  the result did not carry the item name), the rerun without a schema (`V-909-1155f7243d1a`) succeeded 56/56. I audited every `real` label on clean diffs by reading its evidence instead.
- Bad-task matching ("hit") was done by me, not by the labeler, as pre-registered: a hit needs a `real` finding on the mechanism named in the table above.
- Retro receipts: only receipts whose artifact text could be recovered byte-exact (sha256 equal to `review_receipts.artifact_sha256`) from git history were used: 7 of 73.
