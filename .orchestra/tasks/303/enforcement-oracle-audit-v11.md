<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All 12 registered oracle hashes recomputed exactly, including unchanged V9/V10 bytes. The canonical `lib64 -> lib` control passed; cyclic, chained-escape, and content-mismatch controls failed closed. Importing V10 preserves pending-only delivery semantics and does not add activation authority.

Exact recorded self-test:

```text
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 python -m pytest -p no:cacheprovider -q docs/tasks/303/test_v11_delivery_oracle.py docs/tasks/303/test_authority_oracle_selftest.py
..........................                                               [100%]
26 passed in 0.53s
```

cross-family verdict unavailable.

## Findings

blocking: `docs/tasks/303/oracle-v11-evidence.json:99` — `candidate_reference_name_type_mode_bytes_link_equality` is false for explicit directory entries. `inspect_package()` accepts any directory in the derived directory allowlist and immediately discards its representation and mode. Independently adding `runtime/lib/` to an otherwise identical archive produced:

```text
extra explicit archive directory accepted: True
archive bytes differ: True
```

Thus an extra archive entry—and directory mode mismatch—can receive the same observed inventory as the frozen reference, violating the exact AC and permitting a false-green package. Directory entries must be represented in the expected inventory and compared for presence/type/mode, or forbidden entirely when absent from the canonical archive representation.

blocking: `docs/tasks/303/oracle-v11-evidence.json:100` — deriving inventory before construction does not close the package TOCTOU boundary. `validate_package()` hashes `package_path` at `oracle_v11_support.py:185`, then reopens it by pathname at line 188; `v11_delivery_gate.py` later reopens it again to populate the report digest. A deterministic replacement after the digest read was accepted with differing manifest and final archive hashes:

```text
toctou: accepted final archive with digest differing from manifest
manifest_sha256= d2297d8cfe0ab64aa9ae3c588202e6fe86c7ea6a9a7c3c4b44ca50a6d04d75b7
final_sha256= 1548a3369348a81ce62eb47330f80512815e7d1c2ded3b9414d31c07a09dea38
```

The validator must open once with no-follow semantics, pin and verify the file identity, and derive the digest plus tar inspection from that same descriptor. The report must bind that validated digest rather than reopen the path.

## Verdict

CHANGES REQUIRED

## Round (2026-08-16T21:30:47Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Both prior blockers are FIXED.

- Explicit archive directories are rejected before inventory comparison; the physical `runtime/lib/` mutation raises.
- Package and manifest parsing/digests use pinned anonymous snapshots. Final path identity is checked, and the report consumes returned validated digests without reopening paths.
- Replacement, symlink, same-inode mutation, manifest replacement, and parse-versus-digest races fail closed through `O_NOFOLLOW`, descriptor/path identity checks, and snapshot-only parsing.
- Canonical `lib64 -> lib` remains satisfiable.
- All registered hashes match; V9/V10 bytes remain exact.
- Delivery remains pending-only and cannot authorize activation or claim isolation.

Exact selftest output:

```text
..............................                                           [100%]
30 passed in 0.59s
```

Reviewed artifact quote: “A delivery report is never an input to that consumer.”

cross-family verdict unavailable.

## Findings

No blocking findings, suggestions, or questions.

## Verdict

APPROVED
