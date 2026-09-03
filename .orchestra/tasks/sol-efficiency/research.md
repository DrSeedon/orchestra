# Sol/Codex worker efficiency — log forensics

**Date:** 2026-07-25 · **Analyst:** research-sol-efficiency (Opus 5, deliberately not Sol)
**Corpus:** `data/orchestra.db`, read-only snapshot. Log window **2026-07-18T11:00 → 2026-07-25T11:14 UTC** (7 days), 22 780 log rows, 103 sessions.
**Raw data:** `calls_strict.tsv` (5 608 tool calls), `turns_strict.tsv` (580 turns), `sessions.tsv`, `scripts/`.

## TL;DR — the headline is not what anyone expected

**Sol's cost is driven by the NUMBER of tool calls, not by the size of what they return.**

OLS over 103 Sol-worker turns:

```
cost_usd = 0.898 + 0.0859 × n_calls + 1.140 × MB_of_tool_traffic     R² = 0.646
```

| driver | point estimate | bootstrap 95 % CI |
|---|---|---|
| tool-call count | **70 %** | [36 %, 89 %] |
| per-turn fixed overhead + concavity | **26 %** | [11 %, 51 %] |
| tool traffic bytes | **4 %** | [−13 %, +21 %] |

Corroborating correlations: `corr(n_calls,$) = 0.806`, `corr(in_bytes,$) = 0.777`, `corr(out_bytes,$) = 0.497`.

**Do not quote "70/26/4" to the digit** — see §7. The confidence intervals are wide and the bytes interval straddles zero. What survives every robustness check is the *ordering and the ceiling*: **call count is the dominant driver, and tool bytes cannot account for more than ~21 % of spend even at the 95 % bound.**

Consequence: **every "trim the fat output" fix is worth a couple of percent of credits at best.** The levers that matter are (1) fewer round trips for the same work, (2) whatever sits in the per-turn fixed cost.

The $9.50 turn that prompted this task (`feat-usage-analytics` turn #10) was **81 tool calls** of real work — model predicts $8.28, actual $9.50. It was not waste; it was volume.

---

## 1. Method and its validation

Tool calls are paired to their results by **strict adjacency** (a `tool` row immediately followed by a `tool_result` row in the same session). Coverage: **88.7 % overall, 82 % of Sol worker calls**.

I first used FIFO queue pairing (handles parallel batches) and **it produced materially wrong answers** — it attributed a 275 kB result to `FileChange` and a 155 kB result to a `git status` command. Spot-checking the actual adjacent rows showed `FileChange` really returns `{"status": "completed", "files": 1}` (31 bytes). Every byte figure below is on the strict basis. Run-length check: 4 424 of 4 975 tool rows are strictly alternating; parallel batches (run ≥2) are 551 rows, which is the bulk of the unpaired 18 %.

Model-migration caveat handled by **comparing on `backend_type`, never on `model`** — the 07-24 bulk rewrite of Claude model labels does not touch `backend_type='codex'`.

---

## 2. Where the bytes are (and why it matters less than it looks)

### Sol workers — 29 sessions, 114 turns, 2 890 calls, in 4 192 kB / out 8 311 kB

| tool | n | % calls | out kB | % out | avg out | in kB | % in |
|---|---|---|---|---|---|---|---|
| Bash | 1621 | 56.1 | 7685 | **92.5** | 4855 | 1483 | 35.4 |
| FileChange | 478 | 16.5 | 14 | 0.2 | **31** | 2346 | **56.0** |
| WebSearch | 236 | 8.2 | 81 | 1.0 | 349 | 21 | 0.5 |
| send_message | 119 | 4.1 | 6 | 0.1 | 54 | 87 | 2.1 |
| ViewImage | 117 | 4.0 | 25 | 0.3 | 316 | 16 | 0.4 |
| codex_review | 69 | 2.4 | 25 | 0.3 | 366 | 63 | 1.5 |
| serena/* | 90 | 3.1 | 244 | 2.9 | 2 700 | 21 | 0.5 |
| Read | 28 | 1.0 | 100 | 1.2 | 3642 | 3 | 0.1 |
| Edit / Write | 57 | 2.0 | 11 | 0.1 | 205 | 122 | 2.9 |

**Byte concentration** (median result = **256 B**):

| slice | share of Sol result bytes |
|---|---|
| top 1 % of calls (22) | 28.1 % |
| top 5 % (111) | 58.1 % |
| top 10 % (223) | 76.7 % |
| calls > 20 kB (104) | 56.4 % |
| calls > 50 kB (13) | 23.1 % |

So Sol is **disciplined by default and blown out by ~100 calls**. But since bytes carry only 4 % of cost, this tail is a *context-window* problem, not a credit problem.

### Claude workers — for contrast (15 sessions, 50 turns, 1 210 calls, out 11 155 kB)

| tool | n | % calls | out kB | % out | avg out |
|---|---|---|---|---|---|
| Read | 171 | 14.1 | 10 272 | **92.1** | **61 513** |
| Bash | 502 | 41.5 | 436 | 3.9 | 890 |
| Edit | 250 | 20.7 | 56 | 0.5 | 229 |
| Write | 68 | 5.6 | 15 | 0.1 | 220 (in: 646 kB) |

**41 fat Claude results are base64 images = 9.31 MB = 83.5 % of all Claude-worker tool bytes. Sol: 0.00 %.**

> **The prior docs do not transfer.** `token-waste` ("tool_result 87 %", "images read 3-4×") and `tool-result-optimization` ("89 % of bytes = images") were measured on **Claude** workers and remain true for Claude. For Sol they are wrong twice over: images are 0 % of transcript bytes, and tool_result bytes carry ~4 % of *cost* rather than 87 % of anything that matters.

---

## 3. Question by question

### 3.1 Turn profile
Sol: mean **27.0 calls/turn**, median 14, p90 66. Bash-dominated (56 % of calls). `zsh -lc` wrapper on **91 %** of Bash calls (Claude: 0 %); median command length 201 chars vs Claude's 358.

Bash leading verbs (Sol): `sed` 283 (17.5 %), `git` 231, `python` 152, `rg` 145, `uv` 95, `ssh` 94, `sqlite3` 78, `sleep` 53, `find` 40, `pwd` 37.

### 3.2 Repeats — mostly a false alarm
- **Exact-identical Bash within a session: 92 / 1 621 = 5.7 %** (195 kB, 2.9 % of Bash bytes). Claude: 2.4 %. Worst offenders are legitimate re-runs (`pytest` ×7 after fixes, `build_docx.py` ×9).
- **`sed -n` windows: 656 fetches. Literally identical window repeated: 7. Different window of an already-opened file: 251.** Sol reads `session.py` in 13 *distinct* windows, `db.py` in 9. This is **windowed reading, not duplicate reading** — and it is the single best $-denominated lever, because each window is a separate call at $0.086.
- Retry-shaped (same 60-char prefix, different tail): Sol 106 (306 kB) vs **Claude 207 (1 279 kB)** — Sol retries *less* than Claude.

### 3.3 The ten most expensive Sol turns
Each was manually itemised (full list in `turns_strict.tsv`, joined via `calls_strict.tsv`).

| $ | session | calls | out | reason | what it actually was |
|---|---|---|---|---|---|
| 20.86 | sensar-roadmap | 188 | 400 kB | interrupted | DOCX build loop: 91 Bash + 44 FileChange + 38 ViewImage, pdftoppm page proofs |
| 14.92 | research-codex-cost | 99 | 372 kB | end_turn | 65 Bash + 17 FileChange + 6 serena; one 45 kB `rg`, one 35 kB sqlite dump |
| 14.31 | mobile-os-strategy | 104 | 771 kB | end_turn | **two nested `codex exec` runs = 431 kB**, 12 WebSearch |
| 11.80 | sales | 125 | 287 kB | end_turn | one 91 kB `find` across worktrees, 23 WebSearch, 20 send_message, 4 spawn_worker |
| 10.25 | mobile-os-strategy | 52 | 48 kB | interrupted | 20 FileChange — pure editing, cheap bytes, many calls |
| 10.23 | research-codex-abuse | 48 | 170 kB | interrupted | 25 Bash, doc greps |
| 9.56 | mobile-os-strategy | 76 | 302 kB | interrupted | 65 kB `rg` over a Russian-text doc + 2 WebSearch at 41/37 kB |
| 9.50 | feat-usage-analytics | 81 | 259 kB | end_turn | 58 Bash + 20 FileChange + pytest runs — **normal work** |
| 9.49 | mobile-os-strategy | 88 | 153 kB | interrupted | 23 ViewImage proof-reading loop |
| 9.21 | codex-limits-source | 26 | 25 kB | end_turn | only 26 calls — cost sits in ctx:69 %, i.e. the preamble |

**Pattern:** every expensive turn is expensive because it has 50-190 calls. Not one is expensive because of a single fat result. The two nested `codex exec` calls are the only clear-cut waste in the whole top-10.

### 3.4 Overhead of breaks and re-orientation — premise falsified
- Turn endings, Sol: `end_turn` 80 ($244.54), **`interrupted` 18 ($94.98 = 26.8 %)**, `error` 6 ($8.29), `stop_sequence` 5, `tool_use` 2.
- **But interrupted turns are not waste:** $/call is $0.127 vs $0.121 for clean turns — bootstrap difference **+$0.006, 95 % CI [−$0.026, +$0.045]**, i.e. no detectable per-call penalty (though the interval permits up to ~+37 %). They are simply longer (41.6 vs 25.2 calls). 111 `message steered into active Codex turn` events — steering extends turns, it does not burn them.
- **Re-orientation after a break shows no *detectable* excess:** reorient calls among the first 4 calls of a turn = **0.78/turn after a broken turn (n=18) vs 0.90/turn otherwise (n=96)**; z = −0.52, se = 0.23. This test can only detect differences ≳0.6 calls/turn, so it **does not falsify** the premise — it only says any excess is small. Sol reorients ~0.9 times per turn largely unconditionally.
- Total reorientation: 242 / 1 621 Bash calls (14.9 %), 1 216 kB. `git status` alone: 239 calls, median **261 B** — cheap, except 18 calls > 20 kB (764 kB) in artifact-heavy worktrees.
- Codex-side failures in the window: 63 error rows (20 `turn FAILED: error`, 8 `server_error`, 6 × HTTP 503, 4 stream disconnects). The 6 `error`-reason turns cost **$8.29 = 2.3 %** of Sol spend.

### 3.5 Bash style / escaping — not the problem
`zsh -lc` + escaping is **91 %** of Sol Bash calls, but total Bash *input* is 1 483 kB of 4 192 kB, and median command is 201 chars. No measurable retry penalty from broken escaping: near-identical consecutive commands are half Claude's rate. **`tool_errors` is empty (0 rows)** despite shipping 07-18, so I cannot measure tool-level failures directly — the retry inference above is heuristic.

**The real escaping-adjacent defect is different and precise:** Sol bounds output by **lines**, not bytes.
- 18 `head -n`-limited results still exceeded 20 kB, totalling **1 407 kB**.
- 14 fat results have > 300 chars/line = **1 428 kB (17 % of Sol result bytes)**.
- Worst single result in the entire corpus, **687 kB (8 % of all Sol bytes in one call)**: `rg -n "…" ~/.local/share ~/.npm ~/.codex | head -n 250` — it hit `~/.codex/models_cache.json`, where one line is a whole system prompt.
- Claude workers: **zero** long-line blowups (p90 = 139 chars/line).

### 3.6 What Sol does WELL — lock these in
1. **Median tool result 256 B.** Default behaviour is frugal; the mean is hostage to ~100 calls.
2. **Patches, not rewrites.** FileChange 478 vs Write 5. Claude: Edit 250 + **Write 68 (646 kB of input = 40 % of its tool input)**. Sol never re-sends a whole file to change three lines.
3. **Batching.** 70 % of Sol Bash calls contain multiple commands, avg **4.4 commands per call** — this collapses what Claude does in 3-5 round trips into one, which is exactly the right trade given cost is 70 % call-count.
4. **serena actually used: 90 calls vs Claude's 0.** AST navigation instead of reading files whole.
5. **Narrates 2.4× less:** 520 text rows / 169 kB vs Claude 986 rows / 411 kB.
6. **Images never pollute the transcript.** `ViewImage` returns an 85 B stub (`{"status": "viewed", …}`); Claude's `Read` of a PNG returns 61 kB of base64. 0 % vs 83.5 % of tool bytes.
7. **Windowed reads beat whole-file reads** on bytes (avg 4.9 kB/Bash vs Claude's 61.5 kB/Read). The technique is right; only the *count* of windows is wrong.

### 3.7 Sol vs Claude — coarse comparison only

| | turns | sessions | $ total | $ mean | $ median | calls/turn mean | median | p90 |
|---|---|---|---|---|---|---|---|---|
| Sol | 114 (106 with $>0) | 29 | 353.95 | **3.34** | 1.82 | 27.0 | 14 | 66 |
| Claude | 50 (39 with $>0) | 10 | 127.19 | **3.26** | 1.58 | 22.8 | 19 | 43 |

**No detectable difference in per-turn cost:** Mann-Whitney U = 2141, z = 0.33, **p = 0.74**; bootstrap mean difference **+$0.08, 95 % CI [−$1.53, +$1.42]**. Note the interval is ±45 % of the mean — this is "no difference detected with low power", not "proven equal". Sol's distribution is more skewed (lower median, higher p90).

So "Codex ate 14 points of the 7d limit in 6.5 h" is a **volume** statement — 29 active Sol sessions running long turns — not evidence of per-turn inefficiency.

Do not lean on this table for quota planning: the pools are different, and Orchestra is known to under-count Codex cost (missing `cache_write_input_tokens`), which biases the comparison in Sol's favour by an unknown amount.

### 3.8 Sleep — the 07-25 fix appears to have landed
88 `sleep` Bash calls in the window (1 565 s of wall time), **all of them before d19ad34** (2026-07-25T05:22:56 UTC). In the 5.9 h / **356 Codex tool calls after** the commit: **0 sleeps**, versus a pre-fix rate of 3.40 % → 12.1 expected, `P(0 | no change) = 5.5 × 10⁻⁶`.

**Strong evidence the fix works.** One caveat: sleeps cluster by session (25 of 88 came from one worker), so the effective sample is smaller than 356 independent trials and the true p-value is larger than the Poisson figure. Still comfortably significant; re-confirm at ~2 000 post-fix calls.

---

## 4. Recommendations, ranked by expected return

Savings are expressed against **$351.62 / 2 848 calls / 12.7 MB of measured Sol-worker spend in the window**, using marginal costs $0.086/call and $1.14/MB from the regression. Where I cannot ground a number, I say so instead of inventing one.

| # | fix | kind | measured basis | expected saving |
|---|---|---|---|---|
| **R1** | **Read a file once with a generous window, not 3+ narrow ones** | (a) prompt | 251 revisit-calls across 656 sed-windows; 13 windows of one file | **~3 % of Sol credits** (halving revisits ≈ 125 calls ≈ $11; added bytes cost ≈ $1.7) — best $-grounded win found |
| **R2** | **Bound output by BYTES, not lines** (`head -c`, `cut -c1-300`, `rg --max-columns`) | (a) prompt | 1 428 kB in 14 long-line results; 687 kB single worst; 18 head-limited results still > 20 kB | **−17 % of Sol result bytes**; only **~0.7 %** of credits, but removes the largest context spikes. One-line change, near-zero risk |
| **R3** | **Backend byte cap on tool results** (~20-25 kB + `…truncated N bytes` marker) | (b) tool | 104 calls > 20 kB = 56.4 % of result bytes | **−33 % of Sol result bytes ≈ 1.3 % of credits.** Real payoff is context pressure (expensive sessions ran ctx 52-72 %) — **not quantifiable from this data** |
| **R4** | **Forbid `codex exec` inside Bash; use `codex_review`** | (a) prompt | 2 nested runs = 431 kB = 5.2 % of Sol bytes, inside the single most expensive `end_turn` | ~0.2 % of credits directly. Main value: it burns a **second Codex quota invisible to Orchestra's accounting** — an accounting-correctness fix |
| **R5** | **`git status --short -- <paths>` / .gitignore hygiene in artifact-heavy worktrees** | (a)+(b) | 18 of 239 `git status` calls > 20 kB = 764 kB; median is only 261 B | ~0.3 % of credits. Cheap, but do **not** try to reduce re-orientation generally — see R8 |
| **R6** | **Wire `tool_errors` to the event stream** | (b) tool | table has **0 rows** since 07-18 | No direct saving. Prerequisite: it is the one thing I could not measure |
| **R7** | **Log `ViewImage` payload size (or token estimate) for Codex** | (b) tool | 117 ViewImage calls, transcript shows only an 85 B stub | No direct saving. Closes the largest blind spot in this analysis |
| **R8** | **ANTI-recommendation: do NOT split Sol turns to make them cheaper** | (c) | Positive intercept survives every fit: $0.90 (linear), and dropping it costs R² (0.646 → 0.612) while pushing $/call up to $0.0997 | Direction is solid — each extra turn carries a real fixed cost, so splitting adds money. **The magnitude is not** (see §7): the $/call ladder is partly a ratio artifact, and a sqrt term absorbs much of the intercept. Treat "splitting a 60-call turn into three costs ~$1.80" as an upper-bound sketch, not a measurement |
| **R9** | **ANTI-recommendation: do NOT "optimise" FileChange input** | (c) model/tool | 2 346 kB = 56 % of Sol tool input, output 31 B avg. Claude's 68 Writes cost 646 kB for 1/7 the edits | Pushing Sol off patches toward whole-file writes would make things worse. Input bytes are the cheap, cacheable direction. Leave alone |

Also: **R2, R4 and R1 are three lines of prompt text total.** They belong in one edit to `base.md`, not three.

---

## 5. Weaknesses of this analysis — read before acting

1. **The image blind spot is real.** `ViewImage` logs an 85 B stub. Orchestra's logs **cannot tell whether the image entered Sol's model context**. All I can honestly claim is that images are absent from the *transcript*. 117 calls are unmeasured, and `sensar-roadmap`/`mobile-os-strategy` (the two priciest sessions, 38 and 23 ViewImage calls in single turns) are exactly where this would bite. **My "Sol is immune to the image problem" claim is unproven for cost — only proven for transcript bytes.**
2. **18 % of Sol calls are unpaired** (parallel batches, interrupts). Their output bytes are missing from every byte total → byte figures are a **lower bound**.
3. **`tool_errors` is empty**, so tool failure and retry rates are inferred from command-prefix similarity. Weak instrument.
4. **Cost figures are Orchestra's own**, and Codex `cache_write_input_tokens` is known to be missing → **Sol spend is under-counted by an unknown amount**. The Sol-vs-Claude parity in §3.7 could flip.
5. **R² = 0.646** and the coefficient CIs are wide — see §6 for the full list of what this forced me to downgrade. Effort level, cache hit/miss and context size are not in the model (per-turn cache stats are not in these logs).
6. **Correlation is not causation on calls → $.** Long turns may be long because the task was hard. The regression cannot separate difficulty from wastefulness, so "fewer calls" must never be read as "do less work".
7. **Small, concentrated sample.** 114 Sol turns / 29 sessions over 7 days. `mobile-os-strategy` alone is $49 (14 % of spend); the top 4 sessions are 42 %. Several findings rest on a handful of sessions and one worker's habits.
8. **Task mix differs between the two backends** (Claude workers did more DOCX/PDF/image work) — this alone could explain the Read-vs-Bash split without any behavioural difference between models.
9. 15 of 595 `turn ended` records did not match the cost regex and are excluded.
10. The sleep-fix verdict rests on a **5.9 h / 356-call** post-fix window. Suggestive, not settled.

---

## 6. Robustness checks — what survived, what I downgraded

A Codex cross-review was dispatched and **timed out before writing its prose**, but its harness ran to completion and independently reproduced the regression to four decimal places (`b_call = 0.0859`, `b_MB = 1.140`, R² = 0.6461). I then ran its planned attacks myself (`scripts/` + inline). Results:

**Survived:**

| attack | result | verdict |
|---|---|---|
| Does dropping the 18 % unpaired calls break the byte tables? | Imputing missing outputs at each tool's **p90** adds 10 MB (nearly doubling traffic); bytes share moves only **4.1 % → 7.0 %**, calls **69.6 % → 66.6 %**, fixed **26.3 %** unchanged | **Central claim robust.** Byte share cannot be rescued into significance |
| Are a few dominant sessions driving it? | Leave-one-session-out: calls share stays in **65.1–75.6 %** | Robust |
| Are calls and bytes too collinear to separate? | `corr = 0.734`, **VIF = 2.16** | Acceptable; not degenerate |
| R1 arithmetic | 125.5 calls × $0.0859 = **$10.78 = 3.07 %** of $351.62 | Confirmed |
| Sol-vs-Claude parity | Mann-Whitney **p = 0.74** | Now has a test statistic |
| Sleep fix | `P(0 | no change) = 5.5 × 10⁻⁶` | **Upgraded** to strong evidence |

**Downgraded or retracted:**

1. **"70 / 26 / 4" is no longer stated as precise.** Bootstrap 95 % CIs: calls [36 %, 89 %], fixed [11 %, 51 %], bytes **[−13 %, +21 %]**. The bytes interval straddles zero. Robust claim = ordering plus the ~21 % ceiling on bytes, nothing finer.
2. **"26 % = the per-turn preamble" — retracted as a mechanism.** Adding `sqrt(calls)` cuts the intercept $0.898 → $0.342 while barely moving R² (0.646 → 0.649). So the intercept is **partly absorbing concavity in call cost**, not purely fixed preamble. It is real (dropping it costs R²) but it is not cleanly "the system prompt". The `codex-limits-source` example ($9.21 for 26 calls) is consistent with preamble but does not prove it.
3. **"Re-orientation premise falsified" → "no excess detected".** The test is underpowered (detects only ≳0.6 calls/turn).
4. **"Interrupted turns are not waste"** holds directionally, but the CI permits up to a 37 % per-call penalty.
5. **The $/call ladder ($0.284 → $0.100) is a ratio artifact** and is no longer load-bearing for R8. Dividing a fixed cost by more calls mechanically lowers $/call; it cannot by itself prove splitting is harmful. R8 now rests on the intercept's existence, and its magnitude is explicitly unquantified.

R² = 0.646 means a third of variance is still unexplained by calls + bytes; effort, cache hit rate and context size are not in these logs.

## 7. Answer to "where do the tokens burn"

Not in fat tool results — those are ~4 % of cost (≤21 % at the 95 % bound). They burn in:

1. **Round trips — the dominant driver.** 27 calls per turn on average, 66 at p90. Sol's windowed-read habit converts one file into up to 13 billable calls. This is where every recommendation worth acting on lives.
2. **A real per-turn fixed cost** (~$0.90 in the linear fit, ~26 % of spend). Part preamble re-sent each turn, part concavity in call pricing — §6 shows these two cannot be separated with this data. Worth measuring properly, not worth guessing at.
3. **The byte tail — small.** 104 calls carry 56 % of bytes, and 17 % of all Sol bytes come from the single line-vs-bytes bug in R2. Fix it because it is one line and it stops 687 kB context spikes, not because it saves credits.

**The one-sentence version:** we are not paying for fat outputs, we are paying ~$0.09 a time, 27 times a turn.

**STOP — gate reached.** No prompt or tool changes made. Awaiting approval before touching `base.md` (R1/R2/R4), the backend cap (R3), or the telemetry gaps (R6/R7).
