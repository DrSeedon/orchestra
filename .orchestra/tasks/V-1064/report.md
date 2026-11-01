# V-1064 implementation: bounded return packaging and recovery proof

Status: implementation DONE on the supplied source copy; result branch
`task-V-1064/fix-hub-download` is imported/committed by the platform after this turn.
Final affected checks are green; four broad-check environment/naming failures are
listed below. No claim of a fully green 38-module run is made.

Implementation scope: Orchestra source and offline synthetic tests only. No hub
connection, real service credentials, deployment, restart, other-project change,
remote cleanup, new workspace, provider/model turn or new API was performed here.
The platform imports/commits this worker's changes after the turn; this copy has no
`.git` and the worker did not run git commit/push/clone for its own result.

## Result and invariant boundaries

- `HubSsh.get` derives exact directory-name exclusions from existing `BLOCKED_DIRS`
  and applies them at every depth. No `.gitignore` blanket exclusion is introduced.
  GNU tar's `--exclude-tag=pyvenv.cfg` omits custom environment contents and carries
  the marker so existing import validation can preserve legacy environment entries.
- Import validation also treats omitted name-blocked directories as excluded,
  never as an instruction to delete old manifest files. Existing dangerous-snapshot
  deletion detection and input SHA/provenance/collision checks are unchanged.
- `HubSsh.run` bounds the temporary download during receipt rather than writing an
  unlimited file and checking afterwards. An overflow reports the observed lower
  bound and limit; `get` adds the retained workspace ID. The exact oversized full
  archive length is deliberately not claimed after stopping the stream. Successful
  sync reports its exact archive length and transport limit. Timeout, cancellation,
  failed SSH/tar and local-write errors reap the local process and never apply a
  failed/partial download.
- A sync failure is visible both in the reply and failed turn status. Existing
  provider-limit reporting retains precedence when a provider failure also exists.
- No limit was raised or disabled: default return transport is still 629,145,600
  bytes (2 × 300 MiB); import limits remain 20 MiB per file and 300 MiB changed
  payload. Credential filename/content checks remain at the validator. No new
  paid route, dependency or external interface was added.
- `tmp`, SDKs, ZIP/tar files, `.rep` projects, media, results and input originals
  are not newly excluded. The new test explicitly carries representative SDK,
  `tmp/ghidra-early.rep/idata/annotations`, source/results/report/media and an env
  example through the real return command.

## Synthetic evidence

`synthetic-evidence.json` gives measured bytes and returned members, not a live
archive estimate. The reproduction scales the transport cap down to 131,072 bytes
without changing production policy. The old command overflows on nested blocked
caches; the new command fits and imports all allowed outputs. Original synthetic
remote cache files remain intact. A genuinely oversized allowed media output still
refuses twice, keeps canonical state and HEAD unchanged, and deletes no remote or
local original. Exact-limit/one-byte-over, timeout, cancellation, failed local write,
failed tar, truncated archive and symlink non-dereference cases are covered.

The direct existing `_sync_back` proof loads a persisted workspace record, imports
current source, result, task report and video, makes exactly one commit, and repeats
with zero changed/deleted files and no second commit. Provider/client, normal send,
connect/start/provision, UV provisioning, upload refresh and remote deletion methods
are guarded to fail if invoked. Upload-origin originals remain byte-identical and
untracked with their immutable input manifest preserved. This proves recovery from
a transport failure before import; general crash/failed-commit transaction repair
is outside this task. The established sync counter still increments on a no-op sync.

`recovery.md` documents the concrete parent-only internal invocation, service auth
context and state/worktree/branch/HEAD/project/thread/run identity checks. No new
retry tool or endpoint is needed. A nonempty outbox stops that maintenance recipe
before `_sync_back` can consume/delete it. The recipe was not run against the hub;
live recovery has already succeeded by the independent operation below.

## Live incident attribution (parent-supplied evidence, not this worker's measurement)

The former return archive's exact size/composition was not measured here. The
parent reports that Seedon's inventory measured 2,199,133,379 logical regular-file
bytes before cleanup; this is not an archive length. Much of it was legitimate
SDK material under `tmp`: extracted Ghidra+JDK 1,142,268,179 bytes, `ghidra.zip`
456,633,878 and `jdk.tar.gz` 207,858,352. These names are not in BLOCKED_DIRS and this
fix does not exclude them. Seedon verified 6,418 SDK files against archives and
removed only reproducible copies independently; the worker here did none of that.

Seedon also removed 65,813,677 `.venv` bytes and 24,827 bytecode/cache bytes; no npm
or browser cache was found. The subsequent checkout was 332,820,384 logical bytes /
5,876 regular files. A gzip archive measured 160,105,389 bytes before the final
report, but the broker return transport is uncompressed. Unique
`tmp/ghidra-early.rep` analysis data (141,870,119 bytes), 904 original inputs totaling
96,898,193 bytes, browser checks (49,389,388 bytes, including MP4 48,455,107), assets
9,656,949 and other repository context 13,237,643 were retained. Directory totals do
not establish the largest individual file or override existing import limits.

The parent subsequently confirmed that Seedon's independently verified cleanup
and NORMAL sync restored the incident: local HEAD
`a3d8d02f6b63a223fdb2439f82b207973fecc77d`, tracked-clean, code/media/return-audit
imported, 28 Node checks and 904 input SHA checks repeated by Seedon. This recovery
was not caused by this patch or its transport-only recipe. The existing old remote
`hub-0cabf759f930454a` was not accessed, cleaned or replaced by this worker.

## Verification

The provisioned broker runner was used throughout:
`$HOME/.local/share/orchestra/tools/uv/0.11.28/bin/uv` (0.11.28), default `.venv`,
locked dependencies, tests offline. No replacement interpreter/lock was used.
Heavy test runs were serial, `nice -n 15`, with a 2 GiB process address-space cap
(`ulimit -v 2097152`). A cgroup MemoryMax was not configured from this private copy.
`TMPDIR` and pytest `--basetemp` point inside this task's own directory; existing
publication fixtures also create and clean their own repository-local sandboxes.

The imported app was measured as an absolute path and normalized for publication:
`/remote/workspace/app/__init__.py`. Remote/account prefixes in logs are normalized
to `/remote/workspace`; credential-shaped material is checked before publication.

The main initial hub run passed **203 tests**. The broad 38-module guard run returned
**818 passed, 6 failed, 21 subtests passed, 2 warnings**, in 507.04 s. Exact selected
paths are in `test-selection.txt` and the full output is `guards.log`. It includes hub_workspace,
backend_hub, hub_uv, hub_inputs V-1062/V-1063, publication, workspace, all supplied
merge/diff guards and hub callers such as hub_image. Existing acceptance tests were
not edited or weakened. The full repository suite was not run.

Two broad-run failures exposed cleanup/timeout issues in the initial implementation
and were fixed before the final verification: ordinary command cancellation now
waits for the killed process without invoking a second `communicate`; timeout is
converted to `HubWorkspaceError` before the generic `OSError` rethrow (Python's
`TimeoutError` subclasses `OSError`). The final rerun covers both cases and real
streaming timeout/cancellation/local-disk-error process cleanup.

The four remaining broad-run failures are outside this approved fix and were not
hidden by editing or weakening their tests:

1. `tests/test_merge_test_gate.py::test_ci_pytest_does_not_stop_at_first_failure`:
   copied source dependency `.github/workflows/ci.yml` is absent; opening it raises
   `FileNotFoundError`. CI configuration verification requires the real checkout.
2. `tests/test_merge_test_gate.py::test_run_pytest_isolates_live_state_environment`:
   the test hardcodes `ORCHESTRA_DB_PATH.startswith("/tmp/")`; this worker must use
   a repository-local TMPDIR. The actual path is under
   `/remote/workspace/.orchestra/tasks/V-1064/tmp/orchestra-merge-gate-*/orchestra.db`,
   not the mocked production DB. Later assertions in that test remain unverified.
3. `tests/test_merge_test_gate.py::test_orchestra_worktree_is_detected_by_git_common_dir`:
   the supplied source copy intentionally has no root `.git`; the test expects its
   root to be an actual Orchestra Git worktree. This needs a real worktree to pass.
4. `tests/test_workspace.py::TestCreateWorktree::test_different_repos_no_collision`:
   the known long-TMPDIR 80-character slug collision maps both synthetic repositories
   to the same worker directory and raises `ValueError: worktree already exists`.
   The task explicitly excludes fixing that unrelated naming defect.

No alternate interpreter, invented CI file, new root Git repository, external
temporary directory or weakened test was used to make these four checks green.
Parent acceptance should rerun the guard selection in the authoritative checkout
with its normal short temporary paths. No new dependency-import failures occurred.

Final required affected rerun: **323 passed, 19 subtests passed**, no failures or
warnings, in **99.49 s** (`final-hub.log`). Exact command (with the provisioned
runner on PATH, task-local TMPDIR and basetemp, serial nice/address-space limits):

```sh
uv run --frozen python -m pytest tests/test_hub_download_v1064.py tests/test_hub_workspace.py tests/test_backend_hub.py tests/test_hub_uv.py tests/test_hub_image.py tests/test_hub_inputs_v1062.py tests/test_hub_inputs_v1063.py tests/test_publication_gate_v1047.py -q -m 'not live_probe' --timeout=90 --basetemp="$TMPDIR/hub"
```

The final new tests additionally assert that allowed `tmp` SDK/project/archive
paths survive packaging. The synthetic byte inventory was refreshed from that
final run. Source and normalized task artifacts were scanned by the existing
`scripts.secret_scan.scan_text`; the final scan result is `publication-scan.log`.
Only this worker's generated local test sandboxes were removed before export;
all source/tests/reports and full normalized run logs remain. The copy has no Git
metadata for a local `git diff`; the changed transport, sync error handling,
legacy-preservation logic, new tests and CHANGELOG entry were inspected directly.

## Host acceptance — 2026-10-24

The entire reported 38-module selection passed on the VPS: 825 tests, 21 subtests, 2 existing multiprocessing warnings, 121.08 s. Imported app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-hub-download/app/__init__.py`. Raw host output is retained privately in `.orchestra/private/V-1064/host-tests.txt`. No exclusions were added for the four worker-copy limitations; all those cases ran in the real checkout.

My independent mutations removed the return-directory exclusions and disabled propagation of sync failure. Each made its intended committed behavioral test fail, with no collection/import failure. Source bytes restored in finally; raw evidence retained at `.orchestra/private/V-1064/host-mutation-*.txt`. All 17 changed files passed the local literal/forbidden and secret-form scans. Normal merge test and mutation gates passed; no model review under owner freeze.

Merged into main. GitHub publication/CI and loading Python via the authorized idle watcher remain separate checks. The actual Obelisk sync incident was already recovered through Seedon's independently verified SDK cleanup plus normal sync; do not attribute that restoration to this patch. No live retained-workspace recovery recipe, restart or remote operation was executed for this acceptance.
