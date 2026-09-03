# #376 — persistent Codex app-server versus `codex exec`

Research only. Snapshot and provider runs: **2026-08-23**, Codex CLI **0.149.0**. No
Orchestra app/config change, production restart/update, live-session delivery, or production
session was used as a benchmark target.

## Short answer

The current paths are not equivalent in lifecycle. Orchestra creates and initializes one
`codex app-server --stdio` process, starts/resumes one native thread, and retains both across
turns. A warm delivery issues `turn/start`; `codex exec` starts a process and a native thread for
every invocation. Current code confirms that distinction, and the isolated benchmark observed the
corresponding local phases [1][2][M1].

The fixed-context `codex exec` A/A/A control passed the preregistered gate: client/lifecycle
overhead was `2.969 / 3.752 / 2.814 s`, a **0.937 s range**, while the median per-run exec
process/handshake phase was **1.990 s**. Total wall was much noisier (`11.443 / 8.027 / 6.733 s`)
because model wait varied from `8.474` to `3.919 s`. This directly refutes inference of
app-server delay from these total-turn observations without replication/decomposition [M2].

The allowed interleaved app/exec/app/exec run then observed warm app-server client overhead of
`0.081 / 0.385 s` versus exec `3.115 / 3.134 s`. The paired `exec − app` effect was
`3.033 / 2.749 s`, median **2.891 s**, which exceeds A/A noise. However, the preregistered cache
invariant failed: app run 1 had `6,912 / 9,436` cached input tokens (73.25%), while the other three
measured A/B runs had zero cached input. All context hashes, input-token totals, model, effort,
task, schema, calls, tools and AC otherwise matched [M3]. The comparison is therefore marked
**causally invalid by its own frozen rule**.

**No `leave-app-server`, `change-usage`, or `switch-path` verdict is issued.** The evidence supports
the narrow mechanism “a warm persistent process avoids roughly 2–3 seconds of measured local
lifecycle work on this fixture,” but does not support a product path decision without a
cache-valid representative run. Operational no-change follows from absence of a valid verdict,
not from pretending the existing path won.

## Question

- **Context:** Orchestra's persistent Codex backend versus a fresh non-interactive Codex CLI
  invocation on the same machine/account.
- **Change under test:** leave the app-server path, change how each surface is used, or switch to
  `codex exec`.
- **Baseline:** a fresh native thread on an already-started app-server; its cold lifecycle remains
  separately visible.
- **Outcome:** decomposed client/process, queue, model, tool, and post-processing time; exact AC;
  calls; tokens/cache; quota delta; failures. A path verdict additionally requires effect greater
  than A/A noise and every frozen confound check to pass.

## Hypotheses and falsifiers

### H1 — persistence removes measurable per-task lifecycle work

One retained app-server makes steady delivery faster because it does not repeat CLI process and
native-thread startup.

**Falsifier:** interleaved client-overhead effect is no larger than same-path A/A range, reverses
sign, or relies on different model-visible context/cache/task/AC.

**Result:** mechanism observed; path conclusion **UNCERTAIN** because the cache falsifier fired.

### H2 — total-turn differences are mostly model/provider variance

When task and client path are unchanged, model wait can move more than expected transport effect;
therefore total wall may be an unusable app-server-delay locator at this sample size.

**Falsifier:** A/A total-wall/model-wait range is smaller than and stable relative to the transport
effect.

**Result:** **CONFIRMED on this fixture**: A/A total-wall range was `4.710 s`, greater than the
interleaved median total-wall difference `2.385 s`; model-wait range alone was `4.555 s` [M2][M3].

### H3 — cold app-server is intrinsically faster than exec startup

App-server protocol startup itself, rather than retention, provides the gain.

**Falsifier:** cold app-server handshake overlaps exec handshake or changes sign.

**Result:** **REFUTED on this sample**. Measured A/B cold app-server handshake was
`1.627 / 3.053 s`; exec was `1.745 / 2.053 s`. The advantage is retention/amortization, not a
consistently faster cold app-server [M3].

## 1. Exact current paths and lifecycle ownership

### Orchestra persistent path

1. `SessionManager.send()` resolves the session, serializes delivery with the per-session lock,
   performs branch auto-switch if required, and calls `Session.send()`
   (`app/manager.py:1014-1028`) [1].
2. `Session.send()` performs worker admission, pending/steer handling, optional prompt refresh,
   identity/effort refresh, status persistence, and obtains the backend
   (`app/session.py:1043-1219,1221-1235`) [1]. These are Orchestra outer-path costs, not Codex
   transport. The benchmark deliberately did not use the live manager/session and therefore did
   not attribute them to app-server.
3. On the first connection, `_ensure_backend()` refreshes the AGENTS mirror and skills, builds the
   backend, calls `connect()`, publishes handover FDs and activates persistent listener/heartbeat
   tasks (`app/session.py:1722-1798`) [1].
4. `CodexBackend.connect()` refreshes the private managed home, checks CLI/state compatibility,
   may seed state, optionally wraps the process in a user scope, spawns the CLI, wires JSONL pipes,
   performs `initialize`/`initialized`, then `thread/start` or `thread/resume`
   (`app/backend_codex.py:918-1082`) [2]. The actual command ends in
   `app-server --stdio` and fixes effort/multi-agent/web settings
   (`app/backend_codex.py:2229-2245`) [2].
5. A warm idle send does not respawn. It checks whether managed config is stale and sends
   `turn/start` with the retained `threadId`, model and effort
   (`app/backend_codex.py:1096-1134`) [2]. Notifications remain on the persistent reader and are
   consumed by `_persistent_event_loop()` and passed to `_handle_event()`
   (`app/session.py:1791-1796,1854-1865`) [1].
6. Disconnect interrupts an active turn if needed and terminates the owned scope/process; it is a
   session lifecycle operation, not normal per-turn post-processing
   (`app/backend_codex.py:1380-1400`) [2].

Thus the full cold path contains Orchestra admission/prompt/state work plus managed-home/version/
scope/FD work plus app-server handshake. The steady Codex transport seam is only stale-config
check + `turn/start` + event consumption. The benchmark reproduced the latter protocol seam with
`clientInfo.name=orchestra`, but did not claim to benchmark all outer manager/session work.

### `codex exec` path

The direct surface starts `codex` for each invocation, creates a thread, starts a turn, streams
JSONL and exits. The benchmark used the naked CLI with `--json`, fixed output schema and no
`-o` file, so its post-processing is the minimum direct path [M1].

Orchestra's current `codex_review` is strictly heavier than that baseline: it creates prompt/temp
files, starts a background shell job, calls `codex ... exec`/`exec resume`, tees JSONL, validates
and atomically writes the review artifact, records usage and checks execution failures
(`app/mcp_stdio.py:2481-2552,2560-2647`; `app/codex_review_artifact.py:1-201`) [3]. The benchmark
does **not** generalize its direct-exec post-processing number to `codex_review` total wall.

Prior evidence agrees with this ownership split: #372 found two OS processes per retained Codex
session and model wait dominating long turns; #374 proved explicit model/effort delivery; #375
separated configured/reported/accepted context; #377 confirmed all current native app-servers and
the tested CLI are 0.149.0 [4][5][6][7].

## 2. Frozen task and controls

The preregistration is [`protocol.md`](protocol.md); executable harness is
[`benchmark.py`](benchmark.py); analysis is [`analyze.py`](analyze.py).

- Exact prompt: [`task.txt`](task.txt).
- Exact JSON schema: [`output-schema.json`](output-schema.json).
- AC: final JSON equals `{"answer":"ORCHESTRA-376-OK"}`; zero tools.
- Model/effort: `gpt-5.6-sol` / `medium`; every rollout `turn_context` agreed.
- One model call per measured run; fresh native thread and freshly recreated state per arm.
- Same empty absolute cwd, standard tier, read-only sandbox, `never` approval, apps/web/native
  multi-agent disabled, identical context-window settings.
- Fixed home **pathname** but fresh contents: Codex exposes built-in skill paths to the model, so a
  random home path changes the prompt. This was discovered by the excluded pilot, not guessed.
- Provider-backed runs were strictly sequential. Every before/after row printed loadavg and
  `MemAvailable`; the live Orchestra service/session was not invoked by the harness.

### Excluded pilot: context was not actually fixed

The first A/A used a random `CODEX_HOME` pathname per run. Rollout diff showed that the built-in
skill catalog embedded paths such as `$CODEX_HOME/skills/.system/...`; prefix hashes differed and
input totals were `9476/9476/9471`. Those four calls (warm-up + A/A/A) are preserved under
`raw/aa-excluded-variable-home/` and excluded permanently. The repair kept task/schema/metric/gate
unchanged and recreated fresh contents at one fixed pathname. The valid second A/A had identical
base hash, prefix hash, and `9436` input tokens in all runs [M0][M2].

## 3. A/A noise result

The unit is one complete fixed task. The warm-up is excluded. `Client overhead` is
process/handshake + queue + post-processing; model wait and tool work are separate.

| fixed `codex exec` run | process/handshake | queue | model wait | tools | post | client overhead | total wall | AC |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A/A 1 | 1.901 s | 0.247 s | 8.474 s | 0.000 s | 0.821 s | 2.969 s | 11.443 s | PASS |
| A/A 2 | 2.583 s | 0.152 s | 4.275 s | 0.000 s | 1.017 s | 3.752 s | 8.027 s | PASS |
| A/A 3 | 1.990 s | 0.213 s | 3.919 s | 0.000 s | 0.612 s | 2.814 s | 6.733 s | PASS |

- Preregistered client-overhead noise: `max-min = 0.937 s`.
- Expected removable effect: median exec process/handshake `1.990 s`.
- Gate: `0.937 < 1.990`, all AC passed → A/B permitted.
- Total-wall range: `4.710 s`; model-wait range: `4.555 s`. Total wall is not a usable transport
  locator at this sample size.
- All three: 1 call, `9436 input / 0 cached / 21 output / 0 reasoning-output`, 0 tools.

Load was not flat: run starts were load-1 `5.67 / 6.85 / 8.41`; `MemAvailable` remained roughly
16.7–17.4 million kB. This is counter-evidence for total-wall comparisons, but the local metric
still passed its preregistered noise gate [M2].

## 4. Interleaved A/B/A/B result

One excluded warm-up per arm preceded the measured order. App-server process/handshake is shown as
the separately measured cold cost; it is not charged to an already-persistent steady turn.

| run | cold process/handshake | queue | model wait | tools | post | steady client overhead | observed turn/command wall | cache | AC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| app 1 | 1.627 s | 0.032 s | 4.636 s | 0.000 s | 0.050 s | 0.081 s | 4.717 s | 6912/9436 | PASS |
| exec 1 | 1.745 s | 0.180 s | 3.379 s | 0.000 s | 1.190 s | 3.115 s | 6.493 s | 0/9436 | PASS |
| app 2 | 3.053 s | 0.249 s | 3.344 s | 0.000 s | 0.136 s | 0.385 s | 3.729 s | 0/9436 | PASS |
| exec 2 | 2.053 s | 0.251 s | 3.588 s | 0.000 s | 0.830 s | 3.134 s | 6.722 s | 0/9436 | PASS |

Mechanical comparison from [`comparison.json`](comparison.json):

- paired exec-minus-app client overhead: `3.033 / 2.749 s`; median `2.891 s`;
- A/A client-overhead noise: `0.937 s`; observed local effect exceeds it;
- paired exec-minus-app observed wall: `1.777 / 2.993 s`; median `2.385 s`, **smaller than the
  4.710 s A/A total-wall range**;
- all four: exact same base-instructions hash, model-visible prefix hash, `9436` input tokens,
  task/schema/cwd/model/effort, one call, zero tools, `21` output and AC PASS;
- cache rule failed: one run was 73.25% cached, three were 0%; required arm-median difference
  `<=2 pp` and full range `<=5 pp` both failed;
- therefore `valid_causal_comparison=false`, `verdict=no-path-verdict`.

Load-1 immediately before measured A/B runs was `3.21 / 2.87 / 3.04 / 4.60` in interleaved
order. `MemAvailable` was `17,691,628 / 17,703,748 / 17,707,392 / 17,701,972 kB`. The second exec
started under higher load than its paired app run. Its client overhead nevertheless remained close
to exec 1, but the load imbalance stays counter-evidence rather than being normalized away [M3].

## 5. Calls, tokens/cache, quota and failures

### Confirmatory measured runs only

- Runs: 3 A/A + 4 A/B = **7**.
- Calls: **7**, exactly 1 per run.
- AC/failures: **7/7 PASS**, **0/7 failures**; zero tools in every run.
- Token totals: `66,052 input`, `6,912 cached-input` (reported subset of input),
  `147 output`, `0 reasoning-output`, `0 cache-write`.
- Per-run input/output were identical (`9436/21`); only cache attribution differed.

Warm-ups and the excluded pilot remain present for cost/audit but are not added to confirmatory
statistics: 3 valid warm-up calls plus 4 context-invalid pilot calls. Across every benchmark call,
there was no provider/AC failure.

### Quota

The direct meter app-server read `account/rateLimits/read` before and after every provider call.
For every measured A/B run, primary `limitId=codex` stayed at integer `usedPercent=51`; per-run
delta was **0 percentage points at the returned resolution**. The separate Bengalfox/Spark bucket
stayed 0%. This is not proof of zero consumption: task use is below the integer snapshot
resolution, and the Codex account is shared with other machines/sessions. Quota attribution is
therefore **UNRESOLVED / not attributable**, while exact token telemetry above is attributable
[M2][M3]. This follows the #374/#375 warning not to infer per-turn subscription use from a shared
percentage counter [5][6].

## 6. Findings and confidence

1. **CONFIRMED — current lifecycle ownership.** Local source directly shows one retained
   app-server/thread and warm `turn/start`; direct exec starts/exits per invocation. Evidence tier
   2 (current primary source) plus tier 1 event traces [1][2][M3].
2. **CONFIRMED for this fixture/sample — total wall was not a usable app-server-delay locator.**
   Same-path A/A total-wall noise exceeded the interleaved median total-wall difference. Adequate
   replication/modeling could support a different study; this result is not a general impossibility
   claim. Evidence tier 1 [M2][M3].
3. **LIKELY — warm persistence avoids about 2–3 seconds of local lifecycle on this machine/task.**
   Both interleaved pairs showed the same sign and exceeded local A/A noise; code supplies the
   mechanism. Confidence is not CONFIRMED because the frozen cache invariant failed [M3].
4. **REFUTED on this sample — cold app-server is inherently faster.** Its cold handshake overlapped
   and was sometimes slower than exec startup [M3].
5. **UNCERTAIN — end-to-end path/usage decision.** Cache differed, total-wall noise was larger
   than total effect, task class was one trivial tool-free call, and outer Orchestra admission/
   persistence/prompt work was traced but not benchmarked [M2][M3].
6. **CONFIRMED for the present experiment — raw total-turn wall alone did not establish transport
   delay.** This controlled A/A measured large model-wait variance [M2]. Separately, #372 reported
   provider/model wait dominating its long-turn observations [4]; the independent #376 reviewer
   did not inspect that external report because its scope was intentionally restricted.

## Counter-evidence and limitations

- The preregistered cache check failed. Post hoc argument that cache “should not affect local
  overhead” does not reopen the gate; the experiment promised a cache-valid path verdict.
- Provider prompt caching was nondeterministic even after one warm-up per arm. No cache-disable
  control was available in the frozen harness.
- Load was interleaved and printed, but not equal; the second pair had a `3.04 → 4.60` load-1
  shift before app → exec.
- The task is intentionally bounded and tool-free. It isolates lifecycle but does not represent a
  50-tool research turn, persistent resume, compact, steer, or MCP lifecycle.
- The app arm reproduced the current app-server protocol seam, not the live manager/session. This
  obeyed the no-live-target constraint but excludes quota admission, prompt rebuild, DB/SSE writes,
  managed-state seed, systemd scope and FD publication from the measured steady value.
- Conversely, the exec arm was naked `codex exec`; current `codex_review` adds background-job,
  shell, tee, artifact-validation and accounting work.
- Cold app-server setup was measured afresh for every arm only to expose it; a genuinely persistent
  process would pay it once across many turns. A one-shot app-server comparison must include cold
  setup and cannot reuse the steady number.
- Quota snapshots have integer resolution and shared-account interference; zero points is not zero
  usage.
- `n=2` per A/B arm estimates mechanism, not a population latency distribution.

## Decision boundary and next falsifier

No path verdict is made. A new confirmatory study must be preregistered before more provider runs
and should:

1. demonstrate a supported cache-neutral condition before timing (all arms same cached-token
   count/ratio, or a provider-supported cache-disable control);
2. keep the fixed absolute home path while recreating state, because random homes alter the skill
   catalog context;
3. retain A/A and interleaving/load prints;
4. add a second representative deterministic task, ideally a bounded multi-turn/tool fixture;
5. instantiate the Orchestra session/backend stack against an isolated DB/home if outer-path
   overhead is part of the question, still never targeting the live service/session;
6. predeclare whether the decision metric is warm steady latency, cold one-shot latency, or
   throughput over N turns. These are different products and cannot share one number.

Until that falsifier is run, the only justified product action is **no evidence-driven change**.
This is not one of the requested path verdicts because its precondition (valid effect exceeding
noise) was not fully met.

## Affected files and risks if this later becomes implementation

Research-only; no implementation is proposed.

- `app/backend_codex.py`: persistent process/thread, managed home, config refresh, turn protocol,
  disconnect.
- `app/session.py`, `app/manager.py`: admission, prompt/state, delivery lock, event persistence.
- `app/mcp_stdio.py`, `app/codex_review_artifact.py`: current `codex exec` review wrapper and
  additional post-processing.

Risks of switching include losing native steer/resume/FD-handover semantics, duplicating outer
accounting, or optimizing a 2–3 second local phase while model/tool work remains minutes. Risks of
retaining include per-idle-session process/RSS cost documented by #377 and cold setup when sessions
are short-lived [7].

## Sources

1. **Tier 2, current local primary source:** `app/manager.py:1014-1028`;
   `app/session.py:1043-1235,1265-1316,1722-1798,1914-1938` at current task checkout.
2. **Tier 2, current local primary source:** `app/backend_codex.py:918-1140,1380-1400,
   2229-2245` — managed connection, initialize/thread start or resume, warm turn start, teardown,
   exact command owner.
3. **Tier 2, current local primary source:** `app/mcp_stdio.py:2407-2647` and
   `app/codex_review_artifact.py:1-201` — current `codex_review`/`codex exec` wrapper lifecycle.
4. **Tier 1 prior measurement:** `docs/tasks/372/report.md` — process count, load and decomposition
   of long turns; model wait dominated tool work.
5. **Tier 1 current-code/measurement synthesis:** `docs/tasks/374/research.md` and review — exact
   model/effort delivery and shared-quota attribution limit.
6. **Tier 1 current measurement:** `docs/tasks/375/research.md` and review — current 0.149 context,
   token/cache telemetry boundaries and no inference from observational total wall.
7. **Tier 1/2 current audit:** `docs/tasks/377/research.md` and review — CLI/live process version,
   persistent session footprint and applicable lifecycle risks.
8. **Tier 1 direct experiment:** `docs/tasks/376/protocol.md`, `aa-gate.json`, `comparison.json`,
   `aa-run.log`, `ab-run.log`, and per-run raw/summary/rollout artifacts under
   `docs/tasks/376/raw/`.

## Measurement index

- **M0 — excluded pilot:** `raw/aa-excluded-variable-home/`,
  `aa-analysis-excluded-variable-home.log`, `aa-gate-excluded-variable-home.json`.
- **M1 — harness and frozen oracle:** `protocol.md`, `benchmark.py`, `analyze.py`, `task.txt`,
  `output-schema.json`; `python3 -m py_compile ...` and JSON parse passed.
- **M2 — valid A/A:** `raw/aa/`, `aa-run.log`, `aa-analysis.log`, `aa-gate.json`.
- **M3 — interleaved A/B:** `raw/ab/`, `ab-run.log`, `ab-analysis.log`, `comparison.json`.

## Review gate inputs

- **Artifact/consumer:** this research report plus reproducible benchmark artifacts; consumed by
  the task owner deciding whether to change a shared runtime path. No code/config consumer changed.
- **Author:** `gpt-5.6-sol`, Codex runtime, from current Orchestra session metadata.
- **AC:** all eight mandatory protocol clauses; no path verdict unless effect exceeds A/A noise and
  all frozen confound checks pass; no production mutation.
- **Mechanical checks:** `python3 -m py_compile docs/tasks/376/{benchmark,analyze}.py`;
  `python3 docs/tasks/376/analyze.py aa`; `python3 docs/tasks/376/analyze.py ab`;
  exact per-run summary/rollout hashes and outputs; `git diff --check`; secret-shape scan.
- **Review route:** targeted fresh Sol falsification because the conclusion is causal/statistical
  and affects shared runtime lifecycle. The reviewer must specifically try to disprove phase
  attribution, the exclusion of total wall, and the decision to withhold a path verdict.

## Independent review outcome

One fresh targeted Sol round completed in [`review-research.md`](review-research.md). The reviewer
reran both analyzers, recomputed the confirmatory totals (`7 calls / 7 pass / 0 fail / 0 tools`,
`66052 input / 6912 cached / 147 output`), and spot-checked raw-event timing. It quoted the report
line “Operational no-change follows from absence of a valid verdict, not from pretending the
existing path won,” satisfying completed-verdict evidence.

Verdict: **needs minor documentation correction; no blocking findings**. The reviewer agreed that
the cache invariant failure requires withholding all requested path verdicts. Its two suggestions
and one question were resolved in this document: the Codex event path now cites
`_persistent_event_loop()`, total-wall claims are scoped to this fixture/sample, and the #372
sentence distinguishes present evidence from the separately sourced prior report. The review
policy permits no second prose round for suggestion-only changes.

## Knowledge-base note

The task ownership boundary permits writes only under `docs/tasks/376/` and personal memory, so
`docs/kb/` is intentionally not modified despite the normal Phase-1 topic-file rule.
