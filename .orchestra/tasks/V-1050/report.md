# V-1050 — bounded archive publication scanning

Implemented in `app/forbidden_strings.py` and `app/publication_secrets.py`; added
`tests/test_publish_guard_archives.py` and an Unreleased CHANGELOG entry.

## Behavior

- `scan_range` reads new/modified Git blobs at every introduced commit, independently
  of the lossy `--text` patch. Detection uses bytes, not filenames: gzip (including
  tar.gz/tgz), tar (including legacy headers), zip, bzip2, xz, and nested combinations.
- One budget per blob: 16 MiB input, 16 MiB cumulative decoded data and copied TAR
  metadata, 1000 entries/headers/compressed streams, four archive layers. TAR PAX/GNU
  extension bodies are limited to 64 KiB; XZ decoder memory is limited to 32 MiB.
- No extraction to disk. ZIP directory entries are counted before ZipInfo allocation.
  ZIP stored/deflate/BZIP2 payloads are checked against actual decoded size and CRC.
  Deflate/BZIP2 use bounded decoder calls even when ZIP headers lie about size.
- Limits, truncation, unreadable/encrypted content and unsupported ZIP compression
  fail closed. Multi-disk/ZIP64 directories and ZIP-LZMA are explicitly refused.
  ZIP local ZIP64 extras with an ordinary central directory remain supported by stdlib.
- Diagnostics use `outer!member` paths and rule/shape labels. Raw library exceptions
  and matched values are never copied into findings; member names are redacted too.
  Gzip/bzip2/xz streams use explicit `<gzip>`, `<bzip2>`, `<xz>` virtual member names.
- A refusal returns before constructing a potentially huge binary text diff.
  Archive deletions are ignored; adding then deleting a leak in introduced history
  still refuses. `scan_patch` and plain-text literal/shape policy are unchanged.
  Only decoded archive payloads/metadata opt into the existing shared shape patterns.

## Validation actually run

- `nice -n 15 python3 tests/test_publish_guard_archives.py -v`:
  **30 tests, 28 passed, 2 skipped**. Covers all required formats and nested paths,
  clean files, byte/member/depth bounds, corrupt/encrypted archives, forged ZIP sizes,
  CRCs, ZIP BZIP2, XZ dictionary bounds, TAR metadata/extensions, redaction, actual
  Git blob/history/deletion handling and `python -I -S` stdlib-only imports.
- The committed mutation test removes the call to `_scan_archive_blob` in a disposable
  copy and runs the same Git format acceptance test: **10 assertion failures**,
  one for every format case. The unmutated test passes. See `mutation.log`.
- `nice -n 15 python3 .orchestra/tasks/V-1050/run_existing_tests.py`:
  **22 selected existing V-1047 tests, 21 passed, 1 skipped**. Covers literal inventory,
  text/path/message diagnostics, deletion/history behavior, existing plain-text shape
  policy, minimal imports, hook dispatch and installer behavior. Runtime-dependent
  tests are excluded explicitly by the driver, without changing their source.
- `python3 -m py_compile` passed for the changed modules and new test file.
- Imported `app` is the supplied worker copy's namespace package, and the guard was
  imported from its `app/forbidden_strings.py`; the absolute import location is
  reported in the worker's final response, outside publication artifacts.

## Required checks still unavailable

Attempted exactly:

```
uv run --frozen python -m pytest tests/test_publish_guard_archives.py tests/test_publish_guard.py tests/test_publication_gate_v1047.py -q
```

Exit 127: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
`python3 -m pytest --version` also reports `No module named pytest`.
The successful system-Python unittest runs above are fallback evidence, not the required uv checks.

`rg` confirms `scripts/hooks/pre-push` and `scripts/install_git_hooks.py` dispatch to
`scripts/secret_scan.py`, but that scanner and `app/workspace.py` were excluded from
this copy. Consequently the exact merge_worker/pre-push-to-module call sites cannot
be inspected here. Two new tests explicitly cover the real hook and merge gate and
skip only when those files are absent; one existing real-scanner test also skips.
**Before acceptance, run the targeted pytest command in the full checkout and verify
both callers reach `scan_range`. A caller using only `scan_patch` must be wired to
`scan_range`: a decoded patch cannot reconstruct arbitrary compressed bytes.**

No project Git metadata is supplied. No project commit, push, merge, deployment or
service restart was performed. Result copying/commit and clean-tree verification
belong to the platform/orchestrator. Suggested commit title:
`#V-1050: scan compressed publication artifacts with bounded decoding`.

## Non-obvious implementation findings

Security-patched Python 3.12 tarfile parses through `_frombuf` rather than the public
`frombuf` wrapper, including extension-header recursion. The guard therefore bounds
its header-reading entry points; overriding only `frombuf` silently misses headers.
Tests cover both ordinary and hidden extension header limits and later corruption.

Stdlib `ZipExtFile` calls BZIP2 decompression without `max_length` and truncates output
to advertised file size. Reading ZipExtFile in small chunks alone does not bound a
forged-size BZIP2 bomb. The guard validates ZIP layout with stdlib, then uses bounded
raw decoders and checks the complete output. Raw mutation traces redact the worker
checkout path before saving publication artifacts.

## Orchestrator completion (local, after hub turn)

The hub copy lacked `scripts/secret_scan.py` (excluded as credential-like by name), so the
pre-push hook still scanned only decoded text and `test_actual_pre_push_hook_scans_archives`
failed 4/4 subtests on the host. `_pre_push` now also calls `forbidden_strings.scan_archive`
on each added blob. Tests no longer create temp dirs under or write `mutation.log` into this
task directory (a test rewriting a tracked artifact). Host run, app imported from the worktree:
151 passed, 85 subtests passed across the publish-guard, V-1047 and secret suites. Mutation:
replacing the new `scan_archive` call with `pass` fails the hook test, 4 subtests (tar.gz, gz,
zip, nested).
