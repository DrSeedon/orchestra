# V-1279 — topic-create timeout CI repair

Assigned source: 2305b9fe (abbreviated HEAD supplied by orchestrator), CI run 41820028765.
Private broker copy has no .git or remote: full source HEAD and upstream CI logs cannot
be independently recovered here. Result branch: task-V-1279/fix-topic-timeout-ci.

Initial finding: the failing test nests a 10 ms operation timeout inside a 50 ms
end-to-end wait. Production catches TimeoutError, persists topic_create_uncertain,
and shields the owned create task from caller cancellation. Investigate scheduler /
filesystem delay before changing production behavior. No frozen marker found in this
test file; supplied no-blind-retry assertions must be preserved.

Baseline: required broker uv, original targeted test: 1 passed (4.53 s).
A one-shot diagnostic pytest plugin adds 60 ms to synthetic config persistence after
writing the guard. It leaves production and the original test untouched; this models
a slow disk or event-loop stall exceeding the original 50 ms whole-call watchdog.

Confirmed synthetic failure (repro-original.log): original test fails at its outer
0.05 s wait_for with TimeoutError while logging `TG topic create uncertain for orch;
automatic retry disabled`, matching the reported CI symptom. The guard was written
before the injected 60 ms delay. This demonstrates a watchdog/scheduling race; it is
not evidence that production retried a possibly successful Telegram create. Exact
CI host latency remains unmeasured because its logs/environment are not supplied.

Fix scope: only the existing timeout test changes. Its outer hang watchdog becomes
5 s (the neighboring event-based tests use the same allowance), while the operation
deadline remains 10 ms and the never-completing fake must observe cancellation.
Original no-retry assertions remain; additional assertions cover no phantom topic,
a durable uncertainty marker, and no retry after load_config simulates a restart.
app/tg_bridge.py and lock/dependency files remain unchanged.

Post-fix checks so far:
- Lifecycle class with the same 60 ms delayed persistence plugin: 11 passed, 3.02 s.
- Both Telegram bridge test modules, offline: 225 passed, 5 skipped, 5.08 s.

Negative control 1 (mutation-retry.log): deliberately bypassing the primary uncertainty
guard makes the repaired test fail at the original call-count assertion (2 != 1).
This expected failure confirms the longer watchdog does not hide blind retries.
The 5 suite skips use mp4_file: ffmpeg/ffprobe are not installed (unrelated video checks).

Negative control 2 (mutation-forget-on-load.log): deliberately dropping the persisted
uncertainty guard during load_config makes the added restart assertion fail (2 != 1).
Both expected mutation failures were subprocess-local monkeypatches; source code was
never mutated. Logs for the original repro and both negative controls are preserved.

Final inspection: reconstructed the original test file from the small patch and
verified its SHA-256 against the pre-edit hash. Verified app/tg_bridge.py,
pyproject.toml and uv.lock are byte-for-byte unchanged. Imported paths and the exact
runner interpreter are in validation-metadata.txt. Full 40-character source HEAD
remains unavailable: the broker copy intentionally has no git metadata.

Removed only generated test sandboxes and proof-plugin bytecode after inspection;
all failure/success logs, proof plugins, patch and source hashes remain.

Public-merge follow-up: normalized identifying checkout prefixes in 5 artifacts
(9 occurrences). Preserved actual failures and reproduction method without tracked
raw-path backups. Verified all 4 source hashes unchanged; exact new HEAD unavailable
until platform import/commit. See report.md and sanitization-manifest.json.
