# Research: is `codex_review` worth it for workers that themselves run on Sol?

**Date:** 2026-07-25
**Phase:** 1 — research only. No implementation.
**Author:** research-review-value (Opus 5, deliberately not Sol — the tool under evaluation must not judge itself)
**Raw data:** `reviews-graded.tsv` (45 reviews, blind-graded), `codex-review-calls.tsv` (98 tool calls), `blind-grades-raw.tsv` (grades before unblinding)

---

## TL;DR

**The hypothesis is NOT supported by our data.** After removing contamination, Sol-authored work and Claude-authored work receive statistically indistinguishable review signal from `codex_review` (median 4.0 vs 4.5 substantive findings, zero-substantive rate 3/26 vs 0/14, Fisher p=0.54).

But "not supported" here means **"we cannot detect it,"** not "it isn't there." Three things are simultaneously true, and they point in different directions:

1. **The measured degradation is absent.** The raw numbers looked damning until I found the contamination; the effect did not survive it.
2. **The configuration is nevertheless the worst case the literature describes.** `codex_review` runs `gpt-5.6-sol` — the *same checkpoint* as the Sol workers, not merely the same family. Preference-leakage measures that tier at 23.6% vs 2.8% for same-family/different-series.
3. **Our outcome measure is structurally blind to the thing we care about.** Finding-count measures what a review *said*, never what it *missed*. A correct approval and a rubber stamp are the same row in my table.

**Recommendation: change nothing yet; run the one cheap experiment that would actually settle it.** See §7. The strongest evidence in this whole report argues that reviewer identity is the wrong lever — the two highest-damage incidents in the repo came from code that was **never reviewed at all**.

---

## 1. Question (framed)

- **Context:** Orchestra worker fleet, default worker model `gpt-5.6-sol`; `codex_review` MCP tool.
- **Change under test:** worker on Sol calls `codex_review` (reviewer also Sol) — same-model review.
- **Baseline:** worker on Claude calls `codex_review` — genuine cross-LLM review.
- **Measurable outcome:** signal produced per review — rubber-stamp rate, substantive-finding count, severity — and defects that escaped an approval.

### Hypotheses considered

| # | Hypothesis | Falsifier | Outcome |
|---|---|---|---|
| H1 | Sol-worker reviews yield systematically less signal than Claude-worker reviews | Equal or higher finding rates for Sol at adequate power | **REFUTED as stated** — no detectable difference (§3) |
| H2 | Any observed gap is task-type, not model, because model was assigned per task | Arms overlap on the same tasks and the gap persists | **SUPPORTED** — zero task overlap; assignment is fully confounded (§3.3) |
| H3 | The gap is a measurement artifact of how review files are written | Contaminant removal leaves the effect intact | **SUPPORTED** — 5 of 31 Sol files were not reviews (§3.1) |
| H4 | Same-model review is degraded but invisible to finding-count; only escapes reveal it | Escapes distribute evenly, or none exist | **UNCERTAIN** — 2 escapes, both Sol-arm, but n=2 (§5) |

---

## 2. Method and its limits

**Population.** All 98 `codex_review` tool calls in `data/orchestra.db`, 2026-07-18 → 07-25, across 26 workers and 5 projects. Backend attributed per call from `sessions.backend_type`.

**Blinding.** The 45 resolvable output files were copied to `/tmp/blind/` under shuffled IDs `R01…R45` and graded by a subagent that was instructed not to look outside that directory and had no access to worker or backend. Grades were unblinded only after they were written. `blind-grades-raw.tsv` is the pre-unblinding record.

**Integrity checks run:**
- 45 files, **45 distinct content hashes** — no cross-arm duplicate contamination (the failure mode that inflated the earlier `codex-audit` corpus to 679 files).
- No output path claimed by more than one worker.
- Unresolved files: 4 of 49, split 2 Sol / 2 Claude — balanced, so no directional bias.

### Limits that constrain every number below

- 🔴 **`logs` is pruned at 7 days** (`app/db.py:916`, `cleanup_old_logs(days=7)`). The DB window is 07-17→07-25 only. Nothing about the Claude-worker era is recoverable from logs; git artifacts are the only long-lived record.
- 🔴 **The eras do not overlap in the git corpus.** Pre-2026-07-11 artifacts are 28/31 code-adjacent (impl/plan); post-07-11 are 17/24 prose research. Comparing "Claude era" to "Sol era" measures *code diff vs prose*, not model. I therefore restricted the comparison to the single window where both arms coexist.
- 🔴 **Assignment is not random.** The orchestrator chose worker model per task. Any arm difference is confounded with task type by construction.
- 🔴 **n is small.** 26 vs 14 reviews. Only very large effects are detectable.

---

## 3. Findings

### 3.1 The raw comparison looked damning — and was contaminated

First pass, all 45 blind-graded reviews:

| | n | APPROVE_CLEAN | zero-substantive | blocking present | median substantive |
|---|---|---|---|---|---|
| Sol worker | 31 | 4 (12.9%) | 6 (19.4%) | 10 (32.3%) | 3.0 |
| Claude worker | 14 | 0 (0%) | 0 (0%) | 9 (64.3%) | 4.5 |

Directionally this is exactly the hypothesis. **It does not survive inspection.**

Five of the 31 Sol-arm files are not adversarial reviews at all. `sensar-roadmap` and `mobile-os-strategy` used `codex_review` in `exec` mode as a **reader test** — asking Codex to read a strategy memo as an audience member and react:

```
R23 sensar-roadmap      docs/tasks/1/reader-test-main.md            sub=0  APPROVE_NITS
R29 sensar-roadmap      docs/tasks/1/reader-test-audit-fix-main.md  sub=0  APPROVE_CLEAN
R33 sensar-roadmap      docs/tasks/1/reader-test-memo.md            sub=4  APPROVE_NITS
R37 sensar-roadmap      docs/tasks/1/reader-test-audit-fix-memo.md  sub=3  APPROVE_NITS
R40 mobile-os-strategy  docs/tasks/2/reader-test.md                 sub=0  APPROVE_NITS
```

Three of the four zero-substantive Sol results sit in this group. Counting a reader-comprehension test as a failed code review is a category error. **All five are in the Sol arm and none in the Claude arm** — they alone create most of the apparent gap.

### 3.2 With contamination removed, the effect disappears — CONFIRMED

| | n | zero-substantive | blocking present | median substantive | mean substantive |
|---|---|---|---|---|---|
| **Sol worker** | 26 | 3 (11.5%) | 10 (38%) | **4.0** | 4.3 |
| **Claude worker** | 14 | 0 (0%) | 9 (64%) | **4.5** | 5.9 |

Significance (Fisher exact, two-sided):
- zero-substantive: 3/26 vs 0/14 → **p = 0.54**
- blocking present: 10/26 vs 9/14 → **p = 0.19**
- n_substantive (Mann-Whitney, full sample): **p = 0.16**

**Confidence: CONFIRMED that no difference is detectable at this sample size.** Evidence tier: direct measurement on the full population of calls in the window, blind-graded. The median difference (4.0 vs 4.5) is a rounding artifact of small n, not a signal.

### 3.3 The one significant result is fully confounded — REFUTED as evidence

Sensar is the only project with both arms well-represented in the same week (07-18→07-20), so it looked like a natural experiment. Within it, blocking-present is Sol 1/9 vs Claude 6/10, **Fisher p = 0.0088**.

That result is worthless, and here is why:

```
Sensar docs/tasks/1   reviewed for: ['sol']
Sensar docs/tasks/2   reviewed for: ['sol']
Sensar docs/tasks/11  reviewed for: ['claude']
Sensar docs/tasks/15  reviewed for: ['claude']
Sensar docs/tasks/16  reviewed for: ['claude']
Sensar docs/tasks/17  reviewed for: ['claude']
overlap (tasks with BOTH arms): NONE
```

Sol workers did tasks 1–2 (roadmap, strategy brief). Claude workers did tasks 11, 15–17 (**commercial offer, SOW, pricing, product platform**). Contract and pricing documents contain blocking-class defects — wrong prices, unbound scope, legally wrong IP claims — that a strategy memo structurally cannot contain. The top Claude findings confirm it: *"1.8M price rests on placeholder rate and undisclosed 450k external costs; IP claim legally wrong"*, *"SOW binds no configuration, so config 2/3 price can be accepted at the source-only minimum."*

**This measures document genre, not worker model.** Reported here because it is the number most likely to be mistaken for proof.

### 3.4 The 95%-of-reviews-find-bugs claim does not apply to Sol — CONFIRMED

`docs/tasks/codex-audit/research.md` is dated **2026-07-09**. `gpt-5.6-sol` first enters the repo on **2026-07-11** (`0913b51`). At the audit commit, `pipelines/default/pipeline.yaml` role defaults were `orchestrator: opus4.6`, `worker: sonnet`, `full-cycle: opus4.8` — **all Claude**.

The doc never states the reviewed workers' model. Its only claims on the point are indirect:
> *"This is exactly the class of concurrency/fail-open bug that **Claude self-review misses**"*
> *"bugs caught pre-merge that **Claude's own adversarial pass demonstrably missed**"*

Further, the 95% figure rests on the filesystem corpus of **679 files** which the doc itself flags as *"heavy duplication — the same review file is copied across 10+ worktrees"*, with *"31 canonical files"* being the honest count. It is rated LIKELY, *"not independently re-counted."*

**The 95% number is a Claude-era figure resting on a duplicated corpus. It cannot be cited as evidence that `codex_review` earns its keep for Sol workers.** This is the single most load-bearing correction in this report.

### 3.5 Sol workers debate more, and the debate is real — CONFIRMED

| | calls | resume | resume rate |
|---|---|---|---|
| Sol worker | 75 | 36 | **48.0%** |
| Claude worker | 23 | 4 | **17.4%** |

92% of Sol reviews were multi-call vs 50% for Claude. I tested whether this deflates finding counts (the output file is overwritten per round, so a final round could hide earlier findings): **it does not** — median substantive is 4.0 for both single-call and multi-call reviews. Sol workers genuinely iterate with the reviewer more than Claude workers do.

### 3.6 The flagged `feat-usage-analytics` case is a valid approval, not a rubber stamp — CONFIRMED

The orchestrator flagged `feat-usage-analytics` (Sol) receiving "Approve, 0 findings" on its research. Reading the artifact and the call log:

- It is **round 2 of a resumed session** (`n_calls=2, resume=1`), not a single-pass wave-through.
- Codex **independently re-verified a specific numeric claim** against the database: *"медиана для сессий с ≥2 ходами действительно равна **1.7346**, поэтому фактической ошибки здесь нет."*
- It correctly scoped a non-issue: *"Hardcoded snapshot в прототипе допустим и не является требованием к production-реализации."*
- The **same worker, same day**, got `CHANGES_REQUESTED` with **blocking** severity on both its plan (R04, 4 substantive) and its impl (R21, 6 substantive — *"Sync telemetry write can block loop and kill a healthy turn; day-window off-by-one inflates all KPIs"*).

A reviewer that rubber-stamps does not hand the same worker two blocking verdicts hours later. **Verdict: valid approval.**

### 3.7 Cost in Codex-pool credits — LIKELY

Using the measured medians from `docs/tasks/codex-cost/research.md` (fresh 31.137, resume 9.593 credits):

| | calls (8 d) | est. credits |
|---|---|---|
| Sol-worker-initiated | 75 (76.5%) | **~1,560** |
| Claude-worker-initiated | 23 (23.5%) | ~530 |

Reviews are **9.86%** of Orchestra's Sol credits; ~77% of that is Sol-workers reviewing Sol work — roughly **7.5% of the Codex pool**. Confidence LIKELY: medians come from n=11 measured jobs, extrapolated by call count.

This is real but not the drain. Workers themselves are 90.14%. **Cost is not a reason to act.**

---

## 4. The configuration is the worst tier the literature describes — CONFIRMED

`~/.codex/config.toml:1` → `model = "gpt-5.6-sol"`. `codex_review` invokes the **same checkpoint** the Sol workers run on. This matters because the effect is steeply graded by lineage, not by vendor:

**Preference Leakage** (Li et al., **ICML 2025**, arXiv:2502.01534):

| Relatedness | Leakage score |
|---|---|
| **Same model** | **23.6%** |
| Same family, same series | 8.9% |
| Same family, different series | 2.8% |

Our setup is tier 1, the 23.6% row — not the mild "same vendor" case.

**Supporting evidence that the mechanism is real:**
- **When Does Verification Pay Off?** (arXiv:2512.02304, 37 models, 9 benchmarks): *"Verification across model families is more effective than either self-verification or verification within the same family... the benefits of verification decrease as the solver and verifier become more similar."* Cross-family gives 2–3× the verifier gain. **Notably, reasoning post-training raised solver accuracy +35.4% while *increasing* self-verification false-positive rate** — capability does not rescue self-verification.
- **Too Consistent to Detect** (Tan et al., **EMNLP 2025**, arXiv:2505.17656): of questions where one model makes a self-consistent error, only **9.6%** trip a different-family model. The errors a model cannot see in itself are ~90% visible to another.
- **Self-Attribution Bias** (Anthropic, arXiv:2603.04582, Mar 2026, 10 frontier models): SWE-bench code-correctness monitoring AUROC **0.99 → 0.89** under self-attribution; PR approval **5× more likely** to pass patches following prompt injections. Bias *"concentrated on the diagonal."*
- **Do LLM Evaluators Prefer Themselves for a Reason?** (arXiv:2504.03846): on MBPP+, harmful self-preference — preferring one's own answer *given it is wrong* — is **62.7%**.

### The crux, and I want to be precise about it

The orchestrator's brief pointed at the Huang trap (arXiv:2310.01798) from `docs/tasks/self-analysis`. **That citation does not transfer, and using it would be a category error.**

Kamoi et al. (**TACL 2024**, arXiv:2406.01297) define four distinct architectures. Huang et al. tested **intrinsic self-correction only** — same model, *same context*, no external signal. Our case is a **separate process with fresh context reviewing an external artifact (a diff)**, which is structurally closer to cross-model critique.

The difference is measurable. **Self-Correction Bench** (arXiv:2507.02778) injected identical errors either into the model's own completion or into the user message: the position alone accounts for a **64.5%** blind-spot rate, and a single "Wait" token cuts blind spots **89.3%** — the capability is dormant, not absent. Reviewing a diff as external input *is* the good condition.

But it does not reach independence. The honest statement is from the one source that addresses it head-on (Preprints 202601.0892): *"Fresh-context same-model evaluation does NOT satisfy the strict independence conditions... shared weights and training distribution mean parameter-level blind spots remain."* Panickssery et al. (**NeurIPS 2024**, arXiv:2404.13076) showed self-preference persists on **unlabeled** text — masking authorship does not fix it, because the stylistic fingerprint carries the signal.

**So: fresh-context same-model review removes the contextual half of the problem and none of the parametric half.**

---

## 5. Counter-evidence — the parts that argue against acting

I went looking for reasons the hypothesis is wrong, and found substantial ones.

**5.1 The self-preference effect may be an order of magnitude smaller than claimed.** *Are LLM Evaluators Really Narcissists?* (arXiv:2601.22548), **37,448 evaluation pairs**, re-tested four landmark studies including Panickssery: **89.6%** of measured self-preference is explained by evaluator uncertainty, not self-recognition; **44%** of experiments show no or negative bias; **50%** lose significance. Only 10.4% exceeds baseline.

**5.2 The direction is not even consistent across models.** Yang et al. (arXiv:2604.22891), 20 models: **8 positive, 9 negative, 3 negligible**. Claude-Sonnet-4.5 measured **β = −0.229** — actively self-critical. In the CALM benchmark (arXiv:2410.02736), self-enhancement is among the *smallest* biases measured, and GPT-4-class models sit at 1.16–1.74%.

**5.3 Model diversity is not a reliable fix.** *The Cost of Consensus* (arXiv:2605.00914): isolated self-correction beat multi-agent debate in **6 of 6** conditions at 2.1–3.4× lower cost; heterogeneous teams showed **negative synergy in 6 of 8** pairs, worst −25.1pp. Injecting rationales from *unrelated problems* beat genuine peer debate in 5 of 6 conditions. (Sources genuinely disagree here — arXiv:2502.08788 and arXiv:2602.03794 reach the opposite conclusion on the same model classes.)

**5.4 Swapping vendors attacks the smallest term.** *Correlated Errors in LLMs* (**ICML 2025**, arXiv:2506.07962, 349 models): agreement-when-both-wrong is **0.423** vs random 0.127, and **100%** of model pairs are above random. Same-company adds only **+0.066**. The co-failure ceiling paper (arXiv:2606.27288, 67 models) puts within-family ρ at 0.528 vs cross-family 0.459 — a 0.069 gap on a ~0.46 base. **Most error correlation is common-mode and survives any model swap.**

**5.5 Our own escape analysis points somewhere else entirely.** See §6.

---

## 6. Defect escapes — where the damage actually came from

Forensic pass over BUGS.md, CHANGELOG, and git history for cases where a review approved work and a defect surfaced afterwards.

**CONFIRMED escape — `tg-message-delivery` (Sol worker `research-tg-messages`).** The plan review raised the exact failure mode as a question and then **blessed the answer**: *"decide whether an important retry holds the lock. **Resolved:** it holds the per-chat lock through retry_after/network backoff."* Round 2 impl review: *"Verdict: **APPROVED**... New blocking findings: **none**."* Shipped `4fd6816` (07-18).
- +3 days → BUGS.md: *"Setting `_send_expandable(important=True)` causes ALL outbound TG messages to stop... lock never frees → infinite queue. **REVERTED**."*
- +7 days → user-visible ~1h outage; the failing log strings are verbatim from the approved diff. Fixed by `62cf9bc`, which does not tune the approved contract — it **deletes it** for topic metadata.

**LIKELY escape — `codex-cache-research` (Sol worker `research-codex-cache`).** Review asserted the policy was *"wired through session listing, orchestrator listing, MCP cache pill rendering, and frontend rendering consistently."* A hardcoded `3600` survived in `app/routes/system.py` — the same file the diff touched — inflating Codex cache-hit rates on the dashboard for a week until `78f0741`.

Both escapes are Sol→Sol. That is directionally consistent with H4. **But n=2, the Sol arm is larger, and the search space (orchestra tasks) is Sol-dominated — this is suggestive, not evidence.**

**The finding that actually matters, and it cuts against the whole framing:**

> The two highest-damage incidents came from code that was **never reviewed at all**.
> - `0c4c4c0` — 207 lines in the critical TG delivery path, merged with **zero tests and no review artifact**; the 07-25 outage is co-owned by it.
> - `d4c0719` — the `codex_review` CWD fix, **no review artifact**, incomplete; the same bug is reported **six times** in BUGS.md across four weeks.

Also worth recording: `docs/tasks/codex-sessions/codex-review-impl.md` **raised two P2 regressions and the work shipped anyway** in the same commit. That is a gate failure, not a reviewer failure.

**Review coverage and finding-follow-through are larger levers than reviewer identity.**

---

## 7. Counterfactual assessment

Cost framing: Codex pool ≈ separate quota, currently ~7.5% consumed by Sol-worker reviews. Claude pool is the scarcer one (Max $100, halved from $200; each turn costs ~2× the % it used to).

| Option | Signal | Cost | Verdict |
|---|---|---|---|
| **(a) Opus 5 reviewer via separate worker** | Best per literature — crosses lineage, the 23.6%→2.8% jump. Escapes the single-pool risk | Burns the **scarcer** pool; a full Opus turn per review | 🟡 **Targeted use only** — not fleet-wide |
| **(b) `codex_review` only for Claude workers** | Perverse: removes review from precisely the arm with the same-model problem | Saves ~1,560 credits | 🔴 **Reject** |
| **(c) Leave as is** | No measured degradation (§3.2); reviews produce median 4 substantive, mostly anchored findings | Status quo | 🟢 **Defensible default** — but leaves tier-1 lineage + single-pool dependency |
| **(d) Self-review + orchestrator gate** | Weakest. Literature is harsh on unanchored self-critique; the orchestrator is also an LLM, so this is not a human gate | Cheapest | 🔴 **Reject as a replacement** — keep the gate *in addition* |

**Availability risk is a real and separate argument for (a).** Codex was globally down ~1h today (503 `circuit_open`). Today both the work *and* its review depend on one pool. A cross-pool reviewer is a hedge on uptime regardless of what it does for quality.

### Recommended: (c) now, with a decisive experiment before considering (a)

Do not migrate on unmeasured grounds — the data does not support it, and §5 gives strong reasons the effect may be small. Instead close the gap that makes this unanswerable.

**The experiment (cheap, decisive, ~10 Opus turns):** take 8–10 **already-reviewed Sol-authored code diffs**, re-review each with Opus 5 on the identical input, and compare findings on the same artifact. This is the 2×2 the literature says **nobody has run** — every practitioner claim about cross-model review is confounded with context reset. Pre-register the metric: *count of substantive findings raised by Opus 5 that Sol's review missed, and vice versa.* Grade blind.

**Do regardless of the outcome** — both are coverage problems, which the evidence says dominate:
1. **Close the coverage hole.** `0c4c4c0` and `d4c0719` shipped unreviewed into the critical path. Cheap review of *everything* touching shared runtime beats expensive review of some of it.
2. **Enforce finding follow-through.** `codex-sessions` shipped with two P2s raised and unaddressed. A finding that does not gate a merge is a finding that did not happen.

---

## 8. Self-review — weaknesses of this analysis

Per instruction I did **not** use `codex_review` here (conflict of interest: it is the object under evaluation). Instead, the weaknesses I know of:

1. **Underpowered.** n=26 vs 14. I can only exclude very large effects. "No significant difference" at this size is weak evidence of no difference; do not read §3.2 as exoneration.
2. **Grading is single-rater and LLM-produced.** One subagent graded all 45 files. No second rater, so no inter-rater reliability. "Substantive" is a judgment call that another grader would draw differently. Blinding controls bias, not variance.
3. **My outcome measure cannot see the actual failure mode.** Rubber-stamping means *missing* defects. Finding-count measures what was said. A perfect review of clean work and a lazy review of broken work both score zero. §6 is the only part that addresses this, and it rests on n=2.
4. **Assignment is observational, never randomized.** Model was chosen per task by the orchestrator. §3.3 shows the confound is total, not partial. No amount of stratification fixes this in retrospective data.
5. **Backend attribution uses current `sessions.backend_type`.** A worker that switched backend mid-life would be misattributed. I checked `runtime_handoff` and found no switches among the 26 sampled workers, but the column is not a reliable audit log.
6. **Cost figures are extrapolated**, not billed — call counts × medians from n=11 measured jobs in a different 27h window.
7. **I did not read every reviewed artifact myself.** I graded the *reviews*, not the *work* — so I cannot say whether a finding was correct, only whether it was substantive and anchored. False positives are unmeasured.
8. **The literature is contested and I have shown both sides** (§4 vs §5). Anyone quoting only §4 is misusing this document.

---

## 9. Confidence summary

| Finding | Confidence | Basis |
|---|---|---|
| No detectable signal difference between arms | **CONFIRMED** | Direct measurement, blind-graded, full population in window; p=0.54 |
| 5 Sol-arm files were reader-tests, not reviews | **CONFIRMED** | Direct file inspection |
| Sensar result is confounded with task assignment | **CONFIRMED** | Zero task overlap, verified programmatically |
| The 95% claim is Claude-era and does not transfer | **CONFIRMED** | Doc dated 07-09; Sol lands 07-11; git-verified role defaults |
| `feat-usage-analytics` approval is valid, not a stamp | **CONFIRMED** | Round-2 artifact re-verifies 1.7346; same worker got 2 blocking verdicts same day |
| `codex_review` reviewer = same checkpoint as Sol workers | **CONFIRMED** | `~/.codex/config.toml:1` |
| Same-model review is degraded in principle | **LIKELY** | Multi-source, replicated; but magnitude disputed (§5.1, §5.2) |
| Huang trap does not transfer to fresh-context review | **LIKELY** | Kamoi TACL taxonomy + Self-Correction Bench; single direct paper is flawed |
| Sol-arm escapes indicate real degradation | **UNCERTAIN** | n=2, non-random search space |
| Coverage matters more than reviewer identity | **LIKELY** | 2 highest-damage incidents were unreviewed; single repo, not generalizable |
| Sol-worker reviews ≈ 7.5% of Codex pool | **LIKELY** | Extrapolated from n=11 medians |

---

## Sources

**Local (measured this session):** `data/orchestra.db` logs+sessions; `app/db.py:916`; `~/.codex/config.toml:1`; 45 graded review artifacts; git history 2026-05-29→07-25; `BUGS.md`; `docs/tasks/codex-audit/research.md`; `docs/tasks/codex-cost/research.md`; `docs/tasks/codex-sleep/research.md`; `docs/tasks/self-analysis/research.md`.

**External (fetched this session):**
[1] Li et al., *Preference Leakage*, ICML 2025 — arXiv:2502.01534
[2] Lu et al., *When Does Verification Pay Off?* — arXiv:2512.02304
[3] Tan et al., *Too Consistent to Detect*, EMNLP 2025 — arXiv:2505.17656
[4] Khullar et al., *Self-Attribution Bias*, Anthropic 2026 — arXiv:2603.04582
[5] Panickssery et al., *LLM Evaluators Recognize and Favor Their Own Generations*, NeurIPS 2024 — arXiv:2404.13076
[6] Chen et al., *Do LLM Evaluators Prefer Themselves for a Reason?* — arXiv:2504.03846
[7] Kamoi et al., *When Can LLMs Actually Correct Their Own Mistakes?*, TACL 2024 — arXiv:2406.01297
[8] Huang et al., *LLMs Cannot Self-Correct Reasoning Yet*, ICLR 2024 — arXiv:2310.01798
[9] Tsui, *Self-Correction Bench* — arXiv:2507.02778
[10] Roytburg et al., *Are LLM Evaluators Really Narcissists?* — arXiv:2601.22548
[11] Yang et al., *Quantifying and Mitigating Self-Preference Bias of LLM Judges* — arXiv:2604.22891
[12] Kim et al., *Correlated Errors in Large Language Models*, ICML 2025 — arXiv:2506.07962
[13] Bertalanič & Fortuna, *The Cost of Consensus* — arXiv:2605.00914
[14] *Justice or Prejudice?* (CALM) — arXiv:2410.02736
[15] Tyen et al., *LLMs Cannot Find Reasoning Errors...*, ACL Findings 2024 — arXiv:2311.08516
[16] *Limits of Self-Correction: Information-Theoretic Analysis of Correlated Errors* — Preprints.org 202601.0892
[17] *Co-Failure Ceiling* — arXiv:2606.27288
[18] Kamoi et al., *Evaluating LLMs at Detecting Errors in LLM Responses*, COLM 2024 — arXiv:2404.03602
