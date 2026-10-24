"""Build a compact report, preserving and line-indexing every original stdout file."""
from pathlib import Path
import ast
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
NOTES = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.publication_secrets import HUB_SECRET_SHAPES

PRESERVATION = json.loads((NOTES / 'reformat-preservation.json').read_text())
FOLLOWUP = json.loads((NOTES / 'permission-followup-preservation.json').read_text())
SOURCE = tuple(PRESERVATION['source_sha256_before'])


def verify_unchanged():
    for relative, expected in PRESERVATION['source_sha256_before'].items():
        if relative not in FOLLOWUP['allowed_source_changes']:
            assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    for filename, expected in FOLLOWUP['completed_stdout_before_followup_report'].items():
        data = (NOTES / filename).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected['sha256'], filename
        assert len(data.splitlines()) == expected['lines'], filename


verify_unchanged()
BASE = ('tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py '
        'tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py '
        'tests/test_hub_download_v1064.py tests/test_hub_message_v1066.py '
        'tests/test_optional_worker_memory_v1069.py')
POLICY = 'tests/test_hub_file_policy_v1073.py'
FOCUSED = POLICY + ' tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_effort.py tests/test_hub_switch_orphan.py'
FULL = POLICY + ' ' + BASE + ' tests/test_hub_effort.py tests/test_hub_switch_orphan.py'
EXCLUDE = ('not test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools and '
           'not test_retarget_resolves_target_policy_and_claude_option and '
           'not test_hub_policy_matches_native_claude')
RUNS = (
    ('baseline-check.txt', BASE, '', '3 failed; 329 passed; incomplete old doubles + missing prompt'),
    ('policy-check.txt', POLICY, '', '47 passed at that implementation stage'),
    ('focused-check.txt', FOCUSED, '', '15 failed; 128 passed; incomplete lifecycle doubles + missing pipeline'),
    ('focused-recheck.txt', FOCUSED, '', '3 failed; 140 passed; 2 subtests passed; missing pipeline only'),
    ('final-regressions.txt', FULL, '', '4 failed; 406 passed; 2 subtests passed; missing source only'),
    ('final-source-check.txt', FULL, '', '5 failed; 411 passed; 2 subtests passed; four missing-source cases + old tar-only assertion'),
    ('available-regressions.txt', FULL, " -k '" + EXCLUDE + "'", '412 passed; 4 deselected; 2 subtests passed; final available suite'),
    ('policy-final.txt', POLICY, '', '57 passed; final dedicated module'),
    ('permission-before-fix.txt', POLICY + '::test_actual_shell_unreadable_parent_is_not_missing '
     + POLICY + '::test_actual_shell_missing_and_clean_copies_stay_allowed '
     + 'tests/test_hub_switch_orphan.py::HubSessionSwitchTests::test_normal_native_switch_preserves_incident_after_actual_policy_refusal',
     '', '2 failed; 4 passed; exact old permission defect reproduced before the fix'),
    ('permission-native-check.txt', POLICY + ' tests/test_hub_switch_orphan.py tests/test_hub_download_v1064.py',
     '', '90 passed; 2 subtests passed; first permission/native/recovery validation'),
    ('permission-final-regressions.txt', FULL, " -k '" + EXCLUDE + "'", 'final available suite after permission fix'),
    ('permission-final-focused.txt', POLICY + ' tests/test_hub_switch_orphan.py::HubSessionSwitchTests::test_normal_native_switch_preserves_incident_after_actual_policy_refusal',
     '', 'final dedicated policy plus actual incident native switch'),
)


def span(filename):
    return f'L1–L{len((NOTES / filename).read_bytes().splitlines())}'


def details(filename):
    lines = (NOTES / filename).read_text().splitlines()
    failures = next((i for i, line in enumerate(lines, 1) if line.startswith('===') and 'FAILURES' in line), None)
    short = next((i for i, line in enumerate(lines, 1) if line.startswith('===') and 'short test summary info' in line), None)
    if failures is not None and short is not None:
        return f'details L{failures}–L{short - 1}; summary L{short}–L{len(lines)}'
    return f'result L{len(lines)}'


text = '''# V-1073 — containment patch and verification index

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

Runner: provisioned **uv 0.11.28**, default `.venv`, locked dependencies; no alternate interpreter or lock replacement. Imported `app`: `@APP_IMPORT_PATH@`; exact Python/module paths are indexed in `import-check.txt`. Test shells used nice 15 and a 2 GiB virtual-memory limit. `TMPDIR` was this task's `tmp/`; only that generated synthetic fixture tree was removed. Existing public source and real-world copies/history were outside that cleanup.

## Exact commands (repository root)

Common prefix for each historical test/mutation shell; setup created the task `tmp/` first:

```bash
mkdir -p .orchestra/tasks/V-1073/tmp
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH" TMPDIR="$PWD/.orchestra/tasks/V-1073/tmp"
ulimit -v 2097152
```

The following commands retain exact test arguments and redirects; each ran after that shell setup. Commands shared by stages intentionally retain their separate raw outputs.

```bash
'''
for filename, paths, extra, _ in RUNS:
    text += f'nice -n 15 uv run --frozen python -m pytest {paths} -q{extra} > .orchestra/tasks/V-1073/{filename} 2>&1\n'
text += '''nice -n 15 uv run --frozen python .orchestra/tasks/V-1073/verify_mutations.py > .orchestra/tasks/V-1073/mutation-check.txt 2>&1
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
'''
for filename, _, _, result in RUNS:
    actual_summary = (NOTES / filename).read_text().splitlines()[-1]
    text += f'| [{filename}]({filename}) | {span(filename)} | {actual_summary}; {result.split("; ")[-1]}; {details(filename)} |\n'
for filename, summary in (
    ('import-check.txt', 'L1 uv version; L2 Python; L3 absolute app import; L4 hub_workspace import'),
    ('source-prerequisites.txt', 'L1–L2 missing pipeline/prompt; L3–L4 missing complete-suite/contract scripts'),
    ('fixture-cleanup.txt', 'L1 exact synthetic-only cleanup result'),
    ('hygiene-check.txt', 'L1 parsing; L2 scan count; L3 zero findings/no private inventory'),
    ('mutation-check.txt', 'phase index below; L445 overall expected-outcome confirmation'),
    ('report-reformat-check.txt', 'L1–L5 previous documentation-only verification, retained unchanged'),
    ('permission-mutation-check.txt', 'new old-predicate mutation; precise phase/result index below'),
    ('permission-fixture-cleanup.txt', 'L1 exact synthetic-only cleanup after the follow-up tests'),
):
    text += f'| [{filename}]({filename}) | {span(filename)} | {summary} |\n'
text += '''
Mutation phase index, all in `mutation-check.txt`: filename control **L2–L6**, mutant **L7–L244** (assertion diagnostics L9–L229, summary L230–L243); retained-history control **L245–L249**, mutant **L250–L352** (diagnostics L252–L345, summary L346–L351); remote-name control **L353–L357**, mutant **L358–L444** (diagnostics L360–L436, summary L437–L443). The script's labels give each exact in-process mutation; every control exits 0 and each mutant exits the expected 1. No production file mutation occurred.

'''
permission_lines = (NOTES / 'permission-mutation-check.txt').read_text().splitlines()
mutant_start = next(i for i, line in enumerate(permission_lines, 1) if line == 'old test-e predicate mutant')
text += (f'Latest permission mutation: [permission-mutation-check.txt](permission-mutation-check.txt), '
         f'control **L2–L{mutant_start - 1}**, old `test -e` mutant **L{mutant_start}–L{len(permission_lines) - 1}**, '
         f'overall confirmation **L{len(permission_lines)}**. Control passes all five permission/allowed-path cases; '
         'the exact old predicate yields **2 failed, 3 passed**, both failures at real mode-000 assertions. '
         'Only child-process method replacement is used; no production source is mutated.\n\n')
text += '## Current source hashes (pre-follow-up hashes remain in the preservation manifests)\n\n'
for relative in SOURCE:
    digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    text += f'- `{relative}`: `{digest}`\n'
text += '''
Additional context: [notes.md](notes.md). Historical reformat check: [report-reformat-check.txt](report-reformat-check.txt), **L1–L5**, retained unchanged. Current follow-up check: [permission-report-check.txt](permission-report-check.txt), **L1–L5**. Only four approved source/test/CHANGELOG files changed; raw stdout remains intact. Persisted refusal, no-remediation and idle-watcher activation boundaries remain unchanged.
'''
text = text.replace("@APP_IMPORT_PATH@", str(ROOT / "app" / "__init__.py"))
report = NOTES / 'report.md'
report.write_text(text)
# Restrict checks to explicit public source and this task's top-level artifacts.
artifacts = [p for p in NOTES.iterdir() if p.is_file() and p.suffix in {'.md', '.txt', '.py', '.json'}]
files = [ROOT / relative for relative in SOURCE] + artifacts
python_files = [p for p in files if p.suffix == '.py']
for path in python_files:
    ast.parse(path.read_text(), filename=str(path))
for path in files:
    for label, pattern in HUB_SECRET_SHAPES:
        if pattern.search(path.read_text()):
            raise SystemExit(f'{path.relative_to(ROOT)}: {label}')
verify_unchanged()
assert len(text.splitlines()) <= 190
assert len(text.encode()) <= 26_000
changed = [p for p in SOURCE if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != PRESERVATION['source_sha256_before'][p]]
assert set(changed) <= set(FOLLOWUP['allowed_source_changes'])
result = (f'Approved source/test/CHANGELOG files changed: {len(changed)}; other {len(SOURCE) - len(changed)} hashes unchanged.\n'
          f'Prior completed stdout files retained byte-for-byte with verified line counts: {len(FOLLOWUP["completed_stdout_before_followup_report"])}.\n'
          f'Parsed Python source/artifact files: {len(python_files)}. Credential-shape findings: 0.\n'
          f'Compact report: {len(text.splitlines())} lines, {len(text.encode())} UTF-8 bytes.\n'
          'Permission/native follow-up tested; no real provider, audit, deployment, remediation or runtime activation.\n')
(NOTES / 'permission-report-check.txt').write_text(result)
print(result, end='')
