# Research — Agent Self-Analysis / Self-Reflection skill for Orchestra

> **Question:** How should Orchestra build a *self-analysis* mechanism where an agent, after a task/session,
> does a **deep** review — root-cause of mistakes, patterns of inefficiency, prompt-architecture proposals —
> with authority to edit CLAUDE.md, pipeline prompts, modules, roles, skills? Distinct from the existing
> reactive `self-improvement.md` (📝 RULE on user correction).
>
> **Scope of this doc:** Phase-1 research only (truth + prior art + our own measured data). No implementation.
> Approval gate after this. Sources inline `[n]`, listed at bottom. Confidence tags per finding.

---

## TL;DR (the truth, up front)

1. **Intrinsic self-critique of *reasoning* does NOT work** — asking an LLM "review your own answer, is it
   wrong?" with no external signal **degrades** performance (Huang 2024 [4], Tyen 2024 [5]). This is CONFIRMED
   and it kills the naïve "agent, reflect on your mistakes" design. The model can't reliably *find* its own
   errors; it *can* fix them once the error location is given.
2. **Self-reflection WITH an external signal WORKS** — Reflexion [1] and CRITIC [3] both get large gains, but
   *only* because they feed a real signal (test pass/fail, tool output, execution error) into the reflection.
   The lesson for Orchestra: **anchor every self-analysis to hard artifacts** — Codex verdicts, test results,
   tool-call counts, retries, corrections — never to the agent's unaided opinion of its own work.
3. **Accumulated memory becomes noise on long-horizon coding tasks** — episodic/retrospective memory that
   helps on short benchmarks (HumanEval) *fails to transfer* and can degrade full SWE-bench performance
   ("From Knowledge to Noise" [7]). This means: **store distilled, generalizable strategies, not raw
   trajectories or a growing pile of one-off rules** (ReasoningBank [8]). Curation/forgetting is mandatory,
   not optional [9].
4. **Nobody in industry trusts fully-automatic rule extraction into durable config** — Anthropic, Windsurf,
   Cursor, Devin all keep a **two-layer** design (agent writes a working/auto layer silently → human promotes
   to durable rules). Auto-writing into CLAUDE.md without review is done by *no one* [prior art, #85 doc].
5. **Our own measured data (#85):** a Haiku extractor is 100% correct *on genuine corrections* but the
   *detection* gate is the bottleneck (regex precision 0.42; the model fabricates rules on non-corrections
   because it has no "this isn't feedback" defense). Confidence scores are useless as a filter.

**Bottom line recommendation:** build self-analysis as a **structured, artifact-grounded retrospective skill**
(triggered at end of task/session), NOT another always-on prompt instruction. It writes a **proposal report**
(a diff of suggested changes + root-cause reasoning), never auto-edits durable files. A **two-tier scope**
governs autonomy: agent auto-writes to its own memory layer; edits to shared prompts/CLAUDE.md/pipeline.yaml
require human approval. Pattern-detection runs over *history* (past retro reports), not live context.

---

## 1. Scientific approaches — what works, what doesn't, why

### 1.1 Reflexion (Shinn 2023) — verbal RL via episodic memory [1]
- **Mechanism:** three roles — Actor (does the task), Evaluator (scores output), Self-Reflection (writes an NL
  post-mortem). After a *failed* attempt, the self-critique is prepended to context on the next attempt. No
  weight updates — learning lives entirely in the context/memory buffer.
- **Result:** 91% pass@1 on HumanEval vs GPT-4's 80%. Strong on decision-making, coding, reasoning.
- **The critical detail everyone skips:** Reflexion works because the **Evaluator has a real signal** — unit
  tests, environment reward, exact-match. The reflection is anchored to *"the tests failed here,"* not to
  *"do I feel this is wrong."* Remove the external signal and it collapses into intrinsic self-correction (§1.4).
- **Relevance to us:** the Actor/Evaluator/Reflection split maps cleanly onto Orchestra: worker = Actor,
  **Codex review + pytest = Evaluator**, self-analysis skill = Reflection. We already have the Evaluator layer
  the science says is mandatory. **Confidence: CONFIRMED** (NeurIPS 2023, code + logs public).

### 1.2 Self-Refine (Madaan 2023) — iterative self-feedback [2]
- **Mechanism:** one LLM generates → critiques its own output → refines, looped. No external tools.
- **Result:** ~20% avg gain across 7 tasks, +13% on code — **but only with strong models** (GPT-4). Weak
  models (Vicuna-13b) barely moved.
- **Documented limitations (important for us):**
  - **Self-bias** — the model favors its own output when it is also the critic (Xu 2024, cited in [2]).
  - **Feedback ceiling** — improvement is bounded by what the model can *recognize* as an error. If it can't
    see the bug, refinement does nothing.
  - **Task-dependence** — helps on generation/style tasks, much weaker on hard reasoning.
- **Relevance:** self-critique of *style/structure/clarity* (e.g. "was my report too verbose", "did I narrate
  tool calls") is the sweet spot — these are recognizable surface patterns. Self-critique of *whether the code
  is correct* is NOT (that's what Codex/tests are for). **Confidence: CONFIRMED**, with the self-bias caveat.

### 1.3 CRITIC (Gou 2023) — tool-interactive critiquing [3]
- **Mechanism:** verify-then-correct loop using **external tools** — search API for facts, Python interpreter
  for code/math, toxicity classifier. ~3 correction iterations.
- **Central finding (stated by the authors):** *LLMs alone cannot reliably critique/correct their own work;
  external tool feedback is necessary.* This is the empirical backbone for "anchor to artifacts."
- **Relevance:** directly validates using **Codex CLI + pytest + git diff** as the "tools" that make our
  agent's self-analysis trustworthy. **Confidence: CONFIRMED** (ICLR 2024, ~500 citations).

### 1.4 The counter-evidence — "LLMs Cannot Self-Correct Reasoning Yet" (Huang 2024) [4]
- **Definition:** *intrinsic* self-correction = model revises using only its own judgment, no ground-truth,
  no tools.
- **Finding:** intrinsic self-correction **consistently degrades** reasoning-benchmark performance. Prior
  "self-correction works" papers were often **oracle-guided** — they used ground-truth labels to decide *when
  to stop* correcting, so the model only ever "corrected" already-wrong answers. Strip the oracle and gains vanish.
- **Why this matters enormously for our design:** a skill that says *"agent, look back and find your mistakes"*
  with no signal is **exactly the setup Huang shows makes things worse.** We must not build that.
- **Confidence: CONFIRMED** (ICLR 2024, Google DeepMind). This is the single most important constraint on the design.

### 1.5 Tyen 2024 — "cannot find errors, CAN correct given location" [5]
- **Finding:** poor self-correction stems from **inability to *find* the mistake**, not inability to fix it.
  Given the error *location*, correction is robust and improves downstream accuracy across 5 tasks.
- **Design implication (this is the key operational insight):** self-analysis should **not** ask the agent to
  *discover* what went wrong from a blank slate. It should **hand the agent the error locations** — i.e. the
  concrete failure artifacts: "Codex flagged X", "you retried this bash 5×", "the user re-sent the task after
  your first attempt", "3 tests failed here". Then the agent's job is the thing it's *good* at: explain root
  cause + propose fix. **Confidence: CONFIRMED** (ACL Findings 2024).

### 1.6 Constitutional AI / self-critique-against-principles
- CAI-style self-critique works when the model critiques against an **explicit written principle**
  ("did I violate rule X?") rather than open-ended "is this good?". This is a bounded, recognizable check —
  same category that Self-Refine succeeds on. **Relevance:** self-analysis should check the agent's behavior
  against the **explicit rules already in our prompts** (brevity, surgical changes, delegate-don't-DIY,
  fail-loud) — a checklist, not a vibe. **Confidence: LIKELY** (well-established pattern; not benchmarked here).

### Synthesis of the science
| Approach | Works? | Precondition |
|---|---|---|
| Intrinsic reasoning self-correction | ❌ degrades | none — avoid entirely |
| Reflexion (reflect on test/env failure) | ✅ big gains | **external signal** (tests/reward) |
| CRITIC (tool-verified critique) | ✅ | **external tools** (interpreter/search) |
| Self-Refine (style/structure) | ✅ moderate | strong model; surface-recognizable errors |
| Correct-given-location (Tyen) | ✅ robust | **error location supplied** |
| Self-critique vs explicit principle (CAI) | ✅ | written checklist to check against |

**The through-line:** self-analysis is reliable **iff** it is anchored to (a) an external verdict, (b) a
concrete error location, or (c) an explicit written rule. Unanchored introspection is worse than nothing.

---

## 2. Industry — how Devin, Cursor, Windsurf, Anthropic do it

(Detailed prior-art table lives in `docs/tasks/85/approach-comparison.md`; summary here, with the
self-analysis-specific angle.)

- **Anthropic Claude Code — Auto memory + "Dreaming":** agent-decided (prompt, not hook) writes learnings to a
  markdown auto-layer; **human promotes** to CLAUDE.md. *Dreaming* (research preview, 2026) is the closest
  thing to our target: a **scheduled offline process** that reviews up to ~100 past sessions, extracts
  patterns, merges duplicates, deletes stale entries, writes "playbooks." Crucially it is **memory curation,
  not weight updates**, and it runs **over history, not live context** — exactly the pattern-detection layer
  we want. Their own docs admit prompt-memory has *"no guarantee of strict compliance"* → don't rely on a
  prompt instruction alone for enforcement.
- **Windsurf/Cascade:** auto-generates working memories during a session; **promotes** to durable
  `.windsurfrules`. Explicitly names the maintenance problem (memories go stale/conflict → need cleanup).
- **Cursor:** persistent memories + manual rules; **auto-generation of rules from feedback is labeled an
  emerging trend, NOT shipped** — even Cursor doesn't trust full auto-extraction yet. Bugbot "learns from PR
  feedback over time."
- **Devin (Cognition):** Knowledge Base items + Playbooks distilled from *successful* sessions; **codifying
  feedback is manual and recommended as such** ("pick 3 things your team always corrects, write a knowledge
  item for each"). Has explicit **session analysis** — "understand why a session succeeded/failed, extract
  learnings, dedup" — an on-demand analog of Dreaming.

**Three industry facts that constrain our design:**
1. **Two layers, universally:** working/auto layer (agent writes) → durable layer (human promotes). Nobody
   auto-writes durable rules.
2. **Detection is agent-decided via prompt**, not a separate detector pipeline — but paired with review.
3. **Deep pattern extraction runs offline over history** (Dreaming, Devin session analysis), not inline.

**Confidence: CONFIRMED** (multiple primary vendor docs, cross-checked; see #85 doc sources).

---

## 3. The academic warning we must obey — memory → noise [7][8][9]

- **"From Knowledge to Noise" (CTIM-Rover, 2025) [7]:** episodic memory that boosts short-horizon benchmarks
  (HumanEval) **fails to transfer and can degrade full SWE-bench.** Raw retrospective trajectories become
  distractors on long, realistic tasks.
- **ReasoningBank (2025) [8]:** the fix — **store distilled, generalizable reasoning strategies**, not raw
  trajectories or only-successful routines. Learn from *failures* too. Retrieve by relevance, integrate back.
  Up to +34% success / −16% steps when paired with memory-aware test-time scaling.
- **Context rot / memory bloat [9]:** more rules/context measurably *degrades* attention and output; errors
  compound because each response feeds the next. Consensus fix: **distill → consolidate → forget** (prune
  stale/duplicate). Anthropic ships context-editing + a `/memories` tool for exactly this.

**Implication for Orchestra:** our prompts are *already* large (base.md + role + N modules + CLAUDE.md session
notes that grow every session). A self-analysis skill that mints a new rule per task will **accelerate context
rot** and make agents *worse*. So the skill's output must be **distilled and consolidating** (merge/replace,
not append), and a **pruning pass** is a first-class feature, not a "later." **Confidence: CONFIRMED.**

---

## 4. Analysis of the current `self-improvement.md` — weak spots

Current module (29 lines, in `modules/`, loaded by all 4 roles). What it does: on user correction → propose
one `📝 RULE` → wait for approval. What it **lacks**, mapped to the task's asks:

| Gap | Current state | Why it matters (evidence) |
|---|---|---|
| **Reactive only** | Fires *only* on explicit user correction ("no", "redo", rephrase). | Misses silent inefficiency: 20 tool calls where 5 suffice, retries, wrong-approach-then-abandon. Reflexion/Dreaming learn from *failure signals*, not just corrections. |
| **No root-cause** | Output is a surface rule ("do Y not Z"). | Task wants *root cause* ("I re-read the file 4× because the grep hint was missing → fix the prompt's grep guidance"). Tyen [5]: agent is good at this *given the location*. |
| **No metrics** | Zero measurement. | Can't detect inefficiency without tool-call count, retry count, turn count, Codex/test verdicts. CRITIC [3]/Reflexion [1] need the signal. |
| **No pattern detection** | Single-shot, single-session. | "I keep forgetting to run tests before commit" is invisible — needs aggregation across N tasks (Dreaming [Anthropic], Devin session analysis). |
| **No architectural proposals** | Rule only. | Task wants "restructure prompt X because Y" — e.g. "move rule to role file", "this module contradicts that one". Nothing enables prompt-level edits. |
| **Anchoring** | Anchored to correction (good) but not to artifacts. | Fine as-is; the *new* skill must anchor to Codex/tests/metrics to avoid intrinsic-correction failure [4]. |
| **Bloat risk** | "One correction = one rule", append forever. | No consolidation/forgetting → context rot [9]. |

**Verdict:** `self-improvement.md` is correct *for what it is* (a cheap reactive correction-capture, validated
by #85's 100%-on-genuine-corrections result). **Keep it.** It is NOT the deep-analysis mechanism the task
describes. The new skill is a **different, complementary layer** — proactive, artifact-grounded, cross-session.
Don't merge them; the reactive one is per-turn, the analytic one is per-task/session.

---

## 5. Architecture of the new self-analysis skill

### 5.1 Core design principles (derived from §1–§4)
1. **Anchor to artifacts, never to unaided opinion** [1][3][4]. Inputs = Codex verdict, pytest result, git
   diff stats, tool-call count, retry count, user corrections, turn count. No "do you think you did well?"
2. **Hand the agent error *locations*, don't ask it to hunt** [5]. The skill *collects* the failure signals,
   then the agent explains + proposes. This is the split that makes it work.
3. **Propose, never auto-apply to durable files** [prior art, all vendors]. Output is a diff/report.
4. **Two-tier autonomy scope** (§5.4). Own memory = auto. Shared prompts = approval.
5. **Distill + consolidate + prune, don't append** [7][8][9]. Merge into existing notes; kill stale.
6. **Run deep pattern-detection over *history*, not live context** [Anthropic Dreaming]. A separate,
   lower-frequency pass reads past retro reports.
7. **Check against explicit written rules** [CAI], not open-ended quality. The prompts already contain the
   checklist (brevity, surgical, delegate, fail-loud, test-before-commit).

### 5.2 Two mechanisms, clearly separated

**Mechanism A — Per-task Retrospective (the skill).** Fires at end of a substantial task (gate below).
Reads the task's own artifacts, produces a structured **retro report** in `docs/tasks/<id>/retro.md`.
Cheap, local, always safe (it's just a file).

**Mechanism B — Cross-session Pattern Pass (offline, opt-in).** Analog of Dreaming. Reads the last N
`retro.md` files + worker memory, finds **recurring** root causes ("3 tasks in a row I forgot X"), and only
*then* proposes durable prompt/CLAUDE.md edits. Runs on demand or via a scheduled `bg_create(type=cron)`.
This is where architectural proposals come from — a single task is never enough evidence to restructure a prompt.

> Rationale for the split: a per-task rule from n=1 is the exact overfitting that turns memory into noise [7].
> Architectural changes need a *pattern*, which by definition needs history → Mechanism B.

### 5.3 Trigger gates (deterministic — no "agent decides when")
Per Orchestra's determinism principle, triggers are explicit, not vibes:

**Mechanism A triggers (any one):**
- Task touched ≥5 files **or** ≥10 tool calls (matches existing CLAUDE.md reflection threshold).
- Codex review returned CRITICAL/HIGH, **or** a test run failed at any point.
- The user corrected/rephrased mid-task (the `self-improvement` signal also fired).
- A bash/tool command was retried ≥3×.
- Explicit invocation: `/self-analysis` or orchestrator says "do a retro."

**Mechanism B triggers:**
- Explicit `/self-analysis --patterns` **or** scheduled cron (e.g. weekly).
- ≥N (say 5) new `retro.md` files since last pattern pass.

### 5.4 Scope of edits — what's autonomous vs gated
This directly answers the task's "boundaries" question. Two tiers:

**Tier 1 — Autonomous (agent writes directly, no approval):**
- `docs/tasks/<id>/retro.md` — the retro report itself.
- Worker's own persistent memory `docs/workers/<name>.md` (already auto-injected on spawn — safe, scoped,
  affects only that worker). This is the "auto layer" every vendor has.

**Tier 2 — Proposal only (write a diff, require human/orchestrator approval before applying):**
- `CLAUDE.md` (project) — session notes append is lower-risk but still review; **rule/process edits = approval**.
- `pipelines/default/prompts/**` — base.md, modules/, roles/, skills/. **Always approval.** These change
  *every* agent's behavior; an overfit edit here is a fleet-wide regression.
- `pipeline.yaml` — model/skill/module assignments. **Always approval** (structural).

**Why this boundary:** blast radius. A worker-memory edit affects one disposable worker. A `base.md` edit
affects every agent in every project. The science says a single task's evidence is too weak to justify the
latter [4][7]. Tier-2 edits should therefore come almost exclusively from **Mechanism B** (pattern-backed),
not a single retro.

> **Safety rules for any write** (from OpenClaw/vendor best practice): append/merge — never blind overwrite;
> no secrets; keep entries short (distilled, not raw logs); every Tier-2 proposal shows a real diff so the
> reviewer sees exactly what changes.

### 5.5 Where it lives
A **skill** (`pipelines/default/prompts/skills/self-analysis.md`) invoked at the gate, **not** an always-on
module. Reason: always-on modules bloat every turn's context [9]; a skill loads only when triggered. Attach to
`full-cycle` and `worker` roles (the ones that produce code artifacts). Orchestrators get Mechanism B (they
already own CLAUDE.md session notes and run the fleet).

---

## 6. Output format

Two outputs, matching the two mechanisms.

### 6.1 Per-task retro report (`docs/tasks/<id>/retro.md`)
Structured, artifact-grounded, root-cause-first. Template:

```markdown
# Retro — <task-id> (<short title>)

## Metrics (auto-collected, not opinion)
- Tool calls: 34  | Retries: 2 (bash grep ×3)  | Turns: 6
- Files touched: 7 (+210 / −45)
- Codex: 1 HIGH (fixed), 2 LOW  | Tests: 3 failed → green after fix
- User corrections this task: 1 (rephrased scope after first attempt)

## What went wrong (error locations → root cause)
Anchored to a concrete signal each. No signal ⇒ no entry.
- **Signal:** re-ran `grep` 4× before finding the symbol.
  **Root cause:** started editing before mapping the call graph.
  **Category:** process.
- **Signal:** Codex HIGH — missing null check on empty list.
  **Root cause:** skipped edge-case pass (CLAUDE.md rule) under time pressure.
  **Category:** correctness / rule-violation.

## What went well (keep doing)
- Codex review caught the null bug pre-commit → the Evaluator layer worked.

## Proposed changes (Tier-2 → NOT applied, awaiting approval)
| Target | Change | Evidence | Confidence |
|---|---|---|---|
| roles/worker.md | Add "map call graph before editing (grep refs, not strings)" | this task + [see if recurs] | n=1, weak |
_(n=1 items are logged, not promoted — promotion needs Mechanism B.)_

## Written to worker memory (Tier-1, applied)
- docs/workers/<name>.md: "For symbol lookup use serena find_symbol, not raw grep loop."
```

### 6.2 Cross-session pattern report (`docs/self-analysis/patterns-<date>.md`)
Only this one proposes durable prompt/CLAUDE.md edits, because only this one has a *pattern*.

```markdown
# Pattern pass — 2026-07-07 (last 8 retros)

## Recurring root causes (≥3 occurrences)
1. **"Edited before mapping" — 4/8 tasks.** Root cause: no explicit "orient before edit" step.
   → PROPOSE: add one line to roles/worker.md. [diff below]
2. **"Forgot to run tests before commit" — 3/8.** → PROPOSE: strengthen git-workflow.md pre-commit gate.

## Consolidation / pruning (context-rot control)
- worker.md already says "surgical changes" 2× (base + role) → dedupe.
- CLAUDE.md session note from 2026-06 about Fable-dead is stale (Fable restored) → delete.

## Proposed diffs (approval required)
```diff
--- a/pipelines/default/prompts/roles/worker.md
+++ b/pipelines/default/prompts/roles/worker.md
@@ Think before coding
+- Orient before editing: map the call graph (find_symbol / grep *refs*), don't edit-then-search.
```
```

### 6.3 Why a report/diff, not a checklist or silent edit
- **Diff** (not silent edit): every vendor requires review for durable changes; a diff is the reviewable unit.
- **Metrics block first** (not prose): forces artifact-anchoring [1][3][4] — if there's no number/verdict, the
  agent can't invent a problem.
- **Root-cause paired with signal**: enforces Tyen's "location → correction" [5]; entries without a signal are
  disallowed by the template, structurally preventing intrinsic-correction hallucination.

---

## 7. Concrete recommendations (ranked)

1. **Build Mechanism A (per-task retro skill) first.** It's a file-writing skill — zero blast radius, matches
   Reflexion's Actor/Evaluator/Reflection with our existing Codex+pytest as Evaluator. Ship, measure whether
   the retros are actually useful on live tasks (same "prove detection cheaply" logic as #85).
2. **Gate it deterministically** (§5.3) — don't make it always-on (context rot) or agent-whim (non-determinism).
3. **Keep `self-improvement.md` as-is** — it's the cheap reactive layer, proven on genuine corrections. The new
   skill is the deep/proactive layer. Two layers, like every vendor.
4. **Enforce Tier-1/Tier-2 scope** (§5.4). Worker memory = auto; shared prompts/CLAUDE.md/pipeline.yaml =
   proposal + approval. This is the safe/unsafe boundary the task asked to define.
5. **Only Mechanism B proposes prompt-architecture edits**, and only from a **pattern (≥3 recurrences)** — n=1
   is logged, never promoted. Prevents memory→noise [7].
6. **Make pruning/consolidation a feature of Mechanism B**, not an afterthought [9]. Every pattern pass also
   dedupes and deletes stale CLAUDE.md/module content.
7. **Do NOT build:** open-ended "reflect on whether you did well" with no artifact — that's the Huang [4]
   failure mode. Every retro entry must cite a signal.

## 8. Risks / counter-evidence / edge cases
- **Overfitting to n=1** → mitigated by Mechanism A/B split + "n=1 logged not promoted."
- **Self-bias** (model favors its own work) [2] → mitigated by anchoring to *external* Codex/test verdicts, not
  self-scoring.
- **Context rot from accumulation** [9] → mitigated by consolidation/pruning as a first-class Mechanism-B step.
- **Determinism erosion** (agent "creatively" self-analyzing) → mitigated by rigid template (metrics-first,
  signal-required) and explicit gates.
- **Cost:** Mechanism A adds one analysis turn per *substantial* task only (gated), reading files it already
  has. Mechanism B is periodic/offline. Cheap relative to a task that already ran 34 tool calls.
- **Counter-evidence to the whole idea:** "From Knowledge to Noise" [7] shows retrospective memory can *hurt*
  long-horizon tasks. We take this seriously — that's *why* durable edits are pattern-gated and human-approved,
  and why storage is distilled strategies, not trajectories [8]. If, on measurement, retros don't reduce repeat
  mistakes, the honest move is to stop at Mechanism A (local reports for the human) and not wire in durable
  auto-edits at all.

## Affected files (for the eventual plan)
- **New:** `pipelines/default/prompts/skills/self-analysis.md` (the skill), `docs/self-analysis/` (pattern reports).
- **Edit (config):** `pipeline.yaml` — attach `self-analysis` skill to `worker`/`full-cycle`, Mechanism B to orchestrators.
- **Unchanged:** `modules/self-improvement.md` (kept as the reactive layer).
- **Touched by the skill at runtime (per scope tiers):** `docs/tasks/<id>/retro.md`, `docs/workers/<name>.md`
  (Tier-1 auto); `CLAUDE.md`, `prompts/**`, `pipeline.yaml` (Tier-2 proposal-only).

---

## Sources
Scientific:
- [1] Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning*, NeurIPS 2023 — https://arxiv.org/abs/2303.11366 · code https://github.com/noahshinn/reflexion
- [2] Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback*, 2023 — https://arxiv.org/pdf/2303.17651 · https://selfrefine.info/
- [3] Gou et al., *CRITIC: LLMs Can Self-Correct with Tool-Interactive Critiquing*, ICLR 2024 — https://arxiv.org/abs/2305.11738
- [4] Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet*, ICLR 2024 — https://arxiv.org/abs/2310.01798
- [5] Tyen et al., *LLMs Cannot Find Reasoning Errors, but Can Correct Them Given the Error Location*, ACL Findings 2024 — https://arxiv.org/abs/2311.08516 · dataset https://github.com/WHGTyen/BIG-Bench-Mistake
- [6] Anthropic, *Building Effective AI Agents* / *Effective Context Engineering* — https://www.anthropic.com/research/building-effective-agents · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- [7] *From Knowledge to Noise: CTIM-Rover and the Pitfalls of Episodic Memory in SE Agents*, 2025 — https://arxiv.org/pdf/2505.23422
- [8] Ouyang et al., *ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory*, 2025 — https://arxiv.org/abs/2509.25140
- [9] *A Self-Improving Coding Agent (SICA)*, ICLR 2025 workshop — https://arxiv.org/html/2504.15228v1 · context-rot: MindStudio, Augment Code guides (see §3)

Industry (full list + Orchestra's own #85 data): `docs/tasks/85/approach-comparison.md` and `docs/tasks/85/experiment-results.md`
(regex gate precision 0.42; Haiku 100% on genuine corrections; confidence useless as filter).
