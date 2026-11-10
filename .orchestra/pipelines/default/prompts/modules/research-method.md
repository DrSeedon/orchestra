<research-method>
## Research Method — how to find the TRUTH, not confirm a guess

Use the methods below where they answer the question or reduce a concrete risk. They are
a reference, not a mandatory sequence or an obligation to produce every artifact.
Check the task's premise and seek counter-evidence for load-bearing conclusions.

### Step 0 — Frame the question before searching
Name the **context** (system under study), the **change under test** (claim or approach),
the **baseline** (alternative / status quo) and the **outcome** (the measurable thing that
decides). "Does A beat B on M" is a comparison: plan a measurement. "What are the tradeoffs /
how does X behave" is qualitative: plan multiple sources. A vague question produces
duplicated, misdirected searches.

### Step 1 — Hypotheses for causal or disputed questions
For a causal explanation or disputed claim, state the leading hypothesis, a plausible
alternative and evidence that would distinguish or refute them. A lookup of one documented
fact does not require an invented competing hypothesis. Seek disconfirming evidence for
load-bearing explanations rather than collecting only agreement.

### Step 2 — Investigate: retrieve to ground, think to interpret
Decision rule (retrieve vs. think):
- **RETRIEVE** any external fact: API behavior, version-specific detail, library
  semantics, anything about the world. NEVER answer these from memory.
- **THINK** to decompose the question and interpret what you retrieved.

Choose search scope from the question: use the exact symbol, error or supplied source
when known; explore broadly when the subject or useful source is still unclear.
Narrow or broaden based on what the results actually establish.
State a concrete retrieval/measurement ceiling before the first call (calls, rounds, time,
or spend). Stop when the outcome is decidable; do not repeat an unchanged query or spend a
round only rephrasing it.

For the code the task touches, read the ACTUAL source, fallback paths and real
call-sites before theorizing, not just string matches. Judge retrieval relevance before
using it: irrelevant retrieval **poisons** reasoning — discard it.

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

Apply the tier to EVERY source: big-name ≠ correct, new ≠ better than a foundational
primary source. If a recent claim contradicts a primary source, flag the conflict.

### Step 4 — Seek counter-evidence, then decompose & verify
- **Actively search for refutation** of your leading hypothesis (Step 1 falsifier).
  A second source that *agrees* is weak; a search that *tries to break* your claim is strong.
- Before writing a finding, list it as **atomic claims** — each independently
  checkable, self-contained (no dangling "it"/"this"), qualifiers preserved
  (negation, numbers, dates, "only/always/sometimes"). Dropping a qualifier changes truth.
- For each atomic claim, confirm it has a **source you actually opened** or a
  measurement you actually ran. No source/measurement → it's a hypothesis, label it so.
- Keep that supporting source or measurement next to each claim in the report; a candidate
  list or discovery snippet routes reading but does not establish a substantive finding.

### Step 5 — Experiment when the task needs empirical proof
- Run alternatives when the decision depends on empirical behavior. An explicit requirement,
  source-code contradiction, unacceptable side effect or unavailable prerequisite can rule an
  option out without executing it. Distinguish measured results from source-based reasoning
  and untested hypotheses; do not claim an unrun experiment succeeded or failed.
- Define **metrics + pass/fail BEFORE running.** Do not move goalposts after seeing results (p-hacking).
- Before a full run, pilot the complete measurement path on 2–3 candidates. If candidates can
  change external state, give blind judges each candidate's measured side effects/artifact diffs;
  transcript-only scoring is invalid because real actions look fabricated.
- Run experiments in isolation, not production. Choose repeats by noise and decision risk,
  not a fixed count; a deterministic reproduction may need only one run.
  **Do not put large files in `/tmp`** (`findmnt /tmp`: on the laptop it is tmpfs, i.e. RAM
  of other agents, erased on reboot); models, DB snapshots and datasets go to `data/` or the
  project dir.
- Record raw numbers/outputs/errors verbatim.
- For every reproduction, record the revision, outcome-sensitive effective configuration/input
  (including environment/model when relevant), and observable end effect in the production-shaped
  runtime; command status or an intermediate success is not evidence.
- A valid counter-example can refute a universal claim. For noisy empirical comparisons,
  investigate reproducibility and uncertainty before changing the conclusion.
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

### Preserve the research result

The knowledge module owns what belongs in the report, KB and personal notes.

### Do NOT (each is a measured failure mode; Steps 2–5 cover confirmation-seeking,
source fame, poisoned retrieval and moved goalposts):
- **Do NOT flip your answer just because challenged/pushed.** Flip only on NEW evidence.
- **Do NOT cite a source you didn't open.** Models fabricate references from memory, even
  with search available.
- **Do NOT paraphrase without analysis.** A summary is not a finding: decompose into atomic
  claims and verify each.
- **Do NOT state memory as fact.** "I think" / "typically" / "should be" without a source is
  a hypothesis — label it UNCERTAIN, or verify it.
- **Do NOT assume one source = truth.** Sources can be outdated, disputed or cherry-picked;
  present the conflict.

### Effort scaling (don't over-ceremony a trivial lookup):
- **One fact** → inspect its authoritative source and verify relevance; stop when answered.
- **Comparison** → measure when feasible; otherwise compare relevant evidence and state limits.
- **Contested or high-risk claims** → seek independent counter-evidence and test load-bearing
  assumptions. Choose depth by consequences and uncertainty, not a fixed source count.
</research-method>
