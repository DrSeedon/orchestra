# #286 — preregistration: minimal Luna vs Spark refresh

This file, the two prompts, and `run_bench.py` are committed before the first model turn.
No confirmatory cell is added or replaced after results are visible.

## Question and hypotheses

- **Context:** refresh the #222 Luna/Spark routing boundary on current Orchestra history without
  rerunning the five already-measured cells.
- **Change under test:** use Spark instead of Luna for fully closed one-file tasks with a frozen
  test and identical initial repository/context.
- **Baseline:** Luna on the byte-identical task at the same `high` effort.
- **Primary outcome:** frozen-test correctness. Secondary outcomes: mode of failure, completed
  tool calls and failed tool calls, total wall time, cold start, input/cached/output tokens, and
  virtual API-equivalent dollars where an official price exists.

H1: Spark retains Luna's correctness on this narrow class and reduces latency. It is falsified if
Spark fails either frozen oracle or is not faster on either paired task.

H2: Luna remains materially more token/cost efficient. It is falsified if Spark uses no more
input/output tokens on both tasks and an official Spark dollar rate establishes equal or lower
cost. A missing public Spark rate leaves the dollar comparison **UNKNOWN**, never zero.

Alternative H3: #222 already answers every load-bearing question. It is falsified because its
committed rows do not contain per-tool failure outcomes or time to first model action; those are
the only empirical gaps this refresh is allowed to fill.

## Reused evidence — excluded from new-run N

`docs/tasks/222/blind-grades.json` (20 confirmatory runs) remains the evidence for incomplete
specification, text completeness, 102K/164K context behavior, and the earlier code task. Its
reported result is not rerun: Spark silently invented a missing constant 2/2 while Luna asked
2/2; Spark failed loudly before output at ~164K 2/2; both passed 102K extraction 2/2; on the old
closed code cell both passed 2/2 and Spark's median wall was 21% lower. The strict physical
unreachability limitation from #222 remains: network and unrelated HOME paths were available.

## New fixtures

The harness creates a one-commit seed from the historical base snapshot, overlays only the
already-committed acceptance test, then makes both model clones with `git clone --no-local`.
The later implementation commit is absent and must fail `git cat-file -e` in every seed and clone.
The parent repository and cold archive are hidden from model processes with `InaccessiblePaths`.

| Cell | Historical base | Future implementation, unreachable | Writable file | Frozen oracle |
|---|---|---|---|---|
| silence-upsert (#272) | `d0023db6c5137abcd167026475221827b39f56af` | `cfdb1d0e04d79cf628032c2c6426cebe4b1443c4` | `app/db.py` | two named tests in `tests/test_quota_alert_state.py` |
| no-quota-suffix (#277) | `029d7573d8998ed818c0a8da5cad46cf1407c684` | `9268255cf199a0b95e9001e803c3f13544256896` | `app/session_turns.py` | `tests/test_turn_ended_no_quota_suffix.py` |

Frozen acceptance SHA-256 values are respectively
`21b355181967837008612738fe9315c2211e13afba4d9433c3bc34a594ca7331` and
`8a72aee377002be4aa9f212fe1985a6322ec5bb38c71c511922916bded51a563`.

Before model turns the harness must show each exact command exits non-zero for the missing
behavior, not for collection, dependency, or import failure. A model run is invalid if the frozen
test hash changes, a path outside the single writable file changes, the future commit becomes
reachable, an alternates file exists, or a recorded command accesses a prohibited answer source.

Fixture-only verification before this commit produced the intended REDs:

- silence-upsert: `1 failed, 1 passed`; first substantive assertion
  `assert row is not None` / `E assert None is not None`;
- no-quota-suffix: `1 failed`; first substantive assertion
  `assert "5h:" not in ended`, with the old `Claude 5h:67% ...` suffix present.

Neither run invoked a model. Both future commits were unreachable and both oracle hashes matched
the values above.

## Models, N, and equality controls

- Models: `gpt-5.6-luna` and `gpt-5.3-codex-spark`.
- Both use Codex CLI `--ephemeral`, a fresh thread/process/clone, and
  `model_reasoning_effort="high"`.
- N=1 per model per cell: two real tasks × two models = four confirmatory turns. Each pair starts
  concurrently; no other benchmark worker is started.
- Both arms in a cell receive the same seed commit and byte-identical prompt. Model slug is the
  only intended difference.
- Fixed order: silence-upsert pair, then no-quota-suffix pair. No retries.

## Metrics and grading

- **PASS:** exact frozen command exits 0 after the turn; oracle hash unchanged; changed tracked
  paths equal the one allowed production file; that file has a non-empty diff.
- **LOUD_FAIL:** PASS is false and the final explicitly reports failure/blocker or no final exists.
- **SILENT_FALSE_SUCCESS:** PASS is false while the final claims success/green/completion.
- **tool calls:** completed `command_execution`, `mcp_tool_call`, `file_change`, or `web_search`
  JSONL items. **tool-call failures:** completed command with non-zero exit/failed status or MCP
  item with error status.
- **wall:** process launch to process exit, including CLI/session initialization and tools.
- **cold start (primary):** process launch to the first model-generated item
  (`command_execution`, `mcp_tool_call`, `file_change`, `web_search`, or `agent_message`) on the
  fresh ephemeral thread. Launch-to-first-JSON-event is also recorded as client startup.
- Token counters are the final `turn.completed.usage` values. Fresh input is
  `max(input-cached, 0)`.
- Luna virtual API-equivalent uses the current official $0.20 fresh-input / $0.02 cached-input /
  $1.20 output per million tokens. Spark dollars remain `null` while its official rate card says
  `research preview`; a Luna-priced Spark trace is sensitivity only and is never called Spark cost.

No statistical significance or population error rate is claimed from N=2 tasks.

## Official-source claims to verify separately

Primary public pages are opened during this task, not recalled from memory:

1. https://openai.com/index/introducing-gpt-5-3-codex-spark/
2. https://developers.openai.com/api/docs/models/gpt-5.6-luna
3. https://developers.openai.com/api/docs/guides/latest-model
4. https://help.openai.com/en/articles/20001106

Public intent is not inferred across surfaces: Spark's Codex research-preview description and
Luna's public API description are reported as separate product claims, then compared with our
measured ChatGPT-auth CLI behavior.
