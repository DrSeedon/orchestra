# #376 preregistered benchmark protocol

Frozen before provider-backed benchmark runs on 2026-08-23.

## Question and hypotheses

- **Context:** Orchestra uses one persistent `codex app-server --stdio` process and one native
  thread per session. The comparison surface is a fresh `codex exec` process/thread per task.
- **Change under test:** replace the persistent app-server delivery surface with `codex exec`, or
  change how either is used.
- **Baseline:** current persistent app-server path, measured after its process is initialized and
  its fresh thread exists. Its cold lifecycle is still reported separately.
- **Outcome:** local client/lifecycle overhead, decomposed from provider/model wait, plus exact AC,
  calls, tokens/cache, quota snapshot delta and failure rate.

H1: persistent app-server removes per-task process/handshake work, so its steady client overhead is
lower than `codex exec` by more than `codex exec` A/A noise.

Falsifier: the interleaved median effect is no larger than A/A range, reverses sign, or context,
cache, load, model/effort, task or acceptance invariants differ between arms.

H2: total-turn differences previously attributed to app-server are provider/model variance, not
transport.

Falsifier: after removing model wait/tool work and interleaving load, the transport effect remains
larger than A/A noise with all invariants satisfied.

## Frozen task and AC

- Prompt: byte-for-byte contents of `task.txt`.
- Output constraint: byte-for-byte contents of `output-schema.json`, passed as
  `--output-schema` to `codex exec` and `outputSchema` to `turn/start`.
- AC: parse final response as JSON and require exact equality
  `{"answer":"ORCHESTRA-376-OK"}`; require zero tool calls, model `gpt-5.6-sol`, effort `medium`,
  standard service tier and a fresh native thread/home for every provider-backed run.
- Both arms use the same empty absolute cwd, isolated controlled `CODEX_HOME`, ChatGPT auth
  symlink, sandbox `read-only`, approval policy `never`, apps/web/multi-agent disabled and the same
  explicit 872000/784800 context settings.

## Timing definitions

- **Process/handshake:** process spawn to `thread.started` (`codex exec`); process spawn through
  `initialize` + `thread/start` response (cold app-server). The persistent arm pays zero of this
  phase at steady turn delivery; its measured cold cost is not hidden.
- **Queue:** native thread ready / `turn/start` send to `turn.started`.
- **Model wait:** `turn.started` to completed agent message for this tool-free one-call task.
- **Tool work:** paired tool item duration; preregistered expectation is exactly zero.
- **Post-processing:** completed agent message to `turn.completed` and process exit for exec;
  completed agent message to `turn/completed` for persistent app-server. App-server teardown is
  recorded separately and is not part of steady delivery.
- **Primary metric:** client/lifecycle overhead = process/handshake + queue + post-processing for
  exec, versus queue + post-processing for an already-persistent app-server.

## Noise gate and order

1. One excluded `codex exec` warm-up, then three measured `codex exec` A/A/A runs. All provider
   calls are strictly sequential and print loadavg + MemAvailable immediately before and after.
2. A/A noise is the range (`max-min`) of the primary metric. Expected removable effect is the
   median measured exec process/handshake phase. **A/B is forbidden unless noise < expected
   removable effect.** This gate is computed by `analyze.py aa` and consumed by the A/B runner.
3. If the gate passes, one excluded warm-up per arm is run sequentially, followed by measured
   app-server/exec/app-server/exec (A/B/A/B).
4. A path verdict is forbidden unless the median interleaved effect exceeds the preregistered A/A
   noise and all invariants below pass.

## Confound checks

- Model, effort, task hash, schema hash, cwd and controlled config must match exactly.
- Rollout `base_instructions` and the model-visible pre-user response-item sequence are hashed;
  hashes must match across arms. Any mismatch invalidates causal transport attribution.
- Input tokens must match exactly across measured arms. Cached-input ratio arm medians may differ
  by at most 2 percentage points and the full measured range by at most 5 points. Otherwise cache
  is a confound and no path verdict is allowed.
- Calls and tools must match; any AC failure makes the run a failure rather than a timing sample.
- Load is not corrected post hoc. Interleaving plus printed load is the control; obvious load trend
  remains counter-evidence.
- Quota snapshots are reported, but a shared-account percentage delta is marked unattributable if
  foreign turns exist or the provider resolution is coarser than this task.

## Safety and scope

The harness starts disposable direct Codex processes only. It does not call the Orchestra HTTP/MCP
delivery API, target any live Orchestra session, restart/update/configure the service, or alter app
code/config. Disposable state is recreated before every run at one fixed `/var/tmp` home pathname:
Codex exposes built-in skill paths to the model, so a random home pathname would change context.
The home contains only a symlink to existing auth, is parsed, copied as sanitized benchmark
artifacts, and removed after each run.

## Excluded pilot

The first A/A attempt used a different random `CODEX_HOME` pathname per run. The rollout prefix
hashes and input counts (`9476/9476/9471`) exposed the error before A/B: Codex's built-in skill
catalog embeds absolute `$CODEX_HOME/skills/...` paths. Those runs remain under
`raw/aa-excluded-variable-home/` and are excluded permanently. The task, schema, timing metric and
noise rule were not changed; only the violated fixed-context setup was repaired by recreating
fresh contents at one fixed pathname.
