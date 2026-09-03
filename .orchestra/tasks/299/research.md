# Research #299 — Git-переносимое каноническое хранилище задач

Дата: 2026-08-23. Implementation запрещён; это Phase 1 research.

## Question

**Контекст.** Orchestra держит канонические задачи, платежи, YouGile-ссылки и merge-коммиты в локальной SQLite; MCP/HTTP фасад уже используется агентами и человеком.

**Change under test.** Оставить task_create, task_update, task_list, task_get, payment_receive, payment_status и merge-интеграцию, но вынести каноническую запись задачи в Git-переносимый формат. Обязательный UX-контракт — человекочитаемый монотонный номер #N сохраняется.

**Baseline.** tm_* в app/db.py, бизнес-логика app/tm.py, HTTP/MCP routes, Orchestra → YouGile mirror.

**Measurable outcome.** После клонирования второго контура и удаления локальной проекции можно восстановить все задачи/историю/денежные инварианты; два контура не создают дубли stable ID или #N, конфликт не теряется, существующие tool responses и project-scoped #N совместимы.

## Hypotheses and falsifiers

1. H1 — Git canonical + SQLite projection реализуемы без смены фасада. Git даёт историю/recovery, SQLite остаётся query cache. Falsifier: replay из Git не восстанавливает платежные инварианты или существующий consumer требует SQLite rowid как публичную identity.
2. H2 — Markdown/YAML или JSON-per-task лучше одного append-only JSONL. Разнос по task-файлам уменьшает конфликт разных задач. Falsifier: workload стабильно конфликтует в одном файле или ручная правка невалидируема.
3. H3 — UUID/ULID + отдельный display #N нужен вместе с leases. UUID решает merge identity, lease выдаёт два контура без online lock. Falsifier: требуется глобальная contiguous timestamp-order sequence без gaps; тогда offline leases несовместимы.
4. H4 — Платежи можно сделать Git-canonical. Payment/allocation events коммитятся одной Git-транзакцией, SQLite только проекция. Falsifier: legal policy запрещает private Git для денежных заметок даже с redaction/retention procedure.

## 1. Current task data model and consumers

Evidence: schema app/db.py:279-352; core app/tm.py:220-1201; routes app/routes/tm.py:12-230; MCP app/mcp_stdio.py:2042-2157; merge link app/routes/sessions.py:1372-1397; worker CAS app/routes/sessions.py:1481-1501; task-ref commit message app/workspace.py:864-890.

| Table/field | Writers / routes / tools | Transaction and invariant | External consumers | Portability/privacy risk |
|---|---|---|---|---|
| tm_projects.id,name,prefix,scope | ensure_project and scope registration in app/tm.py; task routes resolve project/scope | id PK; scope and prefix unique; project is task-ref authority | task tools, session scope, YouGile board mapping | Absolute scope paths/topology leak; project-local #N is ambiguous globally |
| tm_tasks.id | SQLite AUTOINCREMENT; internal joins and API payloads | local surrogate only | payment allocations, sync log, manager plumbing | Rowid changes on import; never Git identity |
| tm_tasks.par_number,project_id | create_task uses _next_par (MAX + 1 plus docs/tasks guard); resolve_task_ref/get_task_by_par read | unique project_id,par_number; create uses BEGIN IMMEDIATE; #N project-scoped and not reused while docs dir exists | tools, PAR-N parser, branch names, merge messages, YouGile idTaskProject | two offline contours can choose same next number; deletion/reuse breaks links |
| title,description | task_create/update, POST/PUT /api/tm/tasks, MCP | title required; description free Markdown | dashboard/task_get, YouGile HTML, acceptance context | free text can contain secrets/PII/prompt injection; Git history retains old text |
| price_rub,paid_rub | task update, payment engine, YouGile import | price >= 0; price cannot go below paid; paid denormalized from allocations | task list/get, debt, YouGile | financial data; projection drift unless formula checked |
| status | create/update; payment_receive; manager/session CAS; YouGile mapping | enum backlog,new,in_progress,done,paid,cancelled; paid payment-engine-only; done may allocate prepayment | lifecycle, dashboard, YouGile, payment distribution | concurrent status/payment edits cannot be LWW |
| assignee,priority | tools/routes; manager assignment; list filter | no DB actor constraint; priority 0-3 | task_list and worker queue | personal data; contour identity needs provenance |
| acceptance_command | orchestrator-only create/update through mcp_proof and acceptance.py | validated one argv command before write | acceptance gate and task detail | executable content; no secrets/shell operators |
| worker_session_id | manager/session lifecycle | local session link, nullable | spawn/switch/merge | ephemeral/nonportable; provenance only |
| git_commits JSON | link_commits_to_task in BEGIN IMMEDIATE; merge route calls after Git merge | valid JSON, dedupe by hash, revision++ | task_get, merge evidence | merge can succeed while link fails; partial state must be explicit |
| yougile_task_id | tm_yougile create/update/import | unique nullable; async sync after local commit; revision avoids stale push | YouGile mirror, retry routes | external ID not canonical; provider data boundary |
| created/updated/completed/paid_at | create/update/payment engine | ISO UTC strings; update bumps revision | list/get and audit | clock skew; preserve source timestamps |
| sync_revision | every mutation/link/allocation; YouGile log; CAS | monotone only per local row; CAS rejects changed revision | stale YouGile push, worker status | cannot order two contours; replace with revision + Git parent |
| tm_clients.id,name,project_id,balance_rub | ensure_client, payment/import | balance = payments - allocations; sanity check | payment tools/routes, YouGile PAR-35 | restricted financial data; private Git only |
| tm_payments.id,client_id,amount_rub,date,note | receive_payment/import | positive amount; insert inside BEGIN IMMEDIATE | payment status/history, task detail, YouGile journal | PII/secrets in note; rowid must become stable payment event ID |
| tm_payment_allocations | distribution, FIFO deduction, import | positive; per-payment sum <= amount; task paid equals allocation sum | task_get, debt, balance, YouGile | cross-file payment/task update must be one canonical commit |
| tm_sync_log | log_sync and YouGile callbacks/retry | pending after local commit; external sync retriable | dashboard sync log/retry | payload/error may contain provider data; keep operational log local/sanitized |

**Current discrepancy.** Historical design specified global tm_par_sequence and atomic UPDATE RETURNING [L2]. Current migration drops it (app/db.py:692-699) and current _next_par is project-local (app/tm.py:63-78). Do not infer a global sequence from the stale design.

**Current boundary.** Task/payment writes are SQLite-atomic, but YouGile sync and merge commit-link are not one transaction: Git merge reaches first, then link_commits_to_task may fail and is returned as partial. Git canonical needs an explicit projection-debt state.

## 2. Measured current scale and write patterns

The live DB was opened read-only and copied with sqlite3.Connection.backup() into :memory:. Only aggregate queries were retained; no row text/secrets were exported.

| Measure | Result |
|---|---:|
| tm_projects / tm_tasks / tm_clients | 19 / 601 / 1 |
| tm_payments / tm_payment_allocations / tm_sync_log | 2 / 3 / 488 |
| Task statuses | backlog 3; cancelled 22; done 393; in_progress 29; new 152; paid 2 |
| Number range / distinct values | 1–299 / 235 (duplicates are across project scopes) |
| Created / updated windows | 2026-05-16..2026-08-23 / 2026-05-20..2026-08-23 UTC |
| Non-empty descriptions / assignees / acceptance commands | 570 / 113 / 21 |
| YouGile IDs / worker sessions / non-empty commit lists | 17 / 64 / 281 |
| sync_revision min / max / average / sum | 0 / 34 / 2.131447587354409 / 1281 |
| sync action/status | create/ok 77; import/ok 218; update/ok 186; journal_update ok 4,error 1; par35_update error 2 |
| Sync terminal totals | pending 0; ok 485; error 3; skipped 0 |
| Linked commit hashes | 486 total; maximum 30 on one task |
| Payment aggregate / allocations | 39,000 units / 3 allocations; both payments fully allocated |
| Allocation invariant | 2/2 payments satisfy allocated <= amount |
| Tasks created by month | May 90; Jun 154; Jul 151; Aug 206 |
| Tasks updated by month | May 54; Jun 146; Jul 181; Aug 220 |
| Revision distribution | rev0 123; rev1 138; rev2 134; rev3 110; rev4 35; rev5 29; rev6 14; rev7 8; rev8 4; rev9 1; rev11 3; rev12 1; rev34 1 |

Interpretation: scale is small enough for full Git replay, but history matters: 601 rows correspond to 1,281 accumulated revisions plus 486 commit links. A shared append-only JSONL would be a merge hotspot; per-task records/events are justified.

## 3. External patterns and format comparison

Git documents that every clone mirrors repository history and is a recoverable backup [W1]. git-merge documents that non-overlapping changes merge, while conflicting hunks stop until explicit resolution [W2]. This is portability/history, not an automatic transaction across Git and a local projection.

Ratings: ++ strong, + workable, ~ conditional, - poor.

| Pattern / real implementation | Mergeability | Concurrent writers | Atomicity | History | Queries | Tool compatibility | Human edits | Secrets/GDPR deletion | Performance | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| Markdown per task + YAML frontmatter | ++ different files; same task conflicts | + distinct tasks; same task needs merge | + file+commit | ++ | ~ scan/index | + adapter | ++ | - old blobs remain | + at 601, index later | ++ clone |
| YAML/JSON per task | ++ | + field-aware same-task merge | ++ schema file+commit | ++ | + parser/index | ++ | YAML +; JSON ~ | - history retention | ++ projection | ++ |
| One append-only JSONL event log | - one path | - append/reorder conflicts | + line after commit | ++ | ~ replay/index | ++ adapter | ~ | - immutable history | + sequential/compaction | ++ if valid |
| SQLite canonical + Git export | ++ export reconciliation | ++ local; cross-contour races | ++ local txn | ~ DB audit only | ++ | ++ | - | + local delete but export history remains | ++ | ~ export not canonical |
| Hybrid Git canonical + SQLite projection | ++ task/event files | + leases + distinct tasks | ++ canonical commit, replayable projection | ++ | ++ SQLite cache | ++ unchanged facade | + | ~ private Git + purge policy | ++ | ++ |
| git-issue (dspinellis) | + issue directories | + decentralized push/pull | ++ Git commit | ++ | + CLI scan | + | ++ | - | + small repos | ++ |
| git-bug | ++ native object DAG | ++ offline/distributed | ++ object commits | ++ | ++ native index | ~ custom adapter | - | - hard purge | ++ | ++ |
| TicGit | ++ git-meta fields | ++ refs/meta transfer | ++ | ++ | ++ local git-meta.sqlite | + | ~ | - | ++ | ++ |
| git-issues Markdown/YAML | ++ one .issues file | + branch-aware | + auto-stage+commit | ++ | + CLI | ++ | ++ | - | + small/medium | ++ |

### Real Git-backed implementations

* git-issue stores transparent text files in per-issue directories, supports tags/assignment/comments and Git push/pull, and uses the opening commit SHA as identity [W3]. It proves editable records/history but needs an alias layer for #N.
* git-bug stores issues/users/comments as Git objects, supports offline/distributed sync and bridges [W4]. It proves richer native Git merge/query, but is not ordinary human-editable files and has hard deletion semantics.
* TicGit stores fields under ticgit:tickets:<uuid>:* in git-meta, exchanges refs/meta, and maintains .git/git-meta.sqlite as a local query DB [W5]. This is real Git-canonical + projection, but UUID-only UX.
* git-issues uses Markdown/YAML frontmatter, branch-aware history, auto-staging and JSON output; its example preserves id: 1 beside .issues/0001-...md [W6].
* beads_rust is counter-evidence against silent export: its safety document defines import/export/three-way merge/rebuild and rejects stale/empty exports [W7]. The independent Toshik1978 beads implementation describes SQLite plus a stable tested JSONL interface [W8]. This validates explicit projection-head and stale checks, not SQLite as final canonical store.

## 4. Identity schemes and #N

| Scheme | UX | Two-contour behavior | Collision/recovery | Verdict |
|---|---|---|---|---|
| Sequential #N alone | excellent | offline forks can select same N | remap breaks links | reject as sole identity |
| UUID/ULID + display #N | #N remains exact | stable merge identity | UUID stable; aliases preserve refs | required base |
| 4-hex content hash | poor | content collisions and edit identity change | At n=601, birthday probability = 1-exp(-601*600/(2*65536)) = 0.936146 (93.6146%); new-item collision against 601 = 601/65536 = 0.9166%; n=1000 pair probability ≈99.9510% | reject |
| Central allocator | excellent contiguous | safe only online; offline create queues | no duplicate, availability dependency | only if no gaps mandatory |
| Per-contour leases | good; no reuse, gaps allowed | offline creates use disjoint blocks | lease commit is allocator | recommended |
| Import remap/alias | old refs remain visible | source #N maps to canonical #N/UUID | never silently renumber | required |

**Recommended identity contract.** Existing (project_id,par_number) becomes display_no and is preserved exactly on backfill. New records use stable_id (UUIDv4/ULID) plus display_no and display_ref "#N"; display_no is unique within project, never reused, allocated from disjoint per-contour leases. Monotonic means allocation order/no reuse; it does not promise timestamp order across disconnected contours. If contiguous global order/no gaps is mandatory, use a central allocator and explicitly give up offline create.

## 5. Exact two-contour Git sync state machine

Contours are A and B. Canonical truth is merged Git commit canonical_head; each SQLite cache stores projection_head. A cache row is never alternate truth.

| Operation | State transition/rule |
|---|---|
| Create | READY(base=H) → allocate unused lease → record + created event → one Git commit C → CANONICAL_COMMITTED(C) → project and set projection_head=C. No lease = CREATE_BLOCKED_NO_LEASE; never guess #N. |
| Ordinary update | Read base_revision; write record + updated event revision=base+1, base_commit=H; commit. Different files auto-merge. Same task disjoint fields may field-merge; overlap → CONFLICT_SAME_TASK. |
| Same-task conflict | Preserve both parent commits/events; no projection/LWW. Resolve explicitly → conflict_resolved event with parents=[A,B], new revision → project. Never auto-resolve status/price/payment/delete/redaction. |
| Delete | Keep record, write tombstone.deleted=true and delete event; reserve number/aliases. Legal history purge is separate. |
| Restore | Explicit actor/reason writes new revision; keep stable_id and #N; never allocate a new number. |
| Status | Normal event under enum rules; paid only from payment transaction; overlapping status edit blocks, not timestamp LWW. |
| Payment | One service operation writes payment.received + all allocation events + affected snapshots in one Git commit; recompute paid/balance and validate before commit. YouGile is post-commit mirror. |
| Commit-link/merge | After known merge commit, write idempotent commit.linked event. Partial/UNKNOWN merge or link failure leaves retryable debt; never claim linked. |
| Import stale | If projection has no uncommitted canonical write, replay fetched head. If dirty local projection, return STALE_LOCAL_PROJECTION and refuse overwrite/export. |
| Partial commit | Before Git commit staged files are invisible; after Git commit before projection Git is truth and next import repairs projection. |
| No-op/fast-forward | Current/ancestor head = no-op; behind head fast-forwards then projects; merge conflicts remain explicit per [W2]. |

**No dual truth.** After cutover tm_* is projection only. Every mutation commits canonical Git first and projects a named canonical head; direct tm_* mutation is invalid.

## 6. Proposed canonical schema

Use one schema-validated JSON record per task with Markdown description, plus immutable per-task event files (generated JSONL is an export/view, not source). This avoids one append-file hotspot:

    .orchestra/tasks/schema.json
    .orchestra/tasks/projects/<project_id>/tasks/<stable_id>.json
    .orchestra/tasks/projects/<project_id>/events/<stable_id>/<revision>-<event_id>.json
    .orchestra/tasks/allocators/<project_id>.json
    .orchestra/tasks/manifest.json

### Complete record example (synthetic values only)

    {
      "schema_version": 1,
      "stable_id": "01J8EXAMPLE7Q2Y7Q4T3M7V5K8A",
      "project_id": "orchestra",
      "display_no": 299,
      "display_ref": "#299",
      "aliases": [{"contour":"legacy-sqlite","ref":"#299"}],
      "title": "Synthetic task title",
      "description_markdown": "Synthetic description; no real client text.",
      "status": "done",
      "priority": 2,
      "assignee": "worker-example",
      "price_rub": 20000,
      "paid_rub": 15000,
      "acceptance_command": "uv run pytest -q tests/test_example.py",
      "worker_session_id": null,
      "yougile_task_id": null,
      "git_commits": [{"hash":"0123456789abcdef0123456789abcdef01234567","linked_at":"2026-08-23T00:00:00Z"}],
      "payments": [{"payment_id":"pay_01J8EXAMPLE","date":"2026-08-23","amount_rub":15000,"allocation_rub":15000}],
      "created_at": "2026-08-20T00:00:00Z",
      "updated_at": "2026-08-23T00:00:00Z",
      "completed_at": "2026-08-22T00:00:00Z",
      "paid_at": null,
      "revision": 4,
      "base_revision": 3,
      "base_commit": "abcdef0123456789abcdef0123456789abcdef01",
      "provenance": {"contour":"A","actor":"orchestrator-example","source_event":"evt_01J8EXAMPLE"},
      "tombstone": null,
      "redaction": null
    }

### Complete event example (synthetic values only)

    {
      "schema_version": 1,
      "event_id": "evt_01J8EXAMPLE",
      "event_type": "payment.allocated",
      "task_id": "01J8EXAMPLE7Q2Y7Q4T3M7V5K8A",
      "project_id": "orchestra",
      "display_no": 299,
      "revision": 4,
      "base_revision": 3,
      "occurred_at": "2026-08-23T00:00:00Z",
      "actor": {"contour":"A","principal":"orchestrator-example"},
      "changes": {"payment_id":"pay_01J8EXAMPLE","allocation_rub":15000,"paid_rub":15000,"status":"done"},
      "parents": ["abcdef0123456789abcdef0123456789abcdef01"],
      "idempotency_key": "payment:pay_01J8EXAMPLE:task:01J8EXAMPLE7Q2Y7Q4T3M7V5K8A",
      "redaction": null
    }

Payment/client notes are restricted. Canonical Git must be private/access-controlled; secret scanning and field classification are mandatory. Tombstone hides current projections but does not erase old Git blobs; legal deletion requires documented history rewrite/remote retention and must be reported as history debt.

## 7. Unchanged facade and service seams

* app/mcp_stdio.py keeps task_create/update/list/get and payment_receive/status signatures.
* app/routes/tm.py keeps /api/tm/tasks and /api/tm/payments/* and sync paths.
* app/tm.py keeps business seams, but canonical writes go through a task store + projection transaction.
* app/routes/sessions.py and app/workspace.py keep #N resolution, branch names and merge commit links; link events expose partial/unknown states.
* app/tm_yougile.py remains after-commit mirror/outbox; never co-master.
* app/db.py retains SQLite for sessions/logs/merge operations and task projection; add canonical_head/projection_head/debt metadata, not rowid identity.

## 8. Migration/backfill/dual-read/cutover/rollback

1. Freeze task writes briefly; take a fresh consistent Connection.backup snapshot and create an immutable migration manifest before export. The manifest must contain backup watermark/time, source schema hash, canonical cutoff/head, and aggregate expectations derived from that exact snapshot; never export raw DB to research.
2. For each task preserve project_id,par_number as display_no; assign deterministic stable ID (UUIDv5 namespace + project + number); stable payment/allocation IDs; write aliases for #N/plain/prefix refs.
3. Backfill task/payment/allocation records and migration events deterministically; revision 0 and source=sqlite-backfill.
4. Build fresh projection; compare normalized records/invariants against the immutable manifest snapshot; keep old DB read-only as rollback artifact.
5. Dual-read shadow: existing tools use SQLite while Git replay compares normalized responses. Difference = fail-closed projection debt, never stale SQLite wins.
6. Cutover at pinned canonical_head; mutations commit Git first and synchronously project or report debt; direct tm_* writes rejected.
7. Rollback by pinning known-good Git commit and rebuilding SQLite; do not accept divergent direct DB edits; replay canonical events after fix.

### Mechanical acceptance tests for future implementation

* Backfill parity: exact counts and commit-hash multiset must equal the immutable migration manifest derived from the frozen backup (task/project/payment/allocation/sync/link counts); do not hard-code a research-time count. Zero duplicate (project,display_no); all stable IDs resolve.
* Baseline watermark: the earlier Phase-1 snapshot recorded 601 tasks, 19 projects, 2 payments, 3 allocations, 488 sync rows and 486 linked hashes; a later live recheck on 2026-08-23 recorded 601/19/2/3/488 but 489 linked hashes. This one-write drift proves that migration expectations must come from the fresh frozen manifest, not either observed baseline.
* Replay parity: fresh SQLite from canonical HEAD equals frozen normalized tool output after removing only explicitly volatile rowids/session IDs/timestamps.
* Money: allocation <= payment amount; task paid = allocation sum; balance = payments − allocations; zero-price and partial-payment cases.
* Two-contour creates: A/B offline from disjoint leases yield distinct stable IDs/#N; same-task overlap blocks; disjoint fields merge.
* Delete/restore: tombstone hides without freeing #N; restore preserves stable ID/#N and aliases.
* Partial commit: failure after Git commit before projection converges on next import; failure before commit leaves no record.
* Merge-link retry is idempotent and never claims link for partial/unknown merge.
* Stale import returns STALE_LOCAL_PROJECTION and does not overwrite/export stale data.
* Existing MCP/HTTP golden fixtures preserve refs, filters, debt, status, assignee, payments and commits.
* Synthetic secret scan is zero; redaction reports history debt, not false blob deletion.

## 9. Failure matrix/rejected alternatives

| Failure/alternative | Evidence-based result | Decision |
|---|---|---|
| Two contours both MAX+1 | duplicate next number after offline fork | reject; leases/central allocator |
| 4-hex content hash | 93.6146% pair-collision probability at current scale | reject |
| One append-only JSONL | one merge-hotspot path and append order conflict | reject as primary; export allowed |
| SQLite canonical + JSONL export | stale/empty export requires side choice; portability goal unmet [W7] | reject final |
| One Markdown index | one hot file and large diffs | reject; one task/file |
| Git only/no projection | filters/payment joins become replay scans and regress facade latency | reject |
| Last-write-wins | loses status/price/payment/redaction edits | reject |
| Physical delete | loses refs and still leaves old Git blobs | reject; tombstone + legal purge |
| Public Git with secrets/payment notes | clone becomes data leak | reject; private + classification |
| YouGile co-master | original design says Orchestra source, YouGile mirror [L2] | reject |
| SQLite rowid as Git ID | import/rebuild can renumber | reject; UUID/ULID |

## 10. Quantitative decision criteria

All hard gates must pass before implementation is accepted:

1. Identity: 100% backfilled rows retain project-scoped #N; 0 duplicate (project,#N); 0 reused tombstones; 100% old ref spellings resolve.
2. Parity: 100% of records, aggregates and commit-hash multiset equal the immutable migration manifest captured from the fresh frozen backup at the canonical cutoff; 0 unclassified diffs. The 601/19/2/3/488/486 and later 601/19/2/3/488/489 observations are timestamped baselines only, never acceptance constants.
3. Money: 0 violations of allocation <= payment, paid=sum allocations, balance formula and status/payment rule across baseline plus 10 synthetic edge cases.
4. Conflict safety: 0 silent resolutions of overlapping status/price/payment/delete/redaction edits in at least 100 repeated A/B scenarios.
5. Recovery: 100% pre-commit failures leave no canonical mutation; 100% post-commit/pre-projection failures converge; clone recovers without source SQLite.
6. Facade: 100% existing MCP/HTTP golden fixtures; no signature/response-field removal.
7. Privacy: 0 secret-pattern hits in canonical fixtures; restricted-field policy documented; redaction never claims blob erasure.
8. Freshness: projection_head equals canonical_head after successful write; all forced stale cases detected; manifest watermark and canonical cutoff are persisted and displayed.
9. Performance: p95 task_list/task_get no worse than 2x frozen SQLite baseline and <1s at 601 rows; replay of 10,000 synthetic records <30s. These are future acceptance thresholds, not current measurements.
10. Portability: clean clone with no orchestra.db reconstructs normalized task/payment projection; diagnostics report canonical head, projection head and debt/conflict counts.

## Counter-evidence and confidence

* CONFIRMED — schema/writers/routes/merge ordering are in local source; live aggregates are reproducible from Connection.backup(:memory:).
* CONFIRMED — Git clone history/recovery and explicit conflict stops are documented by Git [W1][W2] and reflected in git-issue/git-bug/TicGit/git-issues [W3-W6].
* CONFIRMED — Git-canonical plus local query projection is real: TicGit documents git-meta plus .git/git-meta.sqlite [W5], while beads_rust and the independent beads implementation document import/export/three-way merge/rebuild or a stable JSONL interface [W7][W8].
* LIKELY — per-contour leases are the smallest two-contour allocator preserving #N without online lock; needs implementation-time concurrency tests and user acceptance of gaps.
* UNCERTAIN — legal permission to put payment/client notes in private Git was not supplied; technical redaction is not GDPR erasure.
* REFUTED — old global tm_par_sequence is current; migration drops it and _next_par is project-local.

## Review route

No model/provider/eval/review calls were made, per explicit task prohibition. The codex-debate gate was loaded; this is high-risk persistence/privacy architecture, so the normal reviewer would require a model call and was intentionally not invoked. Mechanical completeness/self-adversarial checks covered all ten required artifact areas, local source lines, measurements and fetched primary sources. No review artifact exists because no review call occurred.

## Affected files, risks, edge cases

Future plan likely touches app/db.py, app/tm.py, app/routes/tm.py, app/mcp_stdio.py, app/routes/sessions.py, app/workspace.py, app/merge_operations.py and app/tm_yougile.py. Keep sessions/logs/merge DB tables local; task tables become projection.

Risks: project-scoped duplicate numbers; two offline creates; same-task status/payment race; partial allocation; zero-price task; YouGile create before projection; merge known but link failed; tombstone restore; stale cache; Git/projection partial failure; scope path leak; acceptance command executable content; history rewrite legal deletion.

## Sources

Local primary sources opened in this session:

[L1] app/db.py:279-352, 692-766 — current schema/migration.
[L2] docs/archive/research/task-manager-design.md:30-130, 276-332, 367-429, 528-675 — historical task/payment/YouGile design.
[L3] app/tm.py:63-78, 220-529, 581-814, 935-1201 — current logic/transactions/invariants.
[L4] app/routes/tm.py:12-230 and app/mcp_stdio.py:2042-2157 — facade.
[L5] app/routes/sessions.py:1372-1501, 1553-1702 and app/workspace.py:864-890 — merge/task links/CAS.
[L6] Safe snapshot: sqlite3.Connection.backup() from /mnt/data/Projects/Python/orchestra/data/orchestra.db into :memory:, aggregate-only queries, 2026-08-23.

External primary sources fetched:

[W1] Git SCM, About Version Control — https://git-scm.com/book/en/v2/Getting-Started-About-Version-Control.html
[W2] Git SCM, git-merge — https://git-scm.com/docs/git-merge
[W3] Diomidis Spinellis, git-issue README — https://github.com/dspinellis/git-issue
[W4] Michael Muré, git-bug README — https://github.com/git-bug/git-bug
[W5] TicGit README — https://github.com/schacon/ticgit
[W6] git-issues project docs — https://steviee.github.io/git-issues/
[W7] beads_rust SYNC_SAFETY.md — https://github.com/Dicklesworthstone/beads_rust/blob/main/docs/SYNC_SAFETY.md
[W8] Toshik1978 beads README/storage description — https://github.com/Toshik1978/beads

## Scope note

docs/kb/README.md was not modified: explicit hard scope permits only docs/kb/task-storage-architecture.md under docs/kb; orchestrator may add the index entry only if scope is widened.
