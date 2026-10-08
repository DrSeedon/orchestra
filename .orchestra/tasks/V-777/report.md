# V-777 — replace apt ffmpeg setup in CI

## Choice

The CI test shards need a real `ffprobe`; the existing workflow comment explicitly rules out a stub. The failure was in apt fetching `libflite1` from the Ubuntu mirror before the bounded install step finished. The replacement downloads the Linux x86_64 LGPL static build from BtbN's FFmpeg Builds, extracts `ffmpeg` and `ffprobe` into `$RUNNER_TEMP`, and adds that directory to both the current shell's `PATH` and `GITHUB_PATH` for later steps. It pins the 2026-09-30 month-end release and verifies the asset SHA-256 before extraction.

BtbN documents that Linux builds target glibc 2.28 and newer, that builds are static, and that the last build of each month is retained for two years (daily builds are retained for 14 days) in its [build README](https://github.com/BtbN/FFmpeg-Builds). This makes the month-end tag a durable pin, unlike a floating `latest` URL or a short-lived daily release. The pinned [2026-09-30 release](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-30-13-08) asset metadata reports digest `sha256:82ccd41f4c04ac6f1633920c83eb4c73c6c9dc954d64da10a2410c1277b83647`; local `sha256sum --check` passed.

## Local clean-directory check

Downloaded the pinned 140,614,116-byte archive, verified its SHA-256, extracted both binaries into a new empty directory, copied them into a fresh `bin` directory with executable mode, and put that directory on `PATH`. Created a small PCM WAV and ran the real `ffprobe` against it. The step's YAML parsed and its `run` body passed `bash -n`.

Output from the local check:

```text
ffmpeg version N-127032-g6ae491a26c-20260930 Copyright (c) 2000-2026 the FFmpeg developers
ffprobe version N-127032-g6ae491a26c-20260930 Copyright (c) 2007-2026 the FFmpeg developers
codec_name=pcm_s16le
sample_rate=8000
channels=1
```

No GitHub Actions run was started; the requested verification was local. No other workflow step or shard changed.
