# Research: Sol vs Opus for non-technical worker roles

**Date:** 2026-07-24 · **Role:** full-cycle Phase 1 (research-only) · **Requested by:** Orchestra-orchestrator

## Question (framed)

- **Context:** Orchestra routes non-technical worker roles — marketer (content/strategy/copy), sales (cold email/scripts/pitch), designer (design prompts/UX-copy/specs), business-analyst (market research/reports) — to a model.
- **Change under test:** Route them to GPT-5.6 Sol (Codex) vs keep on Claude Opus (4.8 or 4.6).
- **Baseline:** Current default = Sol (`gpt5.6sol`) for all worker roles.
- **Outcome:** Decided by writing quality, persuasion, reasoning, and **Russian-language** text quality — from benchmarks (LMArena creative/IF, EQ-Bench, HLE) + native-speaker reviews. User works the **Russian market** → Russian quality is the tie-breaker.

## Hypotheses considered

- **H1** — Claude Opus beats Sol on creative/persuasive writing (Claude's known prose strength). → **CONFIRMED for long-form/prose, but with a twist: the winning Claude is 4.6, not 4.8.**
- **H2** (competing) — Sol matches/beats on structured business analysis & reasoning. → **REFUTED for depth; Claude wins analytical depth. Sol wins breadth/live-web/tool-calling.**
- **H3** (competing) — For Russian, one model clearly dominates. → **REFUTED — genuinely contested; no clean winner. Sol has zero Russian data.**
- **H4** (the orchestrator's implicit assumption) — "marketer/sales on 4.8 not 4.6." → **REFUTED — 4.6 outranks 4.8 on every creative/writing board found.**

Falsifier applied: I looked for boards where the "loser" wins in the relevant category. Found exactly that — Sol *beats* Opus 4.8 on LMArena creative writing, and Opus 4.6 *beats* 4.8. Both surprises survived.

---

## Findings (atomic claims, sourced)

### F1 — On creative writing, Opus 4.6 > Opus 4.8. CONFIRMED (primary leaderboard).
LMArena Creative Writing Elo [1]: Fable 5 **1508** > Opus 4.6 Thinking **1500** > Opus 4.7 Thinking 1488 > Opus 4.6 1478 > **GPT-5.6 Sol Xhigh 1471 (±19)** > **Opus 4.8 Thinking 1463** > **Opus 4.8 1459**.
→ Opus 4.8 is a **creative-voice regression** vs 4.6 (optimized for honesty/coding). Confirmed by a second board: llm-stats "best AI for writing" (2026-07-24) ranks **Opus 4.6 #1 (31.9)**, Opus 4.8 not even listed [2].
*Confidence: CONFIRMED — primary Arena data + second aggregator agree on ordering.*

### F2 — Sol ≈ Opus 4.8 on creative, both behind 4.6/Fable5. CONFIRMED.
On LMArena creative, Sol Xhigh (1471) sits *above* Opus 4.8 (1459) but its error bar is wide (±19 vs ±9). On overall text [1]: Sol XHigh **1485** essentially ties Opus 4.8 Thinking **1484**, both trailing the 4.6/4.7/Fable-5 cluster (1494–1507).
*Confidence: CONFIRMED for ordering; the Sol-vs-4.8 gap is within overlapping error bars (a near-tie).*

### F3 — Both Sol and Opus 4.8 are positioned as CODING/agentic models, not writers. CONFIRMED.
Every head-to-head review (emergent.sh, layer3labs, buda, codingfleet, benchlm) benchmarks them on SWE-bench, Terminal-Bench, FrontierMath, GPQA — **not prose** [3][4][5]. Anthropic positions 4.8 for "reliability/coding/agent sessions"; OpenAI positions Sol for "planning, terminal, long-horizon agents, security." Neither is marketed as a writing model.
*Confidence: CONFIRMED — multiple primary/secondary sources, unanimous.*

### F4 — Short-form conversion copy tilts to GPT; long-form/brand-voice tilts to Claude. UNCERTAIN (wrong-model caveat).
Blind professional-editor test (talkory, 2026-04-16): Claude won Long-Form 5/5 and Creative 5/5; **GPT-5.4 won Marketing-Copy 5/5 and Business-Emails 5/5** [6]. **CAVEAT (Codex caught):** this test used **Claude Sonnet 4.6, NOT Opus 4.6**, and **GPT-5.4, not Sol** — so it does NOT validate Opus 4.6 vs Sol. It only supports the *directional* split (Anthropic-family→long-form, GPT-family→short-form conversion). Benchmark-level split repeated elsewhere: fiction→Claude, marketing/ad copy→GPT (format adherence, IFEval 96) [3][7].
*Confidence: UNCERTAIN for the exact matchup (wrong model versions); LIKELY only for the directional long-form-vs-short-form split.*

### F5 — Cold email: Claude for enterprise/natural, GPT for volume/SMB + creative sales content. LIKELY.
Claude writes shorter (50–70w vs GPT 80–120w), more natural cold emails, real personalization vs GPT's "fake-personalisation opener" [8]. SDR-workflow test rated personalization a **TIE**, with an audience split: **Claude for enterprise outreach + lead-research (context window), GPT for SMB/startup + creative hooks** [9]. **Counter-signal (Codex caught, previously under-weighted):** that same source [9] explicitly says **ChatGPT wins creative Sales Content and brand-voice matching**, Claude wins research — so the "Claude for sales quality" read is only half the story; GPT wins the *creative/brand-voice* half. Versions unnamed (product-level, not model-level).
*Confidence: LIKELY for the enterprise-vs-SMB split; the brand-voice sub-claim is genuinely split, not Claude-favoring.*

### F6 — Market research & business analysis: depth→Claude, breadth→GPT. LIKELY.
Claude wins complex multi-constraint reasoning, long-form report coherence, large-document ingestion (200K ctx, full data-export in one pass), conservative uncertainty-flagging. GPT wins real-time web + tool-calling [3]. Reasoning proxy: GPT-5.6 Sol GPQA 94.6% vs Opus 4.8 93.6% (near-tie) [4].
*Confidence: LIKELY — consistent theme across sources; not a controlled benchmark.*

### F7 — RUSSIAN: genuinely contested; Sol has ZERO data. UNCERTAIN (by design — conflicting evidence).
- **No official leaderboard** breaks out per-language Russian for these versions. OpenAI's GPT-5 System Card multilingual-MMLU covers 14 languages — **Russian is absent** [10]. Anthropic doesn't publish Opus-4.x Russian MMLU.
- **Claude camp** (natural style/tone): vc.ru — Claude "most stylistically precise," **92% tone-match vs ChatGPT 74%**; GPT flagged for bureaucratic template phrases ("в заключение", "таким образом") [11]. Habr 2-mo hands-on: Claude "holds style better, less templated" [12]. **STALE-MODEL CAVEAT (Codex caught):** vc.ru [11] tested **GPT-4o vs Claude 3.5 Sonnet**; Habr [12] is a 2025 product-level comparison (4o / Sonnet 4 / Opus 4). Neither tests current Opus 4.6/4.8 or Sol — so these support "Claude-family has historically written more natural RU style," NOT a current-version verdict.
- **GPT camp** (strict grammar): ofox.ai rates **GPT-5.4 superior for RU** — "надёжная грамматика (падежи, согласование)," natural, no machine-phrasing; recommends GPT for RU copy, Claude only for code [13]. Another vc.ru review: "ChatGPT лучше всех работает с русским... Claude иногда допускает **стилистические кальки с английского**."
- **Both lose to domestic GigaChat Ultra** on raw error-rate — RuQualBench: GigaChat 0.2 err/1k tokens beats Opus 4.5, GPT-5, Gemini 3; benchmark author called **GPT-5 "terrible" on Russian** [14].
- **Sol (GPT-5.6-Sol) specifically: no Russian data at all.** Best proxy is GPT-5.x, which is mixed-to-weak.
*Confidence: UNCERTAIN — two failure modes (Claude=calques, GPT=bureaucratic templates); reviewers disagree by what they weight. Sol untested.*

---

## Counter-evidence (actively sought, presented)

- **GPT can win prose too:** one aggregated review calls GPT-5's voice "the most human of the three"; a Tom's Guide story-writing head-to-head had GPT produce "a vivid, funny character… genuinely surprising twist" vs Claude "slightly less vivid" (low tier, not primary-fetched).
- **GPT-5.6 closed the writing gap:** saas-hackers notes 5.6 is "meaningfully better at writing, less over-formatted boilerplate."
- **One vendor A/B inverts the ad-copy view:** a copywriting-tool vendor claimed Claude got **+23% CTR / +42% B2B conversion** over GPT — but it's a vendor blog, unverified, treat as suspect.
- **On Russian, the conflict is real, not noise** — F7 presents both camps; do not paper over it.

---

## Verdict — TASK-LEVEL routing (revised after Codex adversarial review)

The first draft recommended role-level routing to Opus 4.6. Codex correctly rejected that as over-generalized: it bundled marketing/sales/BA/design/Russian/quota-economics onto one narrow LMArena creative-writing signal. **The evidence supports TASK-level, not role-level, routing — and the default depends on the Codex quota tier.** Full dissent preserved in `codex-review.md`.

**What actually survives as CONFIRMED:** Opus 4.6 beats Opus 4.8 on *creative/voice-sensitive prose* (F1, primary Arena, 4.6-Thinking 1500±7 vs 4.8-Thinking 1463±9 — a real snapshot gap, not noise). Everything broader is weaker.

| Task (not role) | Route to | Why | Confidence |
|---|---|---|---|
| Final voice-sensitive brand/creative prose | **Opus 4.6** | Only clean signal: 4.6 > 4.8 > Sol on Arena creative | CONFIRMED (4.6>4.8), LIKELY (>Sol) |
| Short-form ads / CTA / high-volume email A/B | **Sol** | Punchy conversion copy, format adherence, volume; separate quota | LIKELY |
| Market research — breadth, live web, tool-calling | **Sol** | Real-time web + tools | LIKELY |
| Business analysis / deep research / doc synthesis / correctness-sensitive specs | **Opus 4.8** | Anthropic 4.8 notes: analysis, research, citation precision, uncertainty detection, info density [15]. NOT a creative-voice task | LIKELY |
| General non-technical default (all roles) | **Sol** (under 20× Codex) / **conditional** (under 5×) | See quota logic below | — |
| Russian-language copy | **No winner — test in-house** | All RU sources are stale-model (GPT-4o / Claude 3.5) or vendor-opaque; Sol untested. NO current-version RU verdict exists | UNCERTAIN |

### The 4.8-vs-4.6 answer (orchestrator's explicit question), corrected
It's **task-dependent, not "always 4.6":**
- **Voice-sensitive creative prose → 4.6** (measurable creative-voice edge over 4.8; same price $5/$25).
- **Analytical/BA/research/spec work → 4.8** (Anthropic 4.8 improved exactly these: analysis, deep research, citation, uncertainty [15]; matches repo's existing full-cycle/research routing).
So the orchestrator's "marketer/sales on 4.8" is *right for the analytical sales/BA half* and *wrong for the brand-voice half*. Don't pick one Opus for the whole role — pick per task.

### Quota economics is FIRST-ORDER, not a footnote (Codex's strongest point)
Subscriptions are sunk cost → the real marginal price is **scarce quota**, not API-equivalent dollars. Sol runs on a **separate Codex pool**; routing non-tech roles to Claude burns the **Claude limits that were halved** in the $200→$100 downgrade (CLAUDE.md 07-18). So the default is *conditional on deployment tier*:
- **Planned 20× Codex / 5× Claude:** **Sol stays the default non-tech worker.** Moving routine workers to Claude defeats the subscription strategy. Escalate to Opus *only* for final brand copy (4.6) or deep analysis (4.8).
- **Current 5× Codex** (lasts ~2.5 working days, Claude has ~70% headroom): Claude can absorb overflow — route more to Opus when Codex saturates.
- **Decision threshold (missing, must be measured):** route to Opus only when the *measured* rework saved (native-blind rating uplift, editing-time, retry/failure count) exceeds the opportunity cost of the scarcer pool. A marginal, error-bar-overlapping leaderboard gap is NOT sufficient justification on its own.

### Recommended policy (defensible, quota-aware)
1. **Sol = default** non-technical worker under the planned 20× Codex strategy.
2. **Escalate final brand/voice copy → Opus 4.6** (the one CONFIRMED quality edge).
3. **Route BA / deep research / doc synthesis / correctness-sensitive specs → Opus 4.8.**
4. **If Codex stays at 5× and saturates → use Claude as capacity overflow.**
5. **Do NOT claim a Russian winner** before an in-house blind native test on real copy (this is the user's market — highest-value experiment to run next).

---

## Risks / edge cases (for any config change)

- **Cost/limits:** Opus 4.6 burns Claude Max limits; Sol burns separate Codex pool. Routing 4 non-tech roles to Opus 4.6 shifts load onto Claude limits (already halved after $200→$100 downgrade — see CLAUDE.md 07-18). Weigh limit budget.
- **Leaderboard volatility:** 4 frontier releases in the 6 weeks before this research; Sol GA'd 2026-07-09, so its non-tech scores are early/unsettled (wide error bars). Re-check in ~1 month.
- **No persuasion/marketing benchmark exists** — F4/F5/F6 rest on one blind editor test + practitioner consensus, not controlled science. Treat CTR/conversion % from vendor blogs as marketing.
- **Russian is the weakest-evidence axis** and the most important to the user — recommend a quick in-house A/B on real copy before committing.
- **Roles don't exist yet** in pipeline.yaml (only orchestrator/sub-orchestrator/worker/full-cycle). This is model-routing guidance for *when* those roles are created, or for the orchestrator picking a model per non-tech task today.

---

## Sources (all fetched this session, by me or a sub-researcher)

1. https://arena.ai/leaderboard/text/creative-writing — LMArena Creative Writing Elo (PRIMARY)
2. https://llm-stats.com/leaderboards/best-ai-for-writing — writing leaderboard, Opus 4.6 #1 (2026-07-24)
3. https://www.layer3labs.io/comparisons/gpt-5-6-vs-claude-opus-4-8 + /chatgpt-vs-claude-for-business
4. https://emergent.sh/learn/gpt-5-6-vs-claude-opus-4-8 ; https://docsbot.ai/models/compare/gpt-5-6-sol/claude-opus-4-8
5. https://benchlm.ai/compare/claude-opus-4-8-vs-gpt-5-6-sol
6. https://www.talkory.ai/blog/best-ai-for-writing-in-2026-gpt-5-4-vs-claude-4-6-vs-gemini-3-1-full-test — blind editor test
7. https://benchlm.ai/blog/posts/best-llm-writing ; https://evy.so/compare/best-llms-for-writing/ — Opus 4.6 Arena IF 1500 "brand-voice"
8. https://www.saas-hackers.com/blog/is-claude-or-chatgpt-better-for-cold-emails
9. https://marketbetter.ai/blog/claude-vs-chatgpt-sales-teams/
10. https://arxiv.org/html/2601.03267v1 — GPT-5 System Card, Russian absent from 14-lang MMLU
11. https://vc.ru/ai/3006515-chatgpt-claude-gigachat-sravnenie — Claude 92% RU tone-match
12. https://habr.com/ru/articles/915212/ — Claude holds RU style better
13. https://ofox.ai/ru/blog/luchshaya-llm-dlya-russkogo-yazyka-sravnenie-2026/ — GPT-5.4 better RU grammar
14. https://lenta.ru/news/2026/04/30/gigachat-zanyal-pervoe-mesto-v-benchmarke-ruqualbench/ — GigaChat #1, GPT-5 weak
15. https://www.anthropic.com/news/claude-opus-4-8 — Opus 4.8 improvements: analysis, deep research, citation precision, uncertainty detection (cited by Codex)

## Codex adversarial review outcome (2026-07-24)

Ran `codex_review` to falsify the load-bearing conclusion. Codex **rejected the role-level "route all non-tech to Opus 4.6"** and I **conceded** — its critique held on verification:
- **F4 citation error** — talkory blind test used Claude *Sonnet* 4.6 + GPT-5.4, not Opus 4.6 vs Sol. Downgraded F4 to directional-only.
- **F5 counter-signal** — same sales source says GPT wins creative/brand-voice content; I'd cherry-picked the enterprise half. Corrected.
- **Russian sources stale** — vc.ru = GPT-4o vs Claude 3.5; Habr = 2025. No current-version RU verdict. Dropped the "lean 4.6" for RU.
- **Quota is first-order** — Sol = separate Codex pool; Claude limits halved. Default must be conditional on 5× vs 20× tier. Folded into verdict.
- **4.8 has real analytical strengths** — bundling BA into "4.6" was wrong. Split to task-level.

Result: recommendation changed from *role-level Opus 4.6* → *task-level, Sol-default-under-20×, escalate 4.6 for brand voice / 4.8 for analysis, no Russian winner*. This is the stronger conclusion. Codex verdict + full findings in `codex-review.md`.

**Data gaps:** EQ-Bench live tables JS-rendered (secondary-only); no MMLU-Pro humanities subscore published for either model; no dedicated persuasion/marketing benchmark exists; no Russian head-to-head number for these exact versions; Sol has zero Russian evaluation.
