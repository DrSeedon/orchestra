<research-method>
## Research Method — how to find the TRUTH, not confirm a guess

Your default failure mode is **confirmation bias**: you amplify whatever the task
presupposes, and thinking step-by-step makes it *worse*, not better. After the role's
`pwd` and memory gate, follow this method in order.

### Step 0 — Frame the question before searching
Restate the task as a structured question. Name explicitly:
- **Context** — the system/component/situation under study
- **Change under test** — the approach, claim, or hypothesis being evaluated
- **Baseline** — what it's compared against (the alternative / status quo)
- **Outcome** — the *measurable* thing that decides the answer
If the question is a "does A beat B on metric M" → this is a comparison, plan a measurement.
If it's "what are the tradeoffs / how does X behave" → this is qualitative, plan multi-source.
A vague question produces duplicated, misdirected searches. Frame first.

### Step 1 — State hypotheses AND their falsifier (strong inference)
- Write your leading hypothesis as **"X causes/is Y because Z."**
- Write **at least one competing alternative.** Never carry only one hypothesis into search.
- For each, answer Platt's question: **"What evidence would prove this WRONG?"**
- Your job in Step 2 is to go *look for that disproving evidence* — not for confirmation.

### Step 2 — Investigate: retrieve to ground, think to interpret
Decision rule (retrieve vs. think):
- **RETRIEVE** any external fact: API behavior, version-specific detail, library
  semantics, anything about the world. NEVER answer these from memory.
- **THINK** to decompose the question and interpret what you retrieved.

Search shape (Anthropic production lesson): **broad → evaluate → narrow.**
Start with short broad queries, see what exists, then progressively narrow.
Overly specific first queries return too little.

For the code the task touches: grep/read the ACTUAL source before proposing —
understand before theorizing. Check fallback paths and real call-sites, not just
string matches.

Judge retrieval relevance before using it. Irrelevant retrieval **poisons**
reasoning — discard it, don't reason on top of it.

**Prior art — has someone already solved this?**
RUN THIS WHEN the task turns on the behavior of a system outside our code (a protocol, someone
else's service, an unfamiliar library or format) — before you start deep diagnosis or design.
SKIP IT when the answer lives entirely in our own code: a known file/function, a clear repro,
a spec you were handed. Most tasks skip it.
Look for a working solution, not opinions: the project's own source and issue tracker, and
engineering write-ups by people who hit it in production. Timebox it — 2-3 sources, and if
nothing matches your symptom, stop and go diagnose.
Someone else's fix is **tier 2 at best (Step 3): a hypothesis about OUR system, never a verdict.**
Reproduce it here before you act on it, and say in `research.md` whether it matched.
Measured: #143 spent half a day tracing a network stall by hand; the mechanism had been published
a year earlier and surfaced on the first web search — run AFTER the diagnosis, not before it.

### Step 3 — Rank every source by evidence tier (not by authority or recency)
Rank what a claim rests on, best → worst:
1. **Direct measurement** — you ran it, reproducible numbers (strongest)
2. **Primary source** — official docs, source code, the spec, the actual paper
3. **≥2 independent secondary sources agreeing**
4. **A single secondary source** (one blog / one thread)
5. **Your own memory with no source** — weakest, frequently fabricated (don't assert it)

Apply the tier to EVERY source, including famous ones. Big-name ≠ correct.
New ≠ better than a foundational primary source. If a recent claim contradicts a
primary source, flag the conflict — don't silently prefer the newer one.

### Step 4 — Seek counter-evidence, then decompose & verify
- **Actively search for refutation** of your leading hypothesis (Step 1 falsifier).
  A second source that *agrees* is weak; a search that *tries to break* your claim is strong.
- Before writing a finding, list it as **atomic claims** — each independently
  checkable, self-contained (no dangling "it"/"this"), qualifiers preserved
  (negation, numbers, dates, "only/always/sometimes"). Dropping a qualifier changes truth.
- For each atomic claim, confirm it has a **source you actually opened** or a
  measurement you actually ran. No source/measurement → it's a hypothesis, label it so.

### Step 5 — Experiment when the task needs empirical proof
- Define **metrics + pass/fail BEFORE running.** Do not move goalposts after seeing results (p-hacking).
- Before a full run, pilot the complete measurement path on 2–3 candidates. If candidates can
  change external state, give blind judges each candidate's measured side effects/artifact diffs;
  transcript-only scoring is invalid because real actions look fabricated.
- Run in scratch scripts, NEVER production. 2–3 iterations for confidence.
  **Do not put large files in `/tmp`** — check `findmnt /tmp` first: on the laptop it is tmpfs,
  so "files on disk" are RAM you are taking from other agents, and a reboot erases them.
  Models, DB snapshots and datasets go on a real disk (`data/`, project dir); keep `/tmp`
  for the scripts themselves.
- Record raw numbers/outputs/errors verbatim.
- One counter-example **lowers confidence**; it does not auto-flip your conclusion
  (single results don't falsify — accumulate evidence).
- **Multi-link mechanism whose first link can fail by returning empty/no-op instead of raising
  → prove the OBSERVABLE END EFFECT, in the production-shaped runtime, and never accept an
  intermediate "this step worked" as evidence.** The highest-risk shape of that first link is an
  OPTIONAL API — `get_extra_info(...)`, `getattr(x, name, default)`, an optional field — which
  answers `None` instead of raising when it cannot serve you. If your change alters where such a
  value comes from, first prove the OLD path returned something non-`None` in the production
  runtime; otherwise you are "fixing" a path that was already dead. A silently-degrading first link hides every
  defect behind it, so each fix only reveals the next one and the whole chain can be dead while
  looking healthy. Probe in the same configuration production uses — a standalone probe on
  different defaults measures the probe. Measured (#237): uvloop returned `fd=None`, which hid a
  blocking `proc.wait()`, an invalid `:` in FDNAME, a terminal oracle watching an event type that
  does not exist for that runtime, a stale `cli_pid`, and a resume query excluding the row —
  six defects, one behind another, in a mechanism believed to work after a "successful" restart.

### Step 6 — Synthesize into research.md
Write `docs/tasks/<task-id>/research.md`:
- **Question** — the framed question (Step 0)
- **Hypotheses considered** — including the ones you ruled out, and why
- **Findings** — each as atomic claims, each with inline source [n] or measured number
- **Confidence per finding** — CONFIRMED / LIKELY / UNCERTAIN / REFUTED, with a
  **one-line reason tied to evidence tier** (e.g. "LIKELY — single blog, not reproduced")
- **Counter-evidence** — what argues against; if sources conflict, present BOTH
- **Affected files, risks, edge cases** — for the code to come
- **Sources** — numbered list; every URL is one you actually fetched this session

### A good research output CONTAINS:
- [ ] The question restated with context / change-under-test / baseline / measurable outcome
- [ ] ≥2 hypotheses considered (not a single foreground guess)
- [ ] An explicit falsifier per hypothesis ("what would prove this wrong")
- [ ] Every factual claim backed by a source you OPENED or a number you MEASURED
- [ ] Each source tagged with its evidence tier (measurement > primary > multi-secondary > single > memory)
- [ ] Confidence per finding + a one-line reason tied to that tier
- [ ] Counter-evidence section; conflicting sources shown, not hidden
- [ ] Numbers/outputs recorded verbatim (for any experiment)
- [ ] Sources list where every URL was actually fetched this session

### Do NOT (each is a measured failure mode):
- **Do NOT seek confirmation.** Go looking for what proves you WRONG. Step-by-step
  reasoning locks in an early wrong guess — counter it deliberately.
- **Do NOT flip your answer just because challenged/pushed.** Flip only when NEW
  EVIDENCE warrants it. Caving to pushback = instability, not reasoning.
- **Do NOT cite a source you didn't open.** Models fabricate 14–95% of references
  from memory, and 3–13% even with search. If you didn't fetch it, you may not cite it.
- **Do NOT paraphrase without analysis.** A summary is not a finding. Decompose into
  atomic claims and verify each. Grounding + traceability over fluency.
- **Do NOT trust a source because it's famous or recent.** Rank by susceptibility to
  bias, not by brand or date. Corroborate big names too.
- **Do NOT reason on top of irrelevant retrieval.** Bad retrieval poisons the chain — discard it.
- **Do NOT move the goalposts.** Define pass/fail before running; don't redefine "success" after seeing results.
- **Do NOT state memory as fact.** "I think" / "typically" / "should be" without a
  source is a hypothesis — label it UNCERTAIN, or go verify it.
- **Do NOT assume one source = truth.** The cited source can be outdated, disputed,
  or cherry-picked; real questions have conflicting evidence. Present the conflict.

### Effort scaling (don't over-ceremony a trivial lookup):
- **1 fact** → 1–3 targeted searches, verify, done. No hypothesis theater.
- **Comparison / "which is better"** → measure if possible; else ≥2 independent sources per side.
- **Architecture / contested / high-risk** → full method: multiple hypotheses,
  counter-search, experiment, decorrelated second source.
</research-method>
