# #303 V11 implementation stop: independent runtime prefixes are byte-unstable

## Status

`WIP/STOP`. V11 fixes the earlier `lib64 -> lib` directory-link rejection, but
the frozen delivery gate remains unsatisfiable for an independently built real
Python 3.12 runtime. No privileged activation work was attempted.

## Frozen baseline integrity

After merging current `main` into `task-303/impl-venv-boundary`, every SHA-256
registered by `docs/tasks/303/oracle-v11-evidence.json` matched:

- 12 oracle files, including all preserved V9/V10 bytes;
- 7 V11 supporting artifacts;
- the round-2 review artifact SHA-256
  `1c234fe83756837496c4f6312857e5e695fd0d7a2301d8a20994bc835144285b`.

The registry commit is `f0db5c31`; the approved V11 freeze is
`4d5a49aa145772307e9f4333859ddea7a8c6daf5`.

## Required delivery commands rerun from V11

No V10 green result was carried forward. The exact V11 commands were rerun in
A -> B -> C -> D order from a clean committed tree.

- A reached all frozen source nodes and the package comparison, then failed
  with `AssertionError: package bytes/modes/links differ from derived inventory`.
- B remained RED: `1 failed, 31 passed`; the fail-closed project execution
  identity is not implemented.
- C remained RED: `1 failed, 24 passed`; the provider boundary is not
  implemented.
- D remained RED: `4 failed, 24 passed`; the scoped environment/capability
  delivery is not implemented.

The A implementation now emits the canonical internal runtime directory link
as `runtime/lib64`, type `symlink`, target `lib`, mode `0777`. This moves V11
past the V10 blocker. The next comparison fails on a distinct frozen premise.

## Reproduction independent of the package builder

The following read-only probe invoked V11's own
`_reference_runtime_inventory` twice under one sanitized environment, using two
fresh scratch targets and the same frozen lock:

```text
members_first 3438
members_second 3438
directories_equal True
inventory_difference_count 38
first_differences ['runtime/bin/activate', 'runtime/bin/activate.bat',
'runtime/bin/activate.csh', 'runtime/bin/activate.fish',
'runtime/bin/activate.nu', 'runtime/bin/dotenv', 'runtime/bin/fastapi',
'runtime/bin/httpx', 'runtime/bin/idna', 'runtime/bin/jsonschema',
'runtime/bin/markdown_py', 'runtime/bin/mcp']
bin/activate line 81
 one: VIRTUAL_ENV='<ONE>'
 two: VIRTUAL_ENV='<TWO>'
bin/uvicorn line 1
 one: #!<ONE>/bin/python
 two: #!<TWO>/bin/python
```

There are 38 path-dependent byte differences: activation scripts, console
entry-point shebangs, and their wheel `RECORD` hashes. Therefore two honest
`uv sync --frozen --python /usr/bin/python3.12 --no-install-project` builds at
different paths cannot satisfy V11's required complete byte equality.

## Why no implementation workaround is acceptable

The gate derives the reference under its private
`<delivery-scratch>/reference-runtime` path and invokes the builder with no
reference-runtime input. Making the builder discover and package that oracle
directory would destroy the required independent build. Rewriting candidate
scripts to contain the oracle's temporary prefix could force byte equality,
but the resulting package would be non-installable and would encode an
ephemeral test path. Either route would make the security gate false-green.

The immutable acceptance test must instead be refrozen with an installable,
path-independent runtime representation or a precisely specified normalization
that is independently applied to both inventories. The received test cannot be
edited by this implementation worker.

## Safety state at stop

- No `/opt`, `/var/lib`, `/usr/libexec`, `/etc/systemd`, Unix-account, process,
  service, auth-store, provider-secret, or live configuration mutation occurred.
- No V11 delivery report was emitted, so no delivery-ready or activation claim
  exists.
- Required implementation-phase values remain conceptually unchanged:
  `activation_ready=false`, `privileged_evidence=pending`,
  `activation_authorized=false`, `isolation_claimed=false`, and
  `protected_secret_comparison=pending_privileged_activation`.
- Privileged activation commands remain RED/pending and were not used as a
  substitute for delivery acceptance.
- B, C, D implementation and the mandatory implementation security review were
  not started after the frozen-oracle blocker.

## Implementation commits

- `e6794be5` — V10 A delivery-only runtime package/control plane.
- `0904572a` — V11 canonical runtime directory-link packaging.
