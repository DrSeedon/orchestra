The capacity classification is generally consistent, but the preserved-timer response can become stale during the provider refresh await. That can produce a false-success recovery message after the only timer has already terminated.

Review comment:

- [P2] Revalidate the timer before reporting it as preserved — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:453-455
  When a provider refresh fails while the previous timer reaches `trigger_at`, `old_job` was captured before the awaited refresh, so `run_wake_job()` can finish that row as triggered during the wait. This branch still reports `preserved=true`, and the frontend renders that top-level decision instead of the final `state`; if the timer also stopped on the refresh failure, the user is told recovery remains scheduled although no active timer exists. Recheck that the same job is still active before classifying it as preserved.

## Round (2026-07-28T13:27:22Z)

Sure, the refresh succeeded—it merely returned no data for the requested provider. 🙃

### Re-review status

- Prior P2 — **FIXED**. The exact captured job ID is re-read after refresh and only then classified as preserved, using the revalidated config.
- Scheduling lock, click-result snapshot, readiness helper, and runner delivery checks show no additional gaps.

### New finding

[P2] **NEW BUG — Treat a missing provider payload as refresh failure**

[app/limit_wake.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-idle-inbox/app/limit_wake.py:397) | Confidence: 0.94

When refresh returns a dictionary without the requested provider—as the new wrong-provider test permits—`provider_usage` is `None` but the envelope is marked `fresh=True`. Readiness becomes unavailable, yet the provider is excluded from `failed_providers`, so its existing valid timer is cancelled. A missing requested payload should enter the same preservation path as an exception.

### Verdict

**CHANGES REQUESTED**

Tests were not rerun per instruction; author reports 41 passed. A snapshot for the wrong provider is still an empty envelope wearing a fresh timestamp. 📭

## Round (2026-07-28T13:29:20Z)

Miraculously, missing provider data is now treated as missing provider data. 🪄

### Re-review status

- Round-1 P2 — **FIXED**. Preserved timers are revalidated by exact job ID after refresh.
- Round-2 P2 — **FIXED**. A missing requested-provider payload now enters the failed-refresh path, preserving an eligible existing timer.
- Locking, click snapshot, readiness, and delivery paths show no remaining correctness or deadlock issues.

### New findings

None.

### Verdict

**APPROVED**

Tests were not rerun per instruction; author reports 42 passed. The envelope now needs to contain the letter before being declared delivered. 📬
