# V-1259 — DONE: bounded source integration

Exactly five production files recovered in the actual returned copy; no other
production/test/rule changes. Public canonical source pinned to
`b9d893ec8babd4b2052ac1f497962e1966206bcb`, fetched by exact raw GitHub URL
from V-1257 recovery-conflict-evidence.json and validated before writing.
The pipeline baseline SHA was
`76240fd6d9b15ae1de739306c75f9f22bec6ab0db47adc59863c2dad6e1a2a16`.
Applied only producer recovery-against-d95.patch, with fuzz=0: one terminal
specialist role on known Sol (Phase A) and specialist in three parent can_spawn
lists. Four prompt files now equal b9 bytes exactly; V-1256 policies retained.
V-1258/0716 was never used.

| Actual changed file | Diff lines | Final SHA-256 |
|---|---:|---|
| `.orchestra/pipelines/default/pipeline.yaml` | +23/−3 | `69af96dc84e32751257824e8cdbad493a63d9126e88d3268a304c132363a8df6` |
| `.orchestra/pipelines/default/prompts/modules/orchestration.md` | +19/−1 | `eea635d296c2764c7facea05fe17800ddd28f9917dad57a1960c9cc88d5e29ef` |
| `.orchestra/pipelines/default/prompts/modules/communication-style.md` | +8/−0 | `325dd65bea0fd7ffc440d6a5cf9afad998f2a5a5a75bf7494bacda0aada4bd43` |
| `.orchestra/pipelines/default/prompts/modules/worker-lifecycle.md` | +8/−3 | `f9fe5313a4f61736e924e4c1706311e0eee334fb0804abb5e98ad13defe627d0` |
| `.orchestra/pipelines/default/prompts/roles/orchestrator.md` | +27/−10 | `64095a73004598b73a428d68750ecc4e6086ad239e37b6b6f6f70bbb88f7c68b` |

Full actual before/after diff: five-file.patch; original and pinned canonical
bytes: before/ and canonical/. Before/canonical/final hashes and public commit:
five-file-manifest.json. Semantic comparison independently confirmed the pipeline
has no changes beyond the authorized role and three parent lists.

Checks performed once on the returned source, using provisioned uv 0.11.28,
default .venv, serial, nice=10, OOM score=1000, UV_OFFLINE=1 after setup.
The test-process Git identity was synthetic, with no global Git configuration.
TMPDIR, pytest basetemp and pytest cache were under this task directory.

| Check | Actual result | Evidence |
|---|---|---|
| 15 existing producer paths (606 cases) plus two contract test paths (19 cases) | 625 passed, 56.71 s, exit 0; no skipped/failed cases | pytest.log |
| Pipeline manifest vs actual prompt tree | PASS, exit 0 | pipeline-contract.log |
| Root instruction contract | RED, exit 1: CLAUDE.md absent in supplied copy | instruction-contract.log |
| Phase B patch, dry-run with fuzz=0 | PASS, exit 0; NOT applied | phase-b-dry-run.log |
| Actual import app resolved to workspace app/__init__.py | PASS, exact absolute-path equality asserted | verification.json |
| Producer manifest source paths | 15/15 SHA matched | producer-source-check.json |
| Source scope, post-check immutability, old artifacts | PASS | verification.json |
| New artifact secret-form scan | PASS; no secret inventory or credential discovery | artifact-scan.json |

Commands (PATH prepended with `$HOME/.local/share/orchestra/tools/uv/0.11.28/bin`):

```sh
uv --version
uv run --frozen python .orchestra/tasks/V-1259/recover.py
# The following pytest command had an outer timeout 180s and nice -n 10.
uv run --frozen python -m pytest tests/test_gemini_specialist_v1257.py tests/test_hub_sol_only_v1240.py tests/test_hub_effort.py tests/test_hub_pool.py tests/test_backend_hub.py tests/test_model_registry_503.py tests/test_models.py tests/test_model_gates.py tests/test_backend_routing.py tests/test_default_pipeline.py tests/test_pipeline.py tests/test_hub_file_policy_v1073.py tests/test_hub_snapshot_v1213.py tests/test_hub_archive_v1244.py tests/test_hub_cleanup_generation_v1244.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q --basetemp=.orchestra/tasks/V-1259/scratch/pytest -o cache_dir=.orchestra/tasks/V-1259/scratch/pytest-cache
uv run --frozen python .orchestra/tasks/V-1259/finalize.py
# finalize.py runs these bounded, read-only checks with the same .venv Python:
uv run --frozen python scripts/check_pipeline_manifest.py --check
uv run --frozen python scripts/check_instruction_contract.py
patch --dry-run --batch --fuzz=0 -p1 -i .orchestra/tasks/V-1257/phase-b-specialist.patch
```

The app absolute import path is verified inside this workspace; its SHA-256 is
`8ef0a8cbe986782edfa305e6c8c4010ee8c4bc09bdd579390bc7d62f38af3dc2`.
The literal account path is not copied into tracked evidence. The final handoff
links the actual absolute local app file. No alternate interpreter substituted
for required checks; uv provisioned CPython 3.12.3 into default .venv.

Of 820 initial non-environment/non-cache files, exactly the five authorized source
paths changed; the other 815 remain byte-identical. All 47 V-1257 artifacts,
including all 21 logs, are byte-identical to arrival. The existing sanitized
public phase-a-integration.log and root private-original reference were retained;
the private original was not accessed or rewritten. Tests and guard source are
unchanged. Runtime fixture/cache scratch (50 MiB) was removed after completion.

Limits: full repository suite not run; sparse-copy root instruction contract is
red and needs complete-host validation by root (CLAUDE.md was absent on arrival).
The independent instruction script stops at the missing symlink, so downstream
real-root KB/link coverage remains unverified; its synthetic behavior tests pass.
No Phase B apply, real model execution, live registry/smoke, restart, deploy,
SSH/private DB, worker spawning/review, source publish, merge, commit or push.
Model/file transport operational readiness remains for root after normal idle
activation and a normal admitted specialist smoke. No broker import HEAD exists
in this no-.git copy; broker commits the returned files on task-V-1259/integrate-gemini.
