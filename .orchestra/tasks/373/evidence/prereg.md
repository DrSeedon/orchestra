# #373 — preregistration (frozen before provider calls)

Timestamp: 2026-08-23. Installed binary: `codex-cli 0.149.0`. Model:
`gpt-5.6-sol`; subscription authentication only. Every provider-backed request is
strictly sequential. Each latency row records `/proc/loadavg` immediately before
the request.

## Effort experiment

- Interface: ordinary `codex exec`, isolated temporary `CODEX_HOME` containing a
  copy of the existing auth file and no config, empty temporary cwd, no MCP, web
  disabled, read-only sandbox, approval never, same prompt and JSON schema.
- Order: A/A noise control `high, high`, then interleaved confirmatory
  `high, xhigh, high, xhigh`.
- Task: reconstruct the causal interpretation of a frozen context/usage evidence
  packet. The exact-output grader awards 14 independent points (arithmetic,
  mechanism, counter-evidence and falsifier); no model judge is used.
- Primary acceptance: xhigh is supported for this representative task only if its
  confirmatory median is at least 2/14 above high, neither chronological xhigh
  observation scores below its neighboring high observation, median total latency
  is at most 1.5x high, and median total/output tokens are at most 1.5x high.
  Otherwise this experiment does not justify xhigh for this role. A tied perfect
  score is evidence of no quality gain on this task, not proof that no task benefits.
- Latency is interpretable only if the high/high A/A range is smaller than the
  confirmatory high-vs-xhigh median difference; otherwise it is reported as noise.

## app-server versus exec

- Both interfaces use the same installed binary, model, `high` effort, empty cwd,
  user prompt, empty project/user instructions, subscription auth copy, read-only
  sandbox, approval never, disabled web, no configured MCP, and no tool use.
- A/A control: two fresh `exec` turns. Confirmatory order: `exec, app-server,
  exec, app-server`. Each confirmatory cell has an initial turn and a continuation
  of the same thread, so cache/context reuse is observable.
- `exec` launches a new OS process for both initial and `exec resume` turns.
  app-server launches one process, initializes once, and starts a fresh thread for
  each cell; its continuation uses the same process and thread.
- Metrics: process/handshake time, time to first JSON event, first model delta,
  first answer text, total latency, input/cached/output/reasoning tokens, and peak
  summed RSS of the measured process tree. Failures remain rows and are not retried.
- A transport latency effect is called material only if the absolute difference of
  interface medians exceeds both 10% of the exec median and the A/A absolute range.
  Otherwise the result is indistinguishable from measured noise. Model inference is
  not attributed to transport merely because total latency differs.

## Safety and stopping

- No API key, global config/auth write, restart, update, or production mutation.
- Temporary auth copies and benchmark rollouts are removed when the harness exits;
  only redacted aggregate JSON is retained.
- Per request timeout: 600 seconds. A timeout/rate limit ends that row without a
  retry. No huge context-limit probe is run; the existing bounded 509,046-token
  historical control is reused.
