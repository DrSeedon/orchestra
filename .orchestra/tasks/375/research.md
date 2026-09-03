# #375 — Effective Codex context and compaction under ChatGPT subscription auth

Research only. Snapshot date: **2026-08-23**. No code/config/restart change, no manual live
compact, and no new large provider probe was launched. Existing provider-backed rollouts were
read sequentially and only metadata/token telemetry was extracted.

## Short answer

The 872K setting is not merely present in `~/.codex/config.toml`: for both current
`gpt-5.6-sol` and `gpt-5.6-luna` Orchestra turns on Codex CLI 0.149.0, the managed home contains
`model_context_window = 872000`, `task_started.model_context_window` is **828,400**, and every
examined `token_count.model_context_window` is **828,400**. Both managed homes report
`Logged in using ChatGPT`. The public API's advertised 1,050,000 total context remains a different
surface and is not evidence of subscription-CLI capacity [1][2][4].

Provider acceptance is proven beyond the old 258,400 effective default, but not to the full
ceiling: current Sol 0.149.0 returned a model response at **474,394 input tokens**; an earlier
ChatGPT-auth Luna probe on 0.146.0 completed exact NIAH checks at **275,310** and **509,046** input
tokens. Current Luna 0.149.0 reports the 828,400 window, but its largest observed current request
was only 136,511; therefore current-version Luna acceptance above 272K is **not re-proven**.

The compact thresholds are two different mechanisms:

- Orchestra's delayed precompact arms at **60% of the effective runtime window** and explicitly
  calls native same-thread compact after 25 idle minutes. At 828,400 that is **497,040 input
  tokens**.
- Codex config contains `model_auto_compact_token_limit = 784800`, which is **90% of the raw
  872,000 override but 94.74% of the effective 828,400 window**. The config reference defines the
  key as the auto-history-compaction threshold [3], but neither `task_started` nor `token_count`
  reports the resolved limit.

The current 0.149.0/828,400 cohort contained **1,417 token-count events across 30 rollouts and zero
`context_compacted` events after the window became 828,400**. Its current Sol maximum was 474,394
(57.27%), below the 60% Orchestra trigger; therefore the zero is expected and **does not validate
the 90% firing point**. An older Luna direct probe reached 509,046 (61.45%) without compaction,
which shows native auto-compact did not fire at 60% in that probe. The exact current native firing
point remains **INSUFFICIENT EVIDENCE**; a configuration value alone is not a runtime observation.

Interim recommendation under the explicit no-change constraint: **leave the current settings
unchanged while collecting evidence**, not because 872K+60% is proven preferable. Scope Luna
long-context use to extraction/closed work until a current-version long multi-step acceptance test
exists. The optimal per-model ceiling and compact threshold are **INSUFFICIENT EVIDENCE**.

## Question

- **Context:** Orchestra runs persistent Codex app-server sessions, one managed `CODEX_HOME` per
  session, using ChatGPT subscription authentication.
- **Change under test:** the machine config's `model_context_window=872000` and
  `model_auto_compact_token_limit=784800`, plus Orchestra's 60% delayed precompact.
- **Baseline:** the live model catalog default 272,000 raw / 258,400 effective and Codex's derived
  default compaction behavior.
- **Outcomes:** (1) configured values reach managed homes; (2) current Sol/Luna turn lifecycle and
  `token_count` report the larger window; (3) the provider accepts requests beyond the old ceiling;
  (4) compact timing is observed rather than inferred; (5) context-size effects on TTFT, turn wall,
  cache, token volume, tool loops, compact frequency, and acceptance are separated into measured
  versus modeled claims.

## Hypotheses and falsifiers

| Hypothesis | What would prove it wrong | Result |
|---|---|---|
| H1. Observed Sol and Luna turns receive the 872K override through managed homes and expose 828,400 effective runtime context. | Either observed model's managed home lacks a key, its turn starts at 258,400, or `token_count` reports another window. | **CONFIRMED for one named current Sol turn and one named current Luna turn.** Fleet-wide runtime loading is not claimed. |
| H2. The config proves the provider accepts the full 828,400 effective window. | Runtime reports the window but a provider request fails below it, or no request approaches the ceiling. | **REFUTED as a proof method.** Sol is observed only to 474,394; Luna to 509,046 on 0.146.0. |
| H3. The currently configured “90%” native limit is the same thing as Orchestra's 60% precompact. | Code/logs show an explicit delayed `thread/compact/start`, or the two percentages use different denominators. | **REFUTED.** They are distinct mechanisms and denominators. |
| H4. 60% is empirically better than 90% on current 828,400 sessions. | A current cohort crosses 497,040/784,800 and supplies paired acceptance/cost outcomes. | **UNCERTAIN.** No current 0.149 managed turn crossed even 60%. |
| H5. Larger context necessarily improves or worsens latency/tool-loop length. | Controlled same-task repetitions show no stable sign, or observational telemetry is confounded by task/turn position. | **UNCERTAIN.** One direct pair slows; the larger observational cohort has weak/no monotone relation. |

## 1. Advertised, catalog, configured, effective, accepted

| Layer | Sol | Luna | Evidence and confidence |
|---|---:|---:|---|
| Public API advertised total context | 1,050,000 | 1,050,000 | Official model pages; max output 128,000 [1][2]. **CONFIRMED for API surface only.** |
| Live ChatGPT-auth CLI catalog default raw | 272,000 | 272,000 | Current managed `models_cache.json`. **CONFIRMED measurement.** |
| Live CLI catalog max override raw | 872,000 | 872,000 | Same catalog, `effective_context_window_percent=95`. **CONFIRMED measurement.** |
| Machine + active managed-home config raw | 872,000 | 872,000 | Exact keys in base and named managed homes; files mode 0600. **CONFIRMED.** |
| Configured native auto-compact number | 784,800 | 784,800 | Exact managed-home key. Numerically 90% of raw 872,000; the config threshold and reported effective window may use different token scopes, so their operational ratio is unverified. **CONFIRMED configured, unverified effective trigger.** |
| Turn lifecycle effective window | 828,400 | 828,400 | `task_started` and `token_count` on CLI 0.149.0. **CONFIRMED.** |
| Largest accepted input observed | 474,394 (0.149.0, current) | 509,046 (0.146.0, prior NIAH); 136,511 on current 0.149.0 | Sol proves current provider response beyond 272K; Luna proves older exact extraction beyond 500K, not current full capacity. |

The official configuration reference says `model_context_window` is the context available to the
active model and `model_auto_compact_token_limit` triggers automatic history compaction [3]. It
does not claim that setting either value enlarges the user's entitlement. Official authentication
docs explicitly separate ChatGPT subscription access from API-key usage [4]; both tested managed
homes returned `Logged in using ChatGPT` from `codex login status`.

### 1.1 Managed-home delivery is lazy, not fleet-wide

At 16:37Z, the live DB/filesystem join showed:

```text
nonarchived Codex sessions: total=46 exact_pair=11 stale=34 missing=1
running: total=5 exact=5
waiting: total=3 exact=3
idle: total=38 exact=3
```

Across all historical managed-home directories, only 19 of 208 configs had the new pair. This is
expected from the implementation, not evidence that active turns ignored the settings:
`_prepare_codex_home()` carries only the three allowlisted scalars, while
`_reload_stale_managed_config_before_turn()` rewrites/reconnects an idle managed backend before
its next `turn/start` and verifies that resume preserved the thread id
(`app/backend_codex.py:708-723, 2313-2419`). The focused contract test is
`tests/test_backend_codex.py:901-935`.

The active path is proven end to end for both models:

```text
Sol session 0023dd48…:
  managed config: 872000 / 784800, mode 600, ChatGPT login
  rollout CLI 0.149.0, originator=orchestra
  turn_context.model=gpt-5.6-sol, effort=xhigh
  task_started.model_context_window=828400
  token_count.model_context_window=828400

Luna session 3be26456…:
  managed config: 872000 / 784800, ChatGPT login
  rollout CLI 0.149.0, originator=orchestra
  turn_context.model=gpt-5.6-luna, effort=high
  task_started.model_context_window=828400
  token_count.model_context_window=828400
```

Thus the correct delivery statement is: **all running/waiting Codex homes observed at the snapshot
contained the new config; one named current Sol turn and one named current Luna turn proved that a
process had loaded it; dormant homes remain stale until their next turn**. File contents do not
prove that every already-running process loaded them. “All managed homes/runtimes were updated”
would be false.

## 2. What actually compacted, and at which threshold

### 2.1 Two owners, same rollout event

Orchestra's current code reports context from the last `token_count` input against the runtime
window (`app/backend_codex.py:2015-2052`; `app/usage_contract.py:82-136`). It truncates the
percentage to an integer, so the 60% arm point at 828,400 is exactly 497,040 input tokens.

For Codex sessions, `_precompact_policy()` returns 60%, 1,500 seconds, native same-thread mode;
after the timer fires it calls `Session.compact()` → backend `thread/compact/start`
(`app/session.py:507-539, 648-771, 2319-2394`; `app/backend_codex.py:1203-1270`). This is an
Orchestra-initiated compact using Codex's native protocol. Codex CLI auto-compact is a separate
internal path governed by the configured token limit. Both yield `context_compacted` in the
rollout, so rollout events alone do not attribute cause.

Production logs prove the Orchestra path itself fires: 111 Codex `precompact timer fired` events
from 2026-08-09 through 2026-08-23, each with `delay_seconds=1500`; fired context ranged 60–93%,
with 9 events exactly at 60%. This proves the policy executes, but on the former 258,400 effective
window.

### 2.2 Current large-window observation

Frozen-ish read-only snapshot 16:36:30–16:36:37Z, CLI 0.149.0, only events whose reported window
was 828,400:

```text
30 rollout files
1,417 token_count events
0 context_compacted events after the last reported window became 828400
Sol max input 474,394 (57.27% effective)
Luna max input 136,511 (16.48% effective)
```

This cohort does **not** test either threshold: no current managed turn reached the 60% arm point,
much less configured 784,800. The old Luna two-turn NIAH probe reached 509,046 / 828,400 = 61.45%
with zero compact events. It proves that native auto-compact did not fire at 60% in that 0.146.0
direct run; it does not locate the 0.149.0 threshold.

### 2.3 What is arithmetic and what is empirical

| Claim | Kind | Verdict |
|---|---|---|
| `872000 × 0.95 = 828400` | Arithmetic, corroborated by two runtime channels for both models | **CONFIRMED effective window.** |
| `784800 / 872000 = 90%` | Arithmetic/config | **CONFIRMED configured raw ratio.** |
| `784800 / 828400 = 94.74%` | Arithmetic across two reported/configured numbers | **CONFIRMED arithmetic only.** The config scope (`total` or `body_after_prefix`) and `token_count` input/window semantics have not been shown comparable. |
| Native CLI will compact exactly when `token_count` input reaches 784,800 | Runtime behavior | **INSUFFICIENT EVIDENCE.** Resolved threshold/scope is not emitted and no current turn approached it. |
| Orchestra will arm at 497,040 and compact after 25 idle minutes if still eligible | Code + old-window production execution | **LIKELY for current absolute point; not yet observed at 828,400.** |
| 60% produces a better acceptance/cost tradeoff than native 90% | Comparative experiment | **UNMEASURED.** |

The falsifier for the unresolved native point is one disposable, current-CLI thread that crosses
the candidate region while recording every `task_started`, `token_count`, and
`context_compacted` event. Because that is a paid near-ceiling run and compaction may discard
operational facts (#377's applicable fidelity risks), it was deliberately not performed here.

## 3. Context-size effects

### 3.1 Direct Luna pair: useful but N=1

The #325 ChatGPT-auth probe is the strongest acceptance evidence because its output oracle forced
retrieval from both distant regions. Independent review re-read the raw rollout and confirmed both
`task_complete` events and exact answers [7].

| Luna turn | Input | Cached | TTFT | Turn wall | Model calls | Tools | Acceptance |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 275,310 | 9,984 | 4.454 s | 5.111 s | 1 | 0 | `AAA-OK` |
| 2 | 509,046 | 274,176 | 7.189 s | 8.026 s | 1 | 0 | `AAA-OK BBB-OK` |

The second request carried 1.85× the input, had 1.61× TTFT and 1.57× wall, while keeping exactly
one model call and zero tools. **OBSERVED, not causal:** the second prompt requested two needles,
the order was fixed, there were no repetitions, and CLI version was 0.146.0. It proves
provider/answer acceptance and a latency observation, not a general slope.

### 3.2 Current 0.149.0 observational turns

Predeclared unit: a completed turn whose `task_started` window was 828,400. Context size is the
first nonzero input in that turn. Bins were fixed before aggregation. `model_calls` counts nonzero
`token_count` events; tools count `custom_tool_call|function_call`. Snapshot 16:36:12–16:36:15Z:
82 completed turns, 7 without TTFT telemetry.

| Model / first-input bin | n | Median first input | Median TTFT | Median wall | Median model calls | Median tools | Median first-call cache ratio |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sol `<100K` | 27 | 49,941 | 6.10 s | 161.77 s | 9 | 8 | 27.37% |
| Sol `100–199K` | 17 | 138,885 | 6.54 s | 68.34 s | 8 | 7 | 99.14% |
| Sol `200–299K` | 28 | 255,773 | 9.31 s | 59.73 s | 5.5 | 4.5 | 99.53% |
| Sol `≥300K` | 6 | 342,297 | 9.82 s | 432.89 s | 11.5 | 10.5 | 99.45% |
| Luna `<100K` | 2 | 40,712 | 6.80 s | 491.86 s | 28 | 27 | 34.34% |
| Luna `100–199K` | 2 | 130,435 | 21.33 s | 97.25 s | 7 | 6 | 97.92% |

For Sol, Spearman `first_input ↔ TTFT = 0.221` and `first_input ↔ turn wall = -0.156`.
This is weak and contradictory across outcomes. Later turns naturally have larger, more cached
contexts and often shorter work; task complexity dominates wall/tool count. Luna `n=4` is not a
usable estimate. Therefore:

- **TTFT:** a weak positive observational signal for Sol and one slowing Luna pair; causal effect
  **UNCERTAIN**.
- **Turn latency:** no stable monotone effect; **UNCERTAIN**.
- **Cache read:** larger warm turns are 99% cached, but cached tokens are still retransmitted and
  counted. **CONFIRMED observationally.**
- **Token usage:** direct Luna input rose 275K→509K; current bins associate later/larger turns with
  high cache ratios; #330 models repeated larger prefixes under its counterfactual. **Observed
  association plus modeled mechanism; causal magnitude and post-change multiplier unmeasured.**
- **Tool-loop length:** the Luna pair stayed 1/0; current Sol bins are nonmonotone. **No evidence
  that larger context alone lengthens or shortens the loop.**
- **Compact frequency:** historical small-window corpus had 413 compacts / 45,648 token events and
  113/709 sessions with at least one compact [8]; current large-window cohort has 0/1,417, but no
  turn crossed the new 60% arm point. **The observed zero is not an A/B effect estimate.**
- **Acceptance:** Luna exact NIAH passed at 509K; current Sol returned a response at 474K. Open,
  multi-step Luna acceptance and near-ceiling acceptance for either model remain unmeasured.

### 3.3 The 60% cost proposal is modeled, not experimentally validated

#330 reconstructed the same historical work under a larger window. Under the current 60% policy it
estimated large/small normalized token-cost ratios of **2.332×** if API-style long-context pricing
applies and **1.496×** in its no-long-context-premium Luna case; its wider threshold assumptions
produced 2.33–3.20× [8]. It also measured compact overhead at an upper-bound ≈4.7% of old Codex
usage, mostly summary work and cache destruction.

Those are counterfactual calculations over old 258,400 rollouts, not a provider A/B. The official
API model pages say prompts above 272K use 2× input / 1.5× output pricing [1][2], but official auth
docs distinguish subscription access from API-key billing [4]. No official source opened here says
the same multiplier applies to included ChatGPT subscription credits. The post-change current
cohort is hours old and task-mix uncontrolled. Therefore the exact subscription-pool cost of 60%
versus 90% is **INSUFFICIENT EVIDENCE**.

## 4. Per-model recommendation

| Model | Window recommendation | Compact recommendation | Confidence / falsifier |
|---|---|---|---|
| **Sol** | **No-change interim:** leave 872,000 raw / 828,400 effective configured while it is already serving live long threads. Evidence supports a ceiling above 474,394, not specifically 872,000. | **No-change interim:** leave Orchestra 60% / 25-minute idle precompact in place; native configured 784,800 remains unmeasured. Neither threshold is proven preferable. | **Optimal window/threshold: INSUFFICIENT EVIDENCE.** Falsifier: paired frozen Sol tasks across candidate ceilings/thresholds establish acceptance, total tokens/rework, and compact-fidelity ordering. |
| **Luna** | **No-change interim:** leave the same configured ceiling, but route >272K only for closed/extraction tasks today. A 509K exact NIAH pass proves capacity for that class, not Sol-equivalence on open work. | Leave 60% pending evidence; no current 0.149 Luna turn crossed it. Do not infer that Luna's lower base rate makes a near-full window operationally free. | **Extraction capacity on 0.146 CONFIRMED; current-version optimal window/threshold: INSUFFICIENT EVIDENCE.** Falsifier: a current 0.149 frozen long multi-step task above 272K either fails AC/reroutes (narrow/remove use) or passes repeatedly with lower subscription usage than Sol (broaden it). |

Why leave the settings unchanged for now? Active current Sol work already used 474K and received
responses; lowering the window would force a behavior change in live long threads, and the user
explicitly prohibited config/restart changes. This is change avoidance, not proof that 872K is the
best ceiling. Why not recommend native 90 as the normal target? Neither the exact resolved limit
nor near-threshold acceptance/compact fidelity has been observed, and #377 found applicable
upstream compact-fidelity risks [6].

## 5. Counter-evidence and limits

- Public API 1.05M agrees across Sol/Luna pages, but it is not ChatGPT subscription-CLI evidence.
- Current runtime reports 828,400 for both models, but a local reported window can still precede a
  provider rejection; only accepted calls bound capacity from below.
- Current Sol acceptance at 474K is a real provider response but has no independent task AC.
- Luna 509K has an exact oracle and independent raw-rollout verification, but uses CLI 0.146.0 and
  a simple two-turn extraction fixture.
- The 82-turn latency cohort is observational, not paired; context grows with turn position, cache
  warmth, task type, and tool count. Historical load averages were not recorded, so wall-time
  differences cannot be attributed to context.
- `context_compacted` does not encode whether Codex auto-triggered or Orchestra explicitly called
  `thread/compact/start`; production status logs are required for attribution.
- Dormant managed homes are stale by design. The next-turn reconnect path is code/test-backed and
  observed in active runtime, but 34 idle sessions had not exercised it at the snapshot.
- No destructive compact was run, so summary fidelity after current-version near-ceiling compact
  remains unmeasured.
- #374's effort findings are orthogonal: it confirms model/effort request provenance and warns that
  N=1/noise cannot justify a global policy, but it contains no context-window A/B [5].

## 6. Affected files and risks if this becomes implementation work

No implementation is proposed in this phase.

- `app/backend_codex.py`: managed-home allowlist/write/reconnect, fallback window, rollout context
  parsing, native `thread/compact/start`.
- `app/session.py`: 60% arm threshold, 25-minute delay, eligibility/time-window gates, state update
  after compact.
- `app/usage_contract.py`: effective context percentage uses integer truncation.
- `tests/test_backend_codex.py`, `tests/test_mcp_config_isolation.py`, `tests/test_session.py`:
  delivery/reconnect/precompact contracts.

Risks: changing the raw window changes the absolute 60% threshold; changing 60% changes cost,
compact fidelity, and cache continuity; an idle stale home does not change until reconnect; public
API long-context pricing must not be presented as included-subscription credit behavior; a compact
event without its initiating status log is causally ambiguous.

## 7. Evidence commands and raw outputs

Only safe fields were extracted; no auth contents or process argv were inspected for this result.

```text
codex --version
→ codex-cli 0.149.0

CODEX_HOME=<Sol managed home> codex login status
CODEX_HOME=<Luna managed home> codex login status
→ Logged in using ChatGPT (both)

jq selected catalog fields
→ Sol: context=272000 max=872000 effective=95 auto_compact=null
→ Luna: context=272000 max=872000 effective=95 auto_compact=null

active config + rollout join
→ both models: config 872000/784800; task_started 828400; token_count 828400

current large-window cohort, 16:36Z
→ files=30 token_count_events=1417 compact_events=0
→ sol_max=474394 luna_max=136511

read-only SQLite status-log count
→ Codex precompact_timer_fired n=111; context percentages 60..93; exact 60 n=9
```

## 8. Sources

1. **Tier 2, official OpenAI documentation:** [GPT-5.6 Sol model](https://developers.openai.com/api/docs/models/gpt-5.6-sol) — API context, output limit, >272K API pricing. Opened 2026-08-23.
2. **Tier 2, official OpenAI documentation:** [GPT-5.6 Luna model](https://developers.openai.com/api/docs/models/gpt-5.6-luna) — API context, output limit, >272K API pricing. Opened 2026-08-23.
3. **Tier 2, official OpenAI documentation:** [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) — meanings of the two config keys and total/body-after-prefix scope. Opened 2026-08-23.
4. **Tier 2, official OpenAI documentation:** [Codex authentication](https://learn.chatgpt.com/docs/auth) — ChatGPT subscription vs API-key access and `codex login status`. Opened 2026-08-23.
5. **Tier 1 local code/measurement input:** `docs/tasks/374/research.md` and
   `docs/tasks/374/codex-review-research.md` — model/effort/turn provenance and evidence limits.
6. **Tier 1 local code + Tier 2/4 upstream input:** `docs/tasks/377/research.md` and
   `docs/tasks/377/review-research.md` — CLI 0.149.0, current catalog/config, compact-fidelity risk.
7. **Tier 1 prior provider measurement:** `docs/tasks/325/research.md` and
   `docs/tasks/325/review-research.md` — independently verified 275K/509K Luna NIAH run.
8. **Tier 1 historical measurement + counterfactual model:** `docs/tasks/330/research.md` —
   compact frequency/cache effects and explicitly non-A/B 60% simulation.
9. **Tier 1 current measurements:** managed configs, read-only live DB/status logs, safe rollout
   metadata and token telemetry collected in this session; commands summarized in §7.

## 9. Confidence summary

- **CONFIRMED:** API advertised window; current catalog max; managed config on active observed
  Sol/Luna; ChatGPT auth; 828,400 in both `task_started` and `token_count`; current Sol provider
  response beyond 272K; old Luna exact extraction at 509K; historical execution of the 60% timer.
- **LIKELY:** next-turn lazy delivery to dormant sessions, from current code/test plus observed
  active transition.
- **UNCERTAIN / INSUFFICIENT:** exact 0.149 native auto-compact firing point; optimal 60-vs-90
  threshold; current Luna acceptance above 272K; causal TTFT/wall/tool-loop effect; exact
  ChatGPT-subscription long-context multiplier; open-work Luna acceptance; compact fidelity at the
  new ceiling.
- **REFUTED:** config alone proves provider capacity; “90% configured” equals 90% of the effective
  dashboard window; every historical managed home was eagerly updated; zero current compacts proves
  a lower compact rate.

## Review gate inputs

- **Artifact/consumer:** this research document; consumed by the task owner for a later plan/no-plan
  decision. No executable or external contract changed.
- **Author:** `gpt-5.6-sol`, Codex runtime, from current session metadata.
- **AC:** separate advertised/configured/effective/accepted values by model; verify managed-home and
  runtime delivery; distinguish 60/90 mechanisms and arithmetic/experiment; report all requested
  context-size outcomes; make no destructive compact or state change; give per-model recommendation
  or explicit insufficient-evidence verdict with falsifier.
- **Mechanical checks:** exact value/count commands in §7; source links opened this session;
  `test -s docs/tasks/375/research.md`; no code/config diff.
- **Review route:** targeted Sol research falsification, required by causal/statistical uncertainty
  and absence of a deterministic oracle. Author/reviewer share model family/runtime, so the review is
  a fresh-session second opinion, not cross-family independence.

### Review outcome

One targeted Sol round completed in `docs/tasks/375/review-research.md`. Verdict: no blocking
findings, needs evidentiary-calibration revisions. All four suggestions were accepted: runtime
delivery was narrowed to the two named turns; the 94.74% figure was labeled arithmetic across
possibly different token scopes; the token-cost statement was downgraded to association + model;
and “keep current” was reframed as change avoidance rather than an evidence-backed optimum. No
second round is permitted for suggestion-only changes under the review policy.

## Knowledge-base note

The user limited writes to `docs/tasks/375/` and personal memory, so `docs/kb/` was intentionally
not modified despite the normal Phase-1 topic-file rule.
