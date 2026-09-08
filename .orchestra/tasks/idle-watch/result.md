# Idle watch and dashboard message source

Implemented on branch codex/idle-watch; no service restart or VPS deployment.

- bg_create(type="idle", timeout_seconds=0) installs one reusable watch on the calling orchestrator. An idle root with no running descendants or other active background jobs receives a durable notification. Pending automatic reports block notification. Worker activity rearms it; its own wake/reply does not. Replacement, cancellation and restart use existing BG storage.
- Wake means inspect results and failed report delivery, not proof of success or worker inactivity. A stuck running worker does not satisfy the condition.
- Dashboard sends an explicit channel marker. Anonymous dashboard messages retain unknown authentication provenance but render as dashboard chat. Generic anonymous API messages remain visibly Unknown. Existing unmarked history is unchanged.
- Removed mandatory overnight 30-minute timer from the background-jobs prompt.

Validation uses temporary SQLite databases and mocked model delivery. No paid provider calls or production database writes. Imported module: /mnt/data/Projects/Python/orchestra-idle-watch/app/idle_watch.py.

Checks: 189 passed across test_idle_watch, test_send_provenance_without_auth, test_bg_jobs and test_mcp_stdio; then 8 idle tests passed including added parallel-check and expiry cases; Chromium dashboard-channel regression passed. Unique passing tests: 192. node --check app/static/js/chat.js and git diff --check passed. Live laptop/VPS behavior was not tested or changed; applying backend changes requires owner-initiated restart after merge.
