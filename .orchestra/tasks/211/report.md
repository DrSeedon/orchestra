# Phase 3 report — T1 only

## Outcome

T1 is implemented as tracked, testable artifacts. Nothing was installed or enabled on the VPS:
no systemd configuration, cgroup state, process signals, `MemoryHigh`, temporary watcher, or
running Orchestra process was changed. T2–T5 remain behind their explicit system gate.

The implementation differs from the Phase 2 sketch in one safety-critical detail found by the
first implementation review: it never freezes `orchestra.service` itself. The service cgroup's
freeze bit is shared and not reference-counted, so an external operator freeze could race a
marker and later be undone by the guard. Armed code instead creates an exclusive random child
cgroup, moves only the pidfd-bound candidate into it, freezes and verifies that child, rechecks
identity, signals through the pidfd, and cleans up only that child. A parent freeze remains set.

## Files

- `scripts/orchestra_process_guard.py` — policy parser, exact process reader/matcher,
  age/RSS decision, pidfd + private-cgroup freeze/recheck/signal/thaw protocol, structured
  allowlisted journal events, startup recovery, and default-inert daemon loop.
- `deploy/orchestra-process-guard.conf` — policy-only defaults: `ENABLED=false`,
  `DRY_RUN=true`, `RSS_ACTION=log`; numeric thresholds remain explicitly provisional.
- `deploy/orchestra-process-guard.service` — independent guard service with journal output,
  crash/stop thaw hook, self-restart, runtime marker directory, and no dependency on
  `orchestra.service` health.
- `deploy/manage-process-guard.sh` — tracked `install|disable|rollback`; atomic per-file
  replacement, SHA verification, unit verification, preserved prior files/metadata and service
  state, and full rollback. It was exercised only with `DESTDIR` and fake system commands.
- `tests/test_process_guard.py` — 41 parser, identity, race, error cleanup, unit, and reversible
  deployment tests.
- `docs/tasks/211/codex-review-impl.md` — two implementation-review rounds and final verdict.

No `app/`, pipeline, `CHANGELOG.md`, system file, or live database file was touched.

## Acceptance evidence

- Targeted: `uv run python -m pytest tests/test_process_guard.py -x -q` →
  `41 passed in 4.89s`.
- Python/shell syntax: `uv run python -m py_compile scripts/orchestra_process_guard.py` and
  `bash -n deploy/manage-process-guard.sh` → exit 0.
- Unit syntax: a path-substituted temporary copy passed `systemd-analyze verify`; its only output
  was the pre-existing unrelated warning
  `/etc/systemd/system/xray.service:7: Special user nobody configured, this is not safe!`.
- Full regression: `uv run python -m pytest -x -q > /tmp/pytest-211-final.log 2>&1` →
  `503 passed, 3 skipped`, then the unchanged baseline test
  `tests/test_codex_bin_resolution.py::test_missing_binary_gives_actionable_text_instead_of_exit_127`
  failed because it queried live session `perf` and received 404. `git diff main -- app/mcp_stdio.py
  tests/test_codex_bin_resolution.py` is empty; `uv.lock` stayed unchanged.

### Mutation checks

Each mutation was applied and restored in one guarded command; the post-restore marker was
checked before continuing.

- Remove exact cgroup identity clause → the fixture differing only in cgroup fails.
- Remove exact executable identity clause → the fixture differing only in executable fails.
- Remove exact NUL `argv0` identity clause → the ordinary-Claude fixture fails.
- Disable `finally` thaw → `test_error_after_freeze_always_thaws` fails with `[True]` instead of
  `[True, False]`.
- Bypass `ENABLED` or `DRY_RUN` → the kill-path reachability test fails; bypassing dry-run reaches
  the forbidden pidfd opener.
- Redirect private-child thaw to the parent cgroup → the external-parent-freeze test fails.
- Remove the pre-migration PID identity recheck → the reused innocent PID test observes a cgroup
  move and fails.

## Pre-mortem and checks

- A standalone `ugrep`, ordinary Claude CLI, uvicorn, or outside-cgroup PID is mistaken for the
  embedded applet → live `execve(argv0="ugrep")` versus same-named executable probe, explicit
  negative fixtures, and three independent identity mutations.
- PID reuse relocates an innocent service before the under-freeze recheck → identity is checked
  again after pidfd open and before migration; dedicated outside-cgroup reuse test + mutation.
- Signal or recheck fails after freeze and leaves an agent suspended → context-manager `finally`,
  signal-failure test, freeze-timeout test, recovery test, and thaw mutation.
- Operator freezes the whole Orchestra service during guard activity and guard later thaws it →
  guard writes only its exclusive child bit; race model keeps the parent frozen and a mutation
  proves the test rejects parent thaw.
- Config is installed and unexpectedly arms killing → shipped config requires both an explicit
  `ENABLED=true` and `DRY_RUN=false`; three default-state cases forbid even pidfd/freeze entry.
- Rollback loses a pre-existing config or its mode → isolated `DESTDIR` install/disable/rollback
  restores content and mode and archives deployment state.

## Review

Round 1 returned blocking on shared-cgroup freeze ownership. The code and tests were changed to
the private-child protocol above. Round 2 returned `APPROVED` and quoted the verified executable
line `self._move_pid(candidate.pid, child_dir)`.

Both reviews had Codex exit 0 and substantive output, but Orchestra's stale MCP process then ran
`codex_review_artifact.py` without its new required usage arguments and marked the background job
failed. The verbatim reviewer outputs were recovered into `codex-review-impl.md`; the platform
failure was reported through `report_bug`. No third review was run.

## T5 preparation — pending gate

Tracked `CLAUDE_ENV_FILE` artifacts and an `install|rollback` manager are ready but have not been
installed. Two controlled fresh Claude 2.1.197 probes used the same bounded command:

- without the hook: `grep/find` were functions and plain `grep … tests` recursively found the
  marker with exit 0;
- with `CLAUDE_ENV_FILE` pointing at the tracked hook: both were files at `/usr/bin`, plain GNU
  grep rejected the directory with exit 2, explicit `grep -r` found the marker with exit 0, and
  versions were GNU grep 3.11 / findutils 4.9.0.

`uv run python -m pytest tests/test_claude_env_hook.py -x -q` passes 6 tests. Mutations prove the
suite rejects a missing `find` unset, a modified-file rollback bypass, forced overwrite of a
concurrent destination, and force-overwrite of a retained claim collision.

Codex used all three executable-review rounds. Rounds 1–2 found and drove fixes for post-install
data loss and its TOCTOU race. Round 3 confirmed that race fixed, then found a retained-claim
collision; no-clobber claim creation plus a deterministic collision test now fix it. The ceiling
forbids a fourth round, so that last fix is self-verified but awaits an orchestrator decision.

An independent Opus review then found two blocking failure paths. The partial-install path was
reproduced before changing the manager: the second isolated `install` invocation exited 42;
rollback then exited 2 at `awk` because `installed.sha256` did not exist. The fixed manager records
expected hashes before the first atomic replacement and, after atomically claiming a destination,
accepts only the recorded installed payload or the exact saved predecessor. Rollback can therefore
restore both a completed replacement and an untouched destination after a mid-install failure.
The same review measured that a malformed `CLAUDE_ENV_FILE` makes Claude's generated `bash -c`
exit 2 before the requested command. Install now runs `bash -n` on the source before creating
deploy state; rollback validates a saved hook before claiming any live file. Claim archival also
uses no-clobber `mv -Tn` and fails loudly on a retained destination.

Three additional mutation runs each failed as required and restored the manager with an mtime
update plus an exact-line count: removing source validation made malformed-hook install succeed;
removing saved-hook validation made rollback restore malformed Bash; and removing pre-install
hash recording made the interrupted-install recovery test fail. The independent follow-up verdict
on these changes remains pending.

No system file, systemd manager state, Orchestra process, or agent connection was changed.

## Remaining gates

- T5: obtain the focused independent follow-up verdict, then install the drop-in and obtain a
  separately approved Orchestra restart window; install/rollback themselves never restart the
  service.
- T2: install observe-only and gather direct age/RSS distributions.
- T3: controlled armed acceptance and only then decide on `MemoryHigh` removal.
- T4: permanent OS notification/reporting path.

All remain untouched and require a new explicit user command.
