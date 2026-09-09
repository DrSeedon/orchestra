CHANGES REQUIRED

# #303 enforcement-oracle audit — v5 freeze

Scope: Gate 1 and Gate 2 only. I inspected the executable oracle code at freeze
`8fe615b9cc89b0f94a8cce9e1d7d8d9f659b2e4e` and the hash registry commit
`52d56bba`; I did not evaluate Phase 3 code because none exists at this baseline.
No runtime, configuration, frozen oracle, plan, service, or installed state was changed.

The positive controls are materially better than v4, but the pair is not yet safe to gate
implementation. Gate 2 has a demonstrated false green for a non-atomic replay ledger. Both gates
also prove directly imported helper operations, without proving that the real activation caller
traverses those operations or that the state being asserted is the real selector/admission/process
state. Those are blocking replay/common-mode/false-state failures under the requested calibration.

## Blocking findings

### B1 — Gate 2 accepts a check-then-create replay ledger that authorizes twice concurrently

`exercise_activation_authorization` makes the first and second calls sequentially against the same
callable and directories at
`docs/tasks/303/oracle_support.py:496-521`. That proves ordinary replay rejection, but not atomic
consumption. The reference policy uses `O_EXCL` at
`docs/tasks/303/test_authority_oracle_selftest.py:150-170`; the oracle does not require that
primitive's atomic outcome. A policy that performs `if receipt.exists(): replay` followed by an
ordinary write passes every current signature/context/staleness arm and the sequential replay arm.

I ran that counterexample from an inline temporary probe. It retained the OpenSSL signature check,
time check, context check, same runtime callable, and all eight invalid arms; only nonce consumption
was changed to check-then-write. Result:

```text
sequential_oracle=GREEN replay_state_unchanged=True invalid_arms=8
concurrent_results=[{'authorized': True, 'reason': 'authorized'}, {'authorized': True, 'reason': 'authorized'}] apply_count=2
```

The concurrent probe used a two-party barrier after both `receipt.exists()` checks and before both
ordinary writes. This is a real replay double-apply, not a timing guess. It contradicts the atomic
one-use contract in `docs/tasks/303/plan.md:91` while the frozen executable oracle stays green.

Required correction: refreeze with a deterministic two-caller arm against the exact installed
`runtime_activation.authorize_pending_activation` and the exact installed policy callable, sharing
one consume directory/state. It must assert one authorization, one replay, exactly one apply, one
valid receipt, and no losing-caller selector/admission/process mutation. A check-then-create
implementation must fail that arm.

### B2 — Gate 1 can certify an unused adapter instead of the transient unit's real activation path

The release oracle loads the selected `activation_entrypoint` module and calls
`launcher.activate_installed_artifacts` directly at
`docs/tasks/303/test_release_a_recovery.py:242-260`. The exercise then supplies all observable
effects itself: its scratch protected tree is created at
`docs/tasks/303/oracle_support.py:255-265`, and the tested function receives the oracle-owned
`before_execute`, `runner`, and `commit_activation` callbacks at
`docs/tasks/303/oracle_support.py:320-330`.

No frozen test proves that `systemd-run`, the installed manager CLI, or the transient-unit command
actually calls this function. The only occurrences in executable oracle files are the direct test
load/call and the generic helper:

```text
$ rg -n "activate_installed_artifacts|authorize_pending_activation" \
    docs/tasks/303/test_*.py docs/tasks/303/oracle_support.py
docs/tasks/303/test_release_a_recovery.py:253: assert hasattr(launcher, "activate_installed_artifacts"), (
docs/tasks/303/test_release_a_recovery.py:258:        launcher.activate_installed_artifacts,
docs/tasks/303/test_release_b_identity.py:176:    assert hasattr(runtime, "authorize_pending_activation"), (
docs/tasks/303/test_release_b_identity.py:180:        runtime.authorize_pending_activation,
docs/tasks/303/oracle_support.py:882:    assert hasattr(runtime, "authorize_pending_activation"), (
docs/tasks/303/oracle_support.py:886:        runtime.authorize_pending_activation,
```

Consequently, an implementation may add a compliant test-facing adapter while the real activation
CLI reopens paths or bypasses it. The nine physical swap arms would still pass. Likewise,
`before_state == after_state` proves only that the oracle's three scratch files and injected commit
callback stayed untouched; it is not evidence about the real selector, admission gate, or process
state. This is the exact common-mode/dead-seam and false-state-proof class the audit was asked to
exclude.

Required correction: a refrozen arm must enter through the exact transient-unit/manager command
used by deployment, with deterministic hooks below that caller. A mutation that leaves
`activate_installed_artifacts` correct but makes the real caller bypass it must turn the gate red.
The failure arms must observe the actual scratch transaction's selector/admission/process state,
not only an injected stand-in callback.

### B3 — Gate 2 has the same real-operation reachability and false-state gap

The release test imports `app/runtime_activation.py` and directly calls
`runtime.authorize_pending_activation` at
`docs/tasks/303/test_release_b_identity.py:170-183`. The helper wraps only the callable passed by
the test (`docs/tasks/303/oracle_support.py:450-455,482-493`). Its state-equality proof snapshots a
synthetic `case_root` and an injected `apply_activation` callback
(`docs/tasks/303/oracle_support.py:459-494`), not the application admission/selector/process state.
`assert_bound_consumed_attestation` repeats the same direct helper invocation at
`docs/tasks/303/oracle_support.py:877-889`; it does not add a route/manager consumer.

The policy-call counter correctly rejects a bypass *inside the callable handed to the exercise*.
It cannot reject a real activation route that never calls that helper, or an invalid attempt that
mutates module/global activation state outside the injected callback. Thus the executable oracle
does not yet establish “fail inside the real authorization operation.”

Required correction: invoke the actual activation commit/authorization consumer through its real
route or manager seam with a scratch state backend, and add a wiring mutation that bypasses
`authorize_pending_activation` at that caller. Snapshot every real scratch selector/admission/
process/ledger consumer before and after each invalid and replay attempt.

## What the current executable controls do prove

Gate 1's local mechanism is non-vacuous once its function is assumed to be the production seam:

- actual selected manager/probe/hook source bytes are copied into fresh files and independently
  identified (`oracle_support.py:216-235`);
- rename, symlink replacement, and same-inode/same-size byte mutation are performed for all three
  roles (`oracle_support.py:267-301,361-380`);
- the oracle hashes the exact descriptor supplied to the runner and executes that descriptor via
  `/proc/self/fd/<fd>` (`oracle_support.py:303-318`), then checks expected stdout, zero hostile
  sentinel, zero target execution, zero commit, and scratch-state equality;
- my bounded untracked probe reported all nine reference attacks and rejected deliberate FD
  substitution, path reopen, verifier/execute divergence, and a vacuous zero-execute/zero-commit
  implementation:

```text
reference_attacks=9
fd_substitution=CAUGHT <bare assertion>
path_reopen=CAUGHT artifact swap was accepted: runtime_manager:rename
verifier_execute_divergence=CAUGHT artifact swap was accepted: runtime_manager:rename
vacuous_zero_execute_commit=CAUGHT <bare assertion>
```

Gate 2's sequential and cryptographic controls are also non-vacuous:

- `/usr/bin/openssl pkeyutl` is called directly by the independent verifier
  (`oracle_support.py:134-170`);
- the frozen bytes match RFC 8032 test vector 2. A raw independent run on the installed OpenSSL
  accepted the vector and rejected three controls:

```text
OpenSSL 3.0.13 30 Jan 2024 (Library: OpenSSL 3.0.13 30 Jan 2024)
rfc8032_vector2=0 garbage=1 bitflip=1 wrong_key=1
```

The vector bytes match the [RFC Editor's RFC 8032 test 2](https://www.rfc-editor.org/rfc/inline-errata/rfc8032.html),
and OpenSSL documents `-rawin` as required for Ed25519 in the installed 3.0 line in
[the `pkeyutl` manual](https://docs.openssl.org/3.0/man1/openssl-pkeyutl/).
The real helper invocation covers garbage, bit flip, wrong key, wrong activation context,
cross-host, cross-PID, runtime drift, and stale records at `oracle_support.py:523-607`. The first
sequential call applies once; the second uses the same callable/directories, returns `replay`, does
not apply, and leaves that scratch tree unchanged (`oracle_support.py:496-521`). The shape-only,
no-consumption, and in-call policy-bypass meta-implementations are rejected at
`test_authority_oracle_selftest.py:194-245,303-320`.

These strengths do not close B1-B3.

## Freeze and exact-command evidence

Hash registry integrity:

```text
$ git diff --name-status 8fe615b9..52d56bba
M docs/tasks/303/oracle-v5-evidence.json
M docs/tasks/303/plan-baselines.json
M docs/tasks/303/plan.md

$ sha256sum docs/tasks/303/oracle_support.py \
  docs/tasks/303/test_authority_oracle_selftest.py \
  docs/tasks/303/test_release_a_recovery.py \
  docs/tasks/303/test_release_b_identity.py \
  docs/tasks/303/test_release_c_credentials.py \
  docs/tasks/303/test_release_d_env.py
ed509cc21c454fd9025584677519980480efdd7838d2876aa938a07f80bcf64e  docs/tasks/303/oracle_support.py
6ee87489cdf92a3dd15cef1d02a430ca81fa983fca566c3453a8f7104147548a  docs/tasks/303/test_authority_oracle_selftest.py
a11ce85d524cb68700f97b7256cd4d44e055a5e575013acac8207c0ada82f925  docs/tasks/303/test_release_a_recovery.py
307ef4cedbd4ea509e0985fb9322a5989fc6099b0435645f353c03b2f04dcb58  docs/tasks/303/test_release_b_identity.py
372460aa70f4427fe185eaf0349ed0d40ea340bffcbe1d683604be231fb0d99b  docs/tasks/303/test_release_c_credentials.py
be89030df06a5c3d25f28e92ba9fb5c8a4c71ad9903beb90487ead2181df1f3d  docs/tasks/303/test_release_d_env.py
```

All six values equal `oracle_sha256` in `oracle-v5-evidence.json`. The only post-freeze changes are
the three registry/prose files above; none of the six frozen executables changed.

Exact v5 self-test command:

```text
$ sudo -n env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_authority_oracle_selftest.py
..                                                                       [100%]
2 passed in 2.17s
```

Exact Gate 1 RED command:

```text
$ sudo -n env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_authority_oracle_selftest.py docs/tasks/303/test_release_a_recovery.py -k 'gate1 or ta_'
5 failed, 1 passed, 1 deselected in 2.09s
exit 1; first failure: T-A missing behavior: the live unit still starts through a mutable uv environment
```

Exact Gate 2 RED command:

```text
$ sudo -n env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache /home/kesha/.local/bin/uvx --from pytest==9.0.2 pytest -p no:cacheprovider -q docs/tasks/303/test_authority_oracle_selftest.py docs/tasks/303/test_release_b_identity.py -k 'gate2 or tb_'
3 failed, 1 passed, 1 deselected in 0.63s
exit 1; first failure: T-B missing behavior: no mandatory project-execution identity boundary exists
```

These reproduce the v5 registry and show the meta-oracles execute before the absent Phase 3
implementation fails.

Mutation evidence was recreated only in temporary copies:

```text
Gate 1 copy mutation:
  if artifact_identity_fd(fd) != verified[role]
  -> if False and artifact_identity_fd(fd) != verified[role]
Result: rc=1; AssertionError: artifact swap was accepted: runtime_manager:rename

Gate 2 copy mutation:
  remove the reference policy's independent_ed25519_verify block
Result: rc=1; AssertionError: shape_valid_garbage
```

The frozen hashes were not changed by either run.

## Review route and independence

- Changed artifacts under review: the six frozen oracle executables; consumers are Phase 3
  implementers and the operator's activation decision.
- Named AC: Gate 1 installed-artifact TOCTOU/real-operation enforcement; Gate 2 Ed25519,
  context/staleness, single-use replay, policy wiring, and no pre-authorization state mutation.
- Route: targeted Sol security/enforcement audit, one pass, required by the auth/replay/activation
  risk floor.
- Author/reviewer family: Sol/Codex as supplied by the orchestrator. This is a fresh reviewer
  session but the same model family. It is **not** cross-family independence.
- Cross-family verdict: unavailable; no Opus review was run or claimed.

Final verdict: **CHANGES REQUIRED**. B1 alone is a demonstrated false-green replay oracle; B2 and
B3 additionally leave the real activation callers and real state outside the enforced proof.
