# V-1135 — durable progress for long background jobs

## Retained implementation

The existing run job accepts optional progress configuration (output or command,
interval at least 5 seconds). MCP exposes progress_command, progress_from_output,
progress_interval_seconds. Other job types reject progress; omission preserves
the old execution path. The existing run/adoption watcher owns the sampler.

Samples contain optional status, label, completed, total, unit, percent, rate,
eta_seconds. The platform adds observation time and stores a bounded record in
config._progress, without a schema change. Caller-supplied records are stripped.
Active-row-only writes cannot revive a cancelled job. History is capped at 12
points and raw text at 500 characters. Unknown totals do not create percentages;
percent-only input has a 100-percent scale. Estimated ETA needs three observations
and positive speed. Rewinds reset history; non-finite/negative/bool numbers are
refused. Source text is escaped in the existing JOBS card.

Output reads at most 256 KiB / 200 lines. Command sampling uses the run's existing
pidfd, host/cwd and agent-cgroup environment, 10-second limit and 64-KiB cap.
Cancellation/shutdown clean up the sampler; the run keeps its existing
survive-restart/adoption behavior. Sampling never messages a model. Existing
terminal delivery still wakes the recipient once. The card refreshes through
the existing jobs-tab poll, shortened from 10 to 5 seconds. No new SSE channel,
service, daemon, downloader or dependency.

## Acceptance follow-up corrections

The handoff and recovered durable thread refer to a previous message containing
three concrete corrections, but that message is absent. A clarification request
was sent early; no text arrived. These bounded fixes follow current-code
reproductions. Parent must reconcile them with the omitted list; this report
does not claim that unseen list was completed.

1. Complete successful command observations: read to EOF within the byte cap,
   wait for exit inside the same timeout, reject nonzero exits and oversized
   output, and always use existing process-group cleanup. Fragmented JSON is
   collected completely. Closing stdout cannot evade the execution timeout.
2. Actual output observations survive adoption: persist a bounded source cursor
   (file identity, line position, digest). Re-reading the same line, including
   after a new manager adopts the run or unrelated log output arrives, does not
   refresh its observation time or add history points. A newly appended identical
   sample does count as a new observation.
3. Honest errors and freshness in the card: use sample observation / last
   successful time rather than the latest failed attempt. Keep the last
   successful percentage but hide speed/ETA on error. Show failure even before
   the first successful sample.

## Checks actually run

All Python checks used provisioned uv 0.11.28, the default .venv and
uv run --frozen python -m pytest. The absolute imported app path was verified in
tool output as this copy's app/__init__.py. It is omitted from this tracked report
to avoid publishing the hub account/path.

- Five new regressions failed before corrections (acceptance-before.txt):
  duplicate output; incomplete/nonzero/oversized command output; stdout-close
  timeout; stale observation after errors; first-sample error.
- Targeted Python/Node suite: 32 passed, comprising 23 backend/MCP/adoption and
  9 card tests (targeted.txt).
- Combined targeted and neighboring suite: 284 passed, 1 skipped, 4 subtests
  passed, 34.99 seconds (regression.txt). Files: test_bg_progress_v1135,
  test_jobs_progress_view_v1135, test_jobs_view, test_bg_jobs, test_mcp_stdio,
  test_bg_agent_isolation, test_restart_cut_recovery_1057, test_pidfd_leaks,
  test_work_review_jobs.
- Real Chromium DOM: 2 passed, widths 390 and 1280, 4.36 seconds
  (browser-available.txt). Uses shipped renderer/CSS and synthetic
  bg_progress.ingest records. Covers waiting, first error, running percent/
  speed/ETA, stale/error retaining the last good value, pause, reset, unknown
  total, escaped label/raw detail, completed timeline event, terminal controls/
  hidden live estimates, no horizontal overflow and no JS errors. Requests use
  an intercepted test origin; other network requests are blocked.
- Browser/live-probe inventory: 2 passed, 53 deselected, 12.68 seconds
  (browser-inventory.txt). The two browser cases are registered explicitly in
  test_merge_test_gate.py.
- Instruction contract: failed because this source copy has no CLAUDE.md symlink
  (instruction-contract.txt). Instruction files were not edited.
- Shape-based secret scan using app.secret_mask.mask_secrets: no matches in
  changed source/tests or task artifacts; hub paths were removed from saved logs.

The previous turn's process-tree failure did not reproduce in the current
284-test run. Its previous attribution to the sandbox was a hypothesis, not a
proven baseline comparison; this copy has no Git history.

## Browser prerequisite and reproduction

The default locked Playwright run could not launch because expected Chromium
headless-shell build 1223 is absent (browser.txt). No install was attempted.
Available local build 1248 was passed explicitly, using the same locked Python
runner and unchanged dependency files. This checks Chromium DOM behavior but
does not claim execution on the missing default browser build.

The optional test-only browser_override.py plugin registers
--jobs-browser-executable. To repeat, add this task directory to PYTHONPATH and
run the browser test using uv run --frozen python -m pytest with
-p browser_override --jobs-browser-executable /path/to/installed/chromium.
Normal test runs still use their default browser.

Early browser harness failures were corrected: fixtures now send the API's
JSON-string config, use an intercepted origin for localStorage, and check the
existing timeline on a completed dated event. No frozen tests were changed.

## Remaining boundaries

- Full host suite, service restart, live SSH/cgroups, actual dashboard polling
  integration and real quota/hub routing were not run. Existing isolated tests
  cover environments, ownership and adoption, not a live deployment.
- Sampler commands retain the run's trust/permissions. They are bounded commands,
  not a separately sandboxed read-only interpreter.
- Browser records are synthetic; no full dashboard/API session, screenshots,
  private user data, real models, torrents or downloads.
- No auth/scope/ownership, quota exemption, hub routing, mailbox or V-1130 edits.
  The original V1134 shared-file note still holds: app.js only changed its jobs
  poll interval during initial implementation; this follow-up does not edit it.
- No provider fallback, paid call, service work, push or deployment.
- This copy has no .git. No commit was attempted. Broker must import and commit
  the changed files on task-V-1135/feat-bg-progress-monitor when this turn ends.

Parent publication handling: the original before-correction log is preserved locally under `.orchestra/private/V-1135/original-acceptance-before.txt`; the tracked copy replaces a forbidden private host identifier with a placeholder. This changes evidence presentation only. All three concrete acceptance corrections are reconciled against the parent assignment and implemented.

## Parent host acceptance and final boundary

All three original parent acceptance corrections were reconciled and implemented: complete bounded successful command output, durable output observation identity, and UI freshness/error estimates. Final formatter change preserves dynamic UI locale, missing/nonfunction-helper fallback and numeric precision; the existing locale-contract test remains intact. Worker evidence: 36 targeted tests, two real Chromium width cases and the direct locale/fallback probe. The earlier source-copy symlink/browser limitations do not describe the full host.

Final integrated host HEAD was checked with accepted V-1134 included: required full suite 6888 passed, 54 skipped, six warnings; all 21 real Chromium queue/progress cases passed on the host default locked browser. Four skipped ownership tests need passwordless sudo. Instruction contract passed; imported app was `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-bg-progress-monitor/app/__init__.py`. No tests were weakened. Parent process-local old sampler restoration failed three committed regressions; old renderer restoration failed two committed regressions. All 24 changed files passed shape, known-literal and forbidden-string checks. Private original log evidence and host logs remain in `.orchestra/private/V-1135/`; generated historical screenshots were preserved before restoring tracked originals.

Merged source does not activate the loaded Python or existing MCP sessions. The authorized idle watcher owns service restart; none was initiated manually. Real torrent/download, live SSH/cgroup behavior, automatic sampler/MCP discovery in a live agent and full dashboard polling were not verified by this acceptance. The source/protocol supports these existing run-job paths, but synthetic local process/adoption and renderer tests are the measured coverage.
