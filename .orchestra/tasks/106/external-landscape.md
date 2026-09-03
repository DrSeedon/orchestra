# #106 extension — external context compaction, benchmarks, and Ouroboros memory

**Research date:** 2026-08-01
**Scope:** questions 1–3 only, specifically the Claude-backend handoff governed
by `app/session.py::COMPACT_PROMPT`. Codex sessions take the separate native
`_compact_codex_context()` path. No new prompt candidates were selected and no
paid generation was run; production code was read-only.
**Presentation:** [`docs/artifacts/compact-memory-landscape-106.html`](../../artifacts/compact-memory-landscape-106.html)

## Executive answer

1. The public coding-agent ecosystem does not converge on one magical summary
   prompt. The strongest common pattern is architectural: preserve a raw recent
   tail, summarize only the old/middle span, keep tool-call boundaries atomic,
   and source exact file/action facts from deterministic events. Codex, Aider,
   OpenHands, and Cline all protect recent raw history in some form; Cline also
   computes file operations outside the LLM. The current Orchestra **Claude**
   prompt asks
   for the last 5–10 exchanges “in detail” but structurally protects none of
   them. This is consistent with our measured **39.7% last-three exact recall**
   versus **95.2%** for Kesha, although the external code inspection is not a
   causal ablation of our prompt. **CONFIRMED as an ecosystem mechanism;
   LIKELY as the right repair direction for Orchestra.** [1–11][18]
2. No available benchmark matches Orchestra's contract: a coding-agent handoff
   must preserve exact paths, statuses, commands/errors, pending action,
   durable writes, the latest user wording, and fake-secret safety at a single
   compaction boundary. LongBench and InfiniteBench test long-context model
   capability, not handoff. LoCoMo and LongMemEval-v1 test conversational
   memory. CL-Bench tests learning across questions. Newer LongMemEval-V2,
   MEMTRACK, STATE-Bench, and OdysseyBench are useful external-validity probes,
   but their native outcomes still do not decide which compact prompt Orchestra
   should ship. A **fresh Orchestra-specific holdout should remain the headline
   decision gate**; a small imported trajectory subset is a useful secondary
   diagnostic. **CONFIRMED construct mismatch from benchmark contracts.**
   [19–27]
3. Ouroboros has useful memory mechanics independent of its unconfirmed
   CL-Bench SOTA claim: typed hot/cold tiers, explicit promotion, immediate
   read-after-write, a bounded atomic scratchpad, a raw dialogue suffix, a
   generation-bound consolidation cursor, loud gap markers, and project-local
   fact stores. Orchestra's hybrid vector+FTS retrieval remains a better default
   for a small multi-project team than injecting a growing biography into every
   request. The transferable idea beyond the already-proposed freshness
   watermark is a **tiny typed task-state ledger plus explicit fact promotion
   with provenance/update semantics**, leaving `search_memory` as cold history.
   This is an architectural hypothesis, not a measured Orchestra improvement.
   **CONFIRMED mechanics; LIKELY design direction; effect UNCERTAIN.** [28–38]

## 1. Question, hypotheses, and falsifiers

### Context / change / baseline / outcome

- **Context:** Orchestra's Claude backend compacts a long agent transcript into
  a handoff summary and separately offers persistent project memory through
  `search_memory`. Codex workers use native Codex compaction and are not governed
  by the prompt evaluated in #106.
- **Change under study:** external prompt/mechanics patterns, external
  benchmarks, and Ouroboros memory mechanics that could improve the next
  Orchestra experiment.
- **Baseline:** current Orchestra Claude compact prompt and shared memory
  architecture, plus the already-completed #106 holdout and #110 Ouroboros
  analysis.
- **Outcome for this phase:** source-backed shortlist of mechanisms and a
  justified benchmark strategy. No go/no-go on a new production prompt is
  possible until a fresh holdout is run.

### Competing hypotheses

| Hypothesis | What would falsify it? | Result |
|---|---|---|
| **H1. Prompt wording is the main reason other agents preserve freshness.** | Mature harnesses use short/generic prompts but retain fresh raw turns or deterministic state outside the summary. | **REFUTED as the general explanation.** The external pattern is hybrid prompt + architecture. |
| **H2. A public benchmark can replace our synthetic holdout.** | The benchmark's unit, inputs, and outcome omit exact handoff continuation, file/action evidence, or secret/durable-write checks. | **REFUTED.** No inspected benchmark matches the full contract. |
| **H3. Ouroboros offers no useful memory idea beyond its benchmark score and the freshness watermark.** | Source code implements useful lifecycle/isolation/provenance properties absent from Orchestra. | **REFUTED.** Several mechanics are transferable, but none has an Orchestra effect estimate yet. |

## 2. Method and reproducibility

### Source inspection

Open-source harnesses were inspected at fixed commits, not from remembered
blog summaries:

| Repository | Commit inspected |
|---|---|
| OpenAI Codex | `ee0247f95a6fe2b094ba2253d82cae2a2b4c2dff` |
| Aider | `5dc9490bb35f9729ef2c95d00a19ccd30c26339c` |
| OpenHands software-agent-sdk | `2f27653959f7596769427ee4657247b32c94504e` |
| Cline | `94f897f55933c86a08578385a019211e01a1a36d` |
| Continue | `5522c6f44ca0ac3528b37244818fbfa39b5af470` |
| SWE-agent | `3ea751c087f32b16e039a2233dd6eefecef325d5` |
| Anthropic claude-code public repository | `7ef6eec9d9ba84ea6f233f26c45f1df5c5991843` |
| Ouroboros | `ca76d76ca2f645c25b528575869e2dff132a75ea` |

Reproduction commands (run against temporary clones):

```bash
git -C <repo> rev-parse HEAD
git -C <repo> show <commit>:<path>
git -C <repo> grep -n '<mechanism>' <commit> -- '<paths>'
rg -n '<mechanism>' app/rag.py app/rag_service.py app/mcp_stdio.py app/routes/
```

The exact paths and pinned source links are in the Sources section. External
provider documentation and benchmark repositories were opened on 2026-08-01.

### Interpretation rule

“Prompt public” means the exact runtime instruction exists in an official
source repository. User-facing documentation about `/compact` does not meet
that standard. “Raw recent tail” means unsummarized recent events/messages are
passed forward by code, not merely requested in prose. “Deterministic ledger”
means file/tool facts are derived from events rather than trusted to the
summarizer.

This phase introduces no new outcome measurement. Numbers about Orchestra come
from the completed #106 `analysis.json` pipeline with **N=21 holdout outputs per
variant across seven fixture clusters** [18]. Numbers describing external
benchmarks come from their primary repositories/papers.

## 3. Question 1 — what public harnesses actually do

### Comparison matrix

| Harness | Exact prompt public? | Prompt's mandatory state | What it discards | How freshness is protected | Repeated-compaction risk |
|---|---:|---|---|---|---|
| **Codex CLI** | Yes | progress/decisions; constraints/preferences; next steps; critical data/examples/references | Assistant/tool detail not selected into summary | Up to **20k tokens of raw user messages** are selected backwards and reinserted; prior summaries excluded from this raw-user collection | Code warns that multiple compactions can reduce accuracy |
| **Aider** | Yes | functions, libraries/packages, filenames from assistant code fences; topic progression | non-user/assistant roles; older detail; fenced code in summary | Raw tail gets roughly half the summary budget; prompt explicitly weights recent messages | Recursive head-summary merge, depth ≤3, can drift |
| **OpenHands SDK** | Yes | user context; exact task IDs/status; completed/pending/current state; code/tests/changes/deps/VCS | irrelevant task-type detail; condensed middle | First events plus a recent suffix remain raw; only forgotten middle is summarized; tool units stay atomic | Previous summaries can be summarized again; hard-reset fallback truncates events |
| **Cline** | Yes | goal; done/in-progress/blocked; highlights; next; files read/edited | old tool/file content beyond bounded previews | **20k recent tokens raw**; a later typed user turn is protected; tool pairs atomic | A single initial user task followed by a long tool loop may be summarized; manual CLI `/compact` re-reads canonical transcript to avoid summary-of-summary drift |
| **Continue IDE** | Yes | overview; active development; stack; files; troubleshooting; outstanding work | outdated prior-summary detail; images | IDE keeps history after selected compact index raw | Prior summary is folded into next; CLI fallback may prune the newest content |
| **SWE-agent** | No generative summary in current processor | N/A | old environment observations and superseded file windows | Keeps latest N observations and latest window per file; actions/messages remain | Deterministic omission avoids hallucinated summaries but loses high-level synthesis |
| **Claude Code** | No official runtime prompt found | Docs say requests, decisions/bugs/implementation details, key code snippets | older tool outputs and redundant messages | Recent accessed files are retained; project-root instructions and auto-memory are re-injected | Detailed early instructions may be lost; exact internal boundary policy is private |

### 3.1 Codex CLI

The complete public prompt is only four requested bullets: current progress and
decisions; context/constraints/preferences; remaining work; and critical data,
examples, or references. It ends with a concise/structured continuation
instruction [1]. The important part lives in `compact.rs`: the replacement
history contains the generated summary **and a backwards-selected raw user
message set capped at 20,000 tokens**; summary-shaped messages are excluded from
that raw set [2]. Initial context is re-injected at a controlled boundary.

**Keep:** user requests (raw where budget allows), progress, decisions,
constraints, next steps.
**Drop/compress:** assistant reasoning and tool output unless the summary retains
them.
**Freshness mechanism:** code, not prose.
**Confidence: CONFIRMED — primary source code at pinned commit.**

### 3.2 Aider

Aider's prompt explicitly says to include less detail about older parts and more
about recent messages. It requires function/library/package names and filenames
found in assistant code fences, forbids fenced code in the summary, and asks the
summary to speak as the user [3]. `history.py` then preserves a raw tail under
roughly half the token budget and summarizes the head; if summary + tail is
still too large, the process recurses up to depth three [4]. Only USER and
ASSISTANT roles are fed to the summarizer.

**Keep:** recent raw dialogue, named technical identifiers.
**Drop/compress:** older detail, non-chat roles, raw fenced code.
**Freshness mechanism:** both explicit age weighting and a raw tail.
**Counter-evidence:** tool results in non-chat roles can disappear, and recursive
summarization is exactly where compaction-of-compaction error can accumulate.
**Confidence: CONFIRMED — primary source code.**

### 3.3 OpenHands SDK

The OpenHands prompt is the most explicit public state schema inspected. Its
labels are `USER_CONTEXT`, `TASK_TRACKING`, `COMPLETED`, `PENDING`, and
`CURRENT_STATE`; code tasks add `CODE_STATE`, `TESTS`, `CHANGES`, `DEPS`, and
`VERSION_CONTROL_STATUS`. It specifically requires exact task IDs and statuses
[5]. The rolling condenser preserves a protected prefix and recent suffix,
summarizing only the forgotten interval. Its default factory uses 80 events and
keeps the first four; an event-count compaction targets half that view, and
manipulation indices prevent cutting atomic units [6].

**Keep:** initial contract, recent raw events, exact task identifiers, executable
state.
**Drop/compress:** irrelevant fields and the old/middle span.
**Freshness mechanism:** raw suffix.
**Counter-evidence:** a hard reset may truncate event strings after summarizer
failures, and older summaries remain eligible for later summarization.
**Confidence: CONFIRMED — primary source code.**

### 3.4 Cline

Cline uses a compact schema: `Goal`, `State` (Done/In Progress/Blocked),
`Highlights`, `Next`, and `Files` (Read/Edited) [7]. The mechanics are stronger
than the prose:

- trigger near 90% of usable input, target about 70%;
- retain 20,000 recent tokens by default;
- keep the newest typed user turn raw when it occurs after index 0;
- keep tool-use/result boundaries intact;
- derive read/edited files from tool activity and append a `Files` section if
  the model omitted it;
- bound tool/file previews rather than dumping them [7].

Manual CLI compaction deliberately summarizes the canonical transcript rather
than a sidecar summary, explicitly to avoid repeated summary drift [8].

The latest-user guarantee has a documented exception: if the transcript has
only one initial user task followed by a long tool loop, that task is at index
0 and `findCutIndex()` may use the token-budget cut, folding the prompt into the
summary [7].

**Keep:** raw recent requests, exact file ledger, goal/state/next.
**Drop/compress:** redundant old transcript and long raw outputs.
**Freshness mechanism:** raw tail + latest-user invariant.
**Confidence: CONFIRMED — primary source code.**

### 3.5 Continue

Continue IDE asks for Conversation Overview, Active Development, Technical
Stack, File Operations, Solutions & Troubleshooting, and Outstanding Work; it
requires paths/function/class identifiers and asks a later summary to remove
outdated prior details [9]. The IDE stores the summary at a selected index and
keeps later history raw. The CLI uses a shorter prompt that explicitly asks for
the current stream at the end, but if the summarizer input cannot fit,
`pruneLastMessage` removes from the end [10].

**Keep:** recent active development and outstanding work.
**Drop/compress:** outdated summary facts and images.
**Freshness mechanism:** safe in the IDE path; weaker in the CLI overflow path.
**Confidence: CONFIRMED — primary source code; product paths differ.**

### 3.6 SWE-agent

Current SWE-agent history processing is a useful non-LLM baseline. Optional
`LastNObservations` replaces old environment outputs with an omission marker,
keeps the first observation and last N observations, and supports explicit
keep/remove tags. `ClosedWindowHistoryProcessor` preserves only the latest
visible window for each file and replaces older windows with a count marker
[11]. The current docs say the classic last-five policy is often unnecessary
for newer large-context models.

**Keep:** agent messages/actions, first observation, newest observations and
latest file windows.
**Drop/compress:** old raw environment outputs and superseded windows.
**Freshness mechanism:** deterministic recency.
**Tradeoff:** zero summarizer fabrication, but no synthesized decisions/pending
state.
**Confidence: CONFIRMED — primary source code.**

### 3.7 Claude Code

Anthropic's public repository contains plugins and examples, not the closed CLI
runtime or its exact compact prompt; a repository-wide inspection found no
official prompt artifact. Therefore this research does **not** substitute an
unofficial prompt dump. Official docs expose behavior instead: `/compact` can
take custom instructions; a `Compact Instructions` section in `CLAUDE.md` can
customize it; older tool outputs are cleared before the whole conversation is
summarized; project-root instructions and auto-memory are re-injected; and
details from early instructions may be lost [12–14]. Anthropic's engineering
article says compaction retains architectural decisions, unresolved bugs,
implementation details, and the five most recently accessed files [15].

**Keep:** documented continuation state and recently accessed files.
**Drop/compress:** redundant messages and stale tool output.
**Freshness mechanism:** partially documented file recency; exact recent-message
policy is unknown.
**Confidence: CONFIRMED that the exact official prompt is unavailable in the
inspected official repository; LIKELY behavior from official docs.**

### 3.8 Provider guidance

Anthropic's official session-memory cookbook is unusually concrete. Its
suggested state sections are User Intent, Completed Work, Errors & Corrections,
Active Work, Pending Tasks, and Key References. It prioritizes corrections,
errors, and active work; preserves exact IDs, paths, values/configuration, and
error text; weighs recent events; and keeps messages after the last summarized
index unsummarized [16]. This independently supports the Kesha-like recency and
exact-anchor requirements, but also shows that the raw tail is a data-flow
property.

OpenAI's current Responses API guidance does not publish a human-readable
handoff schema. Server-side compaction produces an opaque encrypted compaction
item carrying key prior state/reasoning. The standalone `/responses/compact`
endpoint returns a canonical next window that clients should pass forward as-is
rather than selectively pruning [17]. This design shifts fidelity from “write a
perfect Markdown summary” toward a provider-owned state representation.

**Confidence: CONFIRMED — current official provider documentation opened on
2026-08-01.**

### 3.9 Academic approaches that transfer — and those that do not

| Approach | Concrete mechanism | Applicability to Orchestra |
|---|---|---|
| Recursive / multi-stage summarization (SummN; recursive book summarization) | chunk, summarize, then merge summaries to fit arbitrary length | Useful only with traceability and source re-grounding. Agent state changes over time; naive recursion can preserve obsolete facts and amplify errors. |
| Context-aware hierarchical merging | refine merged summaries against source context; paper explicitly targets hallucination amplification in recursive merging | Direct support for source ledgers and periodic re-grounding, not for a bigger prompt. |
| MemGPT | hierarchical memory tiers and model-controlled paging between context and external storage | Supports a tiny hot task state + cold `search_memory`, not dumping all project history into compact. |
| Generative Agents | full timestamped memory stream plus retrieval by relevance, recency, importance; higher-level reflections | Recency/provenance ranking is useful; free-form reflections are too weak for exact file/action state. |
| ReSum | periodically reset to original goal plus a compact reasoning state; train a policy to operate from summaries | Relevant architecture, but gains rely partly on summary-conditioned training; not evidence that an off-the-shelf prompt will work. |
| ACON | learn compression guidelines from paired cases where full context succeeds and compressed context fails; compress observations and history | Best methodological match for phase 2: use our failure ledger to mutate/ablate prompt rules. Its published 26–54% peak-token reduction is on AppWorld/OfficeBench/MOQA, not Orchestra. |

The strongest academic lesson is not “summarize recursively.” It is “treat the
compressed state as a sufficient statistic for downstream action, and optimize
it using observed continuation failures while retaining access to source
evidence.” ACON operationalizes that directly; context-aware hierarchical
merging supplies counter-evidence against blind summary-of-summary chains
[39–44].

### 3.10 Implication for the next candidate experiment

The measured #106 defect remains the anchor: the current Orchestra Claude
prompt had **91.3% critical-anchor recall** but only **39.7% last-three exact
recall**; Kesha had
89.1% and 95.2%, respectively [18]. External systems suggest three separable
mechanisms to test later:

1. **prompt-only recency contract** — exact last-three user messages;
2. **raw recent tail** — preserve recent user/tool-safe units outside the
   summary;
3. **deterministic ledger** — inject exact files/actions/status evidence into
   the compact result, independent of the summarizer.

Those are experiment axes, not selected production features. Designing the
2–3 exact candidates and generating a fresh holdout belongs after this gate.

## 4. Question 2 — which benchmarks are actually relevant?

### Fit rubric

This is a declared construct-fit rubric, not a benchmark result:

- **3/3:** agent trajectories with changing state, continuation after a compact
  boundary, and deterministic exact state/action outcome;
- **2/3:** agent trajectories and changing state, but native evaluation is QA or
  whole-task success rather than compact handoff fidelity;
- **1/3:** multi-session/person/continual memory without tool/file continuation;
- **0/3:** static long-context capability only.

No inspected benchmark scores 3/3.

| Benchmark | Native unit and outcome | Fit | Use for Orchestra? |
|---|---|---:|---|
| **LongBench / LongBench-v2** | long-document QA, summarization, few-shot, synthetic and code tasks; v2 is 503 multiple-choice questions over long contexts | 0/3 | No full run. It tests the reader/model, not the handoff contract. |
| **InfiniteBench** | 12 tasks over >100k-token inputs: QA, book summary/MC, code, math, passkey | 0/3 | No. Same construct mismatch, with extra context-length cost. |
| **LoCoMo** | ten long multi-session conversations; QA/event summaries, personal and temporal facts | 1/3 | A small slice can probe preferences/temporal facts, but not paths, tools, or durable writes. |
| **LongMemEval-v1** | 500 questions on extraction, cross-session reasoning, updates, temporal knowledge, abstention | 1/3 | Better contradiction/update diagnostic than LoCoMo; still QA after chat history. |
| **CL-Bench** | continual learning across question families with persistent memory; Ouroboros run used six families | 1/3 | No prompt selection. It measures learning across questions and is expensive; #110 already found the nominal 0.2301 vs 0.223 claim statistically unsupported. |
| **LongMemEval-V2** | 451 curated questions over up to 500 multimodal web-agent trajectories / 115M tokens; memory backend returns bounded evidence to a fixed reader | **2/3** | Best packaged secondary diagnostic for dynamic state, workflows, gotchas, and wrong premises. Use Small/subset, not its leaderboard score as our ship gate. |
| **MEMTRACK** | interleaved Slack/Linear/Git timelines with noise, conflicts, cross-references, file/code context; correctness/efficiency/redundancy | **2/3** | Best content match for conflicts and software-workflow memory. Import a small trace subset if access/setup is practical. |
| **STATE-Bench Agent Learning** | 450 tool-using travel/support/shopping tasks with sandbox DB and simulated users; reusable learnings injected through a retrieval hook | 2/3 | Strong deterministic end-state evaluation, but domain and lifecycle differ from transcript compaction. Useful later for memory architecture, not prompt wording. |
| **OdysseyBench** | long-horizon office workflows with chat histories; raw/RAG/session-summary memory modes and task execution | 2/3 | Useful RAG-vs-summary external check, but setup and office domains add cost without matching exact coding anchors. |

Sources: [19–27].

### Direct verdict

**Do not replace the fresh Orchestra holdout with a foreign benchmark.** That
would make the result look more standard while measuring a different thing.
Our synthetic corpus is “honest” for the production decision because its source
ledger encodes the actual invariants the compact handoff must preserve. Its
weakness is external validity, not construct validity.

The useful compromise for phase 2 is:

1. keep a new, untouched Orchestra-specific holdout as the only ship/no-ship
   gate;
2. import a small blinded subset of **MEMTRACK or LongMemEval-V2 Small** and
   translate each trajectory into the same atomic ledger;
3. report that result separately as external validity, never pool it with the
   Orchestra estimate;
4. use STATE-Bench/OdysseyBench only if we later compare persistent memory
   architectures end-to-end, not compact prompt text.

Why MEMTRACK vs LongMemEval-V2 is not settled here: MEMTRACK is the closer
software-workflow content match; LongMemEval-V2 has the cleaner packaged memory
backend interface and documented Small tier. Dataset access/setup should be
verified before choosing. **LIKELY recommendation — construct analysis from
primary benchmark contracts; no local execution yet.**

## 5. Question 3 — Ouroboros memory beneath the headline

### 5.1 What it actually stores and injects

At the inspected commit, Ouroboros has a typed, multi-tier memory system rather
than one searchable archive:

- a protected Tier-0 context always includes system/Bible, identity,
  scratchpad, knowledge index, and recent dialogue [28];
- project tasks redirect knowledge to a canonical per-project store, add a
  bounded **journal tail**, and inject the project workpad in full; generic tools
  are blocked from reading other project stores [29][36];
- the normal scratchpad append path targets a ten-block cap, writes atomically,
  journals evicted contents, and regenerates a human-readable Markdown view
  [30]. A concurrent append during slow LLM consolidation can leave eleven
  blocks because the merge step prepends the compressed block without
  reapplying the cap [31];
- explicit tools append scratchpad state, update identity with audit records,
  and read/write topic knowledge; knowledge changes retain old/new content and
  hashes in a JSONL history [32][33];
- the dialogue view combines older consolidation blocks with a raw suffix after
  a validated cursor; the cursor is bound to a chat-log generation signature
  [29][31].

### 5.2 Consolidation lifecycle

Dialogue consolidation uses 100-message blocks summarized to roughly 200–500
words. At more than ten summary blocks, the oldest four ordinary blocks are
merged into an “era.” The prompt keeps decisions/agreements, technical
discoveries, task outcomes, failures, and task IDs; it drops routine operations
and redundant/debugging detail [31]. If the cursor's source generation is gone,
Ouroboros durably writes an explicit `[MEMORY GAP]` before rebasing rather than
silently pretending continuity.

Scratchpad consolidation is a separate path. When the live scratchpad is large,
the oldest portion is compressed; durable facts can be promoted into named
knowledge topics, and concurrent new blocks are merged under a lock [31]. This
separation between **working state**, **durable facts**, and **dialogue history**
is the main architectural difference from Orchestra.

### 5.3 Orchestra today

Orchestra indexes project Markdown (including `docs/tasks` and `CLAUDE.md`) and
selected agent logs. It performs hybrid semantic + FTS retrieval with reciprocal
rank fusion and returns a bounded top-k result with source attribution;
cross-project search is opt-in [34][35]. A merge launches project backfill, and
read-only search can continue concurrently [37][38].

This is simpler and cheaper in prompt tokens than an always-injected biography.
It is also passive: the agent must form a good query, retrieved chunks do not
constitute a typed current task state, and there is no explicit promotion
contract from “working fact” to “durable fact with update semantics.” The
already-documented index freshness/watermark issue is intentionally not repeated
as the recommendation here; #110 already covers it [45].

### 5.4 Mechanism-by-mechanism comparison

| Property | Ouroboros | Orchestra | Better current fit |
|---|---|---|---|
| Hot working state | bounded scratchpad, always injected | transcript/compact summary; no typed hot ledger | **Ouroboros mechanism** |
| Cold historical recall | topic files + indices, much state injected | hybrid vector+FTS top-k over docs/logs | **Orchestra** for a small multi-project team |
| Fresh dialogue | raw suffix after a generation-bound cursor | Claude path: summary-only compact handoff; Codex path: native compaction with raw user reinsertion | **Ouroboros mechanism for Claude only** |
| Fact promotion | explicit scratchpad → topic knowledge | author writes docs/CLAUDE; later indexed | **Ouroboros mechanism** |
| Provenance/audit | old/new hashes and JSONL histories; gap markers | source links to canonical Markdown/log rows; Git history | Mixed |
| Project isolation | canonical per-project knowledge/journal/workpad | project namespace; cross-project opt-in | Mixed |
| Contradiction/update semantics | topic overwrite/append, but no general supersedes/TTL model | retrieval may surface old and new chunks together | **Neither** is sufficient |
| Prompt footprint | substantial protected memory always on | bounded retrieval only when queried | **Orchestra** |
| Complexity | multiple stores, consolidators, locks/cursors | one index and canonical project docs/logs | **Orchestra** for MVP |

### 5.5 What is worth borrowing beyond the watermark

1. **Tiny typed hot task state.** Maintain objective, current phase/status,
   current blocker, immediate next action, current branch/worktree, and a small
   exact file/action ledger. Keep it bounded and always available to compact;
   leave long history in RAG.
2. **Explicit promotion.** Moving a fact from hot state to durable project
   memory should be an explicit operation with source, timestamp, scope, and
   overwrite/supersedes semantics. Immediate read-after-write matters more than
   eventual embedding availability.
3. **Loud discontinuity.** If a checkpoint cannot prove continuity with its
   source transcript/ledger, emit a gap/unknown marker. Never fill the hole with
   a fluent inference.
4. **Per-task isolation.** A task checkpoint should not mutate global identity
   or biography by default. Ouroboros's project redirection is useful; its
   always-injected global biography is not.

These recommendations do **not** imply copying Ouroboros's store or
consolidator. A minimum Orchestra experiment could be one small JSON/Markdown
checkpoint owned by the session and a deterministic renderer into compact. The
actual schema and behavior require a separate plan and tests.

### 5.6 Counter-evidence and risks

- Ouroboros's dialogue summaries and era summaries are still LLM-produced and
  recursively merged; source binding detects missing generations, not semantic
  drift inside a successful summary.
- Its ten-block FIFO scratchpad can evict live material if promotion misses it;
  the eviction journal preserves auditability but does not keep the fact in the
  active working set. Concurrent consolidation can also exceed the nominal cap
  by one block because the merge does not reapply it.
- Topic-based knowledge can be overwritten/appended with history, but the code
  does not establish a universal contradiction, expiration, or supersession
  model.
- Always-on identity/scratchpad/index/dialogue increases prompt footprint and
  interference risk. For Orchestra's roughly ten active agents, copying that
  entire architecture would be disproportionate.
- The #110 CL-Bench comparison remains nominally `0.2301` vs `0.223` across six
  task families without a published significance estimate; the mechanics above
  stand on source inspection, not on the SOTA claim [45].

## 6. What this changes — and what it does not

### Supported now

- Treat raw recent preservation and deterministic evidence as first-class
  candidate mechanisms.
- Keep a fresh domain-specific holdout as the decision gate.
- Use one external trajectory subset as a separate external-validity diagnostic.
- Explore a tiny typed hot state and explicit fact promotion; retain Orchestra
  RAG as cold memory.

### Not supported now

- Do not transfer Kesha full; #106 already produced NO-GO.
- Do not claim `recommended-prompt.txt` is validated; it remains an untested
  composite.
- Do not choose the final 2–3 candidates before the gate.
- Do not run LongBench/InfiniteBench/CL-Bench for prestige.
- Do not replace Orchestra memory with Ouroboros's full-injection system.
- Do not modify production `COMPACT_PROMPT`.

## 7. Confidence and remaining uncertainty

| Finding | Confidence | Evidence reason |
|---|---|---|
| Raw-tail preservation is common in mature open harnesses | **CONFIRMED** | independent primary implementations in Codex, Aider, OpenHands, Cline |
| It will improve Orchestra last-three exact recall | **LIKELY** | mechanism matches the failure and external practice, but no fresh Orchestra ablation yet |
| Cline-style deterministic file ledger reduces exact file loss/fabrication | **LIKELY** | direct code mechanism; our judge-ledger incident proves evidence matters, but no candidate run |
| A foreign benchmark can replace our holdout | **REFUTED** | no native contract matches compact handoff invariants |
| LongMemEval-V2/MEMTRACK add useful external validity | **LIKELY** | close dynamic-state contracts; setup/subset not run |
| Ouroboros typed hot/cold lifecycle is better than passive retrieval for current task state | **LIKELY** | direct source mechanics and clear contract gap; effect/cost unmeasured in Orchestra |
| Full Ouroboros memory should be ported | **REFUTED for current MVP scope** | always-on footprint/complexity and recursive drift without a measured benefit |

## Sources

Evidence tiers: **T1 direct measurement**, **T2 primary source**, **T3 ≥2
independent secondary sources**. All URLs below were opened or their pinned
source content was inspected in this session.

1. [Codex compaction prompt @ `ee0247f9`](https://github.com/openai/codex/blob/ee0247f95a6fe2b094ba2253d82cae2a2b4c2dff/codex-rs/prompts/templates/compact/prompt.md) — **T2 primary code**.
2. [Codex compaction mechanics @ `ee0247f9`](https://github.com/openai/codex/blob/ee0247f95a6fe2b094ba2253d82cae2a2b4c2dff/codex-rs/core/src/compact.rs) — **T2 primary code**.
3. [Aider summary prompt @ `5dc9490b`](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/prompts.py) — **T2 primary code**.
4. [Aider history summarizer @ `5dc9490b`](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/history.py) — **T2 primary code**.
5. [OpenHands summarizing prompt @ `2f276539`](https://github.com/All-Hands-AI/software-agent-sdk/blob/2f27653959f7596769427ee4657247b32c94504e/openhands-sdk/openhands/sdk/context/condenser/prompts/summarizing_prompt.j2) — **T2 primary code**.
6. [OpenHands rolling condenser @ `2f276539`](https://github.com/All-Hands-AI/software-agent-sdk/blob/2f27653959f7596769427ee4657247b32c94504e/openhands-sdk/openhands/sdk/context/condenser/llm_summarizing_condenser.py) — **T2 primary code**.
7. [Cline shared compaction @ `94f897f5`](https://github.com/cline/cline/blob/94f897f55933c86a08578385a019211e01a1a36d/sdk/packages/core/src/extensions/context/compaction-shared.ts) — **T2 primary code**.
8. [Cline manual canonical compaction @ `94f897f5`](https://github.com/cline/cline/blob/94f897f55933c86a08578385a019211e01a1a36d/apps/cli/src/runtime/interactive/compaction.ts) — **T2 primary code**.
9. [Continue IDE conversation compaction @ `5522c6f4`](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/core/util/conversationCompaction.ts) — **T2 primary code**.
10. [Continue CLI compaction @ `5522c6f4`](https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/extensions/cli/src/compaction.ts) — **T2 primary code**.
11. [SWE-agent history processors @ `3ea751c0`](https://github.com/SWE-agent/SWE-agent/blob/3ea751c087f32b16e039a2233dd6eefecef325d5/sweagent/agent/history_processors.py) — **T2 primary code**.
12. [Claude Code context-window docs](https://code.claude.com/docs/en/context-window) — **T2 official docs**.
13. [Claude Code sessions docs](https://code.claude.com/docs/en/sessions) — **T2 official docs**.
14. [Claude Code hooks/compact instructions](https://code.claude.com/docs/en/hooks) — **T2 official docs**.
15. [Anthropic: effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — **T2 provider engineering article**.
16. [Anthropic session memory and compaction cookbook](https://platform.claude.com/cookbook/misc-session-memory-compaction) — **T2 official cookbook**.
17. [OpenAI Responses compaction guide](https://developers.openai.com/api/docs/guides/compaction) — **T2 official docs**.
18. [`#106` primary analysis](results/analysis.json) and [research report](research.md) — **T1 direct measurement**, N=21/variant holdout, seven fixture clusters.
19. [LongBench official repository](https://github.com/THUDM/LongBench) — **T2 primary benchmark**.
20. [InfiniteBench official repository](https://github.com/OpenBMB/InfiniteBench) — **T2 primary benchmark**.
21. [LoCoMo official repository](https://github.com/snap-research/locomo) — **T2 primary benchmark**.
22. [LongMemEval-v1 official repository](https://github.com/xiaowu0162/longmemeval) — **T2 primary benchmark**.
23. [LongMemEval-V2 official repository](https://github.com/xiaowu0162/LongMemEval-V2) — **T2 primary benchmark**.
24. [MEMTRACK paper](https://arxiv.org/abs/2510.01353) — **T2 primary paper**.
25. [STATE-Bench official repository](https://github.com/microsoft/STATE-Bench) — **T2 primary benchmark**.
26. [OdysseyBench official repository](https://github.com/microsoft/OdysseyBench) — **T2 primary benchmark**.
27. [CL-Bench official repository](https://github.com/pgasawa/continual-learning-bench) — **T2 primary benchmark**.
28. [Ouroboros context layout @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/context_layout.py) — **T2 primary code**.
29. [Ouroboros context assembly @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/context.py) — **T2 primary code**.
30. [Ouroboros memory store @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/memory.py) — **T2 primary code**.
31. [Ouroboros consolidator @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/consolidator.py) — **T2 primary code**.
32. [Ouroboros control memory tools @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/tools/control.py) — **T2 primary code**.
33. [Ouroboros knowledge tools @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/tools/knowledge.py) — **T2 primary code**.
34. [Orchestra RAG implementation](../../../app/rag.py) — **T2 primary code**.
35. [Orchestra `search_memory` MCP](../../../app/mcp_stdio.py) — **T2 primary code**.
36. [Ouroboros project fact isolation @ `ca76d76`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/project_facts.py) — **T2 primary code**.
37. [Orchestra RAG service](../../../app/rag_service.py) — **T2 primary code**.
38. [Orchestra merge-triggered backfill](../../../app/routes/sessions.py) — **T2 primary code**.
39. [SummN: multi-stage summarization](https://aclanthology.org/2022.acl-long.112/) — **T2 primary paper**.
40. [OpenAI recursive book summarization](https://arxiv.org/abs/2109.10862) — **T2 primary paper**.
41. [Context-Aware Hierarchical Merging](https://aclanthology.org/2025.findings-acl.289/) — **T2 primary paper**.
42. [MemGPT](https://arxiv.org/abs/2310.08560) — **T2 primary paper**.
43. [Generative Agents](https://arxiv.org/abs/2304.03442) and [ReSum](https://arxiv.org/abs/2509.13313) — **T2 primary papers**.
44. [ACON: Optimizing Context Compression](https://www.microsoft.com/en-us/research/publication/acon-optimizing-context-compression-for-long-horizon-llm-agents/) — **T2 primary paper/publication page**.
45. [`#110` Ouroboros research](../110/research.md) — **T1 direct repository/source inspection and published-result audit**.
