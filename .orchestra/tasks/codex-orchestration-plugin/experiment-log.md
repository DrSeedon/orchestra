# Experiment log — Codex-Orchestration research

Date: 2026-07-18
Workspace production code was not modified. Plugin checkout and native config lived under `/tmp`; native policy was disabled after the test.

## Versions

```text
codex-cli 0.144.5
Claude Code 2.1.197
Python 3.13.7
Plugin 0.5.1 @ df1e3da61fcca1b6134fdc1ac1a1f3100d403757
```

## Upstream validation

Commands:

```bash
python3 -m compileall -q plugins tests scripts
python3 -m unittest discover -s tests -v
python3 tests/plugin_lifecycle_smoke.py
python3 scripts/release_check.py
```

Raw terminal summary:

```text
Ran 189 tests in 24.854s
OK
PASS: installed 0.5.0, upgraded to 0.5.1, verified its cache,
and ran native plus custom setup/status/cleanup
Release metadata is consistent for 0.5.1.
```

## Isolated native routing

Configurator arguments (temp `--codex-home` omitted from artifact because it was disposable):

```text
--codex-bin /home/maxim/.local/bin/codex
--executor-model gpt-5.6-sol --executor-effort xhigh
--advisor-fable --advisor-effort high
```

Preview/apply/status raw summary:

```text
Client: codex-cli 0.144.5 — supports native policy
Executor: gpt-5.6-sol@xhigh
Planner: root
Advisor: Claude Fable 5 high
Claude Fable 5 login: ready — first-party
Tool namespace: agents
Native routing policy installed.
Native policy: installed and effective
Routing validation: not performed — config effectiveness does not prove live route
Native routing disabled.
```

## Live Fable calls

No-tools command shape:

```text
claude -p --model claude-fable-5 --effort high --safe-mode
  --tools "" --permission-mode dontAsk --no-session-persistence
  --prompt-suggestions false --output-format json
```

Direct call raw summary:

```json
{
  "signal": "PLAN_APPROVED",
  "used_models": ["claude-fable-5", "claude-haiku-4-5-20251001"],
  "duration_ms": 13820,
  "duration_api_ms": 15403,
  "num_turns": 1,
  "total_cost_usd": 0.042307
}
```

Upstream bridge `review_plan()` raw summary:

```json
{
  "auth_method": "claude.ai",
  "decision": "PLAN_APPROVED",
  "effort": "high",
  "model": "claude-fable-5",
  "used_models": ["claude-fable-5", "claude-haiku-4-5-20251001"]
}
```

## Effort exploratory benchmark

All calls used `codex exec --ephemeral --ignore-user-config --ignore-rules`, Sol, read-only sandbox, and no repository task. Scores were fixed before execution in `research.md`.

| Case | Effort | Score | Wall | Input | Cached | Output | Reasoning | Exit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Path containment | medium | 3/3 | ≤60 s | 18,636 | 0 | 664 | 300 | 0 |
| Path containment | high | 3/3 | ≤90 s | 16,517 | 9,984 | 2,476 | 2,070 | 0 |
| Path containment | xhigh | n/a | >300 s | n/a | n/a | n/a | n/a | session output lost on reconnect; excluded |
| Async subprocess | medium | 3/3 | 134,217 ms | 19,199 | 18,176 | 1,600 | 992 | 0 |
| Async subprocess | high | n/a | 203,502 ms | n/a | n/a | n/a | n/a | 1 |

The first parallel harness yielded before completion and lost exact completion timestamps for the path case; therefore only upper-bound poll intervals are reported. No quality claim uses the invalid `xhigh` or failed `high` run.

## Repository maturity/claim audit

```text
GitHub repository created_at: 2026-07-10T04:33:07Z
As checked 2026-07-18: stars 384, forks 29, open issues/PRs 8
main HEAD: df1e3da61fcca1b6134fdc1ac1a1f3100d403757
Git tags: none
GitHub Releases API: []
```

Repository-wide search found `2x` and `40%` only in README marketing copy and tests asserting that the qualified copy exists. It found no benchmark corpus, raw measurements, repetitions, or variance.
