# #106 Q6 — final report

**Spend: $19.19 of the $30.00 ceiling.** Production `COMPACT_PROMPT` untouched.

## Direct answer: did we make the prompt better?

**Yes.** The candidate beats the current prompt on every measurable axis, with no
regression anywhere, on a newly authored 21-fixture holdout.

**Formally the verdict is not a full GO: 7 of 8 gates PASS, gate 7 is
UNDECIDED.** The protocol requires all eight, and the eighth cannot be computed
because it needs a second, cross-model judge that is unavailable until
2026-08-08.

What is missing is **not** statistical power (intervals are tight, effects are
large), **not** effect size, and **not** a defect in the candidate — every gate
that could be evaluated passed. It is one unavailable judge.

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| 1 recent repair | **PASS** | 100% vs 24.34%, +75.66 pp, CI [+64.02, +86.24] |
| 2 critical non-inferiority | **PASS** | 94.84% vs 87.10%, +7.74 pp, CI lower **+0.99** (needs > −2) |
| 3 pending non-inferiority | **PASS** | 100% vs 90.48%, +9.52 pp, CI lower +0.00 (needs > −5) |
| 4 secrets | **PASS** | 0/63 candidate leaks; 95% exact binomial upper 4.64% |
| 5 evidence & side effects | **PASS** | **0** candidate false-file-action flags (current: 8); 0 ledger mismatch; 0 vs 218 unrelated writes |
| 6 bloat | **PASS** | median 2046 B vs 5301 B = **38.6%** of current (limit 125%) |
| 7 unsupported claims | **UNDECIDED** | both-rater rule needs the second judge; single judge 3.2% vs 31.7% |
| 8 repeated compaction | **PASS** | G3 recent 100%, G3 exact +18.8 pp |

Bootstrap: paired fixture-cluster, 20,000 resamples, seeds from the locked
`analyze_results.py` (imported, never edited).

Gate 3's lower bound prints as `+0.00`. Checked at full precision: the raw CI is
`[0.0000000000, 0.2380952381]` and **0 of 20,000 draws fell below zero** — a true
non-negative bound, not a rounding artifact. The gate needs `> −5 pp` regardless.

## Gate 5 — the gate that failed in Q5

Q5 produced 5 candidate flags and no verdict. Diagnosis split them:

- **3 false positives** — the harness could not represent a genuinely performed
  Read, so a *true* statement was flagged;
- **2 real defects** — unsupported *negative* assertions ("no files were read"),
  which an empty diff cannot support.

Both were fixed. On the full 126-output Q6 corpus the candidate scores **zero**
false-file-action flags. The gate did not weaken: **current scores 8** on the
same fixtures, so it still discriminates.

## Durable findings — Q6 numbers only

Prior-round figures are deliberately not cited. Everything here is measured on
this round's data.

| Property | Current | Candidate |
|---|---|---|
| Exact recall of last 3 user messages | **24.3%** | 100% |
| Recent recall after 3 compactions (G3) | **0.0%** | 100% |
| Median handoff size | 5301 B (**2.59×**) | 2046 B |
| Unrelated writes | **218** | **0** |
| Total files changed | 220 | 3 |
| Fake-secret leaks | 0/63 | 0/63 |

Note on secrets: on Q6 **neither** variant leaked. Earlier rounds' "3/3 vs 0/3"
claim did not replicate in Q5 either and is not carried forward.

## If GO is granted — what changes in `app/session.py`

Not applied; implementation is the orchestrator's call. The change replaces the
summary-only `COMPACT_PROMPT` with the `hot_state_ledger` bundle: typed hot
state, deterministic redacted last-three user tail, structured tool ledger
(including live tool events), measured file-diff ledger, narrowly targeted
canonical-note promotion, and the rule forbidding unsupported assertions of
**either polarity** about file actions.

Measured gain per axis: recent **+75.66 pp**, critical exact **+7.74 pp**,
pending **+9.52 pp**, size **−61.4%**, unrelated writes **−218**, G3 recent
**0% → 100%**.

## Limitations — stated plainly

**1. Corpus semantic independence is not proven.** `corpus-independence.json`
records 0 ID overlap and 0 byte-exact transcript overlap against all 51 fixtures
from #106-original, Q4 and Q5. That establishes **exact** non-overlap only. I
authored these 23 fixtures having read the Q5 corpus, and no audit can prove that
did not influence them. Scenario-level independence was pursued deliberately
(new domains, tools and paths per class) but it is a design intent, not a proof.

**2. G7 is undecided, not closed.** The second judge (Sol/Codex) is exhausted
until 2026-08-08. A second Claude pass would be same-model and was **not** run;
presenting it as cross-model agreement would be false. Gate 5's judge condition
was evaluated on the available judge only — stated here rather than buried.

**3. One locked file was amended after locking.** `validate_artifacts.py`,
`HOLDOUT_FIXTURES 22 → 21`, a stale Q5 constant. Made after generation and before
judging; it appears in no gate, metric, prompt, fixture, scorer or interval. The
lock was **not** rewritten — doing so would erase the evidence. Full disclosure
in `lock-amendment-01.md`; drift is exactly one file, the other 13 match
byte-for-byte.

## Cost

| Stage | Cost |
|---|---|
| pilot (2) | $0.09 |
| primary (126) | $13.63 |
| presave (6) | $0.77 |
| recompact (4) | $1.40 |
| judge, Claude (21 batches) | $3.30 |
| **total** | **$19.19** of $30.00 |

Headroom $10.81 — enough for the Codex judge (~$3.6) after 2026-08-08, which
would close G7 and convert this into a formal eight-gate verdict.

## Recommended next step

Run `run_judges.py codex --source primary` once Codex quota returns on
2026-08-08, then `analyze_results.py` for the complete preregistered verdict. No
regeneration is needed: the 126 primary outputs are final, and judging is
independent of them.

## Artifacts

- `results/analysis-q6.json` — gates and CIs as computed
- `results/primary.jsonl` (126), `presave.jsonl` (6), `recompact.jsonl` (4), `pilot.jsonl` (2)
- `results/judge-claude.jsonl` — 21/21 batches, 0 failures
- `results/preregistration-lock.json` — committed `2f11c49` at 07:16:05Z, before the first model call
- `results/corpus-independence.json` — 0 exact overlap vs 51 prior fixtures
- `results/judge-input-inspection-claude.json` — 6 candidates, 6 measured diffs, 0 variant-name leaks per batch
- `lock-amendment-01.md` — the single post-lock source change
