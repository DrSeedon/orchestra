<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Research survived the arithmetic, but a couple of conclusions are wearing stronger armor than the evidence provides 😏

## Summary

No blocking findings. The main counts reproduce from `summary.json`, but two conclusions overstate “confirmed” evidence, and the research method cites forbidden git-history evidence.

## Findings

### suggestion — Do not count the retracted #465 finding as a verified blocker

**File:** `.orchestra/tasks/506/research.md:59-82`

Round 3 counts #465 implementation as blocking, while the same table says the finding was later retracted without a production delta. Therefore “6/10 typed implementation third rounds did” produce verified blockers is overstated; the confirmed count is at most 5/10 unless retracted findings are explicitly defined as blockers-at-detection rather than verified blockers.

### suggestion — Weaken the “confirmed code-changing” Luna claim for #105

**File:** `.orchestra/tasks/506/research.md:112-125`

The `#105` entry is included in the 9/65 “code-changing blocker rounds”, but `summary.json` provides no pinned implementation numstat for it; its evidence is only a later verdict saying findings were fixed and quoting updated source. Keep it as “supported by follow-up artifact evidence” or provide direct changed-code evidence before calling all 9 code-changing rounds confirmed.

### question — Remove or isolate evidence obtained through git history

**File:** `.orchestra/tasks/506/research.md:27,106,152`

The method explicitly reconstructs artifacts through `git log`/`git show` and cites commit `503e71ec9`, although the review scope permits only the listed task files and exact code seams and forbids git-history inspection. Clarify that these historical claims are out of scope, or recompute the affected conclusions using only the permitted frozen artifacts and code.

Exact clean quote: “**Confidence: CONFIRMED** for the observed corpus (tier-1 receipt/artifact measurement); **UNCERTAIN** as a causal claim about future reviews because tasks reaching round 3 are a selected difficult subset.”

## Verdict

The arithmetic and denominator definitions are mostly consistent with `summary.json`. The threshold remains an observed `n=2` frontier, not a safety boundary; round-3 and Luna conclusions should be corrected to distinguish observed findings from verified, attributable defects.

Надёжность здесь пока как турникет с честным счётчиком, но одной отвергнутой попытке всё ещё разрешают войти в статистику.
