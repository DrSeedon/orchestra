# #114 — External bug inbox that cannot dirty a merge target

## Decision

Move the mutable bug inbox out of every Git checkout and make the service state directory the
only live source of truth. `POST /api/report_bug` will publish a durable record there; an
authenticated reader and a persistent dashboard banner will make new reports visible without
requiring the operator to know a route or filesystem path.

The service will not commit, stage, ignore, or otherwise mutate Git state. The existing
clean-target guard remains byte-for-byte unchanged and continues to reject every unrelated dirty
file.

The dashboard files are a deliberate, minimal expansion from the research boundary. A backend
reader alone does not satisfy the newly clarified requirement that a human notice a report without
already knowing where to look. Approval of this plan therefore authorizes only the banner changes
listed below; it does not authorize other frontend work.

## Storage and API contract

### Canonical location

- Prefer the systemd-provided `$STATE_DIRECTORY`; the shipped service template provisions
  `StateDirectory=orchestra` and `StateDirectoryMode=0700`. For non-systemd development, try the
  XDG state directory and then the user's state directory.
- Validate **every** candidate, including `$STATE_DIRECTORY`, before creating or caching anything.
  Resolve it from its nearest existing ancestor under a sanitized environment with all inherited
  `GIT_*` repository-selection variables removed.
  Accept only the exact `git rev-parse --absolute-git-dir` outcome that means there is no Git
  repository. Reject a worktree, `.git` metadata, a bare repository, a symlink into any of those,
  and every unexpected probe failure.
- Cache only a successfully validated canonical path for the process lifetime. Log that path once.
  A missing or unsafe path is a service error, never a reason to fall back to the checkout.
- The canonical inbox is a private `bug-inbox/` directory (`0700`) containing an immutable migrated
  `legacy.md`, private `tmp/`, and atomically published `records/*.md` (`0600`). It is one
  service-state store with one aggregate reader, not two independently writable inboxes.
- Validation continues through the final tree; validating only the state root is insufficient.
  Every existing component is checked with `lstat` and must be the expected real directory/regular
  file, never a symlink. Creation and later I/O use held directory file descriptors plus
  `dir_fd`/`O_NOFOLLOW` operations, so a component swapped after the initial path probe cannot
  redirect `tmp`, `records`, `legacy.md`, or a record into a checkout. The resolved final tree is
  also rechecked by the sanitized Git probe before the path is cached.

### Writes and durability

- `POST /api/report_bug` keeps the existing Markdown entry format and does not truncate title,
  description, traceback, reproduction, measurements, or environment fields.
- The async route passes the blocking filesystem operation to `asyncio.to_thread`; a long report
  or `fsync` cannot stall the FastAPI event loop.
- Each report is one record file. A writer creates a private temporary file inside `tmp/`
  filesystem, writes the complete UTF-8 entry with a partial-write loop, `fsync`s it, atomically
  renames it to a collision-resistant timestamp/UUID name in `records/`, and `fsync`s that
  directory. Readers ignore temporary files. Concurrent threads/processes therefore publish whole
  immutable records without sharing an append cursor or holding a process-local lock.
- The atomic rename is the visibility boundary. A failure or process death before rename leaves at
  most an ignored temporary file and does not change GET/status. After rename, readers can see only
  the complete record; if the final directory `fsync` or response fails, POST returns 500 but keeps
  the complete published record rather than deleting possible evidence. A retry may duplicate an
  ambiguous report, which is safer than losing or truncating it.
- Startup/first access removes no evidence: it ignores incomplete temporary files and aggregates
  only the immutable legacy snapshot plus fully renamed records. Tests inject death/failure before
  and after the rename and recreate the route state to prove recovery never exposes a prefix,
  overwrites another record, or drops a published record.
- Creation syncs every new directory entry. Existing overly broad permissions are tightened to the
  required modes. A path, open, write, rename, encoding, or sync failure returns HTTP 500 and logs
  and returns `ExceptionClass: message`; no success is reported before durability is confirmed.
- A successful response names the authenticated reader route. It may expose the canonical state
  path to trusted internal callers, but the dashboard needs only the route and version.

### Reads and notification state

- `GET /api/report_bug` snapshots the sorted immutable record filenames, then streams
  `legacy.md` plus exactly that snapshot. It holds no filesystem lock while a network client reads,
  loads no growing archive into memory, and never exposes a temporary/partial record. A report
  published after the snapshot appears on the next read. A missing inbox returns an empty Markdown
  document, not a fabricated report.
- `GET /api/report_bug/status` lists metadata/names only and returns a small payload:
  `has_reports`, an opaque version derived from the legacy metadata, record count, and latest
  immutable filename, plus `view_url`. It never reads report bodies, so long traces do not increase
  response size or bytes read. At this MVP's report volume, a directory-name scan on a changed/
  uncached directory is simpler than a second transactional manifest; process startup performs the
  same reconstruction from canonical files.
- Both GET routes retain the existing `/api/*` authentication middleware; no public reader is
  introduced.

## Human visibility

Add `#bug-report-banner` above the usage bar in the dashboard. On page load and every 30 seconds,
the browser fetches only `/api/report_bug/status`:

- no reports: keep the banner hidden;
- version differs from `localStorage.orchestraBugInboxSeenVersion`: show a conspicuous banner
  saying that new Orchestra bug reports are waiting, with a `Read` link;
- clicking `Read` opens a blank same-origin tab synchronously (so popup blocking cannot eat the
  user gesture), then fetches the complete authenticated reader response; only after `response.ok`
  and full body completion does it render the captured Markdown as text in that tab and record
  exactly the version that was displayed;
- a later published record changes the version and makes the banner reappear;
- a status/read failure is not swallowed: show `ErrorClass/status: response text` in the banner
  and log the same detail.

The version is never marked seen merely by polling, selecting an agent, opening a failed response,
or receiving a partial stream. The first dashboard load after migration has no stored version, so
the migrated live reports are announced immediately. The seen marker is per browser, intentionally:
each operator/device must acknowledge the inbox for itself.

Do not send Telegram alerts or wake an agent session. Telegram tool telemetry is optional and
truncated, while making this a reliable delivery would consume the delivery lane fixed in #100/
#102. The dashboard is the always-on human control surface and can show the full aggregate without
model turns or flood-control pressure.

## Existing `BUGS.md`: one source of truth

The tracked repository file is not allowed to remain a second live inbox.

During the maintenance rollout, while the old writer is stopped, the operator copies the complete
current tracked `BUGS.md` byte-for-byte to external `bug-inbox/legacy.md` and verifies the copy.
That immutable snapshot plus external `records/` become the sole canonical store, including all
historical open reports.

The implementation branch deliberately does **not** edit tracked `BUGS.md`: reports can arrive on
main throughout implementation, so a branch replacement would be stale and conflict at rollout.
After the verified copy and code merge, the operator replaces the tracked file in a separate
human-authored commit with a short static pointer to the dashboard banner and
`GET /api/report_bug`. Git history retains the old snapshot; the pointer contains no report data
and the service never writes it. From activation onward there is one live source, not two files
that can diverge.

Fresh installs start with an empty external inbox and the same tracked pointer. There is no
automatic import on startup: automatic import cannot distinguish a completed migration from a
retry and would reintroduce duplicate-source semantics.

A later re-activation after rollback never reuses an old active store. While the service is stopped,
the operator atomically renames any pre-existing `bug-inbox/` to a timestamped, hashed sibling
archive, verifies it, and creates a new empty store before copying the current tracked aggregate to
`legacy.md`. Because rollback already rebuilt tracked `BUGS.md` from the prior legacy plus records,
the new legacy contains each old report once and the freshly empty `records/` cannot duplicate them.
No activation overwrites or appends into a previous store.

## Load and concurrency proof

The new full-trace prompt increases entry length and report rate, so verification covers payload
size and concurrent writers rather than assuming the old short descriptions:

- submit 32 concurrent reports with unique markers and 128 KiB descriptions (4 MiB aggregate);
- assert every marker and complete entry appears exactly once, no two entries interleave, and the
  immutable record files remain valid UTF-8 with mode `0600`;
- assert the status version changes after every completed publish while the status response
  remains body-size independent;
- hold the writer with deterministic events and prove another coroutine can run while the route is
  awaiting `to_thread`; use no elapsed-time threshold;
- run a second writer in a subprocess against the same inbox to prove unique atomic publication
  works across processes, not merely threads;
- inject partial writes, process death, and failures in open/write/fsync/rename/directory-fsync
  paths on both sides of the publish boundary; after route-state recreation, the aggregate is
  either the exact old snapshot or the old snapshot plus one complete record, never a prefix;
- stall a GET response consumer after its filename snapshot and prove, with controlled events, that
  a writer can publish concurrently because no network-duration lock is held;
- create symlinks at the state root's `bug-inbox`, `tmp`, `records`, `legacy.md`, and record-file
  positions, including swaps after initial validation; every case fails closed without touching the
  symlink target;
- simulate rollback then re-activation with a pre-existing store and prove the old store is archived,
  the new store starts empty, and the aggregate contains every old report exactly once.

There is no configured size cap or rotation in #114: silently dropping the oldest bug would violate
the persistence requirement. At the measured scale, immutable Markdown records plus body-free
status polling are simpler and safer; archive/rotation can be a separate explicit retention task if
the state store later becomes operationally large.

## Files

- `app/routes/system.py`
  - safe state-path selection;
  - atomic durable record publication and snapshot/status readers;
  - POST/GET API contracts and class-bearing failures.
- `deploy/orchestra.service.template`
  - provision the private service state directory.
- `app/templates/dashboard.html`
  - add the otherwise-hidden bug inbox banner.
- `app/static/js/app.js`
  - poll status, persist the acknowledged version, show new reports and reader failures.
- `tests/test_api.py`
  - API, path isolation, durability, permissions, concurrent/large writes, reader/status behavior.
- `tests/test_workspace.py`
  - call production `merge_worktree_to_main()` in a temporary repository after a real report;
    prove the merge passes, then prove an unrelated dirty file still rejects it.
- `tests/test_frontend.py`
  - static dashboard contract for the banner, polling, explicit acknowledgement, and visible error
    path.
- `tests/test_routes_surface.py` and `tests/route_surface_snapshot.json`
  - keep the intended route surface explicit if its existing route inventory requires an update.

The route snapshot is shared with #93 T4. T1 starts only after #93 is merged or its owner releases
that fixture; then this branch syncs to fresh main and adds only #114's two GET routes to the final
snapshot. It must not resolve a concurrent snapshot conflict by accepting unrelated route changes.

Do not modify `app/manager.py`, `app/workspace.py`, `app/routes/sessions.py`,
`app/ssh_tunnel.py`, `app/bg_jobs.py`, `app/rag.py`, `pipelines/`, any Telegram delivery code, or
the clean-target predicate. Do not add a DB table, auto-commit, `.gitignore` exception, or
background sync back into the repository.

## Tickets

### T1 — Durable external inbox that leaves merge targets clean

- Files: `app/routes/system.py`, `deploy/orchestra.service.template`, `tests/test_api.py`,
  `tests/test_workspace.py`, `tests/test_routes_surface.py`, and
  `tests/route_surface_snapshot.json`.
- Deliver the external state-path guard, private creation, atomic record publication, snapshot read,
  constant-size status route, class-bearing failures, and production merge proof end to end.
- AC:
  - a POST with a full 128 KiB trace is returned verbatim by GET; the opaque status version changes
    at atomic publish, while HTTP 200 is returned only after record and directory durability sync;
  - the state directory/file modes are `0700`/`0600`, and file plus relevant directory entries are
    synced;
  - unsafe candidates from `$STATE_DIRECTORY`, XDG, or home—including worktree, `.git`, bare repo,
    missing descendant under a repo, symlink into a repo, and contaminated `GIT_*` environment—are
    rejected without creating or modifying a file; no-follow descriptor tests repeat this for every
    `bug-inbox/tmp/records/legacy/record` descendant and for a post-validation symlink swap;
  - 32 concurrent thread writers plus a subprocess writer produce complete, non-interleaved,
    exactly-once entries; the event loop progress test uses controlled events, not wall clock;
  - every open/write/partial-write/fsync/rename/probe failure returns HTTP 500 with the exception
    class and never falls back to repository `BUGS.md`; before/after-publish failure plus simulated
    restart yields either no new record or one complete new record, never a truncated prefix;
  - a stalled reader does not block a concurrent writer after the reader snapshots immutable names;
  - an operator-rollout fixture archives a pre-existing store instead of overwriting/reusing it,
    then proves re-activation after rollback produces no duplicate legacy or record; ordinary
    process restart continues to open the existing canonical store unchanged;
  - after POST, real production `merge_worktree_to_main()` succeeds on a clean target; an unrelated
    dirty file still produces the existing refusal;
  - the route surface test and its explicit JSON snapshot both include the two additive GET routes;
  - no production merge/manager/workspace/session file changes.
- blocked-by: external #93 T4 merge or explicit release of `tests/route_surface_snapshot.json`

### T2 — Dashboard makes every unseen inbox version visible

- Files: `app/templates/dashboard.html`, `app/static/js/app.js`, `tests/test_frontend.py`,
  `tests/test_api.py`.
- Add the persistent banner, immediate and 30-second lightweight status polling, explicit reader
  acknowledgement, and visible failure state.
- AC:
  - the first dashboard load with any migrated report shows the banner without selecting an agent
    or knowing the API route;
  - polling alone never marks the version seen; clicking `Read` stores the displayed version and
    opens the captured authenticated full reader only after a complete successful response;
  - a later POST changes the version and makes the banner reappear;
  - status polling transfers no report bodies and remains constant-size after the 4 MiB load test;
  - a non-2xx response, partial-body failure, or fetch exception leaves the version unseen and shows
    its status/error class and server text instead of disappearing in `catch {}`;
  - no Telegram message, agent wake, DB row, or Git mutation is introduced.
- blocked-by: T1

## Verification

Focused deterministic suite:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest \
  tests/test_api.py \
  tests/test_workspace.py \
  tests/test_frontend.py \
  tests/test_routes_surface.py -q
```

After focused tests, acquire the shared full-suite lock and run the repository suite once. Read the
captured log once; if an unrelated failure appears, stop and report it rather than changing another
worker's territory. No test uses a wall-clock performance assertion or the live service state.

Implementation review is mandatory despite the small file count: this path is shared by every
project and a false success can lose a report or block all merges again.

## Maintenance rollout (operator-executed)

The old process remains a Git writer until it is stopped. The implementation must not be activated
with an ordinary merge-then-restart sequence.

### Preconditions

1. T1/T2, focused suite, full suite, and implementation review are green on the final branch.
2. Record the branch commit and current main commit. Let active turns finish; announce the short
   maintenance window because stopping Orchestra interrupts active turns.
3. Inspect `git status --porcelain` in main only to identify current state. Do not commit the final
   tracked archive while the old endpoint can still append; abort now on every unrelated dirty path.

### Activate

1. `sudo systemctl stop orchestra`; confirm `systemctl is-active orchestra` reports `inactive`, no
   old uvicorn process remains, and a probe cannot reach the old `/api/report_bug` writer.
2. With the writer now quiesced, inspect `git status --porcelain` again. Commit the final legitimate
   tracked `BUGS.md` state as an explicit human archive commit; abort on every unrelated dirty path
   and confirm the checkout is clean before copying or merging.
3. Install the `StateDirectory=orchestra` / `StateDirectoryMode=0700` service change (template or
   equivalent systemd drop-in), then run `sudo systemctl daemon-reload`.
4. Inspect `/var/lib/orchestra/bug-inbox` without following symlinks. If it already exists, hash its
   complete aggregate and atomically rename it to a unique
   `/var/lib/orchestra/bug-inbox.archive-<UTC>-<hash>` sibling; never overwrite or merge into it.
   Create new empty `bug-inbox/tmp` and `bug-inbox/records` real directories owned by the service
   user/group with mode `0700`, and prove `records/` is empty. Copy the stopped checkout's complete
   tracked `BUGS.md` to
   `/var/lib/orchestra/bug-inbox/legacy.md` with mode `0600`; sync the file and directories. Compare
   byte count and SHA-256 on both copies. Any mismatch aborts before code/pointer Git changes.
5. Manually squash-merge the reviewed #114 branch into main while the service is stopped. Recheck
   `git status --porcelain`; it must be empty.
6. Replace tracked root `BUGS.md` with the static pointer described above and commit that change as
   an explicit human migration commit. The external store is now canonical; do not start the old
   revision after this point without following rollback.
7. `sudo systemctl start orchestra`; confirm `active` and inspect the journal for the selected
   external path and absence of state-path/permission errors.
8. Submit one controlled report with a unique marker. Verify, in order:
   - POST names `/api/report_bug` and succeeds;
   - status version changes and GET contains the full marker;
   - the dashboard shows the unseen banner and `Read` opens the report;
   - main `git status --porcelain` remains empty;
   - the focused real-merge regression test passes against a disposable temporary repository.

Only after all checks pass is the “report_bug never blocks merge” guarantee active. Do not create a
throwaway live main commit merely to test merge; the production helper is already exercised against
a real temporary Git repository.

Abort boundary is explicit. Before the pointer commit (steps 1–5), keep/restore tracked `BUGS.md` as
canonical, revert the #114 merge commit if it was already created, restore the prior unit if changed,
and restart the old revision; the copied/archived external store remains an inert backup. From the
pointer commit onward (steps 6–8), use the full rollback below—never start the old revision against
the pointer file.

### Roll back without losing reports

1. Stop Orchestra; confirm `inactive`, no uvicorn process, and no reachable old/new
   `/api/report_bug` writer. Only then copy the entire external inbox directory to a separately
   named backup; sync it and record hashes for `legacy.md` and every immutable record.
2. Revert the human pointer commit first, then the #114 code commit, while the service remains
   stopped (reverse activation order).
3. In a temporary path outside the checkout, build the expected aggregate from backed-up
   `legacy.md` followed by every backed-up `records/*.md` in filename order. Record the immutable
   record count, byte count, and SHA-256 of that exact concatenation. Rebuild tracked `BUGS.md`, then
   require all three values to match before making one explicit human commit. This carries every
   report received after activation back to the old canonical location without relying on selected
   marker strings.
4. Restore/remove the systemd drop-in if desired (the old service ignores the state directory),
   daemon-reload, start the old revision, and verify a controlled report appears in tracked
   `BUGS.md`.
5. Preserve the external backup until the old report and clean-target behavior have both been
   inspected. The known merge-blocking defect returns under rollback, but no report is discarded.

## Migration and compatibility

No database migration and no API removal. POST keeps its request fields and `result` key, adding
reader/path metadata. The new GET routes are additive. Runtime storage is host-local service state;
backup/retention policy is intentionally outside #114, while the rollout and rollback preserve the
entire existing archive.
