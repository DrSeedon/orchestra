## Summary

- Gate 1 — **STILL BLOCKING**: the plan closes the trust boundary, but the frozen oracle does not execute the installed-artifact replacement attack.
- Gate 2 — **STILL BLOCKING**: the plan specifies signed, one-use attestations, but the oracle neither attacks signature verification nor proves validation and consumption are inseparable on the activation path.
- Gate 3 — **CLOSED**: provider expectations are independently rooted and both `/bin/true` attacks are executable.
- The five frozen oracle paths are unchanged from `622e740e2cd934d7bfe6fac40ab894afef27ac9c` (`git diff --exit-code` returned 0).
- `cross-family verdict unavailable`

Exact RED commands were run:

- `... pytest ... docs/tasks/303/test_release_a_recovery.py` → `4 failed in 0.34s`
- `... pytest ... docs/tasks/303/test_release_b_identity.py` → `2 failed in 0.21s`
- `... pytest ... docs/tasks/303/test_release_c_credentials.py` → `3 failed in 0.28s`
- `... pytest ... docs/tasks/303/test_release_d_env.py` → `5 failed in 0.24s`

These are valid RED outcomes; no collection/import failure masked them.

## Findings

blocking: `docs/tasks/303/test_release_a_recovery.py:260` — Gate 1’s `installed_artifact_swap` is accepted from the rehearsal’s self-reported JSON; lines 265–267 only assert `accepted is False` and a claimed failure string. Unlike the hostile-worktree sentinel at lines 48–87 and the real open-FD swap at lines 213–230, the oracle never replaces a verified installed manager/probe/hook itself and observes which inode executes. A rehearsal can emit `{"accepted": false, "failure": "identity_changed"}` while production verifies one inode and subsequently executes a replaced path. The plan’s immutable installed-root contract at `docs/tasks/303/plan.md:51–58` is sound, but its executable oracle is insufficient.

blocking: `docs/tasks/303/oracle_support.py:205` — Gate 2 accepts any 128-hex `signature`; lines 211–213 check only its shape and public-key hash, while lines 281–308 call `validate_bound_claims` without the signature or public key. A policy implementation that validates every bound field but never verifies Ed25519 would satisfy this oracle with a forged attestation. This contradicts the signature requirement at `docs/tasks/303/plan.md:79–87`.

blocking: `docs/tasks/303/oracle_support.py:281` — replay prevention is tested as two disconnected claims: `validate_bound_claims(... consumed=False)` at lines 283–308 and a scratch-only `consume_once` call at lines 310–314. No frozen oracle exercises the real activation authorization entry point twice. Production can validate repeatedly while omitting or postponing `consume_once`, yet both isolated tests remain green. The required concrete oracle must invoke the same activation-authorizing operation twice and prove the second attempt fails before selector/admission mutation.

suggestion: `docs/tasks/303/test_release_c_credentials.py:56` — Gate 3 is **CLOSED**. The oracle independently pins provider-specific launcher name and root plus live device/inode/size/hash at lines 56–83; rejects resolver-only `/bin/true` injection at lines 226–236; rejects a consistently rewritten manifest/resolver trust root at lines 237–247; and requires the production latch to reject the same shared lie at lines 326–339. This directly exercises both requested counterexamples without consulting the production resolver for expected identity.

## Verdict

CHANGES REQUIRED — corrected three-gate Phase 2 baseline is not valid
