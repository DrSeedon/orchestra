# Wave 4 — deployed and verified on the production dashboard

Code: `d306ed4191a455e80cc3b179380df672131bc087` (includes `e520add50`).
Test import: `/home/kesha/orchestra-worktrees/gemini-quotas-and-hub62-20261118/app`.
Production import: `/home/kesha/orchestra/app`.

- Hub Sol/Astra route to exact Codex 6.2 IDs. Old model IDs are retained for historical reads and rejected by new selection and dispatch guards. The two idle historical Hub Sol workers, backup-space and seedon-sales-sol, retain their original identity and history.
- Checked 27 distinct VPS project instruction files, updated six actual files and preserved existing links. Multicast CTO instructions follow the current Opus policy.
- All five Antigravity windows persisted as named windows in existing `usage_snapshots.provider_usage`. No new SQL columns were needed. Fresh observations are restored on startup.
- Owner dashboard refresh shares a profile-safe cache. TTL 900 seconds, forced cooldown 60 seconds, failure backoff 900 seconds. A completed ACP turn schedules a refresh attempt. If ACP still owns the writer, the attempt defers to the next eligible request. In-band ACP quota telemetry can still update the cache without another process.
- First live restart reached PID 2990190 without a cut. Print mode rejected ACP-only flags and emitted no JSON. Verified CLI help, removed those flags, and added a guarded print-mode regression.
- Final restart reached PID 2991639 with `restart_cut_turns=0`. Telegram PID and foreign tracked files were preserved. Both services active. Provider disable configuration unchanged.
- Live sample at 2026-11-18 12:16:46.690762 UTC contained Gemini 5h/7d, Argon 7d and Claude/3P 5h/7d. Verified the DB row, five graph series, three weekly thresholds and live catalog. Native generation was outside this quota check.
- Test evidence: 488 backend tests passed, two dependency deprecations. Eight headless renderer tests passed. After targeted changes, 57 backend and one renderer tests passed again. The final CLI argument correction passed all three focused quota tests. Instruction, syntax and diff checks passed.
- Live dashboard captures on the VPS and hub in `/tmp/orchestra_gemini_quotas_ui_usage.png` and `/tmp/orchestra_gemini_quotas_ui_gates.png`. Both use live data. Capture framing hides unrelated workspace content and expands the scroll area for the graph. Current windows have a fresh sample. Curves accumulate as subsequent observations arrive.
