# V-1043: quota refusal CI and hub routing hint

## Changes

- `tests/test_quota_admission_e2e.py`: the failing test patches
  `app.backend_hub.hub_configured` to return `None`, at the source of the
  function-local import in `hub_alternative_hint`. Its existing
  `pytest.raises(QuotaGateError, match="hub")` assertion remains and now also
  checks that the refusal recommends `model='hubsol'`.
- Added the opposite E2E case: a configuration problem still refuses the
  above-line Claude worker, contains no `hub` hint, and creates no session.
- `app/models.py`: both Claude and Codex runtimes, including an unspecified
  model, recommend `model='hubsol'` for any work. `hubsonnet` is mentioned only
  for important creative work with a non-empty `model_reason`. Configuration,
  unsupported-runtime and unknown-model guards are preserved.
- `tests/test_models.py`: 12 parameterized hint cases cover Claude, Codex,
  aliases, unspecified model, missing configuration, hub models, Grok and
  unknown models.
- Searched all supplied tests with `rg 'hub_alternative_hint|hubsonnet' tests`.
  No pre-existing test pinned this helper's old text. The provider-pool
  alternatives in `test_quota_admission_e2e.py` belong to hub pool admission,
  not this helper, and were left unchanged.

## Actual verification

Required targeted command (with `UV_OFFLINE=1`, `nice -n 15`):

```text
uv run --frozen python -m pytest tests/test_quota_admission_e2e.py tests/test_models.py -q
```

Could not run: exit 127. `uv` resolves only to the hub forwarding shim, which
reports `uv: not found on the hub and not inside a Mutagen-synced project
(cannot forward via on-remote)`. There is no local `.venv`; `pytest` and
`httpx` are also unavailable. This private copy contains only two application
files; `app.quota_gate`, `app.manager`, `app.routes`, pipeline manifests and
the normal test configuration are absent.

The required full-suite command, `uv run --frozen python scripts/run_tests.py`,
was attempted offline and also exited 127 for the missing runner.
`scripts/run_tests.py` itself is absent. The instruction-contract script and
CLAUDE.md symlink are not supplied either; none were modified or reconstructed.

Fallback actually run:

```text
nice -n 15 python3 .orchestra/tasks/V-1043/offline_check.py
```

System Python 3.12.3 was used explicitly as a limited fallback, not as the
required project check. The script imports the real `app.models` and executes
the 12 new helper test bodies unchanged after removing pytest decorators.
It stubs the unused `httpx` dependency and the hub configuration boundary;
it does not simulate or claim to execute the E2E path.

Results:

- All 12 helper cases passed.
- Reinstating the original routing text failed all 5 positive helper cases.
- Removing the missing-configuration guard failed all 3 unconfigured cases.
- Removing the runtime filter failed 3 unsupported-runtime cases.
- Syntax compilation passed for all 3 modified source/test files.
- Reviewed changed code and task artifacts for accidental secrets, unrelated
  edits and debug leftovers. No secrets or credentials were accessed.

Imported `app` namespace path:
`<hub-workspace>`.

Imported `app.models.__file__`:
`<hub-workspace>`.

Logs: `offline-check.log`, `required-targeted.log`, `required-full.log` here.

## Remaining checks and risk

Run the required targeted pytest checks and full suite in the complete
checkout with uv. In particular, actual E2E execution and reverting the
environment patch under an unconfigured hub remain unverified here. The
existing hub regex assertion is preserved, so without the patch an
unconfigured environment should reproduce the reported original failure.

The helper's return type and empty-hint behavior are unchanged; no persistent
data or admission rules changed, so no migration or recovery action is needed.
No service was restarted, deployed or contacted; no Git operation was run.
Current main CI status cannot be established from this private offline copy.
