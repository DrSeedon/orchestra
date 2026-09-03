# #248 — Task Manager integration audit

## Question

- **Context:** the live Orchestra Task Manager, all five named orchestrator projects, their
  sessions/logs, and the corresponding Git repositories.
- **Change under test:** none in Phase 1. This phase measures whether Task Manager is an
  authoritative representation of real work.
- **Baseline:** a numbered unit of work exists before execution, a worker carries that identity,
  commits link back to the same project/task, and status follows the actual lifecycle.
- **Deciding outcomes:** task-tool calls by orchestrator/project; set differences between tracker
  rows and `^#N:` subjects in each repository's `main`; task/worker/status contradictions; worker
  sessions with empty `task_id` and commits; scope-less task namespaces; and content evidence for
  all 28 canonical `in_progress` tasks.

## Hypotheses considered

1. **H1 — Task Manager is a write-side side channel, not lifecycle authority.** Agents create
   and occasionally update rows, while optional `task_id`, merge, and status paths allow work to
   proceed without keeping those rows authoritative.
   - **Falsifier:** reads are routine, numbered commits reconcile with tracker rows by project,
     and task status/worker links agree with current work.
2. **H2 — The apparent drift is mostly stale display data.** Code-owned spawn/merge hooks preserve
   the underlying associations even if the dashboard looks old.
   - **Falsifier:** a WAL-consistent snapshot contains missing task identities, committed work on
     `new` rows, or `in_progress` rows with archived/no workers.
3. **H3 — Free-string project identity is the dominant defect.** After excluding ghost projects,
   lifecycle use is consistent.
   - **Falsifier:** substantial drift remains inside canonical scope-bound projects.

## Method and counting rules

The live database was opened read-only and copied with `sqlite3.Connection.backup()`; `cp` was
not used. Snapshot: `/home/kesha/orchestra/data/task248-live-IpricQ.db`, SHA-256
`416c7cfac741cf4c2f9966bcc5f3e014db7dddacb4c75bf18d025f5e0af92126`, 241,143,808 bytes.
It contains logs through `2026-08-13T06:37:36.371388+00:00`. No query selected full
`logs.content`; event extraction used `substr(content,1,200)` [E1][E2].

Counting rules were fixed before synthesis:

- orchestrator universe = `is_orchestrator=1 OR role IN ('orchestrator','sub-orchestrator')`;
  the flag alone misses the root Orchestra and Seedon orchestrators;
- task calls = `logs.type='tool'` and either the exact structured `tool_name`, or a separate
  legacy row with empty `tool_name` whose 200-character prefix starts with that exact MCP name;
- commit universe = current `main` subjects matching `^#([0-9]+):`, grouped by repository and
  project scope; secondary numbers in subjects such as `#A, #B:` are intentionally not counted;
- “live worker” = a linked session whose stored status is `idle`, `running`, or `waiting`;
- the 28-task audit = `status='in_progress'` in a project with non-empty registered scope. The
  snapshot actually has 66 `new` rows and 31 `in_progress` rows; three of the latter are in
  scope-less ghost projects [E3][E4].

## Findings

### F1 — Orchestrators do use Task Manager, but overwhelmingly as a write path

**CONFIRMED — direct measurement, tier 1.** Across the snapshot there are 331 creates, 348
updates, 20 lists, and 25 gets by the six orchestrator-role sessions: 679 writes to 45 reads
(15.1:1). Every recorded project except University has at least one create/update, but browsing
is rare or absent [E2].

| Scope / orchestrator | create | update | list | get | days with any task call |
|---|---:|---:|---:|---:|---:|
| `/home/kesha/orchestra` / `Orchestra-orchestrator` | 180 | 202 | 12 | 10 | 11 |
| Seedon / `seedon-orchestrator` | 121 | 95 | 6 | 6 | 11 |
| Seedon / `dev-lead` | 19 | 43 | 1 | 9 | 9 |
| `kesha-tg-bot` orchestrator | 10 | 7 | 1 | 0 | 4 |
| `dnd-game-master` orchestrator | 1 | 1 | 0 | 0 | 2 |
| University orchestrator | 0 | 0 | 0 | 0 | 0 |

This refutes “nobody uses it.” The 6.2% list/get share suggests that explicit task-tool retrieval
is not routine, but does not establish every consultation path: dashboard/API reads, state returned
by create/update, and task state injected into prompts were not measured.

### F2 — Number allocation and Git history have diverged in both directions

**CONFIRMED — direct Git/SQLite set comparison, tier 1.** There are 132 distinct repository/task
numbers in the requested strict `^#N:` position on `main` with no task `N` in that repository's
registered project. The known `#243` and `#244` are in this set. Scanning every `#N` in a leading
comma-separated header such as `#219, #188:` raises the forward count to 137 [E3].

| Repository | missing tracker: primary `^#N:` | missing tracker: any leading header ref | tracker rows with no primary ref | tracker rows with no leading header ref |
|---|---:|---:|---:|---:|
| Orchestra | 67 | 70 | 34 | 23 |
| Seedon | 48 | 50 | 45 | 35 |
| kesha-tg-bot | 16 | 16 | 2 | 2 |
| University | 1 (`#6`; no project row) | 1 | 0 | 0 |
| dnd-game-master | 0 | 0 | 0 | 0 |
| **Canonical total** | **132** | **137** | **81** | **60** |

Eight more tracker rows live in scope-less projects, so the registry cannot name a repository in
which to test the reverse relation. For mapped projects, 60 tracker rows have no reference anywhere
in the recognized leading task header; 81 is only the upper bound produced by looking at the first
number. The eight ghost rows remain structurally unreconcilable and are not added to either count
[E3].

The mechanism is visible in current source: `spawn_worker(..., task_id="")` permits an empty task
identity and creates a `feat/...` branch; merge commit linking reports `TASK_NOT_FOUND` per task
reference but does not roll back an already successful Git merge [S1][S2][S3]. A prompt reminder
cannot make these states impossible.

### F3 — Status is not a lifecycle projection

**CONFIRMED — direct snapshot plus Git main, tier 1.** The contradictions are systematic [E3]:

- `in_progress`: 31 total; 28 canonical and 3 ghost. Of the 28 canonical rows, **17 have no live
  linked worker**: 14 point to archived sessions and 3 have no `worker_session_id`; 11 point to a
  non-archived session.
- `new`: 66 total. **23 already contain linked commits** and 21 have an exact `^#N:` subject on
  `main`.
- `done`: 229 total. Nine have an empty `git_commits` list, but all nine have an exact matching
  `^#N:` commit on `main`; none is truly “done with no Git evidence.” The nine are Orchestra #15,
  Seedon #59/#113/#115/#119, and kesha-tg-bot #1/#3/#4/#5.

The source explains the asymmetry. Spawn writes `in_progress` and a scalar
`worker_session_id`. A successful merge then quarantines/clears the session's task identity, but
does not mark the current task `done`. Switch/merge-next can set the next task `in_progress`
without storing the worker id. Commit linking can add commits while leaving a manually created
task `new` [S1][S2]. The data therefore matches the code contract; it is not a dashboard-only
bug.

### F4 — Empty worker `task_id` is common, but does not equal “untracked work” one-for-one

**CONFIRMED for the counts; REFUTED for the naive interpretation — direct measurement plus source,
tier 1/2.** There are 152 non-orchestrator sessions with an empty `task_id` and a non-empty branch;
132 branch refs still exist. `git cherry main <branch>` finds 26 sessions with at least one
patch-unique commit: 23 archived and 3 idle. Fourteen of those sessions are still referenced by a
task's scalar `worker_session_id`; 12 have no reverse task→worker link [E3].

This is not proof of 26 independent jobs that never had tasks. Post-merge quarantine deliberately
clears `sessions.task_id`, squash merges make original branch commits patch-different from the
squash, and a task stores only one worker id even when several children contribute. What is proven
is narrower and still damaging: after completion the database cannot reconstruct the many-to-one
worker/task history from its durable identity columns alone [S2].

### F5 — Project identity already contains live ghost namespaces

**CONFIRMED — direct snapshot, tier 1.** Three `tm_projects` rows have an empty scope:
`Orchestra`, `Seedon`, and `orchestra`. They contain eight tasks: three `in_progress`, two `new`,
and three `cancelled`. Conversely, `/home/kesha/projects/University` has an orchestrator and Git
repository but no `tm_projects` row. The canonical `/home/kesha/orchestra` project is valid even
though `sessions.is_orchestrator=0` on its root orchestrator; role data is the only reason the
usage audit did not omit it [E2][E3].

The fix belongs to #246 and is intentionally out of scope here.

### F6 — Audit of all 28 canonical `in_progress` tasks

**CONFIRMED where the requested artifact/behavior is present or explicitly absent; LIKELY for
classification of multi-stage tasks.** Every row was checked against `main`, not the worker
branch. Raw commands and outputs are in [E4].

| Task | Verdict | Content evidence / reason |
|---|---|---|
| Orchestra #1 | **already done** | `is_owner_mode()` and `OWNER_MODE` gates exist in main |
| Orchestra #2 | **already done** | report records identical 52-node chats across a switch, no duplicate ids, session-id invalidation, and identical DOM after a real tail message |
| Orchestra #8 | **already done** | `/api/logs/sync`, IndexedDB client, report and verification artifacts exist |
| Orchestra #123 | **already done** | requested HTML and PNG artifact exist |
| Orchestra #144 | **already done** | precompact fixture pins `AUTO_COMPACT_ENABLED=1` |
| Orchestra #150 | **already done** | nullable usage snapshot path and migration/report exist |
| Orchestra #161 | **already done** | refusal body storage/rewind fix and tests exist |
| Orchestra #174 | **actual** | T1/T2 exist, but `t3-canary.md` says T3 is intermediate and UX/status work remains |
| Orchestra #187 | **actual** | T1 report explicitly leaves T2–T6; manifest policy remains commented/inert |
| Orchestra #198 | **already done** | Phase 3 report says T1/T2 complete and review approved |
| Orchestra #201 | **already done** | cache-write accounting exists; Spark is deliberately unpriced (`None`) |
| Orchestra #208 | **actual** | research explicitly says the long-chain effort question was not measured |
| Orchestra #211 | **actual** | report is “T1 only”; T2–T5 remain behind their gates |
| Orchestra #219 | **actual (partially superseded)** | fan/barrier outcome shipped under #231, but #219 plan explicitly leaves T3 and the corpus divisibility recount undone |
| Orchestra #220 | **already done** | Phase 3 report covers T1–T4 and main contains the implementation |
| Orchestra #221 | **already done** | Telegram formatting block is in the orchestrator role prompt |
| Orchestra #223 | **already done** | Phase 3 report covers T1–T3; delegation/oracle contract is in main |
| Orchestra #231 | **already done** | fan tables, barrier, reducer/mailbox path and report exist; live session notes confirm use |
| Orchestra #232 | **already done** | the “should we add Grok?” research answered **DEFER** with explicit limits |
| Orchestra #235 | **already done** | production-DB test guard/follow-up and report are in main |
| Orchestra #238 | **actual** | reviewed plan and RED acceptance test exist; implementation is absent |
| Orchestra #248 | **actual** | this research had no artifact at snapshot time |
| kesha-tg-bot #2 | **already done** | 10-second passive handoff timeout/injection path and task docs exist |
| Seedon #3 | **already done** | main contains the requested task-specific amounts and dates: 14,654.78 RUB July net advance, 2,190 RUB NDFL, 137.27 RUB compensation, plus filing windows and form reconciliation |
| Seedon #112 | **already done** | detail tests assert stored full-dialog ordering and 50 rendered bubbles; typing tests cover start/repeat/stop, error/cancel, and no typing for instant commands |
| Seedon #123 | **already done** | `done.md`, measurements, production verification and landing changes exist |
| Seedon #161 | **already done** | requested research with sources and conclusions exists |
| Seedon #169 | **actual** | worker is running; requested `docs/tasks/169` artifact was absent from main |

Totals: **20 already done, 8 actual (one partially superseded), 0 whole-task duplicates, and 0
unsupported “stale” labels**.
The tracker itself would have reported all 28 simply as `in_progress`.

### F7 — Root cause is split ownership, not agent forgetfulness alone

**CONFIRMED — source paths reproduce every measured class, tier 2, and live counts agree.** Task
identity currently has several independent owners:

1. an agent may call `task_create` and remember the returned number;
2. `spawn_worker.task_id` is optional;
3. the Git branch/commit subject carries a number independently;
4. `tm_tasks.worker_session_id` stores only one worker;
5. post-merge quarantine clears `sessions.task_id`;
6. merge links commits but does not own the current task's terminal status;
7. `task_update` remains the manual terminal-status path.

Forgetting a prompt step therefore creates states that production code accepts. H1 is supported
and H2 is refuted. H3 is independently refuted by canonical-only measurements: 17/28 canonical
in-progress rows have no live worker, 132 primary commit numbers lack a tracker row, and 23 `new`
rows already contain linked work. No ghost task was subtracted from the 28-task denominator.

## Counter-evidence and limits

- Task creation is not generally forgotten: task calls are frequent, and the 331 observed create
  calls equal the 331 current task rows. Equality is not asserted as a one-to-one causal mapping;
  failed calls/results were not joined.
- `task_id=''` after merge is deliberate quarantine behavior, so treating all 26 commit-bearing
  sessions as untracked work would overstate the defect.
- `^#N:` is the user's requested strict selector and yields 132 forward misses. Expanding only the
  recognized leading comma-separated header adds five misses (137). The reverse relation is 60
  rows with no recognized header reference; arbitrary `#N` strings later in prose were deliberately
  excluded to avoid treating incidental references as task ownership.
- Stored `git_commits` often contain pre-squash worker hashes. Of 528 stored links, 346 are not
  ancestors of current `main` (Orchestra 281/285, Seedon 64/240, kesha-tg-bot 1/2; DND 0/1).
  This is consistent with squash/history rewriting and means hash reachability cannot replace
  subject/content checks.
- A file/symbol present in main proves delivery, not that a human-facing external action remains
  current. The three challenged “done” rows now use task-specific reports/assertions [E5]; that is
  why #174/#187/#208/#211/#219/#238 stay actual despite substantial artifacts.
- The snapshot is a point-in-time audit. #246 was already in progress and no code from it was
  evaluated as a completed fix.

## Affected files, risks, and edge cases for Phase 2

- `app/manager.py` — optional task identity at spawn; initial `in_progress`/worker binding.
- `app/routes/sessions.py` — merge, quarantine, next-task switch, commit linking, terminal status.
- `app/workspace.py` — `feat/...` branch when `task_id` is empty; `task-N/...` otherwise.
- `app/tm.py` — task identity, scalar worker binding, commit links, status update APIs.
- `app/mcp_stdio.py` — optional `task_id`, manual create/update/list/get surface.
- `app/db.py` — task/project/session schema; no durable many-worker task relation or enforced
  lifecycle state machine.
- Risks: cross-project ambiguity; merge succeeds while tracking fails; squash makes stored commit
  hashes non-durable; one task may have multiple workers; research tasks may legitimately finish
  without production code; cancelled/negative-result tasks need a terminal state distinct from
  “no work”; a terminal transition must not mark a partial phase done.

Phase 2 must apply the repository's prompt-vs-code test: if forgetting or over-applying a rule can
permit an untracked merge, wrong-project mutation, or lost lifecycle state, the invariant belongs
in code. Prompt text is eligible only for choices whose failure in either direction degrades to
today's safe behavior.

## Sources

1. **[E1, tier 1 direct measurement]** WAL-consistent SQLite snapshot described above; extraction
   SQL and validation in [`evidence/tool-method.txt`](evidence/tool-method.txt) and
   [`evidence/reconcile-method.txt`](evidence/reconcile-method.txt).
2. **[E2, tier 1 direct measurement]** Per-orchestrator/project tables:
   [`tool-usage-by-orchestrator.tsv`](evidence/tool-usage-by-orchestrator.tsv),
   [`tool-usage-by-project.tsv`](evidence/tool-usage-by-project.tsv), and the primary+legacy
   operation expansion [`tool-usage-expanded.tsv`](evidence/tool-usage-expanded.tsv). Legacy
   operation totals were parsed only when the 200-character prefix began with the exact MCP tool
   name.
3. **[E3, tier 1 direct measurement]** Full mechanical tables:
   [`commit-task-reconciliation.tsv`](evidence/commit-task-reconciliation.tsv),
   [`reconciliation-summary.tsv`](evidence/reconciliation-summary.tsv),
   [`status-worker-evidence.tsv`](evidence/status-worker-evidence.tsv),
   [`taskless-worker-commits.tsv`](evidence/taskless-worker-commits.tsv), and
   [`project-inventory.tsv`](evidence/project-inventory.tsv). SQLite validation and compact
   aggregates are in [`snapshot-aggregates.txt`](evidence/snapshot-aggregates.txt); all Git counts
   are tied to [`git-refs.txt`](evidence/git-refs.txt).
4. **[E4, tier 1 direct measurement]** 28-row audit table
   [`open-tasks.tsv`](evidence/open-tasks.tsv), counting method
   [`open-method.txt`](evidence/open-method.txt), and raw main-ref command outputs under
   [`evidence/open-evidence/`](evidence/open-evidence/).
5. **[E5, tier 1 task-specific stored verification]** Strengthened completion evidence for
   [`Orchestra #2`](evidence/open-evidence/home-kesha-orchestra-2-completion.txt),
   [`Seedon #3`](evidence/open-evidence/seedon-3-completion.txt), and
   [`Seedon #112`](evidence/open-evidence/seedon-112-completion.txt), extracted from their pinned
   main reports, tests, and implementation.
6. **[S1, tier 2 primary source]** `app/manager.py:761-914` — optional task resolution and spawn
   transition; `app/workspace.py:492-512` — branch identity.
7. **[S2, tier 2 primary source]** `app/routes/sessions.py:1048-1305` — merge/link/quarantine and
   next-task transition; `app/routes/sessions.py:1360-1510` — branch switch/task transition.
8. **[S3, tier 2 primary source]** `app/tm.py:339-434,958-1017` — project-scoped task resolution,
   non-transactional-to-Git commit linking, and CAS status update.
9. **[S4, tier 2 primary source]** `docs/tasks/93/research.md` and
   `docs/tasks/169/research.md` — prior measured task authority/cross-project failure modes,
   verified against current source before use.

## Second opinion

Codex round 1 returned **CHANGES REQUESTED**. It identified an overstated reverse-reconciliation
denominator, a behavioral inference not proved by tool-call counts, weak evidence for three “done”
rows, a misclassified partially complete #219, a ghost/canonical denominator mix-up, and missing
snapshot validation artifacts. All six findings were accepted and changed; the final round and
verdict are recorded in [`codex-review-research.md`](codex-review-research.md). Round 2 marked all
six findings **FIXED**, found no new blocking/suggestion/question, and returned **APPROVED**.
