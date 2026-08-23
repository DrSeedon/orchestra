# research-quota-map-sol

- `PerformanceResourceTiming.requestStart == 0` plus an absent **completion** log does not prove a request never reached the server. For pre-wire claims, add a marker-bearing ingress log/control; completion and arrival are different events.
- `Promise.allSettled()` does not enter `catch` for rejected children. When auditing stale-data fallback, trace every result branch and verify that failure neither clears nor re-saves the last good value.
- `codex_review` can falsely report `review artifact is blind` when `_blind_review_error` scans raw JSONL containing injected `bwrap:` instructions. Before any retry, inspect the artifact and final JSONL `agent_message`; a complete `## Verdict` plus exact evidence quote is a valid reviewer response.
- Turning a read endpoint cache-only is incomplete unless the cache read is sequenced after its refresh owner. Parallel refresh+read can return `fresh=false/unknown`; verify both API state and the final UI summary so `blocked=false` is not misread as “working”.
