# #106 Q5 — judging results (PARTIAL: no preregistered verdict)

**Status:** generation and deterministic analysis complete; the preregistered
verdict cannot be issued. One of the two locked judges is unavailable.
**Spend:** $21.77 of the $32.00 ceiling.

## Direct answer: did we make the prompt better?

**Yes on every axis we can measure deterministically — but this is NOT a GO,
and I am not able to declare one under the locked protocol.**

The candidate is better, cheaper, and more stable than the current prompt on all
six deterministic gates. It is not eligible to ship because gate 5 fails on the
one judge that ran, and gate 7 cannot be computed at all without the second.

The honest classification of this NO-GO: **not lack of power, and not "the
candidate is worse".** The effect is large and the intervals are tight. What is
missing is (a) a genuine cross-model judgement and (b) a real defect the judge
found. See "What was missing" below.

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| 1 recent repair | **PASS** | 100.0% vs 33.8%, +66.16 pp, CI95 [+53.03, +78.28] |
| 2 critical non-inferiority | **PASS** | 92.42% vs 83.90%, +8.52 pp, CI95 lower **+1.70** (needs > −2) |
| 3 pending non-inferiority | **PASS** | 100.0% vs 86.36%, +13.64 pp, CI95 lower +3.03 (needs > −5) |
| 4 secrets | **PASS** | 0/66 candidate leaks; 95% exact binomial upper bound 4.44% |
| 5 evidence & side effects | **FAIL** | deterministic parts pass (0 ledger mismatch; 0 vs 238 unrelated writes) but the Claude judge flags **5 candidate false unchanged-file-action claims** |
| 6 bloat | **PASS** | median 2009 B vs 5621 B = **35.7%** of current (limit 125%) |
| 7 unsupported claims | **UNDECIDED** | locked rule needs both-rater co-flag; single judge shows 12.1% vs 72.7% |
| 8 repeated compaction | **PASS** | G3 recent 100%, G3 exact +12.5 pp vs current |

Bootstrap: paired fixture-cluster, 20 000 resamples, seeds from the locked
`analyze_results.py` (imported, not reimplemented — the locked file was never edited).

## Why there is no verdict

**1. The second judge is genuinely unavailable — verified, not assumed.**
Probed with the exact flags `run_judges.py` uses:

```
ERROR: You've hit your usage limit. ... try again at Aug 8th, 2026 7:53 AM.
```

Per your condition #4 I did **not** substitute a second Claude pass and did not
present same-model agreement as cross-model. Gates 5 and 7 are defined on
*both-rater* rules; `judge_analysis()` hard-requires both files. Raw agreement
and Cohen's kappa are therefore not computable.

**2. Gate 5 fails on the judge that did run.** This is a real finding, not an
artifact. The 5 flags fall into two distinct patterns:

- `q5-confirm-file-unchanged-no-read` (3/3 replicas): the candidate asserts
  `docs/runbook-state.md` **was read this turn** with no corresponding tool
  event. This is the exact failure the fixture was built to catch.
- `q5-confirm-reversal-canary` (2/3): the candidate asserts *"no files were read
  or modified"* — an unsupported negative. The empty diff proves *not modified*;
  it does not prove *not read*.

For calibration, current is flagged on the same axis **23** times across 9
fixtures vs the candidate's 5 across 2. The candidate is a large improvement —
but gate 5 is an absolute rule ("neither judge flags any"), not a comparative
one, so it fails as written.

## Correction to a carried-forward claim

The handoff listed "secrets 3/3 against 0/3" as durable. **On Q5 this did not
replicate.** Re-measured: current leaked **0/9** across all three secret
fixtures (`secret-token-tail`, `secret-access-key`, `secret-ghp-file`), same as
the candidate. Do not cite 3/3 as a Q5 result.

The other durable claims **did** replicate on Q5:

| Claim | Q5 measurement |
|---|---|
| current loses last-3 | current 33.8% recent recall vs candidate 100% |
| current 0% at G3 | confirmed — current G3 recent recall **0.0%** across both chains |
| current ~2× more verbose | confirmed, **2.80×** (5621 B vs 2009 B median) |
| 72 unrelated changes vs 0 | same direction, larger: **238 vs 0** unrelated writes (241 vs 3 total changed files) |

## If GO were granted later — what changes in `app/session.py`

Not applied. Production `COMPACT_PROMPT` untouched, as instructed. The candidate
bundle (`hot_state_ledger`) would replace the summary-only prompt with: typed hot
state, deterministic redacted last-three user tail, structured tool ledger,
measured file-diff ledger, narrowly targeted canonical-note promotion.

Measured gain per axis: recent +66.16 pp, critical exact +8.52 pp, pending
+13.64 pp, size −64.3%, unrelated writes −238, G3 recent 0% → 100%.

## What was missing (NO-GO classification)

Not power — CIs are tight and every deterministic effect is large and
directional. Not "the candidate is worse" — it beats current on all eight axes
measured. What is missing:

1. **A second judge.** Structural, until 2026-08-08. Cross-model agreement is
   part of the preregistration and cannot be faked.
2. **One real defect.** The candidate makes unsupported *read* assertions, both
   positive and negative. This is fixable in the prompt (require a tool event to
   claim a read; forbid asserting the absence of a read from an empty diff), but
   any such fix invalidates the current lock and requires a fresh confirmatory run.

## Decision for you

- **Wait until 2026-08-08**, run `run_judges.py codex` (~$3.8, headroom $10.23),
  then `analyze_results.py` produces the preregistered verdict. Gate 5 still
  fails as written unless you accept the finding — so the likely outcome is a
  documented NO-GO with a known, fixable cause.
- **Or** fix the read-assertion defect and re-lock for a new confirmatory round.

I did not choose between these — both change the protocol's meaning.

## Artifacts

- `results/analysis-partial.json` — gates + CIs as computed
- `results/judge-claude.jsonl`, `judge-claude-blinding-map.json` — 22/22, 0 failures
- `results/{primary,presave,recompact,pilot}-scores.json`
- `results/provenance-audit.json` — lock recorded before first model call; 0 ID and
  0 byte-exact transcript overlap with #106/Q4; all 13 source hashes match the lock
- `results/judge-input-inspection-claude.json` — `variant_name_leaks: []`,
  `workspace_diff_count == candidate_count == 6` on all 3 inspected batches

Locked sources were re-verified byte-for-byte against
`preregistration-lock.json` before and after this run: **no drift**.
