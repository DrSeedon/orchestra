# V-1150 — parent acceptance

Accepted worker HEAD ae482e430e7cbad158e29e05f8a83aadc2268ae0 after the complete final report, both production/test revisions and actual evidence were read. Canonical merge operation 278aa1e5-3a2c-4392-94e7-d9033d158d9c succeeded, landing 968d23ac803aebad57c0b2dff63c73782acaa696. A fresh worker_wip then showed no uncommitted files or unmerged commits, and the completed hub worker was archived in the same handling. Ignored raw worker evidence was copied into private V-1150 storage before archive.

The accepted implementation increases the explicit native compact budget to a bounded 600 seconds and manual HTTP callers to 660 seconds. A matching late successful terminal publishes fresh session context/status through the existing stream while preserving the original caller result. Per-operation usage cannot contaminate a newer user turn. Immediate result/handoff/persist boundaries reject an obsolete session snapshot. Queue retry, manual stop, unknown usage and genuine terminal/transport failures retain their distinct semantics. No new public endpoint, provider fallback or live compaction was introduced.

## Actual host evidence

| Check | Actual result |
|---|---:|
| Frozen full host runner | 7057 passed, 51 skipped |
| Focused backend/compact regressions | 261 passed |
| Parent process-local defect reversions | 5 intended failures |
| Publication files screened | 18, no findings |

Full command: `uv run --frozen python scripts/run_tests.py`, 449.56 seconds. It ran in the worker's full host worktree outside the service cgroup through the existing localhost user route with nice 15 / choom 1000. The service was already near its memory.high threshold; its limits were not changed. Skips remain skips, not claims that their environmental prerequisites were verified.

The actual imported app path was /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-codex-compact-delivery/app/__init__.py. The instruction contract passed. Generated historical PNG outputs were privately preserved and their original bytes restored; final worktree status and all source/test manifest hashes matched the accepted HEAD. Model review remains frozen by owner decision; these were direct parent checks.

An independent Chromium probe executed production compactAgent, api, connectSSE, context fetching and formatting against local DOM/fetch/EventSource adapters. Its real AbortSignal remained live beyond the old five-second mutation deadline, exactly one POST was sent, context refreshed after a separate late-success stream event, unknown usage did not display old digits, and stale scope events did not overwrite another scope's cache. This is real browser execution with controlled boundaries, not a real provider or deployed end-to-end compact measurement.

Five independent process-local mutations against committed regressions each produced the intended failure: restoring the old deadline terminated the still-running operation; removing the late observer left old context; injecting old compact usage changed a newer turn's usage; removing the queue retry left the retained request undelivered; disabling immediate freshness replaced context after the supported clear lifecycle. No production file was edited for these mutations. The first parent mutation launcher failed before importing tests because its private script directory omitted the worktree from sys.path; that launcher was corrected, only the mutation stage reran, and the already-green full suite was not repeated. Actual stdout/stderr and all private originals remain under V-1150.

## Delivery boundary

No service restart or real provider compact was performed. The frontend asset returned HTTP 200 and its full bytes matched main at the post-merge check (private runtime-after-merge.json); existing browser tabs were not forcibly reloaded. At the post-merge check the live service was still PID 2311175, so Python/backend/MCP changes were not yet active. Activation must occur only through the existing owner-authorized idle watcher; its completion event requires runtime and cut-turn verification. No success claim for a real compact after deployment is made here. Guarded origin publication, exact remote-ref comparison and actual CI are separate delivery checks.
