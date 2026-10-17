# V-911 — frozen protocol (committed before any model run)

Owner approval 17.10.2026 13:44: «Да, давай проверяй всё, конечно. Надо попробовать».

## Question
Does arm C — the original research task plus the V-896 sentence about an external verification criterion, byte-identical
(`C_SUFFIX`, imported from `V-896/tasks.py`) — raise coverage of the key findings on research tasks, compared with the
original task (arm A)? V-896: +0.142 on 3 tasks (task-level sign p=0.039, ≈0.08 after multiplicity). V-906 (root-cause
finding, different phrase): no effect. This run is a replication on NEW tasks.

## Tasks
12 new research questions S01–S12 (`tasks.py`), each from a past Orchestra investigation (#30, #61, #62, #71, #97, #416,
#56, V-575, V-620, V-648, V-680, #93). None is in V-896 (#52, #78, V-624). The model gets the question and a code
snapshot = parent of the commit that added the real research/fix (`build_fixtures.sh`: `app scripts tests pyproject.toml`,
no `.git`, no `.orchestra`, no report, no fix). The 6 key findings per task are written from the real report; the blind
checklist and the format (`R_FORMAT`: no file changes, ≤600 words, starting `FINDINGS:`) are in `tasks.py`. Checklist and
grading rule are fixed by this commit.

## Arms, models, runs
A = task text; C = task text + C_SUFFIX. Luna and Sonnet 5.5 (`resolve_model`), 2 repeats (rep 1, rep 2), subscription only
(`billing_mode="subscription"`, no api_credit). Tools and isolation exactly as V-895/V-896: fresh copy of the snapshot per
run, WRAP preamble, Claude: Read/Write/Edit/Glob/Grep (no shell), Codex: shell+network as the adapter requires; fixed across
arms within a model. Raw output scanned for report paths/task ids/curl/github (`FLAG`); flagged runs are reviewed by hand.
Total: 12 tasks × 2 models × 2 arms × 2 reps = 96 runs.

## Pilot and ceiling rule (set before any run)
Pilot = arm A, rep 1, all 12 tasks × both models (24 runs), graded as below. If mean pilot A coverage (cross-grader) > 0.6,
the tasks are too easy; they are hardened BEFORE the main run, the amendment (what changed, pilot numbers) is appended to
`protocol-amendments.md`, and the pilot rows are discarded. Hardening, fixed now: for each task whose pilot A mean > 0.6,
(1) add the sentence «A teammate's first guess, not yet checked: <plausible but wrong or partial version>» to the prompt in
BOTH arms, and/or (2) remove from the prompt the sub-questions that name findings. If the pilot mean is ≤ 0.6 the pilot rows
are kept as A rep 1 (no re-run).

## Grading (fixed)
Each answer is graded by BOTH Luna and Sonnet, independently, blind to the arm (the grader sees the checklist and the answer
only), 0 / 0.5 / 1 per finding (`GRADER_PROMPT` from V-896), coverage = mean over the findings. **Primary metric: cross-grader**
(grader model ≠ author model). Secondary: same-model grader; mean of both. Failed runs (`ok=false`) are excluded from
both arms of their cell and listed. Known limit: C answers may contain an «external check» section visible to the grader;
the number of answers with such a mention is reported.

## Decision rule (fixed before any run)
C is recommended for research-task prompts only if ALL hold:
1. mean paired difference C − A of the primary metric over cells (task × model × rep) ≥ **+0.10**;
2. the lower bound of the 95% CI of that difference **> 0**, CI = task-clustered bootstrap (resample the 12 tasks, keep all of
   their cells; 10 000 draws), because cells of one task are not independent;
3. paid tokens C / A ≤ **1.2** (ratio of sums over all paired cells, i.e. what the owner pays; paid = output + cache_create +
   fresh input, cache read not counted, KB V-660). The task-clustered CI and the geometric mean are reported.
Otherwise: «not shown» (a positive point estimate with a CI over 0 is «not shown», not «no effect»; negative → no gain).
This is ONE pre-specified confirmatory comparison (all models pooled); per-model, per-task and secondary-metric numbers are
exploratory and labelled so.

## Significance and what n distinguishes (stated before)
12 tasks (clusters), 48 paired cells. V-896 cell-pair sd ≈ 0.17, so the standard error is ≈ 0.025 if cells were independent and
about 0.04–0.06 after clustering by task: a difference of ≈ ±0.10–0.12 is distinguishable from 0 at the 95% level, smaller
effects are not. The planned +0.10 threshold is therefore at the edge of detectability; the report gives the actual SE, sd and
minimum detectable effect from the data.

## Artifacts
`tasks.py run.py grade.py analyze.py build_fixtures.sh`, `raw/` (every run: tokens, turns, final text), `grades/` (each grade),
`results.csv`, `analysis.txt`, `report.md`. Production prompts are not touched.
