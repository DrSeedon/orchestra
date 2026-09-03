# #307 — oversized Codex app-server resume and compact control

Date: 2026-08-24  
Phase: 1 — research only  
Scope: upstream/OpenAI behavior and sanitized measurements; no production-code edits

## Question

- **Context:** Orchestra 150e696e (#284) reads newline-delimited JSON-RPC from
  `codex app-server --stdio` with a 16 MiB `asyncio.StreamReader` limit. COG repeatedly
  failed to reconnect after restart, while a separate Comfy session reported a blank
  native-compact error.
- **Change under test:** identify the exact oversized JSON-RPC envelope and decide whether
  upstream already exposes a bounded resume path; separately determine which compact phase
  exceeded Orchestra's timeout.
- **Baseline:** default `thread/resume` returns reconstructed `thread.turns`; #284 discards a
  record above 16 MiB and keeps reading.
- **Measurable outcome:** method, request id, serialized record bytes, payload class without
  payload contents, and timestamped compact lifecycle evidence.

## Hypotheses considered

1. **H1 — `thread/resume` response.** Default resume reconstructs full turns and embeds generated
   image results, so response `id=2` exceeds 16 MiB.
   - Falsifier: the captured/replayed oversized record has another id/method, or
     `thread/resume(excludeTurns=true)` still emits the same-size record.
2. **H2 — notification (`item/completed`, `turn/completed`, or compact lifecycle).**
   - Falsifier: the oversized record is a response envelope with `id=2` and no `method`.
3. **H3 — `model/list` / `codex_models_manager` timeout.** The stderr timeout causes connect loss.
   - Falsifier: Orchestra never sends `model/list`, and a no-auth local replay deterministically
     produces the oversized `id=2` response.
4. **H4 — Comfy compact lost its RPC acknowledgement or terminal notification.**
   - Falsifier for lost acknowledgement: app-server accepts compact `id=3` and emits
     `turn/started`/`item/started`. Falsifier for permanent terminal loss: app-server later emits
     `item/completed` and `turn/completed` for the same operation.

## Method and safety

- Read current `connect()`, `compact_context()`, `_read_stdout()`, and the former
  `_discard_oversized_record()`, commit `150e696e`, and the #284 tests.
- Queried Orchestra/app-server logs read-only. Payload text, image bytes, prompts, paths inside
  responses, and credentials were neither printed nor committed.
- Replayed preserved rollouts from disposable clones of `state_5.sqlite` and the rollout file.
  Each probe used a fresh `CODEX_HOME`, had no `auth.json`, ran one `codex app-server --stdio`
  process at a time under `MemoryMax=2G`, sent no turn/model request, and deleted the clone.
- The scanner retained at most a 1 KiB envelope prefix and recorded only length, id, method, and
  a short SHA-256 prefix. No raw response was saved.
- Environment: Linux `7.0.0-30-generic` x86_64, `codex-cli 0.149.0`, stdio JSONL.

## Findings

### F1 — the COG oversized record is exactly `thread/resume` response `id=2`

**CONFIRMED — direct replay plus live app-server request log (evidence tier 1).**

The Orchestra request sequence starts at zero, so connect sends:

1. `initialize`, `id=1`;
2. `initialized` notification;
3. `thread/resume`, `id=2` for a stored native thread.

The COG app-server log shows that exact `initialize id=1` / `thread/resume id=2` pair at
05:06:16, 05:14:41, 05:15:59, 05:18:18, and 05:20:34 UTC. The adjacent Orchestra log repeatedly
reports an oversized JSONL record and later `connect failed ... exited with code 0`.

On a disposable replay of the exact preserved COG thread:

| Field | Measured value |
|---|---:|
| rollout size | 49,984,790 B |
| response record | `id=2`, no `method` |
| response record size | **23,159,303 B** |
| excess over Orchestra cap | 6,382,087 B |
| live-reader lower bound | at least 16,777,217 B |
| response SHA-256 prefix | `6a925a27efcd` |

Only small records preceded it: initialize response 214 B, `configWarning` 500 B,
`remoteControl/status/changed` 207 B, and `thread/status/changed` 149 B. This refutes H2 and H3:
the lost frame is not a notification, compact record, or model-catalog response.

### F2 — seven generated images dominate that response

**CONFIRMED — structural rollout parse and exact upstream duplicate (tier 1 + tier 2).**

The COG rollout has exactly seven `image_generation_end` records totaling 22,612,401 B:
3,832,400; 3,446,241; 3,402,603; 3,350,181; 3,050,640; 2,859,390; and 2,670,946 B. Each has a
paired large `custom_tool_call_output`; those seven paired records total 22,608,258 B. No payload
contents were inspected or retained.

This matches open upstream issue [#21988](https://github.com/openai/codex/issues/21988): one turn
with seven generated images produced a 27 MB app-server frame. Current upstream source explicitly
states that `thread/resume` can contain large MCP and image-generation payloads; its response-only
redaction is limited to two ChatGPT mobile remote client names, not `orchestra` [source](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_resume_redaction.rs).

### F3 — `excludeTurns` is the existing upstream bounded-resume contract

**CONFIRMED — official schema/docs/tests plus direct 0.149.0 control (tier 1 + tier 2).**

Official protocol marks `ThreadResumeParams.exclude_turns` as experimental and defines it as
returning only thread metadata and live-resume state without populating `thread.turns`
([schema](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/thread.rs)).
The app-server README documents the same behavior and pagination alternative
([README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)). Upstream tests
assert that id, preview, history mode, runtime workspace roots, and subsequent-turn usability
survive while `turns` is empty
([tests](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_resume.rs)).

The exact COG clone produced:

| Resume mode | Serialized `id=2` response |
|---|---:|
| default full-history | 23,159,303 B |
| `excludeTurns: true` | **5,104 B** |

Reduction: 99.978%. The bounded response retained the exact thread id, `status={"type":"idle"}`,
preview metadata, model/provider/reasoning/approval/sandbox/cwd/runtime-workspace metadata, and
`turns=[]`. A `thread/status/changed` notification still arrived before the response.

The capability is mandatory: sending `excludeTurns:true` after Orchestra's old initialize payload
without `capabilities.experimentalApi=true` returned JSON-RPC `-32600` in 108 B:
`thread/resume.excludeTurns requires experimentalApi capability`.

### F4 — discarding an unknown oversized record is not recovery

**CONFIRMED — code trace (tier 2) and F1.**

`_read_stdout()` cannot parse an envelope after `readline()` raises on size. Under #284 it discards
the record, but the `id=2` future remains unresolved because that record was the only required
resume response. Continuing to later notifications cannot reconstruct the response or prove which
request was lost. EOF/process exit finally rejects pending requests, producing the observed
code-zero connect failure. Raising the cap merely moves the failure threshold; it does not make
arbitrarily large history bounded.

### F5 — Comfy compact was a slow upstream completion, not the oversized COG frame

**CONFIRMED for the timeline; REFUTED for “Comfy emitted the >16 MiB resume” (tier 1).**

The untagged 05:18:19 global journal line was initially attributed to the image-heavy Comfy scope.
Two controls refute that attribution:

- exact Comfy precompact clone through rollout record 1807: 10,444,411 B rollout ->
  `thread/resume id=2` response **933,418 B**;
- live Comfy app-server log accepted `thread/resume id=2`, then compact `id=3` and emitted progress.

Compact timeline (UTC):

| Time | Evidence |
|---|---|
| 05:17:20 | first `thread/compact/start`, request id 5; service restart interrupts it |
| 05:19:03.187 | second native compact begins after successful resume |
| 05:19:04 | app-server accepts `thread/compact/start`, request id 3 |
| 05:19:05 | app-server emits `turn/started` and `item/started` |
| 05:21:04.360 | Orchestra's 120 s envelope expires; `TimeoutError` stringifies to blank detail |
| 05:21:19 | app-server emits `item/completed` and `turn/completed` |
| 05:30:35–05:30:54 | next compact succeeds; Orchestra logs 83% -> 9% |

The second upstream compact completed about 15 s after Orchestra's local deadline. The evidence
does not prove image payloads caused the delay; this rollout had no `image_generation_end` records.
Related image-compaction issues remain relevant background, not an exact duplicate.

### F6 — upstream report/comment, not a pull request

**CONFIRMED — official contribution policy (tier 2).**

OpenAI's [contributing guide](https://github.com/openai/codex/blob/main/docs/contributing.md) says
external code contributions and pull requests are not accepted; it asks for detailed issue reports,
reproduction steps, sanitized logs, and root-cause analysis. It also says to add new information to
an existing issue instead of opening a duplicate. Therefore the publication artifact is a comment
for #21988. Nothing was published in this phase.

## Responsibility split

### OpenAI Codex upstream

- Default `thread/resume` serializes reconstructed `thread.turns` in one JSONL/stdout record.
- Image-generation results are inline and can make one response tens of megabytes.
- `excludeTurns` exists but is experimental and requires the advertised capability.
- Native compact can validly outlive a 120 s downstream deadline; its lifecycle is asynchronous.

### Orchestra downstream

- It selected default full-history resume even though it only consumed `thread.id`.
- The 16 MiB reader is bounded, but #284's discard-and-continue semantics could lose a required
  response while leaving correlation futures pending.
- Compact wrapped acknowledgement, completion, and lifecycle drain in one timeout, then formatted
  `str(TimeoutError())`, erasing exception class and phase.

Local mitigation is already on `main`:

- [`b11ba9be`](https://github.com/DrSeedon/orchestra/commit/b11ba9be1a7c54e936be00ebecbc69ca50fcff4f)
  (#307) — advertise experimental API for metadata-only resume, send `excludeTurns:true`, make
  oversized transport failure terminal, and name compact timeout phase;
- `db8708aa` (#319, local `main`; not yet present on `origin/main` at measurement time) — finish
  bounded poisoned-transport cleanup and pending-message recovery on the current main line.

## Counter-evidence and rejected claims

- **Rejected:** the oversized record was `aggregated_output`, `model/list`, a notification, or
  compact response. Direct envelope replay identifies response `id=2` from `thread/resume`.
- **Rejected:** the 05:18 oversized record belonged to Comfy. Its exact precompact response is
  933,418 B and its connect completed.
- **Rejected:** Comfy compact terminal notification never arrived. It arrived at 05:21:19, after
  the local deadline.
- **Not established:** `codex_models_manager` timeout caused the oversized response or process
  exit. It is a separate known stderr family ([#23119](https://github.com/openai/codex/issues/23119));
  the no-auth replay reproduces the oversized resume without relying on it.
- **Not established:** all compact slowness is an image bug. The measured Comfy rollout lacked
  `image_generation_end` records and a later compact succeeded in 19 s.
- **Not a new upstream class:** [#39148](https://github.com/openai/codex/issues/39148) shows another
  API surface (`read_thread`) ignoring output suppression for `imageGeneration`; #21988 is the
  closer exact frame-size issue for app-server turns/resume.

## Affected surfaces, risks, and edge cases

- Protocol: initialize capability negotiation; stored-thread `thread/resume`; response correlation.
- Runtime: stdout reader, pending requests, process exit, reconnect, queued input, and status reset.
- Compact: acknowledgement vs completion notification vs terminal lifecycle; late terminal events.
- Compatibility: `excludeTurns` without experimental capability fails with `-32600`; history import
  intentionally supplies `history` and must not be silently converted to metadata-only resume.
- Active resume: official schema returns live status outside `thread.turns`; upstream tests prove a
  subsequent turn works, but this research did not start a provider turn by instruction.
- Privacy: never attach a private rollout or raw response to an upstream issue.

## Review and completeness gate

Model review was not run because the orchestrator explicitly prohibited model/provider calls for
the final phase. Mechanical checks cover every requested field: method/id/envelope, CLI version,
transport, byte counts, compact control, upstream duplicate triage, contribution policy, local
mitigation commits, and sanitization. All external URLs below were opened this session.

## Sources

1. OpenAI Codex app-server README — https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
2. V2 thread protocol schema — https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/thread.rs
3. Thread resume tests — https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/thread_resume.rs
4. Resume redaction source — https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_resume_redaction.rs
5. #21988, 27 MB frame / seven generated images — https://github.com/openai/codex/issues/21988
6. #39148, `read_thread` suppression failure — https://github.com/openai/codex/issues/39148
7. #34863, inline PNG compaction amplification — https://github.com/openai/codex/issues/34863
8. #39013, repeated compacted image snapshots — https://github.com/openai/codex/issues/39013
9. #33493, local compaction retains `input_image` — https://github.com/openai/codex/issues/33493
10. #30441, unrecoverable unbounded image history — https://github.com/openai/codex/issues/30441
11. #24388, remote compaction family — https://github.com/openai/codex/issues/24388
12. Contribution policy — https://github.com/openai/codex/blob/main/docs/contributing.md

## Open gap

The exact upstream response-size behavior for a *currently active provider turn* was not probed:
doing so would require a provider/model call, which this phase explicitly forbade. Official schema
and tests establish that live-resume status is returned independently of `thread.turns`.
