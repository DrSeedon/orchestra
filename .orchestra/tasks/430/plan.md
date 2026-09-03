# #430 — план переезда project-local состояния в `.orchestra/`

## Зафиксированные решения

Решения пользователя финальны; архитектурных развилок в реализации нет.

1. Все project repositories мигрируются автоматически и насильно. Временного dual-root resolver,
   fleet freeze и постоянного старого соглашения не будет.
2. Миграция самовосстанавливается: отсутствие, partial/mixed state и dirty refusal видны как
   именованный `ORCHESTRA_LAYOUT_*` error с одной точной repair-командой. Пустой поиск и fallback
   на старый root запрещены.
3. Порядок минимизирует broken window: место и runtime consumers готовы раньше mandatory prompt;
   prompt меняется последним.
4. `Dockerfile` и `docker-compose.yml` удаляются. Docker-контур не сохраняется.
5. `README.md` остаётся в repository root. В `docs/` остаются только пять external-reader files:
   `banner.png`, `dashboard.png`, `orchestrator-vps-onboarding.md`,
   `telegram-bot-api.service.template`, `tg-local-api-setup.md`.
6. Все остальные current `docs/` files переезжают под `.orchestra/`; спорных Markdown-классов нет.
7. Acceptance делит old-path occurrences на три класса дословно:
   - live consumers — старых путей быть не должно;
   - historical evidence — старые пути обязаны остаться и проверяются по path/blob/SHA;
   - negative guards — old literals разрешены только в явно маркированных
     `LEGACY_PATH_FIXTURE` rejection fixtures.

## Preconditions и порядок

- Research commit: `b187dd61`.
- Ветка синхронизирована с `main=87c426fd`; текущая provisional pre-implementation база baseline:
  `819ec7d1d391e31322155e3ed6e7a12910f1976e`.
- `docs/portfolio/**` уже удалён владельцем в `main=57a94193` после external copy + 6/6 SHA parity;
  это satisfied prerequisite, не работа ticket.
- **Непосредственно перед первым** `git mv`, без других действий между gate и move, повторить
  `git merge --no-edit main`; проверить `git rev-list --count HEAD..main` → `0`, затем
  `git diff --name-only "$(git merge-base HEAD main)"..main -- CLAUDE.md docs/ pipelines/` → пусто.
  Обычный `git diff HEAD..main` не годится: он показывает собственные task changes ветки даже
  когда main уже ancestor. Если main снова продвинулся,
  baseline и preservation `before_ref` замораживаются заново.
- Final RED oracle commit: `7a35e5417b55465336845a56b7e8da7d6bae431a`.
  `3eaa00b6`, `ea5059a3` и `d8c1b4c3` исключены: acceptance oracle был усилен после обоих review rounds
  (atomic location+runtime slice, managed dirty/race, executable repair, independent full proofs).
- Acceptance test immutable from final RED commit: никогда не редактировать, переименовывать, skip/xfail
  или ослаблять `tests/test_orchestra_layout_430.py` и его fixtures/configuration.
- Реализация идёт в dependency order: **T1 → T2 → T3 → T4 → T5**.

## Frozen baseline

После fresh-main merge и завершения T1/T2 на clean disposable worktree заморожены 220 test files и
3 689 selected nodes. Six whole-file shards сбалансированы 615/615/615/615/615/614 nodes.

- Base: `b46ae3a452f51c6123fd73ec64eeb43d3f52cad6`.
- Coverage: `observed_nodes=3689`, `collection_nodes=3689`, `coverage_equal=true`.
- Status: 3 559 passed, 39 failed, 88 skipped, 3 xfailed. Из 39 failures семь — ожидаемые
  T3/T4/T5 seams #430, 32 — unrelated baseline.
- Raw pytest ids двух dynamic parametrizations изменились между collection и run
  (`raw_nodeid_symmetric_difference=4`); comparison uses stable base+parameter-ordinal ids.
- Disposable worktree после run содержал только два known test side effects:
  `docs/tasks/356/usage-bar-provider-grid-{1280,1920}.png`; worktree удалён, source tree не менялся.
- Evidence: `docs/tasks/430/baseline-shards/{manifest.json,collection.txt,shard-*.txt,
  failures.txt,failures-raw.txt,summary.json,worktree-status-after.txt}`.
- After implementation запускаются те же six file manifests. Для каждого shard допустим только
  RC 0/1 с terminal summary; union stable statuses обязан ровно равняться frozen collection.
  New failures = `after_failures - before_failures`; ни один новый node не допускается.
- Десять новых #430 acceptance tests запускаются отдельно и должны стать green; они намеренно не
  входят в frozen pre-existing baseline.

## Physical mapping

`git mv` выполняется directory arguments, без shell expansion файлов.

| Source | Destination |
|---|---|
| `docs/kb/` | `.orchestra/kb/` |
| `docs/tasks/` | `.orchestra/tasks/` |
| `docs/workers/` | `.orchestra/workers/` |
| `docs/archive/` | `.orchestra/archive/` |
| `pipelines/` | `.orchestra/pipelines/` |
| `docs/artifacts/` | `.orchestra/artifacts/` |
| `docs/experiments/` | `.orchestra/experiments/` |
| `docs/research/` | `.orchestra/research/` |
| `docs/reviews/` | `.orchestra/reviews/` |
| `docs/tg-media/` | `.orchestra/tg-media/` |
| `docs/codex-field-guide.md` | `.orchestra/guides/codex-field-guide.md` |
| `docs/grok-field-guide.md` | `.orchestra/guides/grok-field-guide.md` |
| `docs/measuring.md` | `.orchestra/guides/measuring.md` |
| `docs/team-structure.md` | `.orchestra/guides/team-structure.md` |
| `docs/HANDOFF-from-laptop.md` | `.orchestra/archive/HANDOFF-from-laptop.md` |
| `docs/codex-full-review.md` | `.orchestra/reviews/codex-full-review.md` |
| `docs/codex-subscription-usage-research-2026-07.md` | `.orchestra/research/codex-subscription-usage-research-2026-07.md` |
| `docs/fork-analysis.md` | `.orchestra/research/fork-analysis.md` |
| `docs/proxy-speed-benchmark.md` | `.orchestra/research/proxy-speed-benchmark.md` |
| `docs/research-context-bug.md` | `.orchestra/research/research-context-bug.md` |
| `docs/research-context-full.md` | `.orchestra/research/research-context-full.md` |
| `docs/research-deepgram.md` | `.orchestra/research/research-deepgram.md` |
| `docs/research-multiproject.md` | `.orchestra/research/research-multiproject.md` |
| `docs/architecture.png` | `.orchestra/artifacts/architecture.png` |
| `docs/fleet-looping.png` | `.orchestra/artifacts/fleet-looping.png` |

Deleted by #430, not moved: `Dockerfile`, `docker-compose.yml`.

Stayed in `docs/`: exactly the five external-reader files listed above. `README.md`, `CLAUDE.md`,
`TODO.md`, `CHANGELOG.md`, `CONTRIBUTING.md` and `BUGS.md` remain at repository root; only their live
links are updated. Historical `CHANGELOG.md` literals are not rewritten.

## App files — exhaustive territory before modification

Behavior/current-root owners:

- `app/orchestra_layout.py` (new)
- `app/bootstrap.py`
- `app/ia/cutover.py`
- `app/ia/knowledge.py`
- `app/ia/project_distribution.py`
- `app/ia/project_knowledge.py`
- `app/main.py`
- `app/manager.py`
- `app/mcp_stdio.py`
- `app/pipeline.py`
- `app/prompting.py`
- `app/session.py`
- `app/tm.py`

Ordinary code comments/docstrings whose task links must become new paths or be removed:

- `app/backend_claude.py`
- `app/backend_codex.py`
- `app/backend_grok.py`
- `app/charts.py`
- `app/fdstore.py`
- `app/harness/mcp.py`
- `app/rag_service.py`
- `app/routes/sessions.py`
- `app/routes/system.py`
- `app/session_turns.py`
- `app/static/js/app.js`
- `app/static/js/chat.js`
- `app/templates/dashboard.html`
- `app/workspace.py`

`app/models.py` contains no old-path referrer and is not touched. No other `app/` file is modified
unless the classified scanner finds a new current reference after the mandatory main sync; such a
file must first be added to this plan/review scope, never changed silently.

## Other file groups

- New scripts: `scripts/migrate_orchestra_layout.py`, `scripts/verify_orchestra_move.py`,
  `scripts/check_orchestra_paths.py`.
- Existing scripts with current path contracts:
  `activate_project_knowledge.py`, `check_kb_contract.py`, `check_pipeline_manifest.py`,
  `grill-spec.sh`, `kb_extract_report.py`, `kb_promote_facts.py`, `migrate_agent.py`,
  `rehearse-seamless-restart.py`, `repair_task_par_collisions.py`.
- Root/config: `.gitignore`, `CLAUDE.md`, `TODO.md`, `README.md`; delete Docker files.
- Moved prompt owners: all 13 files classified `shared_prompt_pipeline` in
  `reference-inventory.tsv`.
- Tests: update every existing `test_referrer` row in the inventory plus focused knowledge,
  distribution, prompting, manager, session, tm and pipeline tests. Frozen oracle
  `tests/test_orchestra_layout_430.py` is never edited.
- `deploy/orchestra.service` contains only a historical measurement comment; it may retain its old
  literal under historical classification and is not a runtime path consumer.

## API/format contract (values are not left to implementation)

New `app/orchestra_layout.py` public seam:

```python
class LayoutMigrationError(RuntimeError):
    code: str
    repair_command: str

def require_project_layout(repository: Path) -> Path: ...
def migrate_project_layout(repository: Path, *, repair: bool = False) -> dict: ...
def migrate_registered_projects(project_roots: Mapping[str, Path]) -> dict[str, dict]: ...
def migrate_registered_project_layouts() -> dict[str, dict]: ...
```

Status values are exactly `migrated`, `repaired`, `already_current`, `failed`. Error codes are
exactly:

- `ORCHESTRA_LAYOUT_MISSING` — neither complete old nor complete new layout;
- `ORCHESTRA_LAYOUT_PARTIAL` — both roots/mixed classes or interrupted journal;
- `ORCHESTRA_LAYOUT_DIRTY` — unrelated uncommitted work prevents safe auto migration;
- `ORCHESTRA_LAYOUT_STALE_WORKTREE` — linked worktree lacks the canonical migration commit/layout;
- `ORCHESTRA_LAYOUT_GIT_ERROR` — Git preflight/move/commit verification failed.

Every error includes the repository path, failed/missing classes and one executable command ending
in `scripts/migrate_orchestra_layout.py --repair <absolute-repository>`. No error path returns an
empty list/string or searches old root.

Migration state:

- `.orchestra/layout.json` is deterministic tracked state with `schema_version=1`,
  `layout=".orchestra"`, sorted `managed_paths` and no timestamp/random id.
- `.orchestra/.layout-migration.json` is a temporary fsynced journal written before the first move;
  it contains the source HEAD and old→new map, enables `--repair`, and is deleted before success
  commit. It is never committed.
- Clean auto migration commits exactly once; second run produces `already_current`, no commit and
  clean status.
- `migrate_project_layout` acquires `app.workspace.repo_mutation_lock(repository)` **before** its
  dirty/preflight snapshot and holds it through verification+commit. Startup runs before
  `auto_resume_all`, so no session starts a turn inside this window.
- Dirty auto mode mutates nothing for root, tracked managed, or untracked managed changes.
  `--repair` may continue a journal/known moving-root changes but must still refuse unrelated dirty
  paths. The immutable race control injects a managed write on lock entry and must get
  `ORCHESTRA_LAYOUT_DIRTY` with zero move.
- Fleet runner force-migrates registered **canonical project checkouts** independently; one failure
  does not stop other projects. It never auto-commits a stale linked worktree. Live/resumable
  worktrees are preflighted before resume: missing T3/layout returns
  `ORCHESTRA_LAYOUT_STALE_WORKTREE` + repair, and the session stays stopped until its branch is
  repaired/merged. This avoids an old branch with new data paths and old repository code.
- T1 builds the fleet runner but does not activate it. T4 calls
  `migrate_registered_project_layouts` in `app/main.py` after `init_db()` and before
  `knowledge_runtime_mode(production_runtime_config())`, atomically with prompt activation.

## Tickets

### T1 — Build the locked forced migrator and executable repair

- Files: `app/orchestra_layout.py` (new), `scripts/migrate_orchestra_layout.py` (new), focused Git
  migration tests, immutable #430 oracle.
- Behavior: implement the API/state/error contract without activating startup/prompt. Every mutation
  holds `repo_mutation_lock` from dirty snapshot through commit. Auto refuses root,
  tracked-managed and untracked-managed dirty states without mutation. Partial repair command is
  absolute, appears once, ends `--repair <absolute repo>`, is executed by the oracle and completes;
  missing-layout execution returns RC 2 plus the same actionable structured failure. Dirty status
  **and dirty bytes** are invariant. Fleet mapping contains canonical checkouts only.
- Test: `uv run python -m pytest -q tests/test_orchestra_layout_430.py -k 't1_'` — RED after review:
  `3 failed`, first missing behavior
  `AssertionError: T1 missing forced migration engine app/orchestra_layout.py`.
- AC: named command is green; one clean migration commit; idempotent second run; partial CLI repair
  succeeds; missing repair returns usable RC2 failure; three dirty classes preserve status+bytes;
  injected lock-entry race is loud/non-mutating; fleet result isolates failures.
- blocked-by: none

### T2 — Remove dead Docker and ordinary stale links

- Files: delete `Dockerfile`, `docker-compose.yml`; update/remove Docker comment in
  `app/bootstrap.py`; update/remove ordinary task-link comments in `app/static/js/app.js`,
  `app/static/js/chat.js`, `app/templates/dashboard.html`; audit `README.md`; update `TODO.md`.
- Behavior: no Docker entrypoint remains. Frontend/template comments use future
  `.orchestra/tasks/**` paths or are deleted; no replacement Docker config appears.
- Test: `uv run python -m pytest -q tests/test_orchestra_layout_430.py -k 't2_'` — RED after review:
  `1 failed`, `assert not (ROOT / 'Dockerfile').exists()`.
- AC: named command is green; README image links resolve; repository has no Docker config.
- blocked-by: none

### T3 — Atomically move the repository and switch every runtime consumer

- Files: every source/destination in **Physical mapping**, `.gitignore`, `CLAUDE.md`, `TODO.md`,
  `README.md`; `app/pipeline.py`, `app/prompting.py`, `app/tm.py`, `app/ia/knowledge.py`,
  `app/ia/project_distribution.py`, `app/ia/project_knowledge.py`, `app/ia/cutover.py`,
  `app/manager.py`, `app/session.py`; nine existing path scripts; all current app/script/test links;
  `scripts/verify_orchestra_move.py` (new); `.orchestra/tasks/430/move-receipt.json`.
- Behavior: **one atomic implementation commit** contains physical `git mv` and all runtime consumer
  changes; no deployable commit has old consumers/new location or vice versa. Immediately before
  move, pass fresh-main gate and freeze `before_ref`. Current runtime/import paths become
  `.orchestra/**`; pinned evidence JSON remains byte-identical.
- Preservation oracle: immutable test independently reads every old blob/mode from `before_ref`,
  compares it with the tree at `location_runtime_commit`, and checks bytes/newlines/SHA-256 for
  three sentinels. It executes `verify_orchestra_move.py --after-ref <location commit>` and requires
  independent/live/stored exact counts. Git must prove `location_runtime_commit^ == before_ref`,
  `merged_main_ref` ancestor of `before_ref`, and current main merge-base equals `merged_main_ref`.
- Receipt: `before_ref`, `merged_main_ref`, `location_runtime_commit` (40 hex), exact `checked_files`, fields
  `["mode","lines","bytes","sha256"]`, `mismatches=[]`, evidence counts,
  `artifact_reading_count=2`.
- Test: `uv run python -m pytest -q tests/test_orchestra_layout_430.py -k 't3_'` — RED after review:
  `4 failed`; independent seams: pipeline root, task-number guard, missing physical root and
  non-final `docs/` set.
- AC: named command is green; independent/live/stored file counts equal with zero mismatch; old
  roots absent; final docs set exact; focused pipeline/prompting/tm/knowledge/distribution suites
  green; `uv.lock` unchanged.
- blocked-by: T1, T2

### T4 — Activate fleet migration and mandatory prompts last

- Files: `app/main.py`, `app/mcp_stdio.py`, `.orchestra/pipelines/default/pipeline.yaml` and all
  prompt modules/roles/skills, delivery/startup/MCP tests,
  `.orchestra/tasks/430/release-receipt.json`.
- Behavior: after T3 commit, activate `migrate_registered_project_layouts` in actual `lifespan`
  before knowledge runtime **and** `auto_resume_all`; canonical checkouts auto-migrate, stale linked
  worktrees remain stopped with repair. `search_memory` reports repair instead of empty result.
  Switch prompts last. Release receipt names distinct location/prompt commits; Git proves ancestry,
  exact old prompt blob preserved at location commit, new repair anchor absent there/present at
  prompt commit, runtime consumer present at location, and prompt/app-main changes at activation.
- Test: `uv run python -m pytest -q tests/test_orchestra_layout_430.py -k 't4_'` — RED after review:
  `2 failed`, separate seams: no lifespan call and no `.orchestra/` in full-cycle prompt.
- AC: named command is green; every role prompt uses new root and repair anchors; Git topology
  receipt passes; fresh real agent completes new memory gate after forced migration.
- blocked-by: T3

### T5 — Enforce classified hygiene, full evidence bindings and regression parity

- Files: `scripts/check_orchestra_paths.py` (new), update `scripts/check_kb_contract.py` defaults,
  `.orchestra/tasks/430/reference_inventory.py`, byte-frozen
  `.orchestra/tasks/430/evidence-bindings-frozen.json`, marked guards/fixtures and focused tests.
- Behavior: scanner reports live/historical/negative counters plus
  `historical_binding_set_sha256`. Immutable oracle independently enumerates the exact historical
  set from the manifest whose immutable SHA-256 is
  `83559af2e573185f5d685f25cefeeb8b94083819f59e91a9b4881e06ddb5b289`. It requires every frozen
  stable-id binding unchanged (new records may be additive), verifies every current
  commit:path→blob and blob SHA, and requires scanner frozen count+digest equality. Old literals
  outside pinned evidence or `LEGACY_PATH_FIXTURE` fail.
- Test: `uv run python -m pytest -q tests/test_orchestra_layout_430.py -k 't5_'` — RED after review:
  `1 failed`, `AssertionError: T5 missing classified live/historical/negative path checker`.
- AC: named command is green; live/unclassified/mismatch counters zero; independent/scanner count
  and digest equal; six frozen baseline shards cover exact collection with no new failed stable node;
  focused #430 suite is `11 passed`.
- blocked-by: T4

## What not to touch/do

- Do not mutate any foreign repository manually; T1 production migration is the only authorized
  fleet writer.
- Do not rewrite/repin historical evidence `git_commit`, `source_path`, `git_blob` or
  `source_sha256`.
- Do not leave symlinks, duplicate old directories or permanent fallback logic.
- Do not edit the immutable acceptance test, fixtures, `conftest.py`, pytest configuration or test
  selection to make RED green.
- Do not activate startup fleet migration or mandatory prompt before atomic T3 is green/committed.
- Do not preserve Docker files as comments/disabled configuration; delete them.

## Plan review outcome

First Luna review (`codex-review-plan.md`) returned **NOT APPROVED** with seven blocking findings
and one suggestion. The original dissent is preserved here because this is an architecture plan:

1. T3 removed location before T2 consumers → **FIXED** by collapsing physical move + runtime
   consumers into atomic T3 and moving startup activation to T4.
2. live/resumable worktree race → **FIXED** by `repo_mutation_lock` from dirty snapshot through
   commit, startup-before-resume activation, and lock-entry race oracle.
3. cleanup ticket required final docs before move → **FIXED**: T2 only deletes Docker/stale prose;
   final docs assertion belongs to atomic T3.
4. dirty managed files untested → **FIXED**: root, tracked-managed and untracked-managed states all
   fail without mutation.
5. repair checked by substrings only → **FIXED**: oracle asserts exact absolute tokens and executes
   partial repair command to completion.
6. move receipt self-confirming → **FIXED**: immutable test independently compares every pre-ref
   mode/blob with current index+working tree, plus three line/byte/SHA sentinels, then cross-checks
   live verifier and stored exact count.
7. evidence checked by aggregate only → **FIXED**: immutable test independently verifies the exact
   record set, every path/blob/SHA and binding-set digest; scanner must match count+digest.
8. prompt-last lacked machine gate → **FIXED**: Git ancestry/tree/diff release receipt is part of T4.

Round 2 remained **NOT APPROVED** with six proof gaps. All were accepted and fixed after the review
ceiling: canonical-only auto migration + stale-worktree stop, dirty byte snapshots, executed
missing-layout RC2 repair, immediate-parent/merged-main freshness proof, prompt preimage comparison,
and byte-frozen exact historical binding manifest. No third plan review is allowed, so the final
artifact must not be called reviewer-approved.

Oracle is re-frozen after all review fixes at the final RED commit named above; earlier RED commits
are excluded.

## Review gate inputs

- Author model/runtime from session metadata: `gpt-5.6-sol` / Codex.
- Changed Phase-2 artifacts before review: this plan, baseline manifests/parser, refreshed reference
  inventory; final frozen acceptance test+binding manifest is commit `7a35e541`.
- Consumers: shared startup/session/prompt runtime, Git persistence/migration, task identity,
  project-local knowledge and every agent role across 21 scopes.
- Exact AC: ticket commands and criteria above; baseline coverage `3689 == 3689`, 39 current
  failures; RED focused command below.
- Risk floor: high (cross-project destructive migration + silent memory-loss path). Sol review would
  be the canonical route, but no auxiliary Sol authorization was given; use one allowed Luna plan
  pass and report that limitation accurately.

## RED evidence — plan terminates here

Final frozen command:

```text
uv run python -m pytest -q tests/test_orchestra_layout_430.py
```

Observed on `7a35e541`: `RC=1`, `11 failed in 2.04s`.

First failing assertion:

```text
AssertionError: T1 missing forced migration engine app/orchestra_layout.py
```
