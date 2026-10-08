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
