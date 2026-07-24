Ну да, операционную стоимость положили в «риски» уже после выбора победителя — очень научно. 😏

## Summary

The fleet-wide conclusion is not supported. A narrower claim survives: **Opus 4.6 is a defensible provisional choice for voice-sensitive creative prose over Opus 4.8**. The document does not establish that marketing, sales, BA, and design should all default to 4.6, nor that Sol should lose default status.

Direct answers:

1. LMArena supports the point-in-time creative ordering, but it is not load-bearing enough for role-wide routing.
2. 4.6 over 4.8 is sound for creative prose, not for analysis-heavy BA/research work.
3. “Russian: uncertain” is honest; the subsequent “lean 4.6 / best Russian style” is not.
4. The separate Codex quota is a first-order constraint that may reverse the recommendation—especially under the planned Codex 20× / Claude 5× setup.

No blocking findings under the supplied crash/corruption/security definition.

## Findings

### [suggestion] Quota economics is outside the decision function, then buried after the verdict

The stated outcome criteria omit capacity entirely ([research.md:10](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:10)); the categorical Claude routing appears first ([research.md:87](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:87)), while separate quotas are acknowledged only afterward as a risk ([research.md:96](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:96)).

That is not a minor caveat. These subscriptions are sunk costs, so the real marginal price is scarce quota, not API-equivalent dollars. The repository’s target strategy is Codex 20× for workers and Claude 5× for orchestrators; measured Claude utilization without workers is about 30% ([CLAUDE.md:78](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/CLAUDE.md:78)). OpenAI documents roughly 75–450 Sol turns per five hours at 5× versus 300–1800 at 20×, with possible weekly caps ([official Codex pricing](https://learn.chatgpt.com/docs/pricing)).

Consequences:

- Under the planned 20× Codex / 5× Claude state, Sol should remain the default unless its measured rework penalty exceeds the opportunity cost of Claude quota.
- Under the current 5× state, where Codex reportedly lasts only ~2.5 working days while Claude has headroom, routing selected work to Claude may balance capacity.
- Therefore “default Sol or not” must be conditional on the deployment tier and live headroom. The present unconditional recommendation is not decision-complete.

### [suggestion] The Arena ordering is real as a snapshot, but over-generalized and statistically over-described

The raw numbers are reported correctly. However:

- Sol has only 1,062 creative-writing votes versus roughly 10,800 for 4.6 and 5,500 for 4.8, explaining its ±19 uncertainty.
- Sol XHigh 1471±19 versus 4.8 Thinking 1463±9 is plainly unresolved.
- 4.6 Thinking 1500±7 versus 4.8 Thinking 1463±9 is a meaningful snapshot difference, so the narrow 4.6 preference is not merely noise.
- But non-thinking 4.6 and Sol are effectively near-tied, and displayed rank spreads overlap substantially. The document collapses thinking/non-thinking and high/xhigh configurations into model-family conclusions.

More importantly, LMArena defines creative writing as stories, poems, jokes, memes, philosophical responses, and unusually creative emails—not ordinary marketing, sales, BA reports, or UX specifications ([category methodology](https://arena.ai/blog/arena-category/)). Thus [research.md:25](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:25) supports “try 4.6 for creative voice,” not “route four professions to 4.6.”

“Confirmed ordering” is fair. “Confirmed creative-voice regression” implies a broader causal and durable result than this evidence establishes.

### [suggestion] The 4.6 recommendation improperly absorbs analysis-heavy roles where 4.8 has contrary evidence

The document says 4.8’s advantages are irrelevant to non-technical work ([research.md:83](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:83)). That is false for business analysts, research, document synthesis, and possibly design specifications.

Anthropic’s 4.8 release evidence specifically reports improvements in translation, deep research, analysis, professional judgment, information density, uncertainty detection, and citation precision—not merely coding ([Anthropic’s Opus 4.8 announcement](https://www.anthropic.com/news/claude-opus-4-8)). The repository’s current routing policy correspondingly assigns 4.8 to research and deep document analysis.

The defensible split is task-level:

- 4.6: final voice-sensitive prose and brand copy.
- 4.8: research, BA, document synthesis, visual analysis, and correctness-sensitive specifications.
- Sol: general default, breadth/tool work, iterations, and short-form variants.

Bundling these into “non-technical writing” destroys the distinction the evidence actually supports.

### [suggestion] Several supporting evaluations compare the wrong models or products

The most serious example is F4 ([research.md:38](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:38)). The cited blind editor test evaluated **Claude Sonnet 4.6**, not Opus 4.6, against GPT-5.4, not Sol ([Talkory test](https://www.talkory.ai/blog/best-ai-for-writing-in-2026-gpt-5-4-vs-claude-4-6-vs-gemini-3-1-full-test)). It cannot validate Opus 4.6 over Sol.

Likewise, the sales sources compare unspecified Claude/ChatGPT products and mix model behavior with interfaces, context limits, image generation, and web access. One cited source explicitly says ChatGPT wins creative sales content and brand-voice matching, while Claude wins research ([MarketBetter comparison](https://marketbetter.ai/blog/claude-vs-chatgpt-sales-teams/)). The document preserves its enterprise-email split but does not carry this stronger counter-signal into the marketer default.

The llm-stats board is also not independent confirmation: its methodology incorporates LMArena voting, and 4.8 being absent from its model set is not evidence that 4.8 lost ([llm-stats methodology](https://llm-stats.com/leaderboards/best-ai-for-writing)).

### [suggestion] The Russian uncertainty label is honest; the “lean 4.6” routing is unsupported

The applicable evidence is weaker than the document admits:

- The favorable vc.ru comparison tested GPT-4o against Claude 3.5 Sonnet, not any current candidate ([vc.ru test](https://vc.ru/ai/3006515-chatgpt-claude-gigachat-sravnenie)).
- The Habr report is a 2025 product-level comparison involving 4o, Sonnet 4, and Opus 4 ([Habr article](https://habr.com/ru/articles/915212/)).
- The only cited source directly including Opus 4.6 says GPT-5.4 has the best Russian generation and recommends 4.6 mainly for coding/analysis. Its methodology is opaque and vendor-affiliated, but its direction opposes the document’s lean ([Ofox comparison](https://ofox.ai/ru/blog/luchshaya-llm-dlya-russkogo-yazyka-sravnenie-2026/)).
- RuQualBench tests older GPT-5 and Opus 4.5, focuses on linguistic error rate, and uses Gemini 2.5 Pro as judge; it does not resolve Sol versus 4.6/4.8 ([RuQualBench report](https://lenta.ru/news/2026/04/30/gigachat-zanyal-pervoe-mesto-v-benchmarke-ruqualbench/)).

Thus “no exact evidence” is correct. But [research.md:80](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:80) and [research.md:87](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-models/docs/tasks/non-tech-models/research.md:87) quietly convert that absence into an Opus preference. The honest result is **no Russian lean** until a native blind evaluation.

### [question] Which operating state is this recommendation for?

Is routing being decided for:

- Current Codex 5×, where Codex is already the constrained pool; or
- Planned Codex 20× / Claude 5×, where moving routine workers to Claude defeats the subscription strategy?

Without fixing that scenario, the same evidence rationally produces opposite routing decisions.

### [question] What measured quality penalty is sufficient to consume Claude quota?

The document never defines a decision threshold. A small MVP evaluation should measure representative Russian tasks by role using blind native ratings, correction time, and failure/retry count. The relevant question is not “which output wins once?” but “does 4.6 save enough human editing or failed turns to justify consuming the scarcer pool?”

Without that threshold, leaderboard differences are decorative rather than operational.

## Verdict

**Reject the load-bearing conclusion as written.**

Retain only this narrower result: **Opus 4.6 is the best current candidate for final, voice-sensitive creative prose, especially versus 4.8, pending Russian validation.**

The simplest defensible policy is:

- Sol remains the default non-technical worker under the planned 20× Codex strategy.
- Escalate final brand/voice copy to Opus 4.6.
- Route BA, deep research, document analysis, and correctness-sensitive specs to Opus 4.8.
- If Codex remains at 5× and saturates, use Claude as capacity overflow.
- Do not claim a Russian winner before the in-house blind test.

The document found a useful creative-writing signal, then made it carry marketing, sales, analysis, design, Russian, and subscription economics on its back. That leaderboard horse is now visibly asking for workers’ compensation. 🐴
