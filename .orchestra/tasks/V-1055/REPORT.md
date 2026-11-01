V-1055 — DONE: uv provisioning implemented; live pytest collection blocker recorded.

Changes:

- `HubSsh.ensure_uv` snapshots the VPS's `~/.local/bin/uv`, accepts only Linux x86_64 ELF and version 0.11.28, hashes the validated snapshot, and checks the hub installation on every Python turn. A valid binary is reused without uploading it. New/corrupt installations use a unique temporary file, verify SHA-256 and exact version, and atomically rename into `$HOME/.local/share/orchestra/tools/uv/0.11.28/bin/uv`. Failed uploads preserve the old binary and remove temporary files. No system installation or remote downloads are added.
- `_provision` invokes this before workspace upload/project launch when both `pyproject.toml` and `uv.lock` are in the manifest, including persistent copies and resumed turns. Other copies need no uv. Failure stops the turn with an explicit error.
- Preamble and resumed-thread prompts give the exact PATH export and frozen pytest command. The worker prompt permits fetching locked dependencies during setup and uv's own cache under HOME; tests themselves remain offline. The default `.venv` is excluded from sync-back archives (the installed environment here was about 481 MiB).
- Added 26 offline unit cases in `tests/test_hub_uv.py`; added CHANGELOG entry. Existing acceptance tests and shared conftest are unchanged.

Observed on this hub:

- Python 3.12.3 / x86_64; pyproject.toml and uv.lock are present. The default uv resolves to the hub shim and fails with exit 127: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
- PyPI release JSON, the pinned uv wheel, and all 76 locked project packages were reachable. The wheel's SHA-256 was checked before extracting the binary. No wheel-cache transfer is necessary on this machine.
- The real production installer ran on this host, replacing only the SSH hop with a local shell and sandboxing HOME inside the task directory to obey the worker's write boundary. Two provisions produced one upload; installed bytes and version matched. The versioned path uses only the hub user's own writable area.
- Imported app namespace path (absolute home prefix redacted as required): `<hub-home>/orchestra-ws/vmi3407579/hub-a7f8a9c310d34420/app`.

Checks actually run:

- `uv run --frozen python -m pytest tests/test_hub_uv.py -q` using the provisioned real binary: exit 2 during collection, `ModuleNotFoundError: No module named 'app.hub_outbox'`. Verbatim output, with only the prohibited absolute home prefix replaced, is in `live-check.txt`.
- `uv run --frozen python .orchestra/tasks/V-1055/offline-check.py`: **26 passed in 0.80s**. This explicitly isolated run uses `--noconftest` and import-only stand-ins for modules omitted from this private copy. It exercises the actual provisioning/backend methods with fake SSH, not publication/outbox/provider APIs. It is not presented as the required normal test run.
- Covered cold/warm installation, mode/content/deletion recovery, corrupt transfer rollback, remote version/platform rejection, connection failure, concurrent installations, local source shim/architecture/version rejection, snapshot consistency, archive exclusion, first/resumed/persistent backend preparation, missing-lock negative cases, and failure before upload/project creation.
- AST parsing passed for both changed application files, the new test file and task harnesses. Final source/artifact scan found no absolute hub-home prefix or credential-shaped strings. Temporary binaries, packages, virtualenv and raw logs were removed before handback.

Remaining checks / limits:

- This copy contains only `app/backend_hub.py` and `app/hub_workspace.py`. It lacks their imports (`hub_outbox`, `publication_secrets`, etc.) and the app modules required by shared test fixtures. An initial frozen run of `tests/test_errtext.py` likewise stopped at missing `app.errtext`. A real passing normal pytest run needs those source files included in owned_dirs; dependency installation is already working. No source modules or fixtures were fabricated to turn that run green.
- Full hub suites with shared fixtures, real VPS-to-hub SSH, and VPS-binary bytes have not been verified here. `scripts/run_tests.py` and `scripts/check_instruction_contract.py` were not supplied, so those checks remain unrun. Run normal hub suites on the complete VPS checkout before integration. No deployment or restart was performed; the platform imports/commits the result branch.

Reproducing the isolated investigation: supply the verified uv 0.11.28 executable at `.orchestra/tasks/V-1055/bootstrap/uv`, set TMPDIR and UV_CACHE_DIR inside the task directory, then run `live-probe.py` or `offline-check.py` through `uv run --frozen python`. The bootstrap wheel hash and resulting executable hash are in `live-check.txt`; downloaded binaries are deliberately not part of the result.
