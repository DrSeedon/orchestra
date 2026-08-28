<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently the emergency backup saves the tidy JSON and hopes SQLite remembers the rest 😅. The report covers the five areas and migration options, but it is not ready for acceptance: two blocking issues and several accuracy/reproducibility gaps remain. No files were edited.

## Findings (blocking/suggestion/question)

**[blocking] Emergency backup omits non-rebuildable state** — `research.md:259`

The proposed no-remote procedure backs up canonical Git and selected JSON files, but omits `data/orchestra.db` logs/session state, active delivery journals, `data/tg-file-outbox/`, `data/uploads/`, and the private project corpus. The report itself says these contain resume history, idempotency state, UNKNOWN delivery evidence, and durable attachments; losing them can cause data loss after disk failure. Add consistent SQLite backup plus active spool/artifact capture before declaring the emergency state preserved.

**[blocking] The proposed project registry boundary contradicts current ownership** — `research.md:200`

`app/ia/runtime.py:432-488` requires the central legacy DB, derives `canonical_project_id` from `tm_projects`, reads/writes `scope-registry.json`, and later uses that mapping for authorization and evidence routing. Calling this registry a disposable cache is unsafe until a project-local manifest becomes the authoritative resolver and migration behavior for identity conflicts is defined.

**[suggestion] Do not label apparent bytes as physical bytes** — `research.md:315`

`du -sb` and `Path.stat().st_size` measure apparent/file length, not allocated physical disk usage. Therefore the “physical volume” tables and the 25.60 GB headline are mislabeled; either rename them to apparent bytes or measure allocated blocks with an explicit hard-link/sparse-file policy.

**[suggestion] Complete the minimal session-registry field list** — `research.md:197`

The cited `app/manager.py:1813-1912` and `app/db.py:1245-1360` also require `cwd`, branch/base branch, `task_id`, pipeline/role, `needs_switch`, and handoff/history fields for resume, adoption, and merge lifecycle. Enumerate these as mandatory engine state, or specify their project-local source and failure behavior.

**[suggestion] Make emergency backup paths unambiguous** — `research.md:259`

The action lists basenames such as `scope-registry.json` and `runtime-state.json`, while `app/ia/runtime.py:362-373` allows `STATE_DIRECTORY` and `XDG_STATE_HOME` overrides. Record the resolved physical paths for this deployment, not only filenames and sizes.

**[suggestion] Qualify the uploads “1 GiB ceiling” claim** — `research.md:151`

`app/tg_bridge.py:145-166` cleans up before downloading and does not enforce the limit after writing the new file. The reported 1,073,854,770 bytes already exceed 1 GiB by 112,946 bytes, so describe this as a cleanup target or document the permitted overshoot.

**[question] Reconcile the worktree byte totals** — `research.md:141`

The populations sum to 90 directories (`57 + 21 + 12`), but the byte subtotals sum to 18,375,891,051 B versus the stated 18,375,879,542 B, a difference of 11,509 B. If this is directory-entry overhead from separate `du -sb` runs, state it; otherwise recalculate from one common enumeration.

**[suggestion] Add missing primary citations for reader/writer claims** — `research.md:152`

`routes/tg.py` is cited as the dashboard upload writer but appears in neither Sources nor Affected files. The message, initial-delivery, merge, and fan journal modules are likewise named generically without exact primary paths/ranges, so those boundary claims are not reproducible under the report’s declared evidence scope.

## Verdict

**❌ Not ready for Phase-1 acceptance.** The migration estimates, breakage lists, and reversibility columns are present, but the emergency advice is incomplete, byte units are inaccurate, and the proposed registry boundary does not match current readers/writers.

Otherwise this is a beautifully tabulated umbrella with no fabric.

## Round (2026-08-27T09:00:21Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Round 2 fixed seven of eight prior findings; one blocking backup gap remains because the recovery inventory omits the engine’s private artifact store. Counts, apparent-byte labeling, registry ownership, session fields, paths, WIP handling, and citations were corrected.

## Findings (blocking/suggestion/question)

- **STILL BROKEN — [blocking] Private artifacts remain outside the recovery set** — [research.md:271](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/docs/tasks/412/research.md:271)

  `app/artifacts.py:121-135` stores durable artifact bodies under `/home/maxim/.local/state/orchestra/artifacts/`, and `:262-275` writes them while `:361-381` reads them. The capture list includes only `data/...` paths and does not include this directory; backing up `orchestra.db` preserves metadata and hashes, not artifact bodies. Add the resolved artifact-store path and its files to the hash/copy manifest.

- **FIXED — [suggestion] Registry ownership:** `research.md:204-213` now keeps the central registry authoritative until verified manifest parity, matching `app/ia/runtime.py:432-488,1406-1461`.

- **FIXED — [suggestion] Apparent versus physical bytes:** `research.md:41-72,327-335` explicitly labels `du -sb`/`stat().st_size` as apparent length.

- **FIXED — [suggestion] Session registry fields:** `research.md:201` now includes the lifecycle fields read by `app/manager.py:1813-1912` and persisted by `app/db.py:1245-1420`.

- **FIXED — [suggestion] Resolved backup paths:** `research.md:270` gives concrete state and data paths.

- **FIXED — [suggestion] Upload overshoot:** `research.md:153-157` now describes a pre-download cleanup target and records the 112,946-byte overshoot.

- **FIXED — [question] Worktree arithmetic:** `research.md:333-335` reports one-enumeration totals that reconcile exactly.

- **FIXED — [suggestion] Primary citations:** `research.md:343-355` now includes the previously missing delivery, fan, artifact, and upload modules.

No additional new blockers found.

## Verdict

**❌ Blocked for Phase-1 acceptance.** The report is otherwise complete, but losing `/home/maxim/.local/state/orchestra/artifacts/` would still make the claimed recovery set incomplete.

A recovery plan that forgets the artifact directory is a fireproof box with the documents left on the desk.
