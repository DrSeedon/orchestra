# #378 — audit of the “Pi agent is ~4× cheaper” screenshot

Research only. Date: 2026-08-23. Raw extraction: [`raw-normalized.csv`](raw-normalized.csv).
Source recovery record: [`source-ledger.md`](source-ledger.md).

## Question

- **Context:** a forwarded screenshot reports score, dollar cost, and `requests` or `calls†` for
  Pi, Cline, Hermes Agent, Claude Code, Codex, and two Ouroboros runs on four cells labelled
  `Three-body GPT`, `Three-body Kimi`, `Heat-2D GPT`, and `Heat-2D Kimi` [1].
- **Change under test:** the claim that Pi's scaffold makes the agent “about four times cheaper.”
- **Baseline:** a matched harness comparison: exact model/snapshot, effort, task checkout/prompt,
  acceptance oracle, retry/stop budget, cache state, and tool capabilities held fixed; only the
  scaffold changes.
- **Outcome:** first require equal acceptance quality, then compare provider-attributable input,
  cached/cache-write, visible output, reasoning tokens, model calls, retries, compactions, and
  reconstructed cost. Local transport time is a separate outcome.

## Hypotheses and falsifiers

### H1 — Pi has an approximately 4× matched cost advantage

Pi reduces provider cost by shrinking fixed context/tool schemas and/or by completing the same
accepted task in fewer model turns.

**Falsifier:** the ratio is not near 4 against each named comparator, quality differs, or the
missing model/token/cache/retry fields prevent a matched comparison.

### H2 — “4×” is a Claude-Code-only aggregate, not a universal scaffold result

The phrase summarizes the four Pi-versus-Claude-Code dollar cells, while Cline, Hermes, and Codex
either give different ratios or no computable ratio.

**Falsifier:** normalized per-cell arithmetic shows a stable ≈4× ratio against the other
comparators with matched quality and complete dollar values.

### H3 — the screenshot cannot identify the causal component

Observed dollars combine model pricing, effort, prompt/history, tool schemas, cache, output and
reasoning, number of turns, retries, compaction, and possibly different accounting surfaces. A
three-column summary cannot attribute the remainder to “scaffold overhead.”

**Falsifier:** raw logs expose all components and a controlled ablation changes one component at a
time while holding acceptance fixed.

## Short answer

**The universal claim is refuted by the screenshot itself.** “Pi is ~4× cheaper” is a reasonable
loose description only of **Pi versus Claude Code**: the four cell ratios
`Claude cost / Pi cost` are **4.323×, 3.121×, 5.035×, and 3.297×**; their arithmetic mean is
**3.944×**, geometric mean **3.869×**, and ratio of summed dollars **3.571×** [1][2]. Even there,
quality is equal in only two cells. The two equal-score GPT cells are 4.323× and 5.035× (combined
4.692×), but exact model, effort, cache, token mix, retries, and score oracle remain absent.

Against **Cline**, ratios range from **0.168× to 5.398×** and summed dollars give **2.144×**, not
4×. On the two equal-score GPT cells the ratios are **1.765× and 2.962×** (combined **2.385×**).
The 0.168× cell is a cheap `0F` Cline failure versus Pi score 65, so it is not an efficiency win
for Cline or a loss for Pi; it demonstrates why cost without quality is not the target [1][2].

Against **Hermes**, the three populated ratios are **1.976×, 4.217×, 3.180×**; the corresponding
scores differ in every cell and the fourth cell is missing. The sum over the three known costs is
3.649× Pi's corresponding sum, but this is not a quality-matched estimate [1][2].

For **Codex**, every dollar cell is `н/д`. No Pi/Codex cost ratio exists. Codex uses 1.091×–2.000×
the displayed request count and scores higher than Pi in three of four cells, but request count is
not a dollar value and the exact model is not identified [1][2].

The forwarded payload itself contains no link/entity bytes, and the original public PR/log was
**not identifiable from the supplied material and documented searches**. Exact web/GitHub searches
and full PR/issue metadata/comment searches in the plausible public Ouroboros repository found no
matching table or trajectory [3]. A public unindexed/deleted artifact may still exist; no link or
PR number is invented.

## Findings

### F1 — “4× versus all” is arithmetically false

| Comparator | Per-cell comparator/Pi cost ratio | Aggregate over comparable populated cells | Quality limitation |
|---|---|---:|---|
| Claude Code | 4.323, 3.121, 5.035, 3.297 | 3.571× by summed dollars | scores equal only in cells 1 and 3 |
| Cline | 1.765, 0.168, 2.962, 5.398 | 2.144× | cells 2 and 4 have different scores; cell 2 is `0F` |
| Hermes Agent | 1.976, 4.217, 3.180, missing | 3.649× over first three only | no populated cell has equal score |
| Codex | not computable | not computable | all dollar values missing |

**Confidence: CONFIRMED** — direct arithmetic from all screenshot cells, reproduced in the CSV.
This confirms what the image says, not the provenance of its values [1][2].

### F2 — request count does not explain the dollar ratio

Across all four cells, Pi shows `$2.379 / 75 = $0.03172` per displayed request and Claude Code
`$8.496 / 148 = $0.05741`. Claude Code has **1.973×** as many requests but **3.571×** the dollars;
the remaining factor is **1.810× dollars per displayed request**. Cline has fewer displayed
requests than Pi (**61 vs 75, 0.813×**) but **2.144×** the dollars, hence **2.636× dollars per
request** on this aggregate [2].

These derived values are diagnostic, not unit economics: `request` is undefined, Ouroboros uses
`calls†` with a missing footnote, and cost per request bundles prompt/history size, cache, output,
reasoning, model price, and failures. They do establish that “Pi used fewer turns” is not a
complete explanation and is false as a count explanation against Cline.

**Confidence: CONFIRMED arithmetic; causal interpretation UNCERTAIN** — count semantics and raw
usage are absent [1][2].

### F3 — model, effort, task, and quality are not normalized

- `GPT` and `Kimi` are labels, not exact model ids or snapshots. The image does not show provider,
  service tier, temperature, context window, or pricing date.
- No effort/reasoning setting appears. The current Orchestra route sends `gpt-5.6-sol` at `xhigh`
  and `gpt-5.6-luna` at `high`; #374 proves that delivery but also finds no representative
  long-horizon Sol effort sweep [6]. Therefore an unnamed GPT/Kimi result cannot be transferred to
  Sol, especially not to Sol/xhigh.
- Task repository, base SHA, prompt bytes, timeout, stop rule, and acceptance command are absent.
- The score rubric is absent. The CSV preserves raw scores and only labels higher/equal/lower; it
  does not assume equal semantic difficulty. The `k=5` Ouroboros score is explicitly aggregate
  (`4/5` or `5/5`) while the other rows look like single-cell scores, so those rows are not the
  same statistical unit.

**Confidence: CONFIRMED absence; exact run configuration UNKNOWN** [1][2][3][6].

### F4 — cache and token normalization are impossible from the screenshot

The OpenAI Responses contract exposes input tokens, cached/cache-write details, output tokens, and
reasoning-token details separately [5]. None appears in the screenshot. #375 also establishes that
on the Codex/OpenAI surface cached tokens are included in input-token accounting, so a
same-named `input_tokens` field from another provider cannot be divided blindly [7].

A valid cost reconstruction must use mutually exclusive provider billing buckets and the same
rate card for the exact model/date. It must not infer subscription-pool usage from API-equivalent
dollars or a shared integer quota counter; #374/#376 found that per-run quota attribution was not
available at that resolution [6][8].

**Confidence: CONFIRMED normalization gap** — primary API schema plus current local measurements;
the screenshot contains none of the required fields [1][5][6][7][8].

### F5 — current Pi is small by default, not invariantly small

At current Pi commit `a69bef7` (package 0.84.2), the default coding harness creates four tools:
`read`, `bash`, `edit`, and `write`. Its system-prompt builder is compact, but it also appends
project context files, loaded skill metadata, optional custom tools, and optional appended prompt
text [4]. The actual initial prompt and schema are therefore run-dependent. Current Pi defaults
also allow three agent-level transient retries and LLM-based compaction at
`contextWindow − 16,384` tokens [4].

These facts describe the current public implementation only. They do **not** establish which Pi
version, resources, retries, or compaction settings produced the screenshot.

**Confidence: CONFIRMED for current source; screenshot applicability UNCERTAIN** [3][4].

## Scaffold-overhead decomposition

For model turn `i`, provider cost is a function of the exact model/rate card and mutually exclusive
usage buckets. Model-visible input can be decomposed conceptually as:

`input_i = fixed prompt + project/context files + tool schemas + retained history + tool results + current user input`

The task total is the sum over normal turns, retry turns, and compaction/summary turns. The
screenshot exposes only the final total and a count with undefined semantics, so the following
components remain a decomposition plan rather than measured shares:

1. **Initial prompt/context.** Measure bytes and provider token count of system/developer text,
   project instructions, skills, and task prompt before the first model call. Fixed context is
   transmitted again on later calls; cache may discount price but does not make tokens disappear.
2. **Tool schema.** Capture the exact serialized tool array and its token count/fingerprint. Tool
   names alone are insufficient: descriptions, JSON Schema, deferred loading, and MCP wrapper
   metadata can dominate the fixed prefix. A fair mechanism test exposes semantically equivalent
   tools.
3. **Model-turn count.** Count provider assistant-producing calls, not shell invocations, UI
   events, or tool calls. Also record tool-call count separately. The screenshot's `requests` and
   `calls†` cannot be assumed equivalent.
4. **Retry/loop strategy.** Count transient provider retries, context-overflow recovery, invalid
   tool-call correction, verifier retries, and stop/budget exits. Include all paid attempts in
   cost even when the final score is zero. Pi's current three-retry default is a hypothesis about
   an unmatched run, not a value to impute.
5. **Compaction.** Record trigger, summary model/call, tokens before/after, retained tail, cache
   destruction, and any post-compact rework. Current Pi uses a separate summary call; current
   Orchestra Codex uses native same-thread compact with fidelity risks described by #377 [4][9].
6. **Transport/lifecycle.** Separate process startup, JSON-RPC/stdio, queueing, tool time, model
   wait, and post-processing. #376 observed roughly 2–3 seconds of warm local lifecycle avoided by
   a retained app-server on one tool-free fixture, but its cache invariant failed and it issued no
   path verdict. Local lifecycle time does not explain a 4× provider-dollar ratio unless it changes
   model calls, context, cache, or retry behavior [8].

**Finding:** no component can be assigned a percentage of the screenshot's dollar gap. The only
measured decomposition is count versus average dollars per displayed count, and even that count's
semantics are incomplete.

**Confidence: CONFIRMED as an identifiability limit** [1][2][4][5][6][7][8][9].

## Smallest reproducible Orchestra benchmark

This is a **mechanism pilot**, not a policy-validating study. It compares Pi with an isolated
Orchestra Codex path on exact `gpt-5.6-sol`; it does not reuse the screenshot's unnamed `GPT` result.

### Frozen unit

1. Prepare one tiny repository-level bug at a public base SHA in a clean clone made with
   `--no-local`. The solution must require at least one read, edit, and test command but stay far
   below compaction. Keep the known-good patch outside both workspaces.
2. Freeze one byte-identical task prompt and one hidden behavioral oracle before any run. The
   evaluator proves **RED on base** and **GREEN on known-good**. Agents cannot read the hidden test
   or expected output.
3. Acceptance is binary: the exact hidden command exits 0. A cheaper failed run never beats an
   accepted run. File-diff constraints and timeout are identical.

### Matched controls

- Exact model alias: `gpt-5.6-sol` on ChatGPT subscription auth for both surfaces; record the
  response/turn model actually reported. Do not substitute a newer alias.
- Exact effort: one predeclared value on both arms (recommended `xhigh` to match current Orchestra
  Sol delivery from #374). No adaptive effort escalation.
- Same task checkout, prompt bytes, cwd shape, time limit, maximum model turns, and no foreign
  account traffic during the run window when possible.
- Mechanism tool surface: only four equivalent operations (`read`, `bash`, `edit`, `write`). Save
  the exact serialized schema and SHA-256 for each arm. If semantic/schema equivalence cannot be
  achieved, classify tool schema as part of the treatment rather than “normalized.”
- Disable extensions, project instructions, skills, web, subagents, automatic provider retries,
  and compaction. Compaction must remain zero by fixture design. Agent-level retry is zero. This
  isolates fixed scaffold, schemas, loop decisions, and transport.
- Fresh native thread and fresh checkout per run. Capture cache-read/write fields; a cache mismatch
  invalidates a cold-cost verdict unless the provider exposes a supported cache-neutral control.

### Smallest run schedule and stop rule

Run **four task executions strictly sequentially** in a frozen balanced order, for example
`Pi → Orchestra → Orchestra → Pi`. This gives two observations per arm and only a crude within-arm
noise observation. Print load and memory before every run. No extra cell is added after seeing the
oracle.

For every model turn, preserve raw event/usage records and calculate:

- acceptance and final diff hash;
- model calls, tool calls, retry/compaction counts;
- input, cached input, cache write, visible output, reasoning tokens;
- fixed prompt/context bytes and tokens; tool-schema bytes/tokens/hash; tool-result bytes;
- provider-token reconstructed dollars using one dated rate card;
- client/process, queue, model wait, tool, post-processing, and total wall separately.

Fail-closed validity rule: both arms must pass both repetitions; exact model, effort, task bytes,
oracle command, schemas, and configured budgets must agree; every run must report
`provider_retries == 0`, `agent_retries == 0`, `compactions == 0`, and
`model_calls <= preregistered_max_turns`; no timeout/budget overrun is accepted. The
preregistered cache control must also pass. Any violation yields `no scaffold ratio`, with the
failed invariant named.

Exploratory estimator: report the two adjacent paired cost ratios (`Orchestra₁/Pi₁` and
`Orchestra₂/Pi₂`), the arm medians, and each arm's min–max spread. With only two observations per
arm there is no defensible population-noise threshold: even same-sign paired ratios are a
**candidate effect requiring confirmation**, not an established scaffold effect. A confirmatory
study must be preregistered after this pilot with a noise-derived threshold, more balanced repeats,
and at least one additional task class. The four-run pilot cannot validate a global “4×” policy.

### Why no provider run was launched in #378

The missing source logs prevent reconstructing the screenshot's task, model, effort, oracle,
schemas, and cache state. A new call today would answer a new benchmark, not audit those cells.
Launching it before freezing the fixture and controls would violate the matched-run requirement
and could not justify transfer to Sol. Therefore #378 stops at the reproducible design and spends
no provider calls.

## Counter-evidence and limitations

- The Claude-Code ratios really do cluster around four. This argues against saying the screenshot
  is fabricated; it supports only a narrow comparator-specific summary.
- Two equal-score Claude cells show a 4.69× aggregate gap. This is the strongest image-internal
  evidence for a real efficiency difference, but score equality does not establish the same model,
  effort, retry budget, or token accounting.
- Cline's Heat-2D Kimi cell has a higher score and 5.398× cost; a product-default comparison might
  rationally pay more for that quality. Cline's Three-body Kimi cell is cheaper because it is `0F`.
  Both directions defeat cost-only ranking.
- Hermes is cheaper than Claude Code in some cells and more expensive than Pi, but all populated
  Pi/Hermes scores differ. No quality-matched Hermes ratio exists.
- Codex has higher raw score on three cells but no dollars. Any statement that Pi is cheaper than
  Codex would be invented.
- `cost_usd` may be provider-billed, API-equivalent, or reconstructed; the screenshot does not say.
- Public-source search can prove that no matching indexed artifact was found, not that no public
  artifact ever existed. Deleted/unindexed attachments and lost forward links remain possible.

## Confidence summary

- **CONFIRMED:** screenshot transcription; per-cell/aggregate arithmetic; “4× versus all” is
  false; no Codex cost ratio; count alone does not explain the dollar totals.
- **CONFIRMED absence / UNKNOWN value:** exact models, effort, token/cache/retry/schema fields,
  task/score oracle, request/call footnote, and source links.
- **CONFIRMED current mechanics, screenshot applicability UNCERTAIN:** Pi defaults and
  Orchestra/Codex behavior from #374–#377.
- **UNCERTAIN:** any causal share attributed to prompt, schemas, turns, retry, compaction, or
  transport; any claim about Sol without the designed matched run.
- **REFUTED:** “Pi is approximately four times cheaper than Claude Code, Cline, Hermes, and Codex
  on this table.”

## Affected files, risks, and edge cases

Research-only. No code, config, deployment, auth, provider call, or production session changed.

- Artifacts: `docs/tasks/378/research.md`, `source-ledger.md`, `raw-normalized.csv`, and the selected
  review artifact.
- The `k=5` per-run cost/count normalization is arithmetic division by five, not proof that all five
  runs used equal budgets or that aggregate success percent is comparable with single-run scores.
- A future benchmark must keep its hidden oracle outside the agent-visible Git object store; a
  worktree sharing the answer commit is contaminated even when checked out at an older branch.
- Subscription quota deltas remain shared-account measurements unless an exclusive window and
  sufficient meter resolution are proven.

## Sources

1. Supplied screenshot, SHA-256 and metadata in `source-ledger.md` (single secondary artifact).
2. `docs/tasks/378/raw-normalized.csv` — mechanical transcription and per-run/per-Pi arithmetic;
   its intentionally bounded per-cell schema and the dataset-wide unknown fields are defined in
   `source-ledger.md`.
3. `docs/tasks/378/source-ledger.md` — exact source-recovery queries and negative results.
4. Current Pi primary source/docs at commit `a69bef7`: system-prompt builder, harness constructor,
   compaction, and retry settings; exact fetched links are in the ledger.
5. Official OpenAI Responses API reference opened 2026-08-23; exact link in the ledger.
6. `docs/tasks/374/research.md` + `codex-review-research.md` — effort provenance and comparison gap.
7. `docs/tasks/375/research.md` + review — context/cache telemetry semantics and limits.
8. `docs/tasks/376/research.md`, protocol/raw artifacts + review — persistent/exec decomposition
   and cache-invalid causal verdict.
9. `docs/tasks/377/research.md` + review — current app-server, compact, and lifecycle evidence.
10. `docs/tasks/378/review-research.md` — two-round targeted Sol falsification and final verdict.

## Review gate inputs

- **Artifact/consumer:** this research report, CSV, and source ledger; consumed by the task owner
  deciding whether a matched benchmark is warranted. No executable consumer changed.
- **Author runtime/model:** live session metadata at finalization reports `gpt-5.6-sol`, runtime
  `codex`, role `full-cycle`; the API returned no effort value, so author effort is not inferred.
- **AC:** recover original source or explicitly prove the recovery limit; transcribe every cell;
  normalize every requested field or mark it unknown; separate Claude/Cline/Hermes/Codex ratios;
  decompose all six overhead components without causal invention; do not transfer to Sol; reuse
  #374–#377; design the smallest sequential matched benchmark; no provider/code/config/deploy work.
- **Mechanical checks:** rectangular 24-column/28-row CSV; explicit missing/unknown semantics in
  the ledger; recomputed comparator ratios and totals; exact-query ledger; `git diff --check`;
  source URL list opened this session.
- **Review route:** targeted fresh Sol falsification under `codex-debate`, because this is a
  causal/statistical research conclusion with no strong deterministic oracle. The reviewer is
  asked to falsify the arithmetic, source-recovery boundary, missing-field calibration,
  decomposition, and benchmark controls.

## Independent review outcome

- Route: targeted fresh Sol (`gpt-5.6-sol`) in one persistent review thread; author and reviewer
  use the same runtime/model family, so this is a fresh adversarial second opinion, not cross-family
  independence.
- Round 1: arithmetic, comparator separation, no causal-share invention, and no transfer to Sol
  were confirmed. Two blockers were accepted: the four-run pilot lacked a defensible noise/effect
  rule, and its validity gate did not fail closed on retries/compaction/turn budgets. Two
  suggestions were also accepted: make missing-value/CSV scope explicit and narrow the source
  recovery wording.
- Artifact changes: the pilot now reports only a candidate effect at `n=2`; all retry, compaction,
  turn-cap, timeout, budget, cache, schema, model, effort, task, and oracle mismatches invalidate a
  ratio; CSV blanks are explicit; and source recovery is limited to the supplied material and
  documented searches.
- Round 2 (final prose round): **APPROVED — all four prior findings fixed, no new findings** [10].
  Completed-verdict evidence was verified in this file: “The four-run pilot cannot validate a
  global “4×” policy.”

## Knowledge-base note

The user explicitly limited writes to `docs/tasks/378/` and personal memory. Therefore the normal
Phase-1 `docs/kb/` append is intentionally not performed.
