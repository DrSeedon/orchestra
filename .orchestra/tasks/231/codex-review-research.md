## Summary

The document identifies real coordination costs, but its strongest conclusions exceed the evidence. The main problems are: the advertised two-factor model omits tool-round trips already present in the report’s own formula; the barrier counterfactual is not reproducible from the stated grouping rule; child execution spend is compared with coordination spend; and the proposed JOIN experiment does not isolate context size.

## Findings

suggestion: §5.1 — “Каждая из 27 архитектур двигает ровно один множитель.”

The claimed decomposition into exactly two independent multipliers contradicts the document’s own measured model: “`стоимость ≈ Σ_ходов (размер контекста × число вызовов инструментов × цена токена)`.” Tool-call count is a third driver, and §3.5 shows it varies materially by trigger: 15 calls for a child versus 3 for a parent. It is not absorbed by activation count: one activation can contain many context rereads. Token price, output/reasoning tokens, and cache behavior also vary. The 137-token message versus 1.32M cache-read observation establishes that message length is small; it does not establish a two-factor cost law or independence between its factors.

suggestion: §3.7 — “группа — пробуждения родителя отчётами ≥2 РАЗНЫХ детей в окне 30 минут”

The grouping rule is underspecified and can overcount eliminable wakeups. It does not say whether the window is fixed, rolling, or transitively extended. Under a rolling rule, reports at minutes 0, 25, and 50 could become one group despite spanning 50 minutes. More importantly, “same parent + different children + 30 minutes” does not prove that the children belong to the same fan/JOIN; unrelated tasks under a busy coordinator would be merged counterfactually. The estimate needs fan identity or another causal grouping key, plus a sensitivity analysis across window sizes.

suggestion: §3.7 — “барьер оставил бы из группы одно пробуждение (самое дорогое), остальные снял.”

Keeping the most expensive observed turn is not the counterfactual cost of a barrier. A post-barrier synthesis turn may be more expensive because it receives all reports, invokes different tools, and occurs later with a larger context; conversely, some observed “kept” work may have been an avoidable partial synthesis. Selecting the maximum mechanically biases saved dollars downward within the chosen groups, while the grouping rule can bias the eligible set upward. Calling the resulting `$261.15` confirmed or a lower bound is therefore not supported.

suggestion: §3.7 — “это 5.61% всего расхода платформы”

The percentage is internally inconsistent with the stated totals. The report gives total spend as `$4765.57`; `$261.15 / $4765.57 = 5.48%`, not 5.61%. A second denominator inconsistency appears in §3.2: “`$3391.45 = 72.8% всего расхода платформы`,” whereas the same total yields 71.2%. The document should name the denominator used for each percentage and reconcile excluded/unclassified spend.

suggestion: §3.1 + §11.1 — “Самая дорогая — пробуждение РЕБЁНКА родителем: $2687.95, 56.4% всего расхода.”

This is mostly execution cost, not demonstrated coordination overhead. A child awakened with an implementation or research assignment then performs the actual work; charging its whole turn to “opening its eyes” makes useful computation indistinguishable from coordination. The later admission—“`Ребёнок-табличник стоит $0.09, ребёнок с десятью веб-запросами — $5`”—shows task content drives this category. Therefore the platform-wide data does not reverse “children are cheap, dispatcher expensive”; it shows that full workers doing substantive work are expensive. The comparison requires matched task output or an estimate of the incremental coordination portion of child turns.

suggestion: §5.4 — “Pull-модель превращает самую дешёвую операцию классических систем в самую дорогую нашу.”

There is a direct counter-case: runtime-blocked pull or mailbox delivery consumed during an already necessary work turn. The source table says of Linda: “`A process suspended in in() or read() becomes runnable when a matching tuple becomes available in tuple space`.” That is notification-backed blocking, not repeated model polling. Likewise, a worker can claim its next task at the end of its current turn, amortizing the check into an activation that already exists. The report itself concedes runtime blocking works, so the conclusion should reject agent-driven polling, not pull/market architectures as a class.

suggestion: §5.4 — “Аукцион в нашей цене строго хуже иерархии.”

This conclusion applies the wakeup multiplier while ignoring the state multiplier that §5.1 declares equally load-bearing. The source table states: “`no global shared store`” and that the manager reranks bids against a local ranked list. A small stateless allocator could process bids cheaply, batch them, or do so without activating the expensive semantic parent. Contract Net may still be a poor fit, but `≥2N` manager events versus `N` parent events does not prove it is strictly more expensive in dollars.

suggestion: §9.1 + §9.3 — “оба на Luna со свежим пустым контекстом”

Neither experimental arm contains the large-context parent, so the experiment cannot estimate the causal effect of context size. Arm B additionally reveals the decisive comparison axis—“`где физически лежит файл памяти агента`” versus where the platform reads it—making A versus B a test of prompt specificity, not “ownership of the question” versus accumulated context. A pass establishes that a fresh collector can solve this one prepared diff; a failure may reflect model capability, table representation, or instructions. Add a parent-context arm with identical instructions and blind evaluation; otherwise all three stated outcomes admit unrelated explanations.

suggestion: §3.4 — “Это фальсификатор H1 в её грубой форме.”

Zero tool calls is not a valid proxy for an unproductive or unnecessary wakeup. A parent may read reports and produce a substantive synthesis, decision, or answer without tools; conversely, a needless wakeup can call several coordination tools. The calculation also pools all participant classes, while H1 concerns parent wakeups specifically. The stronger daily measure later reports “`чисто-координационные ходы — 89 из 218, $64.40 из $281.25 = 22.9%`,” which cuts against dismissing the hypothesis based on all-platform zero-tool turns. H1 should be tested through counterfactual necessity or output classification, not tool count.

suggestion: §5.2 — “Мы и Claude Code subagents — единственные две строки в выборке с N без барьера.”

This misstates the cited classical architectures. The source table says MapReduce has “`N task-completion-message wakeups in a failure-free round`” and Pregel has “`N worker-response wakeups at one barrier for N workers`.” Their user program or next superstep may advance once, but their coordinating master still processes N completions. The comparison silently changes which participant counts as “the coordinator.” Separate runtime bookkeeping activations from expensive model activations; otherwise the architectural classification is not like-for-like.

## Verdict

No blocking issue, since this is a research artifact rather than executable code. However, the main recommendation is not yet evidence-backed: the barrier savings need a reproducible causal grouping and corrected denominator; the cost model needs at least the tool-round-trip factor; and the JOIN experiment must include an actual large-context control arm. The current conclusions should be treated as hypotheses, not confirmed architecture choices.

## Round (2026-08-12T13:10:52Z)

## Round 2

Re-review status: prior findings 1, 2, 4, 5, 6, 7, 9 are fixed; finding 3 is still partially broken; finding 8 is improved but still broken. The arithmetic in the four §3.7 sensitivity rows and §7 checks against `$4785.21`.

## Findings

suggestion: §3.1 — NEW BUG — “`Координационная доля пробуждений детей ≈ 893 × $0.131 ≈ $137.94.`”

The displayed arithmetic is false: `893 × $0.131 = $116.98`, not `$137.94`. The claimed value implies `$0.15447` per activation. Since `$137.94` feeds directly into `$1031.56`, the document must show the actual weighted calculation or correct both figures. The other additions are arithmetically consistent: `$627.72 + $265.90 + $137.94 = $1031.56`, and `$1031.56 / $4785.21 = 21.56%`.

suggestion: §3.1/§3.9 — NEW BUG — “`Цена активации = цена одного вызова = ход / (вызовы + 1).`”

This does not identify a fixed activation price; it allocates the observed turn cost equally across model invocations by definition. The first completion can differ from later tool continuations in output/reasoning tokens, cache writes, model or pricing, and context size. §3.9 admits only the context-growth bias, not these other non-exchangeabilities. The narrow defensible label is “average cost per model invocation,” not “activation price.” Consequently `$137.94` is an allocation under an equal-invocation assumption, not measured coordination cost.

suggestion: §3.1 — STILL BROKEN from prior finding 5 — “`ходы родителя, разбуженного ребёнком (весь ход — координация)`”

Treating every child-triggered parent turn and every peer-triggered turn as coordination repeats the original category error on different rows. Such turns can contain substantive synthesis, review, diagnosis, or implementation decisions. Therefore “`Это и есть цена нашей координации: 21.6% расхода`” is stronger than the evidence. At most, `$1031.56` is spend on coordination-triggered turns plus an allocated activation share; it is an upper bound on coordination overhead.

suggestion: §3.7 — STILL BROKEN from prior finding 3 — “`Надбавка — центы; вычесть её из $208 нечем, но и исказить она не может.`”

The 137-token argument bounds only extra input-message tokens. It does not bound additional synthesis calls, output/reasoning, validation tools, or work created by jointly considering several reports. Thus the observed maximum is still not a valid barrier counterfactual, and “cannot distort” is unsupported. The sensitivity percentages themselves are correct: 2.06%, 3.49%, 4.35%, and 4.94%.

suggestion: §3.7/§9 — NEW BUG — “`Барьер даёт 2.1–4.9% в зависимости от дедлайна | CONFIRMED`”

The grouping count is now robust and reproducible, but dollar savings remain counterfactual because retained-turn cost is unobserved. “Confirmed” overstates the corrected evidence; “Likely” or “estimated, grouping confirmed” would match §3.7’s acknowledged limitation.

suggestion: §8.3/§12 — STILL BROKEN from prior finding 8 — “`C | накачанный до ~200–300K нерелевантным материалом | слепая, дословно как в A`”

The three-arm design isolates prompt specificity and irrelevant-context load, but it does not reproduce the parent’s accumulated relevant state. C tests distraction/context pressure, not whether task-relevant accumulated context enables the JOIN. It also does not resolve the recorded disagreement: A↔B operationalizes possession of a supplied hint, but cannot show that the parent must own or derive that hint. I do not accept the design as resolving “question ownership”; it only measures whether explicitly supplying the comparison axis helps.

question: §8.3 — NEW BUG — “`Прошло только B` / `Прошло только C` / `Не прошло ни одно`”

The decision table omits plausible outcomes: A+B pass, B+C pass, A+C pass, or all three pass. In particular, B passing alongside another arm does not establish the same inference as “only B.” Pre-register conclusions for all eight pass/fail combinations or reduce the claimed decision scope.

suggestion: §11 — NEW BUG/stale inference — “`сэкономлено ≈$0.9 ... (6%), что независимо совпадает с платформенной оценкой §3.7 при дедлайне 30–60 минут.`”

The rewritten §3.7 gives 4.35% at 30 minutes and 4.94% at 60 minutes, with an uncertain retained-turn counterfactual. A rough 6% single-task anecdote does not “independently coincide” with that range. This is a surviving first-edition conclusion and should be described only as directionally consistent.

## Verdict

Substantially improved, with seven prior findings resolved and all requested denominator arithmetic correct except the explicit `893 × $0.131` calculation. The remaining load-bearing issue is the new `$1031.56 = 21.6%` coordination claim: its activation component is an allocation, while its parent and peer components still include substantive work. The artifact is not ready to call that figure measured coordination cost, and the §8.3 experiment still does not isolate relevant accumulated context or fully resolve question ownership.
