# #412 — План project-local раздачи knowledge

План составлен после Phase-1 gate и решений пользователя 2026-08-28.

## Зафиксированные решения

- Backup **не делается**. Отсутствие резервной копии и remote принято пользователем как риск;
  это больше не gate и повторно не предлагается.
- Live T2 выполняется только как `--apply` **без `--commit`**: владелец проекта сам решает,
  добавлять ли `docs/kb/` в Git. До такого решения знания не бэкапятся и не приезжают в clone —
  это принятое следствие выбранного режима.
- Все project knowledge records раздаются в `<project>/docs/kb/`; shared central cache не остаётся.
- `/mnt/data/media` уже Git repo: current HEAD `35e1a2e2f0a9f24a22616cff11d5dfbac6d4ec94`,
  clean, tracked ровно `.gitignore` и `CLAUDE.md`; remote отсутствует и не блокирует работу.
- Отсутствие remote у любого repo — свойство, не blocker. Push запрещён во всех repo.
- Порядок неизменен: byte-preserving landing → count/SHA/no-local-clone parity → один
  global owner switch → 764 facts → central cleanup → prompt delivery.
- Central cleanup — отдельный последний behavioral ticket; до него source не удаляется.

## Hard Phase-3 stop

Этот turn заканчивается на `PLAN READY`. **Ни T1 implementation, ни T2 `--apply`, ни один
foreign-repo commit не запускаются до следующего явного сообщения оркестратора, разрешающего
Phase 3.** Dry-run против live destinations также ждёт этого gate; до него разрешены только
read-only проверки и frozen tests в текущем worktree.

## Scope и границы записи

### Orchestra repository

Новые/изменяемые implementation files:

- `app/ia/project_distribution.py` — frozen inventory, local commits, per-project manifests;
- `scripts/distribute_project_knowledge.py` — dry-run/apply/verify CLI;
- `app/ia/project_knowledge.py` — process-global per-project owner/router;
- `app/ia/project_cleanup.py` — fail-closed central cleanup;
- `app/ia/runtime.py`, `app/ia/knowledge.py`, `app/ia/projections.py` — routing integration;
- `app/routes/knowledge.py`, `app/routes/memory.py`, `app/mcp_stdio.py` — agent/API delivery;
- `scripts/kb_promote_facts.py` — existing 764-fact conversion to project-local JSON;
- `app/ia/cutover.py` и семь prompt-owner files — final owner semantics;
- focused tests and `docs/tasks/412/{distribution-manifest.json,report.md}`.

### Foreign repositories

Разрешены только:

- create/update files under `<repo>/docs/kb/`;
- live T2 использует `--apply` без commit: файлы остаются uncommitted, HEAD и весь index
  не меняются; commit-capable ветка остаётся протестированной, но в живом проходе запрещена;
- a temporary `--no-local` clone outside the repo for verification.

Запрещены: code/config edits, existing-history rewrite/rebase, branch deletion, push/fetch/pull,
remote changes, cleanup outside `docs/kb/`. `/mnt/data/media` obeys ту же границу.

### Quarantine

Live records без reachable/unique owner пишутся только в
`/mnt/data/Projects/_orchestra-orphans/<project_id>/docs/kb/records/` и входят в manifest.
Ни одна запись не выбрасывается и не переназначается по basename.

## Таблица раздачи перед стартом

Read-only срез: 2026-08-28 02:37:56 UTC; central HEAD
`b8d30ee2943dc3b93b3ace33a7f188f8b259f84d`; counts не изменились с research.
T2 перед apply повторно вычисляет frozen HEAD/counts; drift останавливает проход и обновляет
manifest, а не подгоняет эти числа молча.

| Project | Records | Точный destination directory |
|---|---:|---|
| `orchestra` | 12,759 | `/mnt/data/Projects/Python/orchestra/docs/kb/records/evidence/` |
| `cog-second-brain-77dd306ac2a0` | 5,106 | `/home/maxim/Рабочий стол/Cursor/COG-second-brain/docs/kb/records/evidence/` |
| `scope-mnt-data-projects-comfy-image-pipeline-11e5d3b4b1f9` | 1,728 | `/mnt/data/Projects/comfy-image-pipeline/docs/kb/records/evidence/` |
| `seedon` | 321 | `/mnt/data/Projects/Python/seedon/docs/kb/records/evidence/` |
| `sensar-5e197e867bb2` | 180 | `/home/maxim/Рабочий стол/Cursor/Sensar/docs/kb/records/evidence/` |
| `tradingcryptobot` | 177 | `/mnt/data/Projects/Python/TradingCryptoBot/docs/kb/records/evidence/` |
| `mnt-data-projects-python-claude-code-game-master-ccdad4e9b586` | 152 | `/mnt/data/Projects/Python/Claude-Code-Game-Master/docs/kb/records/evidence/` |
| `mnt-data-projects-python-aperant-0972b1340a75` | 112 | `/mnt/data/Projects/Python/Aperant/docs/kb/records/evidence/` |
| `kesha-tg-bot` | 96 | `/mnt/data/Projects/Python/kesha-tg-bot/docs/kb/records/evidence/` |
| `polus` | 86 | `/home/maxim/polus/docs/kb/records/evidence/` |
| `university` | 77 | `/mnt/data/Projects/University/docs/kb/records/evidence/` |
| `vpn-service-7c16d6f598b1` | 75 | `/mnt/data/Projects/Python/VPN-Service/docs/kb/records/evidence/` |
| `parsing-hub` | 43 | `/mnt/data/Projects/Python/Parsing/docs/kb/records/evidence/` |
| `stargate-tactics` | 12 | `/mnt/data/Projects/Python/stargate-tactics/docs/kb/records/evidence/` |
| `mnt-data-projects-unity-defaultprojectunity-317002a674e4` | 10 | `/mnt/data/Projects/Unity/DefaultProjectUnity/docs/kb/records/evidence/` |
| `mnt-data-projects-python-games-b14eae05bed5` | 9 | `/mnt/data/Projects/Python/games/docs/kb/records/evidence/` |
| `webview-c212de852078` | 5 | `/mnt/data/Projects/Python/WebView/docs/kb/records/evidence/` |
| `mnt-data-media-30494f74a194` | 0 | `/mnt/data/media/docs/kb/records/evidence/` |
| **Итого** | **20,948** | 18 Git repositories |

## Manifest и landing contract

Каждый project получает собственный `docs/kb/manifest.json` с record-level
`stable_id/path/size/SHA-256`; детали чужого project не копируются в Orchestra.
`docs/tasks/412/distribution-manifest.json` — engine migration receipt только с per-project
count/digest/repo/commit/fresh-clone result, без массива foreign records.

Для каждого repo T2 фиксирует независимо от выбранного режима:

1. `before_head`, `target_commit`, `git status` до/после;
2. commit mode: changed commit paths — непустое подмножество `docs/kb/**`; uncommitted mode:
   HEAD прежний, а dirty paths создаются только под `docs/kb/**`; media в обоих режимах получает
   `docs/kb/{manifest.json,.gitattributes}`;
3. per-project count и digest sorted raw bytes;
4. SHA каждого target blob = source SHA;
5. direct working-tree receipt: каждый target file перечитан с диска и совпал с source SHA;
6. remote refs before/after одинаковы; при remote=0 фиксируется пустой map;
7. quarantine records/count/reason, если live mapping изменился.

## Migration/cutover rules

- Global owner остаётся `central`, пока T2 manifest не `verified` по всем 18 repo.
- T3 activation принимает один immutable map `project_id→target_commit`; один missing/mismatched
  head оставляет generation central целиком — per-project partial activation запрещена.
- T4 не переизвлекает facts: input — ровно `docs/tasks/kb-extract/part-1..5.json`;
  764→764, current/rejected 689/75, null date/reason 275/397.
- T5 cleanup сначала повторяет T2/T3 parity; `prepared`, quarantine mismatch или head drift
  отказывают до первой mutation. Engine registry/sessions/quotas/receipts не удаляются.
- T6 prompts меняются только после live project-local read/write success; literal `docs/kb/`
  сохраняется.

## Tickets

### T1 — Byte-preserving distribution engine

- Files: `app/ia/project_distribution.py`, `scripts/distribute_project_knowledge.py`,
  `tests/test_project_knowledge_distribution_412.py`.
- Test: `uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t1_byte_preserving_distribution_is_scoped_and_manifested` — committed RED in `4ed3c8fb`.
- RED: `AssertionError: T1 missing app.ia.project_distribution`.
- AC: named command is green; actual CLI `--dry-run`, `--apply --commit`, and `--verify` paths
  plus alternate `--apply` without commit execute through an independent Git command gate;
  dry-run preserves every source/destination/
  quarantine worktree file, status, ref, config and registry byte; apply preserves source HEAD/bytes, writes only `docs/kb/**`,
  creates per-project manifests and, only in commit mode, local commits; uncommitted mode preserves
  HEAD and all foreign worktree/index snapshots, is idempotently resumable, and passes independent
  `--verify`; both modes leave all remote refs/config unchanged and invoke
  no push/pull/fetch/remote/reset/rebase subcommand, and quarantines an unmapped project explicitly.
- blocked-by: none.

### T2 — Live 18-project landing and parity receipt

- Files: only the 18 `docs/kb/` destinations in the table; local commits in those repos;
  `docs/tasks/412/{distribution-manifest.json,git-command-log.jsonl}`;
  `docs/tasks/412/report.md` evidence section.
- Test: `uv run pytest -q docs/tasks/412/acceptance/test_t2_live_distribution.py::test_t2_live_distribution_matches_frozen_manifest` — committed RED in `4ed3c8fb`.
- RED: `AssertionError: T2 distribution manifest missing`.
- AC: named command is green with the exact 18-row `project_id→repository_root→record_count`
  mapping from this plan; the oracle reads raw bytes independently from pinned central Git,
  resolves production `state_root`, requires current central HEAD and scope-registry SHA to equal
  the frozen receipt,
  recomputes per-project digests, proves byte-equality in target commits, creates real
  `git clone --no-local --no-checkout` copies with no alternates and rechecks digests there,
  requires unchanged HEAD and raw Git index digest in all 18 repositories, dirty paths only under
  `docs/kb/**`, direct file-byte parity (fresh-clone verification is inapplicable until an owner
  commits), unchanged foreign status/index/file hashes and remote refs/config, 20,948 unique IDs,
  quarantine 0, and zero add/update-index/commit/push commands. Aperant may report no dirty paths:
  its existing ignore hides `docs/kb/`, and the migration must not force-add it.
  actual post-run `ls-remote` refs equal frozen before/after maps, and no forbidden Git command
  appears in the externally captured gate log.
- blocked-by: T1.

### T3 — One global project-local owner switch

- Files: `app/ia/project_knowledge.py`, `app/ia/runtime.py`, `app/ia/knowledge.py`,
  `app/ia/projections.py`, `app/routes/knowledge.py`, `app/routes/memory.py`,
  `app/mcp_stdio.py`, focused runtime tests.
- Test: `uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t3_owner_switch_is_global_and_project_isolated` — committed RED in `4ed3c8fb`.
- RED: `AssertionError: T3 missing app.ia.project_knowledge`.
- AC: named command is green; missing, extra, and wrong-head project maps leave persisted state
  byte-unchanged and a fresh router central; successful activation persists across a fresh router
  and process-global context; caller project cannot read another project's record; project-local
  write reaches only its repo; central fallback works both before and after activation until cleanup. Focused regressions
  `tests/test_knowledge_runtime_debt_361.py`, `tests/test_knowledge_detail_summary.py`,
  `tests/test_knowledge_import_linking_409.py` are green.
- blocked-by: T2.

### T4 — Convert the frozen 764 facts inside Orchestra `docs/kb`

- Files: `scripts/kb_promote_facts.py`,
  `docs/kb/records/{facts,events,registry.json}`, `docs/kb/manifest.json`, focused tests.
- Test: `uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t4_extracted_facts_convert_one_to_one_and_idempotently` — committed RED in `4ed3c8fb`.
- RED: `AssertionError: T4 missing write_project_fact_records`.
- AC: named command is green; exact five input filenames/SHA-256 values are frozen; all 764
  deterministic stable IDs map one-to-one to source statement/status/reason/date/evidence/path/
  lines/topic/kind and full provenance (`task_id/evidence_uri/git_commit/path/anchor/measurement`);
  aggregate counts are 764/689/75/275/397; first run reports
  created=764, input files stay byte-identical, and rerun creates 0 with the same canonical head.
- blocked-by: T3.

### T5 — Fail-closed central cleanup

- Files: `app/ia/project_cleanup.py`, `app/ia/project_distribution.py`, `app/ia/projections.py`,
  `app/rag.py`, cleanup-focused tests; live central state only after all checks.
- Test: `uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t5_cleanup_refuses_without_parity_and_preserves_engine_state` — committed RED in `4ed3c8fb`.
- RED: `AssertionError: T5 missing app.ia.project_cleanup`.
- AC: named command is green; prepared or independently mismatched distribution receipts produce
  byte-for-byte no mutation; quarantine mismatch and target-head drift also fail before mutation;
  success requires verified distribution digest, persisted project-local
  owner generation, 764→764 fact receipt and target Git parity; cleanup removes central evidence/
  tasks plus foreign current/FTS and real RAG `files/file_chunks/vec_files/fts_files` and
  `logs_indexed/log_chunks/vec_logs/fts_logs` rows while preserving scope registry, runtime receipts,
  owner/fact receipts, sessions and quota DB bytes. Live cleanup proves the same zero-foreign conditions before source
  directories are removed. No cleanup runs before T2–T4 evidence is recorded.
- blocked-by: T4.

### T6 — Final prompt/cutover delivery

- Files: `app/ia/cutover.py`, `pipelines/default/prompts/base.md`,
  `pipelines/default/prompts/modules/{memory-search,research-method,orchestration,report-format}.md`,
  `pipelines/default/prompts/roles/{full-cycle,orchestrator}.md`,
  `docs/tasks/412/live-owner-receipt.json`,
  `docs/tasks/412/acceptance/test_t6_live_owner.py`, focused tests.
- Test: `uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t6_prompt_and_cutover_deliver_project_local_owner docs/tasks/412/acceptance/test_t6_live_owner.py::test_t6_live_owner_receipt_binds_real_session_and_nonempty_io` — committed RED in `4ed3c8fb`.
- RED: `AssertionError: T6 cutover still forbids docs/kb directives`.
- AC: named command is green; exact anchor
  `Project knowledge is canonical only inside the current repository's \`docs/kb/\`.` is
  required by cutover and delivered by `build_system_prompt` to all five roles; existing README
  read and full-cycle append directives remain delivered to their intended roles; no forbidden
  directive contains `docs/kb`; a checked-in live-owner receipt requires nonempty query/promote
  evidence, binds `agent_session_id` to a real `orchestra.db` session/scope, and binds project-local
  read/write paths to the target Git commit and blob SHA-256 values.
- blocked-by: T5.

Dependency chain is acyclic and intentionally serial: **T1 → T2 → T3 → T4 → T5 → T6**.

## What not to touch

- No backup, remote creation, push, pull, fetch or remote configuration.
- No changes in foreign repos outside `docs/kb/`.
- No task/fact re-extraction and no invented values for missing date/reason.
- No central cleanup in T1–T4.
- No prompt change before live owner success.
- No service restart unless separately authorized under existing incident rules.

## Review decision gate

- Changed Phase-2 files/consumers: this plan and two frozen oracle files; future consumers are
  18 Git repos, knowledge API, runtime owner, projections, prompts and destructive cleanup.
- Author metadata: `audit-data-locality`, `gpt-5.6-sol`, Codex, full-cycle.
- AC: six ticket commands above plus user boundaries (only `docs/kb`, local commits, no push,
  central cleanup last).
- Oracle evidence: six named commands exit 1 for the missing behavior; tests were frozen at
  `4ed3c8fb`. This is high-risk persistence/destructive/shared-runtime planning; Sol review is
  technically preferred but not authorized. Two Luna rounds were consumed. Round 2 still returned
  blocking oracle findings; every item was checked and the tests were materially hardened after
  the ceiling. A third model round is prohibited, so no clean reviewer verdict is claimed.

## Review outcome

Review route: Luna, 2 prose rounds (ceiling reached). Round 1 found 10 blocking oracle gaps;
Round 2 verified 5 fixed and left 9 prior/new blockers. After the ceiling, frozen oracles were
hardened at `4ed3c8fb` without a prohibited third model call:

| Final-round finding | Mechanical closure in current oracle |
|---|---|
| Git commands/remote refs self-reported | T1 executes through deny/log Git wrapper; T2 reads external gate log and actual `ls-remote` refs |
| central fallback only pre-activation | T3 reads the central-only record again after project-local activation |
| incomplete provenance | T4 compares `task_id`, `evidence_uri`, `git_commit`, path, anchor and measurement per stable ID |
| refusal not byte-preserving | T5 snapshots all files under temp state, owner/fact receipts and DB sidecars before every refusal |
| live receipt could be empty/fake | separate delivery check requires nonempty query/promote lists and resolves session id/scope from live `orchestra.db` |
| dry-run could mutate | T1 snapshots central/dest/quarantine files, statuses, refs, configs and registry bytes |
| stale/hard-coded central | T2 resolves production `state_root`, requires current HEAD and scope-registry digest equal receipt |
| incomplete SQLite/vector cleanup | T5 uses actual RagMemory schema plus current FTS and checks every file/log vector/FTS layer |
| no quarantine/head-drift refusal | T5 has independent byte-preserving refusal arms for both |

The reviewer artifact `docs/tasks/412/review-plan-luna.md` therefore retains a **BLOCKED**
verdict for the pre-`4ed3c8fb` version. No clean reviewer verdict is claimed; the phase gate owner
must decide whether the post-ceiling mechanical closures are sufficient.

## Frozen RED evidence

| Ticket | Exit | First missing-behavior assertion |
|---|---:|---|
| T1 | 1 | `AssertionError: T1 missing app.ia.project_distribution` |
| T2 | 1 | `AssertionError: T2 distribution manifest missing` |
| T3 | 1 | `AssertionError: T3 missing app.ia.project_knowledge` |
| T4 | 1 | `AssertionError: T4 missing write_project_fact_records` |
| T5 | 1 | `AssertionError: T5 missing app.ia.project_cleanup` |
| T6 | 1 | `AssertionError: T6 cutover still forbids docs/kb directives` |

`uv run pytest -q tests/test_project_knowledge_distribution_412.py::test_t1_byte_preserving_distribution_is_scoped_and_manifested` → exit 1: `AssertionError: T1 missing app.ia.project_distribution`.
