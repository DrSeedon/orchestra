# V-831 follow-up: why tool calls and text appear in chunks

The owner reported on 14.10 that tool calls appear "обрывками" and that text appears all at once ("бам и всё").
Verdict: **the tool-call chunks were caused by us**: the agent CLI environment we set turns off fine-grained tool streaming. That is fixed.
**The text chunks are upstream.** Opus 5.5 text reaches the CLI in bursts, and our old typewriter painted each burst within a few frames. The display now paces it.

## 1. What the CLI receives (timestamped `stream-json`, CLI 2.1.293, model claude-opus-5-5)

Method: `cli_capture.py` stamps every stdout line of `claude -p … --include-partial-messages`. A burst is a set of deltas arriving within 15 ms of each other (`bursts.py`); `analyze_cli.py` gives per-delta stats.

| capture | block | deltas | bursts | chars per burst p50/p90/max | gap between bursts, ms p50/p90/max |
|---|---|---|---|---|---|
| `cli_opus_write.jsonl` (my shell env) | tool_use (Write, 3 658 chars) | 263 | 240 | 15/23/107 | 50/56/382 |
| `cli_sonnet_write.jsonl` (my shell env) | tool_use (4 254 chars) | 388 | 350 | 11/20/86 | 33/39/296 |
| `cli_opus_write_prodenv.jsonl` (`DISABLE_TELEMETRY=1 DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, as Orchestra sets) | tool_use | 513 | **3** | 133/133/**3 451** | 509/509/**12 661** |
| `cli_opus_write_prodenv_fgts.jsonl` (same + `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`) | tool_use | 269 | 252 | 14/23/71 | 50/58/318 |
| `cli_opus.jsonl` (my shell env) | text (5 092 chars) | 323 | 27 | 189/222/291 | 580/633/1 167 |

The same production-shaped stream, seen on the live server's SSE for this worker session (`sse_live_self.jsonl`, recorded with `sse_record.py` and the internal token): my Write call of about 3 600 chars arrived as `137` chars, then **10.6 s of silence**, then one frame of `3 500` chars.

**Cause in the CLI.** The bundled CLI code (`claude.exe`, function guarding `eager_input_streaming`) enables fine-grained tool streaming when `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING` is not false and one of two conditions holds:
- first-party auth together with the remote GrowthBook flag `tengu_fgts`;
- the env var is explicitly true.

Orchestra launches agent CLIs with `DISABLE_TELEMETRY=1` and `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1` (#56). With those set, the flag keeps its default `false`. The API then sends tool input one complete JSON value at a time, so a 3.4 KB `content` value arrives in one piece at the end. The A/B pair above shows that adding the variable alone restores ~14 chars every 50 ms.

**Text is different.** It arrives in ~190-char bursts every ~600 ms even in my unrestricted shell. The individual deltas are small (p50 16 chars) but arrive packed together. The batching therefore happens before the CLI (API/transport). The CLI does not merge them, and there is no flag for this in the client code I inspected.

**Codex.** `sse_live_codex_perf_audit.jsonl` recorded 180 s of the running Luna worker. It contained 10 frames and no agent-message text at all (the worker was executing commands). Codex text granularity was therefore not measured in this pass. Codex `stream` payloads go through the same paced bubble.

## 2. What the browser paints (`browser_replay.py`)

The captures were replayed with their real timestamps through `ClaudeBackend._convert → AgentSession → broker → SSE (coalesce per ~100 ms tick) → dashboard`, on a separate demo server with a temp DB. The page sampled the visible length of the tool card and the text bubble every animation frame (`replay-*-samples.json`, summaries in `replay-*.txt`).

| run | tool card: paint updates · chars per update p50/max · longest stall | text bubble: chars per update p50/p90 · ms between updates p50/p90 |
|---|---|---|
| **before** (committed JS, production CLI env) | **2** · 128/**3 365** · **12.8 s** | 36/60 · 61/**386** |
| after JS only (still production CLI env) | 61 · 76/78 · 12.5 s (nothing arrives to show) | 19/26 · 63/70 |
| **after** (JS + fine-grained streaming) | **601** · 4/100 · 0.47 s | 18/27 · 63/76 |

The 14–15 s maxima in the text column are the pause between the two replayed captures, not part of either stream.

Screens: `replay-before-0.png`, `replay-after-0.png` (the card is mid-word "Switches forward fram…" at 307 симв/с).

## 3. Fixes

- `app/backend_claude.py`: the agent CLI env gets `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`. This is Python, so it **needs an Orchestra restart**. It also only applies to a session after its CLI process is relaunched. Test: `test_agent_cli_streams_tool_arguments_finely`.
- `app/static/js/live-activity.js`, `LivePacer`: reveals arrived text at a rate that spreads each burst over the observed gap between bursts (EMA, clamped 80–1200 ms), with at least half a char per frame. It is used by the tool-input card (one RAF loop per card) and by the streaming text bubble in `chat.js`, where it replaces `max(12, pending/8)` per frame. A final `text` row or a replay flushes immediately. This is JS, so it is picked up on page reload. Test: `test_pacer_spreads_a_burst_over_the_observed_gap`.

Known tradeoff: the paced text lags the arrived text by at most about one burst gap (~0.6 s for Opus text). It catches up instantly when the final row lands.
