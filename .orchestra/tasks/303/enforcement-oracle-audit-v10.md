<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The delivery/activation split otherwise behaves as intended:

- V10 selftest: `9 passed`.
- All four delivery commands remain RED with the recorded failure counts.
- All four privileged activation commands remain RED/pending with the recorded failure counts.
- Every SHA-256 in `oracle-v10-evidence.json` matches.
- The six preserved V9 oracle hashes exactly match `oracle-v9-evidence.json`.
- Delivery reports are forced to `activation_ready=false`, `privileged_evidence=pending`, `activation_authorized=false`, and `isolation_claimed=false`.
- The privileged consumer reads signed root-owned attestations and live host state, not delivery reports.
- The preserved `/var/lib`, `/opt`, `/usr/libexec`, installed-unit/PID1, PID/starttime/runtime, Ed25519, and atomic replay arms remain executable mandatory RED gates.
- No files or production state were modified.

## Findings

### blocking — Package validation accepts credential and activation-state payloads under alternate names

[`oracle_v10_support.py`](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/oracle_v10_support.py:122) rejects only seven exact path components. It does not enforce the broader claims in [`plan.md`](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/plan.md:315), nor validate symlink destinations against the forbidden-state policy.

Concrete task-local mutations produced false GREEN results from `inspect_package()`:

- `app-source/app/provider-credentials.json` containing a refresh token
- `app-source/.ssh/id_ed25519`
- `state/activation-receipt.json` containing forged authorization/signature data
- a relative symlink targeting `state/activation-receipt.json`

The manifest can still self-report `provider_credentials_included=false` and `activation_state_included=false`; validation checks those booleans but does not derive them from package contents. The current selftest covers only `.env`-adjacent exact names, `state/keys/private`, one absolute authority path, and an escaping symlink ([test lines 79–113](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/test_v10_delivery_oracle.py:79)).

This does not let the package satisfy the real privileged activation consumer, but it permits secret exposure and contradicts the frozen claim that delivery packages contain no credential, receipt, signed evidence, or protected-state record. That is blocking under the supplied calibration.

Required correction: derive exclusion from an explicit allowed package inventory or comprehensive typed package schema, reject sensitive resolved symlink targets, and add the above false-green cases to the frozen selftest.

## Verdict

CHANGES REQUIRED

## Round (2026-08-16T20:25:41Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Prior round-1 counterexamples: **FIXED**. Exact rerun output:

```text
......... [100%]
9 passed in 0.35s
provider_credentials: REJECTED
ssh_private_key: REJECTED
activation_receipt: REJECTED
relative_sensitive_link: REJECTED
```

All 18 registered hashes match, and the six V9 oracle hashes remain unchanged. Delivery reports remain pending-only and are not consumed by the privileged activation path. The real `/var/lib`, `/opt`, `/usr/libexec`, installed systemd/PID1, PID/starttime/runtime, signature, and atomic replay gates remain mandatory.

Cross-family verdict unavailable.

## Findings

### blocking — Derived inventory trusts every Git-tracked application file without checking for secrets

[`_tracked_application_inventory()`](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/v10_delivery_gate.py:174) automatically allowlists every tracked path under `app` and `pipelines`. Exact archive equality prevents builder-added files, but does not prove the allowed source itself contains no credentials or activation evidence.

Executable counterexample:

```text
tracked_app_secret: FALSE_GREEN
```

This used an archive containing `app-source/app/provider-credentials.json` with `refresh_token=SECRET` and passed `inspect_package()` when that path was included in the same allowlist production derives from Git. Manifest flags remain non-authoritative, but nothing independently validates the sensitivity of allowlisted source content.

Thus the original four extra-member attacks are closed, but the new allowlist creates an equivalent secret-exposure path for a clean committed source file. The plan’s unconditional claim that delivery packages contain no provider credential is not yet enforced.

## Verdict

CHANGES REQUIRED

## Round (2026-08-16T20:41:03Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Round-2 blocker: **FIXED**.

Exact rerun:

```text
......... [100%]
9 passed in 0.37s
tracked_json REJECTED: untyped application payload
tracked_named_literal REJECTED: literal credential
tracked_known_token REJECTED: token material
tracked_private_key REJECTED: private key material
TRACKED_PUBLIC_SOURCE_OK 120
```

Attempts to set activation, privileged evidence, isolation, or protected-secret comparison complete all returned `REJECTED`. All 18 registered hashes match; the six V9 authority-oracle hashes remain unchanged. Delivery reports are absent from the privileged consumer, while `/var/lib`, `/opt`, `/usr/libexec`, installed systemd/PID1, live PID/starttime/runtime, Ed25519, and atomic replay gates remain mandatory.

Owner-only `0700` candidate storage does not expand the readable authority set.

Cross-family verdict unavailable.

## Findings

### suggestion — Cleanup does not cover pre-validation inventory failure

In [`_build_package()`](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-venv-boundary/docs/tasks/303/v10_delivery_gate.py:360), `_expected_package_inventory()` runs after package construction but outside the cleanup `try`. If source-content validation fails there, the candidate archive remains instead of reaching `package.unlink()` at line 375.

This is not blocking: the archive remains inside a builder-owned `0700` directory, no delivery report is emitted, and no new principal gains read or activation authority. Moving inventory derivation before construction—or including it in the cleanup scope—would make the stated cleanup guarantee exact.

## Verdict

APPROVED
