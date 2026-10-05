# V-719 — RUAccent on the laptop

## Diagnosis

The laptop checkout `/mnt/data/Projects/Python/orchestra` was clean at `ebf24923` and had
`--stress-only`. `make.py` defaults `TTS_HOME` to `~/.local/share/orchestra-tts` and
`TTS_PYTHON` to `TTS_HOME/venv/bin/python`. On the laptop, that TTS path is a symlink to
`/mnt/data/Apps/orchestra-video/orchestra-tts`; the venv has RUAccent 1.5.8.3. `RUAccent.load`
gets its main weights from `TTS_HOME/ruaccent-model`, not the Hugging Face hub cache. The VPS
directory is 505 MiB; the laptop copy is `528,728,988` bytes. `make.py` then revealed a second
asset root: `ruaccent.py` checks for `ruaccent/koziev` beside the installed package and requests
it from Hugging Face if absent. The laptop lacked that directory; the VPS package's `koziev`
assets total 189 MiB. With both directories installed, `HF_HUB_OFFLINE=1` proves the worker uses
the local copies: neither asset root requires the hub cache on the successful path.

## Changes

`.orchestra/tasks/V-691/setup-laptop.sh` restores the model from
`/mnt/data/Apps/orchestra-video/ruaccent-model.tar` and package data from
`/mnt/data/Apps/orchestra-video/ruaccent-koziev.tar` when required files are absent, then verifies
them. Both archives passed `tar -tf`; the updated installer was copied to the laptop and passed
`bash -n`. The `explainer-video` skill now requires stopping and reporting a RUAccent load failure;
manual stress markers are described as targeted corrections. Laptop archive SHA-256 values:
`ruaccent-model.tar` — `706141e53f98ad6a20533a01ef772e9ab5ee5e53ed99794f0e6fb4fc23ba42e6`;
`ruaccent-koziev.tar` — `9d83df9e5cae165cb62e501200b8db65050d73cc4072f12e007191d13d632cd8`.

## Verification status

`bash -n .orchestra/tasks/V-691/setup-laptop.sh` passed. `tests/test_explainer_video.py` passed
(14 tests). Resumable `rsync --partial --append-verify` transferred both asset roots; both reusable
archives were validated. The final laptop `--stress-only` run passed with `HF_HUB_OFFLINE=1`,
`nice -n 15`, `MemoryMax=2G`, and the existing Chromium path. It exited 0 with eight annotated
phrases and created `cache-ttl.stress.txt` (1,700 bytes). Raw stdout is in
[`laptop-stress-only-final.log`](laptop-stress-only-final.log); the laptop checkout remained clean
at `ebf24923`. The first probe used Playwright's default browser cache and stopped before RUAccent;
the successful invocation set `PLAYWRIGHT_BROWSERS_PATH` to the existing `/mnt/data/Apps/orchestra-video/ms-playwright` installation.
