# V-1073 — containment patch and verification index

## Result and scope

The narrow public-code patch is ready for root acceptance on platform-managed `task-V-1073/fix-hub-data-file-filter`. Only supplied public source and invented fixtures were used. No private audit, real SSH/provider/service operation, paid API, auxiliary model, deployment, merge, push or restart was performed. Git actions inside invented test repositories were fixture setup only. CHANGELOG was handwritten. The approved permission follow-up changes only `app/hub_workspace.py`, its two regression modules and CHANGELOG; the remaining six delivered source/test files are hash-verified unchanged. All original and prior-follow-up stdout files remain verbatim.

`COMPANY-DATA.md` is excluded at root/nested depth, with mixed case and explicit ownership. `_under` still permits public root files. `blocked_reason` owns the narrow name rule; `write_tar` also refuses an accidentally supplied private path list before opening output. No broad numeric/PII detector or new general policy system was added.

Filtering only the new plan is unsafe: an old manifest would otherwise schedule the excluded path for deletion and lose its hash. Refresh/base reuse therefore check manifest, immutable `input_manifest` and hub-made evidence before diffing, dropping files or replacing baselines. `uploaded=False` is not evidence of remote absence: partial uploads are checked too. The exact broker copy is inspected by name only, returning a sentinel and no inventory/content; find/transport failures propagate. Base checks remain inside the existing lock. Root's synthetic mode-000 probe exposed that shell `test -e` treats EACCES like absence; two actual permission regressions reproduced this before the fix. The existence decision now uses stdlib `python3` `os.lstat`, allowing **only ENOENT** as missing. EACCES, ENOTDIR, ELOOP, interpreter failure and find/transport failure refuse; diagnostics give errno without filenames or contents. This requires `python3` on the hub; a missing interpreter fails closed. No additional package/API or general policy was added.

A separate `file_policy_blocked` boolean records detection without erasing hashes, manifests, provenance or thread identity. Persisted records are rechecked against stale in-memory objects. Provider starts, steers, model reconfiguration, no-work retries, provisioning and sync-back fail closed on retained evidence. Recorded contaminated workspaces refuse ordinary release before project deletion/history scrubbing. No automatic remediation or new sweep was added.

After removal of only a verified synthetic foreign duplicate, actual `_sync_back` and direct `apply_changes` refuse stale private-file provenance before absence can delete the LOCAL original. Both `uploaded` values are covered. Sync-back checks names before download; originals are preserved. `capture_inputs` also serves local `merge_inputs` and remains independent: unchanged local inputs keep their existing provenance behavior; changed/missing inputs still refuse. Credential, input, prompt and publication guards were not relaxed.

V-1064 transport-only recovery permits the added read-only name inspection and still forbids provider calls, provisioning, uploads and deletions. Its test now requires exactly two inspections plus two downloads across two recoveries and retains all original preservation assertions. Existing transport doubles were completed for the new operation. Production behavior was run through the real import/sync/provision paths with offline fake transports; the shell check was executed locally on synthetic fixture directories. No tests were weakened to fabricate missing source dependencies.

## Persisted-refusal boundary and supported continuation

**Even if an operator completes owner-approved deletion of all seven remote duplicates described by root, the current persisted refusal still prevents hub resume.** This worker did not inspect/remove those real copies. Removing a duplicate does not clear `file_policy_blocked`, old private manifest/input evidence, or the retained thread history. There is no automatic unlock, authorized-reset endpoint, history deletion or remediation implementation in this task.

A new hub thread/workspace ID for the **same worktree** is not a supported escape: `HubBackend._run_turn` checks all retained records for that worktree before creating/releasing a replacement (`app/backend_hub.py:454–499`). Workspace refusal is enforced at `app/hub_workspace.py:998–1001`; ordinary release checks it before deleting the project (`app/hub_workspace.py:1300–1322`). No supported clean-hub-replacement/remediation path preserving these records was found. Remaining remediation: root must review the exact current state and obtain/confirm owner permission for a separately designed evidence-preserving retirement/replacement lifecycle. That step is unimplemented and unexecuted; editing flags/manifests, deleting records, switching directories, or deleting history is not prescribed or authorized here.

There **is an existing native continuation route** for an idle worker: the normal `change_worker_model(name, model)` tool / `POST /api/sessions/{name}/change-model`, with a root-approved native target allowed by existing model/quota policy (`app/mcp_stdio.py:2417–2432`, `app/routes/sessions.py:2006–2036`). `AgentSession._change_model_locked` routes runtime changes to `_change_runtime_chat_locked` (`app/session.py:4278–4304`). It builds recent DB-chat handoff, disconnects the old backend, persists the native runtime and old-session reference before attempting old hub release; cleanup refusal is caught/logged and does not reverse the persisted switch (`app/session.py:3998–4082`). The blocked hub record/thread/provenance remains; the hub prohibition is not reset. This route carries recent chat and requires root to judge the destination/handoff appropriate; it is not a privacy audit or a promise about uninspected real history.

Specific proof: `HubSessionSwitchTests.test_normal_native_switch_preserves_incident_after_actual_policy_refusal` (`tests/test_hub_switch_orphan.py:313`) now calls ordinary public `change_model` with retained synthetic incident state and real `release_workspace`/`HubFilePolicyError`. It asserts the native saver snapshot precedes refusal, native runtime persists, prior/new session-history references remain, incident-record bytes/hashes/input provenance and both originals remain, and no hub provider/project/history call occurs. The existing generic cleanup-error test stays unchanged. Handoff/DB saving are fixture boundaries; no live switch or native provider turn is claimed. The four local-provenance cases (`tests/test_hub_file_policy_v1073.py:407`) also retain refusal while preserving unchanged/changed input checks.

## Final checks, prerequisites and unfinished work

Latest dedicated module plus actual incident native-switch test: **66 passed** (65 policy cases + 1 switch). Latest available combined suite: **421 passed, 4 deselected, 2 subtests passed**. Earlier 57/412 results remain indexed as prior-stage evidence. Actual shell permission tests assert an unprivileged UID; root-run CI drops only the fixture child to numeric UID/GID 65534 and accesses its fixture via an inherited FD, without changing outside ancestor permissions. Existing/missing leaves beneath mode 000 both refuse; genuine missing/clean/lost paths pass; ENOTDIR/ELOOP and unavailable probe interpreter refuse. This worker exercised the non-root branch; the root-UID drop branch remains unrun here and needs the host rerun. Mutation controls: 12, 3 and 4 passed; disabling filename/history/remote checks yielded respectively 11 failed + 1 passed, 3 failed, and 4 failed, all with expected exit 1 and regression assertions. Mutations run only in child Python processes, without editing production files.

Four existing cases require absent `.orchestra/pipelines/default/pipeline.yaml` or `.orchestra/pipelines/default/prompts/hub/worker.md`: `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`, `test_retarget_resolves_target_policy_and_claude_option`, and the two `test_hub_policy_matches_native_claude` cases. Their failures remain verbatim. Parent separately reported the previous host run: 416 passed + 2 subtests, instruction-contract PASS, filename mutant 11 failures and history mutant 4 failures; host raw logs were not supplied or fetched. Those are pre-permission-fix parent-reported results, not a claim of final host verification. Earlier mock/interface errors were fixed by completing doubles. The unfiltered final-source run also exposed the old V-1064 tar-only command assertion; after the documented update, the available suite passed. Only the four missing-source cases were deselected in that final run; no skip was added to their tests.

`scripts/run_tests.py` and `scripts/check_instruction_contract.py` are absent, so the complete-project runner and instruction-contract check remain **unrun**. Root must rerun the updated permission/native tests, all four missing-source cases and instruction contract, complete CI and final diff/commit acceptance in the full repository. No alternate runner is claimed as those required checks. This copy has no Git baseline metadata; root/platform own commit import, merge/push and live activation through the existing idle watcher. Real audit/remediation stays with root; erased historical evidence was not reconstructed.

Runner: provisioned **uv 0.11.28**, default `.venv`, locked dependencies; no alternate interpreter or lock replacement. Imported `app`: `/home/<private-identifier>/orchestra-ws/vmi3407579/hub-b9f6de676c8c405c/app/__init__.py`; exact Python/module paths are indexed in `import-check.txt`. Test shells used nice 15 and a 2 GiB virtual-memory limit. `TMPDIR` was this task's `tmp/`; only that generated synthetic fixture tree was removed. Existing public source and real-world copies/history were outside that cleanup.

## Exact commands (repository root)

Common prefix for each historical test/mutation shell; setup created the task `tmp/` first:

```bash
mkdir -p .orchestra/tasks/V-1073/tmp
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH" TMPDIR="$PWD/.orchestra/tasks/V-1073/tmp"
ulimit -v 2097152
```

The following commands retain exact test arguments and redirects; each ran after that shell setup. Commands shared by stages intentionally retain their separate raw outputs.

```bash
nice -n 15 uv run --frozen python -m pytest tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py tests/test_optional_worker_memory_v1069.py -q > .orchestra/tasks/V-1073/baseline-check.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py -q > .orchestra/tasks/V-1073/policy-check.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py -q > .orchestra/tasks/V-1073/focused-check.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py -q > .orchestra/tasks/V-1073/focused-recheck.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py tests/test_optional_worker_memory_v1069.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py -q > .orchestra/tasks/V-1073/final-regressions.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py tests/test_optional_worker_memory_v1069.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py -q > .orchestra/tasks/V-1073/final-source-check.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py tests/test_optional_worker_memory_v1069.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py -q -k 'not test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools and not test_retarget_resolves_target_policy_and_claude_option and not test_hub_policy_matches_native_claude' > .orchestra/tasks/V-1073/available-regressions.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py -q > .orchestra/tasks/V-1073/policy-final.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py::test_actual_shell_unreadable_parent_is_not_missing tests/test_hub_file_policy_v1073.py::test_actual_shell_missing_and_clean_copies_stay_allowed tests/test_hub_switch_orphan.py::HubSessionSwitchTests::test_normal_native_switch_preserves_incident_after_actual_policy_refusal -q > .orchestra/tasks/V-1073/permission-before-fix.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_hub_switch_orphan.py tests/test_hub_download_v1064.py -q > .orchestra/tasks/V-1073/permission-native-check.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py tests/test_optional_worker_memory_v1069.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py -q -k 'not test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools and not test_retarget_resolves_target_policy_and_claude_option and not test_hub_policy_matches_native_claude' > .orchestra/tasks/V-1073/permission-final-regressions.txt 2>&1
nice -n 15 uv run --frozen python -m pytest tests/test_hub_file_policy_v1073.py tests/test_hub_switch_orphan.py::HubSessionSwitchTests::test_normal_native_switch_preserves_incident_after_actual_policy_refusal -q > .orchestra/tasks/V-1073/permission-final-focused.txt 2>&1
nice -n 15 uv run --frozen python .orchestra/tasks/V-1073/verify_mutations.py > .orchestra/tasks/V-1073/mutation-check.txt 2>&1
nice -n 15 uv run --frozen python .orchestra/tasks/V-1073/verify_permission_mutation.py > .orchestra/tasks/V-1073/permission-mutation-check.txt 2>&1
```

Identity check (same PATH/default venv; `uv --version` and Python output were combined in `import-check.txt`):

```bash
uv --version
uv run --frozen python -c 'from pathlib import Path; import sys, app, app.hub_workspace; print("python=" + sys.executable); print("app=" + str(Path(app.__file__).resolve())); print("hub_workspace=" + str(Path(app.hub_workspace.__file__).resolve()))'
```

Source-prerequisite check used `uv run --frozen python -` with this stdin, stdout to `source-prerequisites.txt`:

```python
from pathlib import Path
for relative in ('.orchestra/pipelines/default/pipeline.yaml', '.orchestra/pipelines/default/prompts/hub/worker.md', 'scripts/run_tests.py', 'scripts/check_instruction_contract.py'):
    print(f'{relative}: {"present" if Path(relative).is_file() else "absent from supplied copy"}')
```

Fixture cleanup used `uv run --frozen python -`, stdout to `fixture-cleanup.txt`; only these operations ran:

```python
from pathlib import Path
import shutil
fixture_tree = Path('.orchestra/tasks/V-1073/tmp')
assert fixture_tree.resolve() == fixture_tree.absolute()
assert not fixture_tree.is_symlink()
shutil.rmtree(fixture_tree)
print('Removed only .orchestra/tasks/V-1073/tmp: generated synthetic test fixtures.')
```

The same fixture-only cleanup is repeated after the permission follow-up, with new stdout in `permission-fixture-cleanup.txt`; the original cleanup log is unchanged.

Original hygiene check: `uv run --frozen python .orchestra/tasks/V-1073/finalize_report.py`; it parsed 11 Python source/artifact files and scanned 27 explicit source/task artifacts using existing publication credential shapes, with zero findings and no credential-inventory lookup. Its original output remains `hygiene-check.txt`. The report builder retains the old `report-reformat-check.txt` and uses `reformat-preservation.json` plus `permission-followup-preservation.json` to verify original stdout hashes and the six source files outside the approved follow-up. It writes current hygiene/source hashes to `permission-report-check.txt`; the permission/native behavioral runs below were executed separately with provisioned uv.

## Exact 1-based stdout index (complete bodies stay in the linked files)

All existing stdout files below are retained byte-for-byte, including intermediate failures; no log bodies are duplicated here. Full-file intervals include progress, diagnostics and results. Original line counts and SHA-256 values are retained in both preservation manifests and verified on rebuild.

| File | Complete lines | Result / precise detail index |
| --- | --- | --- |
| [baseline-check.txt](baseline-check.txt) | L1–L111 | 3 failed, 329 passed in 115.53s (0:01:55); incomplete old doubles + missing prompt; details L9–L106; summary L107–L111 |
| [policy-check.txt](policy-check.txt) | L1–L2 | 47 passed in 9.50s; 47 passed at that implementation stage; result L2 |
| [focused-check.txt](focused-check.txt) | L1–L493 | 15 failed, 128 passed in 11.64s; incomplete lifecycle doubles + missing pipeline; details L3–L476; summary L477–L493 |
| [focused-recheck.txt](focused-recheck.txt) | L1–L152 | 3 failed, 140 passed, 2 subtests passed in 13.38s; missing pipeline only; details L4–L147; summary L148–L152 |
| [final-regressions.txt](final-regressions.txt) | L1–L175 | 4 failed, 406 passed, 2 subtests passed in 122.36s (0:02:02); missing source only; details L7–L169; summary L170–L175 |
| [final-source-check.txt](final-source-check.txt) | L1–L234 | 5 failed, 411 passed, 2 subtests passed in 127.55s (0:02:07); four missing-source cases + old tar-only assertion; details L7–L227; summary L228–L234 |
| [available-regressions.txt](available-regressions.txt) | L1–L7 | 412 passed, 4 deselected, 2 subtests passed in 126.08s (0:02:06); final available suite; result L7 |
| [policy-final.txt](policy-final.txt) | L1–L2 | 57 passed in 12.05s; final dedicated module; result L2 |
| [permission-before-fix.txt](permission-before-fix.txt) | L1–L64 | 2 failed, 4 passed in 2.86s; exact old permission defect reproduced before the fix; details L2–L60; summary L61–L64 |
| [permission-native-check.txt](permission-native-check.txt) | L1–L3 | 90 passed, 2 subtests passed in 17.18s; first permission/native/recovery validation; result L3 |
| [permission-final-regressions.txt](permission-final-regressions.txt) | L1–L7 | 421 passed, 4 deselected, 2 subtests passed in 152.21s (0:02:32); final available suite after permission fix; result L7 |
| [permission-final-focused.txt](permission-final-focused.txt) | L1–L2 | 66 passed in 16.44s; final dedicated policy plus actual incident native switch; result L2 |
| [import-check.txt](import-check.txt) | L1–L4 | L1 uv version; L2 Python; L3 absolute app import; L4 hub_workspace import |
| [source-prerequisites.txt](source-prerequisites.txt) | L1–L4 | L1–L2 missing pipeline/prompt; L3–L4 missing complete-suite/contract scripts |
| [fixture-cleanup.txt](fixture-cleanup.txt) | L1–L1 | L1 exact synthetic-only cleanup result |
| [hygiene-check.txt](hygiene-check.txt) | L1–L3 | L1 parsing; L2 scan count; L3 zero findings/no private inventory |
| [mutation-check.txt](mutation-check.txt) | L1–L445 | phase index below; L445 overall expected-outcome confirmation |
| [report-reformat-check.txt](report-reformat-check.txt) | L1–L5 | L1–L5 previous documentation-only verification, retained unchanged |
| [permission-mutation-check.txt](permission-mutation-check.txt) | L1–L74 | new old-predicate mutation; precise phase/result index below |
| [permission-fixture-cleanup.txt](permission-fixture-cleanup.txt) | L1–L1 | L1 exact synthetic-only cleanup after the follow-up tests |

Mutation phase index, all in `mutation-check.txt`: filename control **L2–L6**, mutant **L7–L244** (assertion diagnostics L9–L229, summary L230–L243); retained-history control **L245–L249**, mutant **L250–L352** (diagnostics L252–L345, summary L346–L351); remote-name control **L353–L357**, mutant **L358–L444** (diagnostics L360–L436, summary L437–L443). The script's labels give each exact in-process mutation; every control exits 0 and each mutant exits the expected 1. No production file mutation occurred.

Latest permission mutation: [permission-mutation-check.txt](permission-mutation-check.txt), control **L2–L6**, old `test -e` mutant **L7–L73**, overall confirmation **L74**. Control passes all five permission/allowed-path cases; the exact old predicate yields **2 failed, 3 passed**, both failures at real mode-000 assertions. Only child-process method replacement is used; no production source is mutated.

## Current source hashes (pre-follow-up hashes remain in the preservation manifests)

- `app/hub_workspace.py`: `0cd60215fdbecd3a45cd03f88416908d90408c38a7a2706a23543553bf442901`
- `app/backend_hub.py`: `12e948ea4583b4df65bb5d9d6e2f8a2a0a79c14b9852c4e633b13034de8c75ff`
- `tests/test_hub_file_policy_v1073.py`: `f464a24fac8068ed8782d727b231262bfa6f8a4d5db05537325f03b3822aa493`
- `tests/test_hub_workspace.py`: `be86111d51f653f8d901354d3a2eabf2e355b50a5f89af38beed65ec52e16274`
- `tests/test_backend_hub.py`: `51f1d2d5cb6d4f9ab7b36129a7d6c688f8d1ff16504b6ec08e496ee7d8219a41`
- `tests/test_hub_uv.py`: `07194e68c12c3f3a3493868f4016d5e9422aef18f8a6990610b14fa3bc939340`
- `tests/test_hub_effort.py`: `f331bd331576ceb3804598aad42efca6eed57c78b489a939dd78ca3b92dd5a75`
- `tests/test_hub_switch_orphan.py`: `ed19d3ed11fbe70790fcd743ba6f6f7f3e1c5057e56e4cf319cd9e7d5c1d509b`
- `tests/test_hub_download_v1064.py`: `175bc730b21bd674fe8fc12f450fe2ebef0e366e5b79db4d644d68e14c5fe4e9`
- `CHANGELOG.md`: `9dde47e6ac8c8e0c30a799a4e496ab24962372be26d0ea59c828b9fb990d8af7`

Additional context: [notes.md](notes.md). Historical reformat check: [report-reformat-check.txt](report-reformat-check.txt), **L1–L5**, retained unchanged. Current follow-up check: [permission-report-check.txt](permission-report-check.txt), **L1–L5**. Only four approved source/test/CHANGELOG files changed; raw stdout remains intact. Persisted refusal, no-remediation and idle-watcher activation boundaries remain unchanged.

## Root host acceptance and publication boundary
Root read this entire compact report and all production/test diffs. Final complete-source selection:425passed,2subtests, instructioncontractPASS; app /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-hub-data-file-filter/app/__init__.py. Independent old filename/history/permission mutants fail11/4/2committed cases respectively; production files never edited by mutations. Real non-root permission paths passed; root-UID-drop branch was not run here because sudo refused NoNewPrivileges, with no bypass attempted. Original worker stdout and report are retained privately; public log/report copies replace forbidden runtime identifiers with `<private-identifier>` and are NOT verbatim originals. Historical preservation manifests/hash checks describe the original worker artifacts before publication redaction; publication-redactions.json identifies the affected public copies. Actual PD audit/remote cleanup are separate and no deletion authorization has been received. Persisted hub refusal intentionally remains after duplicate removal; native switch path is tested without actual provider. LivePython requires existingidlewatcher; no manualrestart.
