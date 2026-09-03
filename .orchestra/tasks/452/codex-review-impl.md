<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The targeted tests pass, but the implementation misrenders the server's explicit null headroom as zero and hides the fallback release status. This violates the requirement to preserve textual status when no headroom value exists.

Review comment:

- [P2] Treat null headroom as missing — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/quota-headroom-compact/app/static/js/usage.js:168-169
  When the server sends `headroom_pp: null` for a gated lane, `Number(null)` becomes `0`, so this renders `🎯 +0.0` and suppresses the textual release status in both consumers. Check for a missing value before numeric conversion so `release` remains the fallback when no headroom exists.

## Round (2026-09-03T07:44:32Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Round 2: `null` наконец перестал притворяться `0.0`. 🫠

## Summary

Prior finding: **FIXED**. The null check now precedes `Number()`, and both consumers retain the release-status fallback. No blocking regressions found. Review limited to `/tmp/quota-headroom-452.diff`; Codex reviewer unavailable.

## Findings

- **blocking:** None.
- **suggestion:** Add a regression test with `headroom_pp: null` and release metadata, asserting textual release status appears and no headroom marker is rendered.
- **question:** None.

## Verdict

**APPROVED** with a non-blocking test-coverage suggestion.

Exact diff evidence: `if (!lane || lane.headroom_pp == null) return '';`

At least the release status no longer has to wear a fake numeric moustache. 🎭
