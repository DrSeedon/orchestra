# #303 Phase 3 implementation stop — frozen V10 runtime inventory

## Outcome

Implementation stopped at ticket A. The frozen delivery command cannot reach package
comparison on this host because its independently built reference Python 3.12 environment
contains the normal virtual-environment link `lib64 -> lib`, while the frozen inventory
rejects every symlink whose resolved target is a directory.

The acceptance oracle and all frozen evidence files remain byte-identical. No privileged
activation command was changed, skipped, or represented as green. No production path,
service, process, account, auth store, credential, or installed unit was mutated.

## Exact acceptance command

```text
env -u VIRTUAL_ENV -u UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/var/tmp/orchestra-task303-uv-cache-kesha /home/kesha/.local/bin/uvx --from pytest==9.0.2 python docs/tasks/303/v10_delivery_gate.py A
```

Observed after the source nodes became green:

```text
RuntimeError: package input is not a regular file: /var/tmp/orchestra-package-runtime-2xwoanxn/lib
```

The builder encountered the `lib64 -> lib` directory link first. An independent positive
probe then called the frozen reference-inventory function directly with the exact Python,
uv, environment sanitization, and scratch-root shape used by the acceptance command:

```text
AssertionError: runtime directory/device link is unsupported:
/var/tmp/task303-reference-probe-tca_vr1v/reference/lib64
LIB64 True -> /var/tmp/task303-reference-probe-tca_vr1v/reference/lib
```

The failing frozen clause is `docs/tasks/303/v10_delivery_gate.py:254`:

```python
assert resolved.is_file(), f"runtime directory/device link is unsupported: {path}"
```

This occurs in the oracle-owned reference build, independently of the candidate archive.
Changing only tracked delivery implementation cannot make it green without either mutating
the immutable acceptance oracle or causing the package builder to prepopulate and rewrite the
oracle's future reference directory. The latter would destroy the required independent
inventory boundary and is therefore not an acceptable workaround.

## Work completed before the stop

Commit `e6794be5` adds the delivery-only A package/control-plane source, fixed pending-only
unit templates, activation-surface manifest, direct versioned service templates, and the exact
root-refusing installer wrapper. The frozen A source subset is green:

```text
12 passed in 1.61s
```

The full delivery command remains RED for the oracle defect above. B, C, and D implementation
did not start because all four delivery commands share the same reference-runtime inventory.

## Required resolution

Refreeze V10 so the separately built runtime inventory handles a virtual-environment directory
alias deterministically (for example, omit directory links from both candidate and reference
inventories while continuing to reject links in the final archive). Then rerun the frozen-hash
gate and resume A -> B -> C -> D. The current acceptance test must not be edited in place.
