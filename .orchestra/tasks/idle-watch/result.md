# Idle watch and dashboard message source

Implemented on branch codex/idle-watch. Initial implementation checks are below; subsequent merge and local activation are recorded at the end.

- bg_create(type="idle", timeout_seconds=0) installs one reusable watch on the calling orchestrator. An idle root with no running descendants or other active background jobs receives a durable notification. Pending automatic reports block notification. Worker activity rearms it; its own wake/reply does not. Replacement, cancellation and restart use existing BG storage.
- Wake means inspect results and failed report delivery, not proof of success or worker inactivity. A stuck running worker does not satisfy the condition.
- Dashboard sends an explicit channel marker. Anonymous dashboard messages retain unknown authentication provenance but render as dashboard chat. Generic anonymous API messages remain visibly Unknown. Existing unmarked history is unchanged.
- Removed mandatory overnight 30-minute timer from the background-jobs prompt.

Validation uses temporary SQLite databases and mocked model delivery. No paid provider calls or production database writes. Imported module: /mnt/data/Projects/Python/orchestra-idle-watch/app/idle_watch.py.

Checks: 189 passed across test_idle_watch, test_send_provenance_without_auth, test_bg_jobs and test_mcp_stdio; then 8 idle tests passed including added parallel-check and expiry cases; Chromium dashboard-channel regression passed. Unique passing tests: 192. node --check app/static/js/chat.js and git diff --check passed. Live laptop/VPS behavior was not tested or changed; applying backend changes requires owner-initiated restart after merge.


## Merge and local recovery — 2026-09-08

- Implementation commit: `5f7e72c5`. Merged with current origin/main and pushed as `4311a566`; no conflicts. After integration, 153 tests passed (idle watch, sender provenance, MCP stdio and MCP proof). Imported module: `/mnt/data/Projects/Python/orchestra/app/idle_watch.py`.
- Later local outage was caused by a separate storage cutover: code required SQLite schema 1 while the configured database still had user_version 0. Startup failed repeatedly from 19:05 local time. The idle-watch change did not introduce this schema requirement.
- Owner explicitly authorized recovery on the laptop only. Stopped local orchestra.service and orchestra.socket, ran the existing migration against fresh local sources, and kept the original database and canonical repository intact.
- Recovery directory: `data/storage-recovery-local-20260908/`. It contains the source SQLite backup, migrated database, private task repository, migration report, previous environment configuration and activation receipt. This directory is private and Git-ignored; do not publish its raw contents.
- At migration: 896 local tasks, 668 sessions, 302357 log rows, 43 background jobs and 2002 message deliveries preserved. Foreign-key violations: zero. Session statuses matched: 592 archived, 76 idle.
- Set local ORCHESTRA_DB_PATH and ORCHESTRA_TASK_REPOSITORY to the checked migrated pair and started the local socket/service. Dashboard, /api/sessions and /api/stats returned HTTP 200; 76 visible sessions; systemd active/running, NRestarts=0. Previous restart receipt had cut_names=[]; no cut worker needed resuming.
- Remaining startup warnings: project layout migration for VPN-Service, parsing-hub, stargate-tactics and university; Telegram TOPIC_ID_INVALID. Not repaired in this task. These did not block the successful HTTP checks.
- This recovery did not touch VPS. Subsequent cross-node task-store activation/sync was documented separately in `../storage-simplification/deployment.md`; the 896-task count above describes this local recovery point, not the later combined store.
