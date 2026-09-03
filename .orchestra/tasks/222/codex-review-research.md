## Summary

The recorded counts, medians, totals, token ratios, and Luna virtual cost agree with `blind-grades.json`. Spark’s missing price is correctly represented as unknown, not zero. No crash, corruption, or security blocker was found.

Exact quote from `research.md`: “Отдельный quota-бакет не компенсирует тихую ложь о готовности.”

## Findings

suggestion: `run_bench.py:229` — The isolation evidence does not prove that future answers were unreachable. The transient units retain unrestricted network access and `HOME=/home/kesha`; the leakage detector examines only recorded `command_execution` strings, despite recognizing `web_search` as a tool type. A model could access remote GitHub content, another URL, or readable material elsewhere under `$HOME` without triggering the listed markers. Narrow the claim to “future Git objects and two known local paths were inaccessible,” or rerun with network and unrelated home paths inaccessible.

suggestion: `research.md:76` — The reported `0.03592834 pp` and `111.33×` have unjustified precision and cannot establish that Spark consumes its own bucket faster. The calculation assumes quota utilization is linear in token credits, allocates a rounded three-point endpoint delta proportionally, and compares buckets of unknown capacity. The document acknowledges these limitations but still labels Spark pool economy “REFUTED” and says its indicator was consumed “substantially faster.” Present the value as an illustrative allocation model, not a measured bucket delta; omit the 111.33× headline unless bucket calibration is established.

suggestion: `research.md:94` — The proposed Spark gate does not exclude the measured text failure. That run had explicit requirements and green named tests, yet silently omitted a required fact. Requiring an “acceptance oracle” is insufficient unless every correctness-critical acceptance criterion is mechanically exercised by that oracle. Require per-criterion executable coverage, or exclude semantic prose/prompt edits that need human completeness review.

question: `research.md:29` — Within the permitted artifacts, the claimed chronology—preregistration before runs, corrected grades committed before key disclosure, and no post-key confirmatory additions—is asserted but not independently demonstrated. Since git history and raw run artifacts were excluded from review, this portion remains unverified rather than falsified. Consider preserving immutable timestamps/hashes and correction provenance inside a durable benchmark manifest.

## Verdict

VERDICT: APPROVED — no blocking findings

## Round (2026-08-12T09:50:18Z)

## Summary

Round 2 resolves the substantive concerns about overclaiming, quota arithmetic, and semantic text routing. The routing rule is now appropriately narrow and follows from the measured failures.

Exact changed quote: “Confirmatory-прогоны нельзя чинить задним числом после раскрытия ключа.”

## Findings

suggestion: **Isolation — FIXED in prose, underlying limitation remains.** The report now accurately distinguishes proven Git/known-root isolation from global physical unreachability and explicitly acknowledges that the original strict premise was not fully met. This is honest and appropriately limits confidence; no confirmatory rerun is possible without making it exploratory.

suggestion: **Quota allocation — FIXED.** The report removes the unjustified ratio and “REFUTED” conclusion, labels ≈0.04 pp as illustrative, gives a plausible rounding range, and states the assumptions about linearity, concurrent accounting, and unknown bucket capacities. `UNKNOWN, не $0` remains correct for Spark.

suggestion: **Semantic text routing — FIXED.** The gate now requires mechanical coverage of every correctness-critical criterion and excludes semantic prose/prompt work without literal anchors. This directly addresses the observed false completion.

question: **Chronology provenance — PARTIALLY FIXED.** The hashes match the current bounded files and improve reproducibility. However, hashes plus timestamps stated inside `research.md` do not independently prove when those versions were committed or when the key was disclosed; verifying that chronology would require the intentionally excluded history/raw evidence. The report should continue treating chronology as documented provenance, not independently established by this review.

suggestion: **Routing rule — JUSTIFIED with stated scope.** The ≤2-file limit, complete constants, pre-existing per-criterion oracle, 100K conservative threshold, no semantic prose, and no retry constraints map directly to measured failure modes. The rule does not claim a precise context cliff or general performance equivalence.

## Verdict

VERDICT: APPROVED — no blocking findings
