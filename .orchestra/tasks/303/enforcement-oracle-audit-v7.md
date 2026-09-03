<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Frozen V7 hashes match `c83f4437e73432e6b3752014b7786126e59b48a2` and registry commit `316c8d5a`.

Executed the exact recorded commands:

- Selftest: `5 passed in 0.29s`, exit 0.
- Gate A RED: `5 failed, 4 passed, 2 deselected`, exit 1.
- Gate B RED: `3 failed, 4 passed, 1 deselected`, exit 1.

The systemd-to-manager binding and deterministic two-process replay oracle are materially corrected. However, the “installer cannot activate” and “only shipped production authority entry” requirement remains false-greenable.

Reviewed artifact line: “scope: oracle mechanics only; no production authority implementation is supplied”

V5 and V6 remain rejected evidence. Runtime/config/prod were untouched.

cross-family verdict unavailable.

## Findings

blocking: `docs/tasks/303/test_release_a_recovery.py:154` — installer enforcement relies on a short denylist of literal substrings. An installer can activate the unit through `systemctl start --wait "$unit"`, an escaped/constructed unit name, or invoke `"$manager" activate` without matching any assertion at lines 161–165. The test also does not inspect other shipped scripts or application routes, so an alternate production authority entry can coexist with both correct fixed units and still pass. This violates Gate 1’s release-wiring condition and Gate 2’s requirement that the fixed one-shot unit be the only shipped production authority entry → add an executable/static oracle covering all shipped activation-capable consumers and mutation controls proving indirect installer activation, direct manager invocation, and an alternate application route make the gate red.

## Verdict

CHANGES REQUIRED

## Round (2026-08-16T19:44:12Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Prior finding: **STILL BROKEN**.

All V8 immutable hashes match freeze `9c80ec07d30e918e8f9a8d79c4be8bc984afeafe` and registry `75fc5e99`.

Exact recorded commands produced:

- Selftest: `6 passed in 0.41s`, exit 0.
- Focused Gate A RED: `6 failed, 5 passed, 2 deselected in 0.65s`, exit 1.
- Focused Gate B RED: `4 failed, 5 passed, 1 deselected in 0.40s`, exit 1.

Both Release A and B call `assert_shipped_activation_surface(ROOT)`. The three recorded mutations are rejected. Root-owned mode `0500` prevents controller/project UIDs from directly importing or executing the manager.

cross-family verdict unavailable.

## Findings

blocking: `docs/tasks/303/oracle_support.py:230` — the shell inventory remains lexical and allows a root installer to construct both `systemctl` and `start` across assignments. I injected:

```sh
unit=orchestra-runtime-recovery@task303.service
ctl=/usr/bin/sys
ctl="${ctl}temctl"
action=sta
action="${action}rt"
"$ctl" "$action" --wait "$unit"
```

`assert_shipped_activation_surface()` returned `FALSE_GREEN: 7 files scanned`. This executes the same indirect activation rejected by the recorded literal mutation. The `0500` manager contract does not protect this path because the installer/systemd runs as root → reject variable executables/actions structurally or replace the shell installer authority surface with a closed executable/allowlisted command representation.

## Verdict

CHANGES REQUIRED

## Round (2026-08-16T19:52:26Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Prior blocker: **FIXED**.

All V9 hashes match freeze `6045144a5fc207b276048b622f5f63f04dff26eb` and registry `d9ee00d1`.

Exact command results:

- Selftest: `6 passed in 0.31s`, exit 0.
- Focused Gate A RED: `6 failed, 5 passed, 2 deselected in 0.74s`, exit 1.
- Focused Gate B RED: `4 failed, 5 passed, 1 deselected in 0.42s`, exit 1.

The prior constructed `sys`+`temctl` / `sta`+`rt` attack was rejected: `deploy/install.sh is not the exact root-refusing package-builder wrapper`.

Release A directly enforces `installer == SAFE_INSTALLER_SOURCE`. In that frozen source, `/usr/bin/id -u == 0` reaches `exit 77` before the sole builder `exec`. Root bootstrap is confined to explicit runbook commands; installed authority artifacts require root ownership and mode `0500`. Alternate application routes remain covered by whole-corpus inventory and denied direct manager access by DAC.

A CRLF-only representation normalizes to the same text, but introduces no command or authority path. No byte-preserving or alternate invocation capable of gaining root activation authority was found.

Reviewed artifact line: “The legacy shell installer is not parsed or denylisted: its entire source must equal the frozen root-refusing package-builder wrapper.”

cross-family verdict unavailable.

## Findings

No blocking findings within the reviewed seam.

## Verdict

APPROVED
