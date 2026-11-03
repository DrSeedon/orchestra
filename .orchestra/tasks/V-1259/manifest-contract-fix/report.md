# V-1259 — DONE: Phase B manifest/prompt contract resolved

Only the new V-1257 paragraph in `.orchestra/pipelines/default/prompts/modules/model-routing.md` changed: three lines replaced.
The prompt now refers to the model configured by the `specialist` role in the
default pipeline manifest, while keeping exact external Hub provider/model
`antigravity/gemini-4-argon`. The manifest owns internal versioned model IDs;
runtime guards still own admission. No checker/allowlist, app/registry/backend,
alias/schema, test, role or manifest edits in this follow-up. All owner dates and
scope, funding/privacy/quota/task/project identity, history/recovery and staged
activation boundaries are byte-identical outside those three lines.

| Source evidence | SHA-256 |
|---|---|
| Before this prompt fix | `e71535084b1c6f2e1f4c712df9ee49a942bc2b066780aedb3209022f1afab1c4` |
| Final model-routing.md | `7c5e7412bdef52c731fb7b4e625b1dd4476f739d4f32a7cea4eb174dd6ec4de1` |
| Exact public b9 canonical model-routing.md | `11f1eb940f5308637bcc478fbae80acd00d605ca4198b4dbd0f0a05aab077475` |
| Actual Phase A manifest (untouched) | `69af96dc84e32751257824e8cdbad493a63d9126e88d3268a304c132363a8df6` |
| Actual temporary Phase B manifest tested, then exactly restored | `7af87574909ff66a8e99b915bfe7f4a912fa0cdefa5ad9207da6a788713c9493` |

Review delta: one-prompt-fix.patch. Full final prompt vs pinned public
`b9d893ec8babd4b2052ac1f497962e1966206bcb`: canonical-b9-to-final.patch;
canonical-source.json supplies URL and validated SHA. All relevant app/registry/
backend/pipeline/prompt/test/checker/lock source hashes: final-source-shas.json.

| Fresh completed offline check | Actual result | Evidence |
|---|---|---|
| Phase A actual Sol manifest: same affected and available contract test paths | 149 passed, 34.6 s, exit 0 | phase-a-pytest.log |
| Phase B actual temporary Argon manifest: same paths | 149 passed, 43.7 s, exit 0 | phase-b-pytest.log |
| Static manifest/prompt contract on actual Phase A | PASS, exit 0 | phase-a-pipeline-contract.log |
| Static manifest/prompt contract on actual temporary Phase B | PASS, exit 0 | phase-b-pipeline-contract.log |
| Unchanged Phase B patch dry-run, fuzz=0 | PASS, exit 0 | phase-b-dry-run.log |
| Six frozen V-1256 delivery cases, 2 roles × 3 modules | Unchanged; all six collected and passed in BOTH runs | phase-a-evidence.json, phase-b-evidence.json |
| Temporary tree and process pipeline pointer restored to Phase A | PASS; root manifest bytes/inode/mtime/size never changed | phase-b-evidence.json |
| Actual-root instruction contract | RED, exit 1: supplied copy lacks CLAUDE.md | instruction-contract.log |
| All other initial source/context files | 819 byte-identical | before-manifest.json, verification.json |
| Previous task artifacts, including all red and 625/149 logs | 102 byte-identical | prior-artifacts-manifest.json |

No failed/skipped cases in these completed runs. Static Phase B now passes the
same unchanged canonical checker that previously rejected the copied internal ID.
Earlier red Phase B/pretest/root-instruction checks are preserved, not rewritten.
Root instruction checking still stops at the absent CLAUDE.md; complete-host
instruction/KB/link validation remains root's responsibility. No fabricated link.

Provisioned uv 0.11.28, default .venv, exact workspace app import, UV_OFFLINE=1
during tests, synthetic fixtures and process-local test Git identity. Serial,
nice=10/OOM score=1000, finite 180-second outer bound per test command. Repeated
only the same affected paths because the assembled routing prompt changed; no
full 625 repeat or full repository suite. The reused task-local plugin was copied
without changing its prior accepted version or prior evidence. It redirects only
the test process to a copied pipeline tree for Phase B, loads exact Argon before
tests, runs the real static checker on that manifest, and restores the tree and
pointer exactly afterward. Root source was never patched for Phase B.

Commands (in each test shell):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
# Set task-local TMPDIR and PYTHONPATH to this manifest-contract-fix directory;
# UV_OFFLINE=1, PYTHONDONTWRITEBYTECODE=1, synthetic Git identity, no NOTIFY_SOCKET.
# Each pytest command ran with timeout 180s nice -n 10:
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=A --basetemp=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/pytest-a -o cache_dir=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/cache-a
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=B --basetemp=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/pytest-b -o cache_dir=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/cache-b
uv run --frozen python .orchestra/tasks/V-1259/manifest-contract-fix/finish.py
# Plugin runs with the same .venv Python and the actual selected manifest:
uv run --frozen python scripts/check_pipeline_manifest.py --check --manifest <phase-manifest>
# Phase B patch commands run ONLY in task-local copied source:
patch --dry-run --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
patch --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
uv run --frozen python scripts/check_instruction_contract.py
```

Absolute app import was asserted as this exact workspace's app/__init__.py;
its absolute path SHA is `8ef0a8cbe986782edfa305e6c8c4010ee8c4bc09bdd579390bc7d62f38af3dc2`.
The handoff links the actual local app file. Task-owned test scratch was removed.
Artifact form-secret scan uses app.secret_mask without reading secret inventories.

Returned SOURCE integration is coherent for both phases; source is not merged or
activated. This copy has no .git and invents no new imported SHA; broker owns
committing the returned file. Root owns merge/complete-host instruction checking,
normal idle activation, live registry verification and admitted specialist smoke.
No real model/Hub turn, SSH/private DB, new worker/review, restart/deploy, Phase B
hot apply, paid calls, publication, git commit/push or live-state writes occurred.
