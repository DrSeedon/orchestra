# V-1143 notes
- Upstream pinned: microsoft/TokenEconomizer @ 1deb887bb6816188e24580f8812e65288af5757c (depth-1 clone in /tmp/v1143-src, copy in /tmp/v1143-run/repo).
- Probe sandbox: `env -i`, PATH=/tmp/v1143-bin (symlinks: python3 git sh env + coreutils; NO codex/claude/copilot) so any side call fails closed. Scripts are in probes/, verbatim stdout in evidence/.
- Gotcha: `find`/`head` symlinks created via `command -v` can resolve to the hub shim and loop ("Too many levels of symbolic links"); link /usr/bin/<tool> explicitly.
- uv `--with pytest` is unlocked (upstream has no uv.lock); only used to run upstream tests, not our repo.
- Probe P3 judge is a deterministic stub: verdict quality is NOT measured.
- Paper text came through WebFetch summarisation (secondary); Table 1 cross-checked against README. Base64 prompt appendices not decoded.
