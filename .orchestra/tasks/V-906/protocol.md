# V-906 protocol (frozen before any run)

Question (owner, 17.10.2026): does appending the phrase R from prediction.md to a task improve it, where and why. Prediction: prediction.md (commit e4fcfa4e, not changed).

Arms: A = original task; R = A + "\n\n" + phrase (verbatim from prediction.md, Russian). Models: luna, sonnet (Sonnet 5.5). 2 repeats. Subscription only, no api_credit. No Astra/Sol.

Tasks: T1..T8 (root cause, first obvious version is false), K1..K4 (root cause obvious), C1..C4 (creative, = V-896 K1,K2,K4,K5). Snapshot per T/K = `app scripts tests pyproject.toml` at the parent of the fixing commit (no .git, .orchestra, reports, fix). Reference causes and checklists in tasks.py, frozen in the same commit. Environment check (validate_repro.sh): the regression tests of the fix commit overlaid on the snapshot must fail there.

Isolation: as V-895/V-896: fresh copy per run, prompt says work only inside the directory; raw output scanned for `.orchestra/tasks`, `/home/kesha/orchestra/` (other than the venv python), `github.com`, `curl`, fix commit ids.
Tools: Luna has a shell (can run code), Sonnet has Read/Write/Edit/Glob/Grep only (platform adapter keeps Bash closed): Sonnet can write a repro script but cannot run it. This is a property of the platform, analysed per model.

Metrics:
- T, K: correct = grader `primary` == 1 (see GRADER_PROMPT). Grader of a different model than the author is the primary one (Luna answers graded by Sonnet, Sonnet answers by Luna); the same-model grade is a sensitivity check. Blind to arm. decoy_main reported. Reproduction: (a) grader field `reproduction`; (b) Luna: count of command-execution items in the raw stream that run python/pytest/git/uv/bash scripts (not rg/sed/cat/ls); (c) both: files created in the run dir.
- C: blind pairwise A vs R, two judges (Luna and Sonnet), seeded random order, criteria of V-896. R-win-rate over decisions.
- All: paid tokens = output + cache write + fresh input (cache read not counted); turns.

Ceiling rule: pilot = the A arm of T (both models, rep 1) run first. If A correct >= 75% of T cells, the T tasks are made harder before the main run and the change is recorded in protocol-amendments.md.

Decision against prediction (from prediction.md): "helps" in T = R minus A >= +15 pp (>= 2 of 8 tasks in the per-task sense); refuted if T gain < 2 tasks of 8 (noise), or harm in K or C, or T paid tokens > 1.5x. Significance: paired by cell, exact sign test and bootstrap CI; n and detectable difference stated.
