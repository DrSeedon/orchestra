# V-1156 — Terra: sources and runtime limits (2026-10-31)

Exact target: **GPT-6.1 Terra**, `gpt-6.1-terra`, released 2026-10-26; not GPT-6.2.

## Pricing: separate contracts

All rates per million tokens, Standard speed/tier:

| Contract | Terra | GPT-6.1 Sol |
|---|---|---|
| API dollars: input / cached / cache write (30 min) / output | 1 / 0.05 / 1.25 / 5 | 2 / 0.1 / 2.5 / 10 |
| Codex subscription credits: input / cached / output | 25 / 1.25 / 125 | 50 / 2.5 / 250 |

API sources opened by this worker: [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol). API Terra input >272K applies 2× input/cache and 1.5× output for the whole request; 12-hour cache writes differ. Existing Codex accounting uses Standard API-equivalent prices, without a long-context tier calculation. It is virtual accounting, not a charge to this subscription; this task does not expand that accounting contract.

[Subscription pricing](https://learn.chatgpt.com/docs/pricing), opened here: no separate Codex cache-write charge; credit prices alone do not determine included subscription usage. Halving token rates does not establish halving actual task cost or subscription quota consumption.

## Published evaluations, not Orchestra measurements

- [Plotly primary Terra report](https://plotly.com/blog/gpt-6-1-terra-plotly-data-analytics-bench/), opened here, published Oct 26: Terra 40/43, $1.31, median 15 s; Sol 43/43, $2.61, median 18 s. Terra misses two hidden patterns and a causal question; no proven causal explanation was found. Default reasoning via OpenRouter, private synthetic analytics exam. [Methodology](https://plotly.com/blog/introducing-dataanalyticsbench/), opened here: one run/model, 43 English questions, 20M-row wind-energy warehouse, Plotly Studio Embedded; no error bars or confidence intervals. Private questions/answers limit independent reproduction. These dollars and timings are the publisher's harness results.
- [Artificial Analysis primary comparison](https://artificialanalysis.ai/models/releases/comparisons/gpt-6-1-terra-vs-gpt-6-1-sol), opened by the parent; safe findings supplied to this worker: Index v5.0, nine evaluations, matched Medium Terra/Sol 38/46, High 42/50, Max 51/55 (higher better). Terminal-Bench 4 Max 55.6%/56.1% (higher better). Weighted task cost Max $0.96/$1.27, but Sol High $0.59. Summary gives no repeat N or confidence intervals; descriptive differences, not percent intelligence or predictions for Orchestra. This worker did not refetch AA or run evaluations.
- [OpenAI launch](https://openai.com/index/introducing-gpt-6-1-terra/), opened here: its own Terminal-Bench 4 Max Terra 50.3% (higher better). Different published harness from AA; do not combine scores. Announcement also describes visual/computer-use gains; sample counts and uncertainty for these claims are not supplied in its fetched text. No local paid evaluation was performed.

## Availability is separate from schema and successful inference

[Official Models](https://learn.chatgpt.com/docs/models), opened here: CLI >=0.159.0 and explicit `-m gpt-6.1-terra`. API describes a 1,050,000-token context and reasoning `none/low/medium/high/xhigh/max`; neither establishes this CLI session's budget.

Parent accepted local-ops V-1157 safe findings: installed CLI 0.166.0; successful direct app-server initialize + model/list, complete one-page enumeration; exact Terra present, hidden=false, isDefault=false. Provider default effort low; listed low/medium/high/xhigh/max/ultra. Generic Orchestra server effort keeps low/medium/high/xhigh/max; ultra is a client parallel mode, API none is not added. Orchestra's existing explicit default high is unchanged; the provider default low is not silently substituted. No context/effective-budget fields in the record/schema. Therefore 258400 remains explicitly a conservative fallback, overridden by existing runtime metadata/telemetry. No inference was performed; model/list proves listing only. Auth kind was ChatGPT account. A separate managed-daemon version probe failed RC1 (missing socket), while direct model/list succeeded; no native CLI restarted. No protected raw material requested or copied.

## Caller map and scope

`app/models.py` feeds resolve/request validation, derived backend/provider/context views, dashboard/catalog APIs and flags. `app/backend_codex.py` owns API-equivalent prices and conservative context; the runtime factory already passes the exact model to Codex. Native manual selection uses existing UI model data, without a new hardcoded frontend list. Worker spawn/model-change and dynamic workflows already use admission. Terra joins manual-only IDs and defaults agents=false; even old stored agents=true cannot enable it. `quota_bucket_for_model` selects the shared Codex bucket, and `lane_for_model` keeps its Sol policy. Luna's reason-gated native exception, billing, hub models/routes and Sol/Codex aliases are unchanged. Legacy GPT-5.6 Terra retains exact recovery identity and historical rates; its ID does not become selectable or alias to new Terra.

No .git/remote in the worker copy; commit, merge, push, host/full acceptance and production activation belong to the parent/platform. AGENTS and live DB/env/credentials/provider configuration are untouched; model review stays frozen.
