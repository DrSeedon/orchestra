# Measurement snapshot for #170

This directory is a redacted, read-only reconstruction of Codex worker
`feat-groom-demo`, session `313c5206-05fe-4a02-b9ba-0928eed88a98`, through
`2026-08-09T13:54:49.350Z`. The session was archived after its last turn; the
captured rollout and database rows remain the source of truth.

## Reproduce

Run from the Orchestra checkout. The analyzer opens SQLite with
`mode=ro`; it does not copy or mutate the live database.

```bash
python3 -m py_compile docs/tasks/170/measurements/analyze_session.py
python3 docs/tasks/170/measurements/analyze_session.py \
  > /tmp/task170-aggregate.json
```

The defaults are pinned in the script:

- database: `/home/kesha/orchestra/data/orchestra.db`;
- scope/name: `/home/kesha/projects/seedon`, `feat-groom-demo`;
- rollout: `/home/kesha/.codex/sessions/2026/08/09/rollout-2026-08-09T09-31-21-019fe56e-f44f-73a3-b92c-48b6ebde1dbc.jsonl`;
- quota-client cutover: `2026-08-08T12:54:46Z` (`8369737`).
- evidence cutoff: target's final turn end, `2026-08-09T13:54:49.350Z`;
  later audit calls cannot change the matched before/after sample.

Recheck the live route/process without exposing the token:

```bash
curl -fsS -H "Authorization: Bearer $INTERNAL_TOKEN" --get \
  --data-urlencode 'model=gpt-5.6-sol' \
  http://127.0.0.1:8888/api/usage/readiness
systemctl show orchestra -p MainPID -p ActiveEnterTimestamp --value
git reflog main --date=iso-strict --format='%H %gd %cd %gs'
```

## Output map

- `aggregate.json`: p50/p95/max and component totals.
- `turns.csv`: all 26 turns, trigger/queue time, TTFT, tools, usage and safe phase labels.
- `messages.csv`: new-turn versus in-flight steering, byte counts and delivery/next-model latency.
- `tool_calls.csv`, `mcp_calls.csv`: redacted per-call timings and classes.
- `background_jobs.csv`: all standalone review jobs and durations; no commands/prompts.
- `context_events.csv`, `compactions.csv`: turn lifecycle, precompact and native compaction.
- `payload_sizes.csv`, `heavy_results.csv`, `read_counts.csv`: volume and repeated-read evidence without content.
- `tool_errors.csv`, `web_searches.csv`: safe error/search classes and counts.
- `codex_review_cutover.csv`: matched `codex_review` outcomes before/after `8369737`; scopes are hashed.
- `environment.json`: live version-skew, prompt/config sizes and sanitized incident strings.

Percentiles use nearest-rank p95 and ordinary median p50. `TTFT` is Codex's
authoritative `task_complete.time_to_first_token_ms`. `effective_tool_union_s`
extends yielded commands through their matching wait/resume cell and removes
overlap. The residual is **not** asserted to be pure provider compute: it also
contains model reasoning/generation and uninstrumented internal activity such
as native web search.

No prompt text, command text, credentials, MCP arguments/results, or retrieved
file contents are serialized. A case-insensitive secret-marker scan of this
directory found no credential-shaped output.
