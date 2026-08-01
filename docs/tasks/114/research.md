# #114 — Durable bug inbox that cannot dirty a merge target

## Question

- **Context:** every project reports Orchestra platform bugs through the one live
  `/api/report_bug` endpoint. That endpoint currently appends to tracked `BUGS.md` in
  Orchestra's checked-out target tree; `merge_worker` correctly refuses every dirty target.
- **Change under test:** move the append-only live inbox out of every Git worktree while
  retaining an immediately visible tool event and a durable, human-readable file.
- **Baseline:** keep tracked `BUGS.md`, auto-commit it, or exempt it from the clean-target
  guard.
- **Outcome:** after a report, the complete entry exists, the target remains clean, the real
  merge path succeeds, and another unrelated dirty file still makes that path fail.

## Hypotheses and falsifiers

1. **H1 — a provisioned and Git-validated state file is the smallest safe boundary.**
   `report_bug` can append to systemd's `$STATE_DIRECTORY/BUGS.md`, with a validated XDG/home
   fallback for direct development runs, without participating in any project's Git
   transaction. It is wrong if the deployed service cannot persist there, path resolution can
   land in any Git worktree, a report becomes invisible, or merge protection must be weakened.
2. **H2 — exempting tracked `BUGS.md` is sufficient.** It is wrong if the file remains dirty
   after a merge, conflicts with a worker, or masks a human edit to the same file.
3. **H3 — an automatic single-file commit is safe.** It is wrong if report and human/merge
   operations can race on the same index, worktree, or branch, or if the service changes
   user-owned history.
4. **H4 — SQLite is preferable to a state file.** It is wrong if making reports human-visible
   requires a new schema, reader, UI, or export path that the append-only file does not need.

## Experiment contract (defined before execution)

The controlled `/tmp` experiment will use the production
`merge_worktree_to_main()` implementation:

- baseline pass condition: appending a tracked `BUGS.md` makes `git status --porcelain`
  non-empty and merge is rejected specifically as a dirty target;
- candidate pass condition: appending the identical bytes to an external state file leaves
  the target status empty and the same merge succeeds;
- guard-preservation pass condition: adding an unrelated untracked file still makes the same
  merge fail;
- durability/visibility pass condition: the external file contains the complete title,
  reporter, scope, and multiline trace after the merge.

After adversarial review exposed path-aliasing, rollout, and first-create durability gaps, a
second experiment is defined before execution:

- a direct state path nested under a Git checkout must be rejected;
- an external symlink resolving into a Git checkout must be rejected;
- a missing descendant below a Git checkout must be rejected using its nearest existing parent;
- an ordinary external directory and the live host fallback must be accepted;
- the revised design must not modify tracked `BUGS.md`, so the old writer and the implementation
  branch cannot conflict on that file.

After round 2 found two more Git false-accept cases, a third experiment is defined before
execution:

- inherited repository-selection variables (`GIT_DIR`, `GIT_WORK_TREE`, and every other `GIT_*`)
  must not influence the probe;
- a normal worktree path, its `.git` metadata directory, and a bare repository must all be
  rejected;
- an ordinary external directory must still be accepted even when an unrelated invalid `.git`
  directory exists above it;
- any probe result other than a recognized repository or the specific `not a git repository`
  outcome fails closed.

## Findings

### F1 — the endpoint writes into the exact checkout protected by merge

**CONFIRMED — source code, live-process inspection, Git state, and repeated history agree.**

`report_bug_endpoint()` constructs the path by walking three parents from
`app/routes/system.py`, then opens `<checkout>/BUGS.md` in append mode. The live service cwd is
`/mnt/data/Projects/Python/orchestra`, and that checkout tracks `BUGS.md`. The merge authority
holds a repository lock and rejects every non-empty `git status --porcelain` result before
touching the target; it does not distinguish service-created changes from human work.[1][2]

The local Git history contains four separate `BUGS.md` commits on 2026-08-01 (`6daf774`,
`0e9b852`, `1ae97b9`, `d1429b1`), independently corroborating the orchestrator's report of five
manual interventions during the day. The count difference is not evidence against the symptom:
one intervention need not map one-to-one to a surviving single-file commit.[2]

### F2 — the production merge guard is correct and must remain file-agnostic

**CONFIRMED — production code plus controlled direct execution.**

The guard rejects a tracked `BUGS.md` modification before merge. Special-casing that path would
leave a tracked file dirty indefinitely and would also make a human edit to the same file the
only tracked change that bypasses fail-loud protection. Git's own documentation states that
ignore rules do not affect already tracked files.[5] No change to `app/workspace.py`, its lock,
or its clean-target predicate is required by the safe candidate.[1][3]

### F3 — a provisioned state directory plus path validation meets the boundary

**CONFIRMED for the deployed host; CONFIRMED for the shipped systemd template after the proposed
directive; custom launchers fail loud unless they provide a safe writable fallback.**

The first recommendation was too broad: an absolute XDG path can still be inside a worktree or
traverse a symlink into one. The corrected boundary is:

1. prefer systemd's absolute `$STATE_DIRECTORY`;
2. otherwise consider absolute `$XDG_STATE_HOME/orchestra` and
   `Path.home() / ".local/state/orchestra"` in order;
3. resolve existing symlink components, locate the nearest existing ancestor, and use Git's own
   `rev-parse --absolute-git-dir` discovery across filesystem boundaries under an environment
   stripped of every inherited `GIT_*` selector;
4. reject ordinary worktrees, their metadata directories, and bare repositories; accept only the
   specific `not a git repository` outcome and fail closed on every other probe error;
5. never fall back to the source checkout.[8]

The systemd `StateDirectory=orchestra` directive creates `/var/lib/orchestra` for a system
service, assigns it to the configured service user, and exposes the absolute path as
`$STATE_DIRECTORY`; `StateDirectoryMode=0700` makes the intended privacy explicit.[6] This closes
the shipped-service portability gap instead of inferring a writable home from `User=`.

For direct development runs, the XDG specification designates `$XDG_STATE_HOME` for state that
persists across application restarts and defines `~/.local/state` as its default.[4] On the live
host the service runs as `maxim`, has `HOME=/home/maxim`, has no XDG override, and the resolved
`/home/maxim/.local/state/orchestra` candidate is outside Git with a writable parent.[2]

All project agents submit reporter and scope to the same Orchestra API, so this remains one
cross-project platform inbox.[1] Existing tracked `BUGS.md` stays untouched as the historical
archive. Human aggregate visibility comes from an authenticated `GET /api/report_bug` that reads
the canonical state file; successful POST/tool results name that view and the filesystem path.
The existing dashboard tool card remains useful immediate evidence, but it is not the sole
discoverability contract because its success renderer can clip or hide returned details.[1]

### F4 — the candidate passes the real merge path without weakening it

**CONFIRMED — direct measurement against `merge_worktree_to_main()` at commit `c5f1d0d`.**

Raw controlled result (temporary repositories and state directories under `/tmp`):

```json
{
  "baseline": {
    "status": "M BUGS.md",
    "merge_ok": false,
    "error": "target working tree is dirty (1 file(s): BUGS.md) — commit or discard first"
  },
  "candidate": {
    "status": "",
    "merge_ok": true,
    "entry_exact": true,
    "merged_payload": true
  },
  "guard": {
    "status": "?? human-wip.txt",
    "merge_ok": false,
    "error": "target working tree is dirty (1 file(s): human-wip.txt) — commit or discard first"
  }
}
```

All four predeclared experiment conditions passed. The implementation test must repeat this at
the HTTP boundary rather than merely testing the path helper: call `/api/report_bug`, then invoke
the real merge function on a temporary target/worker pair.

The adversarial path experiment also passed after replacing a naive `.git`-ancestor check with
Git's own repository discovery (the naive check correctly failed the experiment because this host
contains an unrelated empty `/tmp/.git` directory):

```json
{
  "repo_direct_rejected": true,
  "repo_missing_descendant_rejected": true,
  "symlink_into_repo_rejected": true,
  "external_accepted": true,
  "live_fallback_accepted": true,
  "live_fallback_resolved": "/home/maxim/.local/state/orchestra"
}
```

This result narrows the implementation contract: filesystem-name heuristics are insufficient;
the helper must use a bounded Git probe on the resolved nearest existing ancestor.

Round 2 then demonstrated that `--is-inside-work-tree` alone answers the wrong question inside
Git metadata and can be redirected by inherited `GIT_DIR`. The corrected, environment-sanitized
`--absolute-git-dir` probe produced:

```json
{
  "worktree": [false, "/tmp/.../repo/.git"],
  "metadata": [false, "/tmp/.../repo/.git"],
  "bare": [false, "/tmp/.../bare.git"],
  "external_with_contaminated_env": [true, "not-a-repository"],
  "live_fallback_with_contaminated_env": [true, "not-a-repository"]
}
```

Here `false` means “not an acceptable state path.” The process environment deliberately contained
both `GIT_DIR=<other bare repo>` and `GIT_WORK_TREE=<worktree>`; sanitization prevented either from
changing the result.

### F5 — alternatives are inferior under the stated constraints

**CONFIRMED for auto-commit/exemption; LIKELY for SQLite/git-notes based on current surfaces.**

- **Automatic commit:** explicitly prohibited by the owner. It would also introduce a second Git
  writer outside the merge lock and alter user-owned branch history. Acquiring the merge lock
  would serialize only Orchestra operations, not manual human edits.
- **Clean-guard exemption:** preserves the exact dirty state that caused the incident, masks human
  edits to `BUGS.md`, and eventually collides with a branch that touches the file.
- **SQLite:** `app/db.py` has no bug-report table. A new table alone is invisible; it would need a
  schema, reader/API, and likely UI/export path. The existing Markdown contract already supplies a
  readable append-only aggregate with less machinery.[1]
- **Git notes or a private ref:** avoids the worktree but mutates Git metadata, is not fetched or
  displayed by default, and is less discoverable than the existing dashboard plus a named state
  file. It solves the wrong half of the problem.

## Counter-evidence and residual risks

- The state inbox is not automatically versioned or pushed. That is intentional—versioning is the
  coupling that blocks merge—but host backup policy remains outside this task. For a newly created
  inbox, durability requires `fsync` of the file and its parent directory entry; newly created
  fallback directories require syncing their parents too. A 500 response on any create/write/fsync
  failure prevents a false success.[7]
- A custom launcher may provide neither `$STATE_DIRECTORY` nor a safe writable home. The endpoint
  must fail loud with `ExceptionClass: message`; it must never fall back to a Git checkout. The
  shipped systemd template provisions the state directory, and the current host fallback is
  measured safe.
- Until the merged Python code is activated by an explicitly authorized service restart, the old
  live endpoint will continue writing tracked `BUGS.md`. The code change itself cannot remove
  that deployment window. The implementation deliberately does not touch tracked `BUGS.md`, so
  rollout needs only the existing final clean-target check plus prompt activation—not a competing
  pointer-file merge.
- The dashboard visibility is per reporting session and its result card is not a complete reader.
  The authenticated GET route is therefore the canonical human-readable aggregate view.

## Rollout boundary

The runtime fix cannot make the already running old endpoint stop appending to tracked
`BUGS.md`. Therefore a zero-race rollout is an explicit operational prerequisite, not something
the code can pretend to guarantee:

1. finish and verify the #114 branch without modifying tracked `BUGS.md`;
2. with operator approval, stop/quiesce the old Orchestra service so no report can arrive;
3. preserve any final tracked archive change and manually squash-merge the branch while the
   service is stopped (the HTTP `merge_worker` authority is unavailable at that point);
4. start the new version, submit one controlled report, read it through `GET /api/report_bug`,
   verify the target is clean, then run one disposable real merge;
5. if any check fails, stop and restore the previous service revision—the tracked archive remains
   untouched by the new code.

Without this maintenance sequence, a report in the merge-to-restart window can still dirty the
target. No claim of “never blocks merge” is valid before activation. Restart/stop is not authorized
by research approval alone and must be explicitly approved at rollout.

The permanent human entry point stays within the allowed backend boundary: `GET /api/report_bug`
is present in the authenticated API/OpenAPI surface, and every successful `report_bug` response
names it and the state path. The existing dashboard card still shows the required multiline trace
at report time. A new frontend link would be nicer, but it is not required for persistence or
visibility and is outside this task's assigned frontend territory.

## Recommended design

1. Add a small path selector in `app/routes/system.py`: prefer `$STATE_DIRECTORY`, then safe
   XDG/home candidates. Resolve each candidate; under a sanitized subprocess environment use
   `git rev-parse --absolute-git-dir` on its nearest existing ancestor and reject worktrees,
   metadata, bare repositories, and unexpected probe failures.
2. Provision `StateDirectory=orchestra` and `StateDirectoryMode=0700` in the shipped systemd
   template. For development fallback creation, sync created directory entries. Create the inbox
   as `0600`, append UTF-8, `fsync` the file and its directory entry. On any failure return HTTP
   500 and log `ExceptionClass: message`; never retry into the repository.
3. Add authenticated `GET /api/report_bug` as the human-readable aggregate. Return the canonical
   path and GET route from POST. Leave tracked `BUGS.md` unchanged to avoid the rollout conflict.
4. Do not modify `app/workspace.py`, `app/manager.py`, or any clean-target rule.
5. Activate only through the maintenance rollout above; ordinary merge-before-restart is not a
   race-free deployment for this particular old writer.

## Affected files and verification surface

- `app/routes/system.py` — compute and write the external state inbox; class-bearing failures.
- `deploy/orchestra.service.template` — provision the system-service state directory and mode.
- `tests/test_api.py` and/or `tests/test_workspace.py` — exact persisted entry, error visibility,
  authenticated aggregate read, XDG-in-repo and symlink rejection, report-then-real-merge success,
  unrelated-dirty rejection, and file/directory sync behavior.
- No DB migration, frontend change, auto-commit, or merge-path change.

## Adversarial second opinion

Codex round 1 agreed with the external-inbox principle but found four blocking omissions:
untrusted absolute/symlinked XDG paths, no provisioned state directory for system users, a rollout
conflict caused by changing tracked `BUGS.md`, and incomplete first-create durability. All four
were verified and accepted. Round 2 then found that `--is-inside-work-tree` false-accepts Git
metadata and obeys contaminating `GIT_*` variables, and that only a quiesced maintenance rollout
can close the old-writer window. Both were measured/accepted: the probe is now sanitized and uses
`--absolute-git-dir`, while rollout explicitly stops the old service before a manual squash merge.
The recommendation leaves tracked `BUGS.md` untouched, provides an authenticated aggregate reader,
and synchronizes file and directory entries. The permanent backend/OpenAPI entry point is retained
instead of expanding into forbidden frontend work. Full debate is in `codex-review-research.md`.

## Sources

1. Orchestra source at `c5f1d0d`: `app/routes/system.py:991-1007`,
   `app/mcp_stdio.py:627-644`, `app/workspace.py:464-487,664-914`,
   `app/static/js/app.js:3431-3470,4054-4059`, `app/db.py:13-34`, and
   `deploy/orchestra.service.template:5-16` — primary source.
2. Direct live inspection on 2026-08-01: service cwd/user/environment, target tracking state, and
   `git log -- BUGS.md`; no live file was modified — direct measurement.
3. Controlled `/tmp` experiment on 2026-08-01 using production
   `merge_worktree_to_main()` — direct measurement; raw result reproduced above.
4. [XDG Base Directory Specification 0.8](https://specifications.freedesktop.org/basedir-spec/latest/),
   fetched 2026-08-01 — primary specification, especially `$XDG_STATE_HOME` and its default.
5. [Git `gitignore` documentation](https://git-scm.com/docs/gitignore), fetched 2026-08-01 —
   primary documentation: ignore rules cover intentionally untracked files and do not affect
   files already tracked by Git.
6. [Linux `systemd.exec(5)` manual](https://man7.org/linux/man-pages/man5/systemd.exec.5.html),
   fetched 2026-08-01 — primary manual mirror: `StateDirectory=` creates a service-owned state
   directory and exports its absolute path as `$STATE_DIRECTORY`.
7. [Linux `fsync(2)` manual](https://man7.org/linux/man-pages/man2/fsync.2.html), fetched
   2026-08-01 — primary manual: syncing a file does not necessarily persist its directory entry;
   the containing directory needs an explicit `fsync`.
8. [Git `rev-parse` documentation](https://git-scm.com/docs/git-rev-parse), fetched 2026-08-01 —
   primary documentation: `--absolute-git-dir` returns the canonical repository directory and
   errors outside a repository/worktree; `GIT_DIR` otherwise influences discovery.
