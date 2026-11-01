# V-1148 — parent findings and acceptance

Research outcome: Codex actually compacted in every checked Orchestra-requested operation. The recurring error is the caller's fixed deadline; a later successful remote outcome does not reach the already-completed session result/context-update path. This task changes no production code, timeout, protocol, authentication or live session. An implementation is not claimed.

## Live evidence and boundaries

Read-only evidence covers the VPS from 30 October 00:00 UTC through 31 October 03:54:15 UTC: complete matching status/error/system DB query and accessible service journal, plus four exact native rollout files. Sensitive source records and identifiers remain private under V-1148. The bounded join uses operation diagnostic timestamps, elapsed time and matching persisted compacted records; duplicate logger presentations are removed before counting.

| Observed explicit Orchestra compact calls | Count |
|---|--:|
| Total | 11 |
| Caller success within deadline | 2 |
| Caller timeout, subsequently matching completed remote operation | 9 |
| Persisted native compacted record and lower subsequent context-token count | 11 |

The configured caller deadline is 120 seconds. Observed remote terminal elapsed times in this finite set range from 103.179 to 226.683 seconds; this is not an upper runtime guarantee. All nine timeout operations have late=true, compacted=true and completed terminal evidence. One records a retryable stream-disconnection error before eventual completion. The other observations do not establish a provider error. This does not retroactively attribute the older historical incidents in V-1076.

The separate native automatic compaction inside an ordinary user turn bypasses this explicit-call deadline. Eight such start/completed pairs were present in the checked DB records and continued through ordinary turns. Their existence does not validate the explicit-call UI. No manual compact POST was present in the checked journal; the user's precise button/session/host episode was not independently reproduced. Laptop logs and historical browser rendering were not examined. No real compact or provider request was made for research.

Current source corroborates the distinction. CodexBackend retains the timed-out operation until late terminal reconciliation and logs separate caller/remote outcomes. AgentSession updates/persists context and logs normal success only after the awaited result returns successfully. The late reducer does not re-enter that coroutine. The frontend's compactAgent fetches context on successful response and displays an error indicator for a returned error. Consequently late success need not immediately correct the visible result or cached context. The exact duration of an actual stale browser display was not measured.

Official documentation was searched and fetched: https://learn.chatgpt.com/docs/app-server#trigger-thread-compaction . It defines an immediate empty ACK followed by turn/item lifecycle notifications. Orchestra's fixed deadline is its own client behavior, not a documented provider completion guarantee.

## Independent verification

The complete worker report, full task probe/validator, commands and evidence were read. All nine supplied source/test SHA-256 values match the host worktree. No app or product test was changed. The worker honestly distinguishes its blocked normal collection from seven AST-only scenarios with injected timestamps; those scenarios are not a real timing measurement or app integration claim.

On the complete host worktree, frozen uv normal fixtures ran both committed modules tests/test_codex_compact_state.py and tests/test_backend_codex.py: 212 passed in 7.08 seconds. The earlier independent main-checkout compact-state run passed 103 cases. The parent independently ran all seven task probe scenarios; they passed. The instruction contract passed. Actual imported app path: /home/kesha/orchestra/worktrees/home-kesha-orchestra/research-codex-compact/app/__init__.py. Verbatim host output stays private. No full suite, live compaction, real HTTP/UI exercise or provider performance benchmark is claimed.

Late usage can also update shared backend last-call cache while a new user turn exists, and explicitly tagged usage after retirement is ignored. These are bounded synthetic/source findings, not demonstrated incorrect live accounting. They merit targeted follow-up rather than a claim that the current sample lost money or data. Existing ownership, failure and unknown-outcome protections must be preserved by any eventual fix.

Publication: five report/log files had runtime identity/path literals normalized, with original bytes and before/after hashes preserved privately. Synthetic numeric records, source hashes and probe code were unchanged. Two tiny generated task-local catalog/lock files are also present in the research bundle; the catalog contains only version 1 and an empty projects list, no deployment inventory. All published artifacts require the normal form/literal/forbidden-string scan before merge and push. No model review was run: owner freeze remains in force.
