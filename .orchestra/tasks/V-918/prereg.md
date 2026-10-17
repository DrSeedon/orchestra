# V-918: preregistration (written before any reviewer run, 2026-10-17)

Question (owner, 17.10): does model review help on SILENT defects (merged unnoticed, fixed later)? V-909 had n=2 such tasks.

## Sets
BAD (n=23): origin commits on first-parent main, landed 2026-06-01.., size 20..1500 changed code lines outside .orchestra and *.md,
whose lines were blamed (git blame -w on lines deleted/changed by a later fix commit, `mine.py`) by a later "fix" commit >= 1 day
after and >= 2 lines, AND two independent vetters (Sonnet 5.5, Luna; inline packet = origin diff + fix patches; `vet.py`,
`vet_sonnet.json`, `vet_luna.json`) both answered verdict=yes "the fix corrected a defect introduced by the origin and visible in its diff".
Agreement of vetters: 23 yes/yes, 23 no/no, 14 split/unclear of 67 candidates. Known limit: vetters saw the later fix, i.e. BAD is defined by hindsight; a defect that was a
reasonable design uncertainty may still be counted.
CLEAN (n=23): random (seed 918) commits not blamed by any mined fix, never themselves a fix, landed 2026-06-01..2026-10-02 (>= 14 days of exposure), size-matched to BAD
(nearest size, random among 5 nearest). "Clean" = no later fix touched its lines; not proof of no defects.

## Reviewer
Same as V-909 (`run_reviews.py` derived from it): Luna gpt-6-luna, frozen codex_review implementation prompt, task calibration = commit subject only, snapshot of
commit without history, danger-full-access (read-only bwrap unusable). TWO independent repeats per diff (92 runs). Reviewer never sees the later fix.

## Matching / labeling
Per review, two blind labelers (Sonnet 5.5, Luna) get shuffled anonymous items, no stratum info. Step A (all items): list findings, label each real/noise/preexisting
against code + later history (as V-909 protocol). Step B (BAD items only, after A): given the vetted defect mechanism, does any finding describe that mechanism? A HIT needs both
labelers to say yes (primary); either-labeler is the sensitivity row.

## Metrics and decision rule (fixed now)
1. Recall = share of BAD diffs with a HIT in at least one of the 2 repeats (also per-repeat mean). Wilson 95%.
2. Precision-on-clean = real findings / findings on CLEAN, both labelers agree "real" (primary), pooled; Wilson 95%, and share of clean diffs with >=1 real finding.
3. Specificity contrast: share of BAD diffs having >=1 real finding vs share of CLEAN diffs having >=1 real finding (Fisher exact).
4. Cost: paid tokens (output + fresh input) and seconds per diff.
Verdict:
- HELPS on silent defects: recall >= 30% AND Wilson lower bound >= 15% AND precision-on-clean >= 30%.
- DOES NOT HELP: recall point < 20% OR Wilson upper bound < 35%.
- Otherwise INCONCLUSIVE (state the n needed).
The owner's wish for "100% sure" is not attainable from any n; report the interval, not certainty.
