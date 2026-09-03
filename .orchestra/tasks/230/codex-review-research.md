## Summary

The research proves the core OS primitive: both CLI processes can survive a supervisor restart, and the replacement process can read their inherited stdout pipes. It does not yet prove the requested end-to-end behavior in Orchestra.

The central gap is reconstituting the active turn’s Python-side protocol state. `_load_from_db()` restores durable session metadata, not pending JSON-RPC requests, lifecycle futures, event-consumer state, permission callbacks, accumulated output, or exactly-once persistence. Consequently, “no separate session processes required” remains plausible, but “≈550 lines” and “no new serialization required” are not supported.

## Findings

blocking: F8 / lines 203–228 — `_load_from_db()` does not restore a mid-turn session. It constructs a new `AgentSession`, calls `session.start()`, and current `auto_resume_all()` explicitly resets `running` sessions to `idle`. Meanwhile the backends retain live-only state: Codex has pending request futures, reader tasks, active turn ID and compact lifecycle state; Claude has the SDK client/receiver plus conversion maps and pending error state. These are not in the DB. A new reader can parse bytes, but Orchestra still must reconstruct which turn owns them, persist and publish their events, resolve completion, update usage/status, deliver `on_idle`, and avoid starting a competing turn → replace “new serialization is not required” with an explicit mid-turn state inventory and recovery contract, then estimate from a working end-to-end prototype.

blocking: F1 / lines 47–87 — Claude demonstrates a surviving CLI and a post-restart terminal result, but not adoption by the real SDK/Orchestra event pipeline. The probe reads raw stream-json using `bypassPermissions`; production uses `permission_mode="default"` and an in-process `can_use_tool` callback. A turn requesting permission or another SDK control exchange after gen1 dies may stall or behave differently. Codex is weaker still: the probe never received `turn/completed` or the promised final `FINISHED`; `m4-done` proves only that the shell subprocess completed. The document’s own open question acknowledges this → label F1 “partial”: raw transport continuity confirmed; production Claude adoption and Codex turn completion unconfirmed. Test through `ClaudeSDKClient(custom transport)` and the real Codex backend until Orchestra persists the terminal event and runs the idle callback.

blocking: F3 / lines 115–127 — “zero bytes lost” and “maximum 0.12 s” exceed the evidence. The 208-byte single-writer harness validates ordered pipe delivery, but graceful leftover persistence is unavailable under SIGKILL, where F2 already measured 378 consumed-but-uncommitted records. There is also a distinct crash window after a frame is read and before its DB side effects complete: replaying it can duplicate logs, usage, notifications, or tool lifecycle records, while not replaying it loses them. This is an exactly-once side-effect problem, not merely a partial-line problem → specify framing plus durable cursor/idempotency semantics and test graceful restart and SIGKILL at every read/persist boundary. Restrict 0.12 s to this harness; it is not an application bound.

suggestion: F4 / lines 129–151 — the arithmetic does not establish 58 seconds of API unavailability. The journal shows 55 seconds between “Stopping” and “Stopped,” but without continuous probes it does not show when the old listener stopped accepting requests. The toy A/B proves that socket activation removed four connection refusals in two short restarts; it does not prove socket activation is the only valid solution, nor that its backlog and caller timeouts survive Orchestra’s real startup → conclude that uninterrupted/retriable tool access is required. Present socket activation as the leading measured mechanism, pending a real-start probe; alternatives such as graceful listener handoff or retrying MCP calls have not been falsified.

blocking: F9 / lines 230–242 — parentage proves that MCP shims survive with the CLI, but not that tools and prompts swap on the next turn. The design still needs an atomic turn-boundary protocol: observe definitive completion, prevent queued/injected input from starting on the old CLI, drain its output, terminate/reap the old CLI and MCP children, resume the same conversation on a fresh CLI, and only then release queued input. Codex did not emit definitive completion in F1, so the boundary required by the user is currently unobserved in one of the two live runtimes → downgrade F9 and make this state machine a required Phase 2 prototype.

suggestion: F2 / lines 95–108 — the measured claim is valid for the tested unit configuration, but “stop means the child dies” generalizes from a continuously writing child. With `KillMode=process`, releasing the FD store removes systemd’s duplicate, but an idle CLI may not attempt a write and therefore may remain in the cgroup after `stop`; MCP descendants may also keep it alive. This does not preserve service, but it changes cleanup and future-start safety → state precisely that `stop` discards the stored descriptors and provides no continuity guarantee; separately test and define termination of idle descendants.

blocking: Counter-evidence / missing failure mode — the document omits post-restart control-channel requests from an already-running Claude turn. The production SDK supplies permission decisions through Python callbacks, while the successful Claude probe bypassed permissions. If the surviving CLI emits a control request after gen1 exits and before a fully initialized replacement SDK client owns the transport, the turn can hang or take an unintended permission path. Socket activation does not help because this traffic is on CLI stdio, not HTTP → add this risk and test a turn deliberately requiring a post-restart permission callback. This is distinct from the already-mentioned two-reader, FD-capacity, and orphan risks.

suggestion: overall answer — the task asks for “restart must never interrupt any agent turn.” The evidence establishes survival for one shell-heavy turn per runtime under graceful restart and one synthetic SIGKILL case, while explicitly leaving network-waiting turns, real Claude transport adoption, Codex completion, multi-session load, backlog limits, and two runtimes untested. “Achievable without (D)” is a reasonable research hypothesis, but “must never” needs a defined support envelope and failure semantics for crash, stop, reboot, FD-store rejection, startup failure, and update incompatibility → frame the conclusion as a promising architecture requiring a Phase 2 end-to-end proof, not as confirmed satisfaction of the user’s invariant.

## Verdict

Request changes.

The document identifies a credible alternative to the large process rewrite and convincingly validates FD survival. It does not yet validate Orchestra-level turn continuity, exactly-once event handling, or next-turn swapping. The strongest unsupported assertion is that durable DB reconstruction eliminates the need to preserve mid-turn Python state; current code demonstrates the opposite.

## Round (2026-08-12T13:17:17Z)

## Round 2

### Re-review status

- F8 mid-turn Python state — STILL BROKEN. The main correction is good, but line 277 still says: “`всё это и сегодня переживает рестарт через БД, новой сериализации не требуется`.” This directly contradicts lines 247–267 and preserves the original unsupported claim. Remove or narrow it to durable fields only.
- Missing permission/control channel — FIXED in substance, but F10’s certainty needs correction; see finding 1.
- F1 production-path evidence — FIXED.
- F9 next-turn swap protocol — FIXED.
- F3 loss/duplication semantics — FIXED. I concede the narrow point: with a non-replayable pipe, one consumed frame cannot inherently enter the persistence path twice. The transport’s crash semantics are at-most-once. Duplication would require an additional mechanism—such as mistakenly restoring already-consumed buffered bytes—and is not implied by the measured design.
- F4 HTTP availability — FIXED.
- F2 stop semantics — FIXED.
- Overall framing — STILL BROKEN because the headline conclusion remains stronger than the unresolved blockers permit; see finding 3.

## Findings

suggestion: F10 — `pending_control_responses` is the wrong state to cite for incoming permission requests. It tracks SDK→CLI requests created by `_send_control_request`; CLI→SDK permission requests are tracked in `_inflight_requests` and handled by `_handle_control_request`. I found no SDK-side timeout around that incoming handler. The quoted 60-second timeout applies in the opposite direction: “`timeout: Timeout in seconds to wait for response (default 60s)`.” Therefore “the CLI waits” is plausible, but not confirmed: any timeout would be implemented by the CLI/protocol peer, which the inspected SDK does not establish → cite `_inflight_requests` for permissions and label wait-versus-fail UNKNOWN pending a real probe.

blocking: F8 / inventory — the deleted conclusion survives verbatim at line 277: “`всё это и сегодня переживает рестарт через БД, новой сериализации не требуется`.” It is also factually false for the 63 runtime-assigned attributes as a group; the same section lists several that exist only in memory → replace this bullet with an explicit count of fields actually restored by `_load_from_db`, without extrapolating from the dataclass inventory.

suggestion: Phase verdict / H2 — “Возможно ли это … да” and “вариант (D) … НЕ нужен” remain premature while F10 is described as capable of “обрушить весь замысел,” the Claude SDK adopt path has never run, and no production event pipeline has completed an adopted turn. Raw FD continuity refutes “separate processes are physically the only way to preserve pipes,” but it does not yet refute “a persistent session-side process is needed to preserve callbacks and mid-turn state” → state that the FD-store design is a viable candidate that may avoid (D), pending Phase 2 falsifiers.

blocking: missing failure mode — an MCP tool request already accepted by the old HTTP server is not protected by socket activation. Socket activation preserves new connections queued on the listening socket; it does not migrate an established connection or the old Python handler. If restart kills that handler after its tool-side effect commits but before the HTTP response reaches the surviving MCP shim, the agent observes a failed/ambiguous tool call. Retrying could duplicate a non-idempotent operation; not retrying can interrupt the turn despite the CLI and its pipe surviving → add in-flight HTTP draining or an idempotency/reconciliation contract to the required design and Phase 2 tests.

suggestion: F3 — the at-most-once conclusion is correct for pipe frames, but “duplication impossible” should be scoped to that layer. The newly identified HTTP ambiguity can duplicate the underlying tool operation if a retry policy is added, and a flawed graceful-buffer handoff could also replay bytes. Say “the pipe itself has no inherent replay path,” not an unqualified “дублирование невозможно.”

## Verdict

Not approved yet: two blocking issues remain—the contradictory F8 claim and unhandled in-flight MCP HTTP requests. The Round 1 concerns were otherwise addressed well, and F3’s transport-level at-most-once argument is correct.
