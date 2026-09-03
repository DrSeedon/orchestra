# #283 — Ox Alpha production-harness reconciliation (research only)

## Question

**Context:** Orchestra's current `harness` runtime executes an OpenAI-format agent loop over
OpenRouter. Historical #366–#369 used `stealth/ox-alpha` for real repository work (858 tool
calls, 0 tool errors), while the frozen #236 matrix recorded six successful-looking Ox turns
with no text, tools, or usage.

**Change under test:** re-run three frozen task classes through the production
`HarnessBackend → AgentLoop → OpenRouterClient` path while preserving the production
`reasoning.effort` field, then reconcile useful completion, oracle/alternate/production-path
scores, tool errors, report/artifact agreement, latency, rounds, empty responses, 429s, and
`usage.cost`.

**Baseline:** #236's frozen Ox run omitted `reasoning.effort`; #366–#369 ran the production
harness on real work with the adaptive effort classifier and tool loop.

**Outcome:** a current production-shaped inference result, or a fail-closed reason why no
current result can be collected. The identity of Ox is not inferred from behavior.

## Hypotheses and falsifiers

1. **H1 — effort-sensitive response:** omitting `reasoning.effort` contributed materially to
   #236's six empty turns; production effort would restore text/tool activity.
   **Falsifier:** two interleaved current repetitions with the production effort field still
   produce consecutive empty responses, or the endpoint rejects/ignores the field while the
   request body proves it was sent.
2. **H2 — endpoint/provider drift:** the empty #236 turns were primarily route/provider
   instability rather than effort.
   **Falsifier:** guarded current runs with production effort complete all task classes with
   artifact output and no empty turns, while a no-effort control (not authorized in this task)
   is the only failing condition.
3. **H3 — harness/tool-path defect:** the model may have returned content, but the production
   event/tool persistence path lost it.
   **Falsifier:** raw SSE contains text/tool deltas while `AgentLoop` events/artifacts are empty;
   conversely, absence of raw SSE content with `end_turn` falsifies this hypothesis.
4. **H4 — identity/benchmark equivalence:** Ox can be treated as GLM-5.3.
   **Falsifier:** already available provider evidence labels Ox as anonymous third-party and
   independent benchmark data lists the models separately. That falsifier is satisfied; identity
   remains unverified.

## Frozen protocol (written before any inference call)

- Exact model: `stealth/ox-alpha`; no GLM, Sol, Fable, Opus, comparison model, or fallback.
- Six serial task runs, interleaved as `closed_edit(r1) → closed_trace(r1) → open_audit(r1)
  → open_audit(r2) → closed_trace(r2) → closed_edit(r2)`.
- `closed_edit`: immutable failing RED test plus a mechanically accepted valid alternate;
  grade the resulting implementation by the frozen assertions, never by source-text shape.
- `closed_trace`: production-path answer with a compound oracle for path/runtime/POST URL and a
  separate fallback-reachability oracle; semantically valid paths must not be rejected for
  harmless constructor detail.
- `open_audit`: public read-only fixture only; external grader checks the exact preregistered
  real/decoy category set and the written evidence artifact. Ox never grades itself.
- Before **every** `/chat/completions` attempt, fetch the exact OpenRouter metadata row for
  `stealth/ox-alpha`; require exact ID match, no fallback-model list, and every declared price
  field to be a numeric zero (booleans/strings/unknown fields fail closed). Preserve the
  sanitized API/page receipt and post-response `usage.cost`.
- Maximum 40 guarded HTTP attempts, serial. Stop immediately on any nonzero/unknown price,
  catalog disappearance, two consecutive empty responses, platform 429, more than 10 attempts
  for one task, `MemAvailable < 4 GiB`, or incomplete cleanup.
- Raw events, sanitized artifacts, and mechanical grader output belong under
  `docs/tasks/283/evidence/`; no production/config/service/model-registry mutation.
- No model reviewer: one Luna author session, as explicitly authorized by the user.

## Live guard result (terminal before inference)

The preflight was run before any metadata or inference HTTP request:

```text
key_present=False
base_url=
MemAvailable:    3666888 kB
```

The protocol threshold is 4 GiB (`4,194,304 kB`); measured available memory was
`3,666,888 kB`, so the mandatory memory stop fired. The expected `OPENROUTER_API_KEY`,
`OPENROUTER_KEY`, and `ANTHROPIC_API_KEY` environment sources were also absent. Therefore
there were **0 guarded metadata calls, 0 inference attempts, 0 model calls, 0 artifacts from
the evaluated model, and 0 post-response costs** in #283. No stop condition was bypassed and no
retry was attempted. The sanitized stop receipt is
`docs/tasks/283/evidence/preflight-stop.json`.

This is an **incomplete current measurement**, not a negative model result. The live endpoint
was not probed, so current availability, price, latency, empty-response rate, 429 rate,
`usage.cost`, and production-path artifact scores remain unknown for #283.

## Production-path evidence and actual effort mapping

The current source proves the path, without making a live claim:

- `app/runtime_registry.py:324-339` registers runtime `harness`; its factory constructs
  `HarnessBackend`.
- `app/backend_harness.py:211-245` receives one user message, computes
  `classify_effort(user_msg, is_orchestrator)`, and constructs `AgentLoop` with that effort.
- `app/harness/loop.py:207-247` passes the effort to `OpenRouterClient.stream`; every streamed
  final usage is retained and tool calls are dispatched through the production tool path.
- `app/harness/llm.py:154-168` puts `"reasoning": {"effort": effort}` in the request body when
  effort is non-null; `:258-315` owns the actual streaming POST and SSE accumulation.
- `app/backend_harness.py:450-486` consumes per-round usage and preserves native `usage.cost`
  when present; this is the post-response cost observation the frozen protocol would record.

For the frozen task prompts, the production classifier's deterministic branch is:

| task | classifier trigger | body field that would be sent |
|---|---|---|
| `closed_edit` | `Fix` matches `_HIGH_EFFORT_RE` | `reasoning.effort = "high"` |
| `closed_trace` | `Trace` matches `_HIGH_EFFORT_RE` | `reasoning.effort = "high"` |
| `open_audit` | no high-effort keyword; prompt length is 391 (<400); worker is not orchestrator | `reasoning.effort = "medium"` |

These are source-derived production settings, not model observations. The current
`_harness_factory` does not pass `BackendBuildContext.effort` into `HarnessBackend`; effort is
computed per turn by `HarnessBackend.events()`. That distinction matters when comparing #236:
the frozen runner's no-effort body and production's adaptive body are different experiments.

## Historical reconciliation

### #366–#369 production work

The existing Ox KB records 858 tool calls, 0 tool errors, and 45 turns across four workers:

| worker/task | tool calls | tool errors | turns |
|---|---:|---:|---:|
| #369 `feat-harness-bubbles` | 156 | 0 | 4 |
| #366 `feat-model-catalog` | 219 | 0 | 14 |
| #368 `feat-or-quota` | 235 | 0 | 15 |
| #367 `harness-tools` | 238 | 0 | 11 |
| **total** | **858** | **0** | **45** |

The same record documents three report/artifact mismatches, including an empty screenshot
claim, a mutation report whose combined run was red, and a supposed green run that was really
an `ImportError`. Thus 858/0 proves substantial tool-loop capability in that historical
production workload, but not perfect reporting or current endpoint stability.

### #236 frozen no-effort Ox matrix

The six preserved raw records (`docs/tasks/236/evidence/matrix/r{1,2}-*stealth__ox-alpha.json`)
all report `ok=true`, `stop_reason=end_turn`, exactly one HTTP attempt, zero tool calls, zero
successful rounds, no reported cost, and zero rate limits. The task artifacts show:

| task/repetition | latency (s) | useful artifact/result |
|---|---:|---|
| closed_edit r1 | 7.102 | unchanged RED baseline; 2/6 assertions passed (0.3333) |
| closed_trace r1 | 5.015 | `answer.json` missing; 0/4 |
| open_audit r1 | 38.251 | `findings.json` missing; 0 score |
| closed_edit r2 | 5.965 | unchanged RED baseline; 2/6 assertions passed (0.3333) |
| closed_trace r2 | 4.746 | `answer.json` missing; 0/4 |
| open_audit r2 | 5.138 | `findings.json` missing; 0 score |

The recorded median latency was 5.551 s. All six responses were empty at the event layer;
there was no text, tool call, usage round, or model artifact to grade. The #236 matrix
explicitly omitted `reasoning.effort`, so it cannot distinguish H1 from H2.

### What can and cannot be concluded

- **Confirmed:** the same model identifier has direct historical capability evidence under the
  production harness (#366–#369) and direct historical empty-turn evidence under a no-effort
  frozen matrix (#236).
- **Likely but unmeasured here:** production's adaptive effort may explain part of the gap;
  source shows `high/high/medium` would be sent for the three frozen tasks, but no current model
  response was obtained.
- **Unresolved:** endpoint drift, provider routing, and effort sensitivity cannot be separated
  without the guarded current run. Because the hard stop fired before metadata, even availability
  and price remain unverified today.
- **Refuted:** treating Ox as GLM-5.3. OpenRouter's inspected evidence calls Ox an anonymous
  third-party route; current independent benchmark material compares Ox and GLM separately.
  No identity equivalence is established.

## Counter-evidence and risks

- The strongest counter-evidence to “Ox is unusable” is the 858-call historical production
  record. The strongest counter-evidence to “Ox is a stable default” is six empty current-day
  frozen responses plus three historical report/artifact mismatches.
- The #236 matrix was intentionally no-effort and therefore not a production-parity test; this
  is a real confounder, not proof that effort caused the empties.
- The current source's `HarnessBackend.connect()` creates a JSONL store under
  `data/harness-sessions` (`app/backend_harness.py:185-204`, `app/harness/sessions.py:24-43`).
  A future guarded reproduction must isolate/replace that store in process memory or a permitted
  fixture path; otherwise “read-only” evaluation would mutate production-adjacent state.
- A future run must preserve raw SSE and grader artifacts independently: `end_turn` with no
  tool event is not evidence of useful completion, and a model report is not evidence that the
  file/test artifact exists.

## Review route

User explicitly authorized one Luna author session and no additional model reviewer. Per the
authorized protocol, no reviewer was called. Mechanical evidence and the hard-stop receipt are
the review substitute; this report does not claim external model approval.

## Sources

1. `app/runtime_registry.py:324-339` — harness runtime registration/factory.
2. `app/backend_harness.py:211-245,450-486` — production turn wiring, classifier, usage/cost.
3. `app/harness/loop.py:207-247` — AgentLoop effort forwarding and tool/event handling.
4. `app/harness/llm.py:154-168,258-315` — request body, reasoning field, stream POST/SSE.
5. `docs/kb/ox-alpha-harness-verdict.md` — #366–#369 aggregate and #236 identity/empty-run record.
6. `docs/tasks/236/evidence/matrix/r{1,2}-*stealth__ox-alpha.json` — six sanitized raw result records.
7. `docs/tasks/236/research.md` — frozen protocol, current metadata/identity boundary, and no-effort caveat.
8. `docs/tasks/283/evidence/preflight-stop.json` — this task's sanitized preflight measurement.

## Confidence

- Production wiring and effort mapping: **CONFIRMED** by current source inspection.
- Historical 858/0 and six empty no-effort records: **CONFIRMED** by existing artifacts.
- Effort as the cause of the #236 empties: **UNCERTAIN**; no current guarded inference was
  permitted after the memory/key hard stop.
- Ox identity as GLM-5.3: **REFUTED as an established fact**; anonymous third-party labeling and
  separate benchmark treatment remain the evidence boundary.

## #283 remote Contabo continuation (23.08.2026)

The user-authorized Contabo contour passed preflight: remote `MemAvailable=17,800,992 KiB` in
the final runner summary (the concurrent preflight probe measured `17,820,772 KiB`), and the
key name was present in `/home/kesha/orchestra/.env` without ever being printed or copied into
an artifact. The runner was staged under `/var/tmp/orchestra-283-eval-57473bf0`, imported the
remote production checkout read-only, used an isolated SQLite counter and in-memory session
store, and never touched the live service, repository, or counter.

The run executed the frozen serial interleave
`r1-edit → r1-trace → r1-audit → r2-audit → r2-trace → r2-edit` using only
`stealth/ox-alpha`. Every one of 31 HTTP attempts fetched the exact metadata row first;
all 31 rows matched `stealth/ox-alpha`, had pricing exactly `{"prompt":"0","completion":"0"}`
(numeric-equivalent zero), and had the same tool/reasoning capability declaration. The public
model page returned HTTP 200; its sanitized receipt is preserved with SHA-256
`4bfad4c1e5f6282c5c9f3c3ed76b2c2785bdc68dc6c484e36b0ad2e279d82a36`.

No fallback model list was sent. There were 0 platform 429, 0 upstream 429, 0 tool errors,
0 empty responses, and no nonzero `usage.cost`. Thirty post-response rounds explicitly
reported `usage.cost=0.0`; one round omitted the field and is recorded as missing rather than
converted to zero. HTTP attempt counts per task were `[7,5,4,4,6,5]` in the actual interleave;
latencies were 44.526, 41.788, 69.026, 50.489, 61.108, and 34.893 seconds (median 47.5075 s).
The preserved raw output is under `docs/tasks/283/evidence/remote-57473bf0/` and passed the
sanitized secret-form scan (`10 files, 0 hits`).

### Corrected mechanical grading

The frozen runner's first grader contained two independently observable oracle defects, so its
raw scores remain preserved and are not silently replaced:

- `closed_trace` expected qualified names `HarnessBackend.send`/`Client.complete`, although the
  fixture's actual function names are `send`/`complete`. Both Ox answers exactly matched the
  fixture path `create → build → send → complete → post`, runtime `harness`, POST URL, and
  `paid_fallback_reachable=false`. The corrected compound/fallback oracle therefore scores both
  repetitions 4/4.
- `open_audit` assumed `categories` contained only strings. Repetition 1 returned five
  evidence-bearing objects with a `category` field and a correct five-finding report; the grader
  raised `TypeError` before scoring. The corrected evidence extractor scores it 5 TP/0 FP =
  10/10. Repetition 2 returned five real strings plus `lock_contention`, scoring 5 TP/1 FP =
  9/10 under the same external rule.

The corrected scores are therefore: `closed_edit=1.0,1.0`; `closed_trace=1.0,1.0`;
`open_audit=10,9`; valid alternate control `true`; 6/6 useful tasks; useful
completion/request `6/31 = 0.193548`; corrected production-path oracle 6/6; report/artifact
agreement 6/6. The raw primary-grader output and the post-run correction are both preserved in
`summary.json` and `corrected-grades.json`; no model call was repeated after inspecting output.

### Reconciled conclusion

The production-shaped effort hypothesis is supported operationally: all six turns used the
production `HarnessBackend.events()` path with source-derived `reasoning.effort` mapping
`high/high/medium`, and all six produced non-empty artifacts. This does **not** prove effort
alone caused #236's empties, because #283 changed both the effort field and the harness path
relative to the no-effort runner. It does refute “the endpoint is currently incapable of useful
Ox work”: the guarded remote run completed both closed edits, both corrected traces, and both
audits, with no price, fallback, 429, or tool-error incident.

The remaining capability boundary is narrow: corrected trace reliability was high on this
fixture, while audit quality varied (10 then 9) due one unsupported `lock_contention` claim.
Historical #366–#369's 858/0 capability evidence and #236's six empty no-effort records are
both retained; neither licenses the unverified identity claim that Ox is GLM-5.3, nor a blanket
production default without artifact acceptance.
