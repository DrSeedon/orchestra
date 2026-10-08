# V-769 — bound CI dependency installation

## Findings from Actions

Both cancelled runs were GitHub Actions **attempt 1**; attempt 2 completed. The failure was in package downloads during `apt-get install`, not in `apt-get update`:

- Run [37679776268](https://github.com/DrSeedon/orchestra/actions/runs/37679776268), shard 1: `apt-get update` logged `Fetched 12.6 MB in 1s (9232 kB/s)` at line 355 of [the shard log](run-37679776268-attempt1-shard1.log). The install then planned 99 packages / 105 MB at line 406. Its last download entry before GitHub cancelled the 20-minute step was `Get:87 http://azure.archive.ubuntu.com/ubuntu noble-updates/main amd64 mesa-libgallium ... [10.8 MB]` at line 494; cancellation is line 495.
- Run 37679776268, shard 5: install also planned 99 packages / 105 MB (line 386 of [the shard log](run-37679776268-attempt1-shard5.log)) and finished only after 18m16s. The following, redundant `playwright install --with-deps chromium` launched another apt transaction: 21.5 MB of packages (line 1021), `fonts-freefont-ttf ... [5641 kB]` (line 1025), then GitHub cancelled the job at line 1026.
- Run [37743851490](https://github.com/DrSeedon/orchestra/actions/runs/37743851490), shard 2: update completed; install planned 99 packages / 105 MB at line 408 of [the shard log](run-37743851490-attempt1-shard2.log). Late entries include `mesa-libgallium ... [10.8 MB]` from `azure.archive.ubuntu.com` at line 496 and `pocketsphinx-en-us ... [27.4 MB]` from the same mirror at line 513; GitHub cancelled the step at line 514.

The logs show slow package retrieval from `azure.archive.ubuntu.com`; the update metadata was fetched promptly. They do not show apt reporting an error before GitHub cancelled the jobs. The retries on attempt 2 succeeded, which is consistent with a transient runner/mirror download problem.

## Change

The six `test` shards already run `-m "not live_probe and not browser"`. Removed their redundant `playwright install --with-deps chromium` step; the separate browser job still installs Chromium and runs the same browser tests. The six-shard matrix and pytest commands are unchanged.

The remaining ffmpeg setup now has an 8-minute step ceiling, two bounded attempts for update and install, APT transport retries/timeouts, and `--no-install-recommends`. After a failed first install attempt it runs `dpkg --configure -a` under a 60-second timeout before retrying; if recovery fails, installation stops rather than running apt against an unconfigured package state. It verifies that the required `ffprobe` binary is installed. The previous install requested 99 packages / 105 MB; avoiding optional recommendations reduces downloads while retaining ffmpeg/ffprobe.

## Verification and limit

The workflow YAML parsed, the install step passed `bash -n`, the matrix remained `[0, 1, 2, 3, 4, 5]`, and `git diff --check` passed. I scanned all three saved attempt logs (2,083 lines total) for common GitHub/AWS bearer-token patterns; there were no matches. No tests or shard assignments were changed. This branch cannot trigger the requested Actions acceptance run; the next main run will measure whether the bounded setup and reduced package set resolve the observed stalls.

## Follow-up after run 37747175830

The first commit removed Playwright installation from the six test shards because they filter `browser` tests. Run 37747175830 showed that several non-`browser`-marked tests still launch Chromium directly. Attempt 1 failed on shards 2, 3, 4 and 5 with the same missing `chromium_headless_shell-1223` executable. The complete failing set from the four shard logs is:

- Shard 2: `tests/test_connection_recovery.py::test_recovery_isolates_failure_and_can_run_again[sync]`, `[async]`, and `[chat_reset]`; `tests/test_connection_recovery.py::test_runtime_status_flags_change_the_rendered_detail` (four setup errors).
- Shard 3: `tests/test_explainer_video.py::test_manual_stress_marker_is_removed_from_scene_caption`.
- Shard 4: `tests/test_artifacts_browser.py::test_t3_chromium_keeps_active_html_in_the_sandboxed_child`.
- Shard 5: `tests/test_audit0901_sysquota.py::test_lane_label_prints_the_threshold_that_actually_gates_it`.

The saved logs are `run-37747175830-attempt1-shard{2,3,4,5}.log`; each error points at `BrowserType.launch: Executable doesn't exist at /home/runner/.cache/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-linux64/chrome-headless-shell`.

Successful `--with-deps` logs confirm that Playwright downloaded the missing binary, but also ran apt: run 37743851490 attempt 2 shard 2 unpacked five font packages and X fonts and upgraded Mesa packages already on the Ubuntu runner (`libgl1-mesa-dri`, `libglx-mesa0`, `libgbm1`, and `mesa-libgallium` were unpacked over version `25.2.8-0ubuntu0.24.04.2`). It downloaded the headless shell at line 1152 of `run-37743851490-attempt2-shard2.log`. In run 37747175830, the separate browser job completed with `184 passed, 7 skipped` after the same `--with-deps` step; the log shows those Mesa upgrades and its downloaded shell at line 569 of `run-37747175830-attempt1-browser.log`.

Restored the browser binary to each test shard using `uv run playwright install chromium`, without `--with-deps`, under a five-minute step ceiling with two 120-second attempts. The separate browser job retains its full `--with-deps` install. The six-shard matrix and all pytest commands remain unchanged. Workflow YAML and the new shell block parse; no branch Actions run is possible, so this relies on the previous green runs showing the relevant Mesa libraries already present on `ubuntu-latest`.

The six additional saved logs (9,791 lines) were also scanned for common GitHub/AWS bearer-token patterns; none matched.
