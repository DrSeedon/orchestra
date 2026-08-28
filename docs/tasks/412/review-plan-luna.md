<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

18 repos, destructive cleanup, and manifests grading their own homework—what could possibly go wrong 😏

## Summary

The arithmetic is correct: 20,948 records across 18 projects, and the frozen source contains 764 facts with the stated distributions. All six named tests currently exit 1, so no already-green RED blocker was found.

The plan is not ready for approval: several critical oracles are self-referential and do not independently prove path safety, source parity, no-local cloning, remote immutability, global cutover, one-to-one fact conversion, cleanup preservation, or prompt delivery order.

## Findings

### blocking: Live distribution lacks an explicit post-approval gate

**Location:** [plan.md:121](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/docs/tasks/412/plan.md:121)

T2 is explicitly a live landing with local commits across 18 repositories, but the plan never states that `apply` and foreign-repo commits must wait for the user’s next approval. Add a hard stop before any live distribution or commit operation.

### blocking: T2 does not freeze the exact project mapping or per-project counts

**Location:** [test_t2_live_distribution.py:31](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/docs/tasks/412/acceptance/test_t2_live_distribution.py:31)

The test checks only `18` projects and an aggregate sum. It does not require the table’s exact `project_id → repository_root → record_count` mapping, unique project IDs, or exact destination paths, so a manifest can redistribute records into arbitrary repositories and still pass.

### blocking: T2 SHA parity is self-referential

**Location:** [test_t2_live_distribution.py:44](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/docs/tasks/412/acceptance/test_t2_live_distribution.py:44)

The test compares payloads only with SHA values supplied by the same project manifest and compares that digest with the global receipt. It never compares against the central source inventory or independently recomputes the sorted raw-byte digest, allowing fabricated but internally consistent records to pass.

### blocking: `--no-local` clone evidence is only an attestation

**Location:** [test_t2_live_distribution.py:45](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/docs/tasks/412/acceptance/test_t2_live_distribution.py:45)

No clone is created and no clone filesystem is inspected; `ok: true`, `mode: "--no-local"`, head, and digest are all trusted fields. The oracle must perform an actual temporary `git clone --no-local`, verify the cloned head and digest, and check that no alternates/local object sharing was used.

### blocking: Push/fetch/pull and local-commit constraints are not enforced

**Location:** [test_project_knowledge_distribution_412.py:173](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/tests/test_project_knowledge_distribution_412.py:173)

T1 checks only `origin/main`; T2 checks no remote refs at all, and neither live test validates `before_head → target_commit`. A new remote tag/branch, fetch/pull, or an existing pre-distribution commit could go unnoticed. Capture all refs/config before and after, deny remote-mutating commands during apply, and require a new local commit for every non-empty target.

### blocking: T1 does not exercise the distribution CLI

**Location:** [test_project_knowledge_distribution_412.py:138](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/tests/test_project_knowledge_distribution_412.py:138)

The ticket includes `scripts/distribute_project_knowledge.py`, but the test imports only the Python module and calls its function directly. The actual `--dry-run`, `--apply`, and `--verify` entry points can be broken or bypass safety checks while T1 remains green.

### blocking: T3 does not prove a process-global, persistent all-or-none switch

**Location:** [test_project_knowledge_distribution_412.py:198](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/tests/test_project_knowledge_distribution_412.py:198)

Only one router instance is tested, and failed activation checks only its in-memory `active_owner`. There is no assertion that the persisted state remains central, no fresh-router check, no missing/extra project-map case, and no project-local write or central fallback test. A partially persisted or instance-local implementation could pass.

### blocking: T4 does not verify one-to-one fact conversion

**Location:** [test_project_knowledge_distribution_412.py:220](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/tests/test_project_knowledge_distribution_412.py:220)

The test glob-matches any `part-*.json` files and checks only aggregate status/null counts. It does not assert the exact five inputs, source-row identity, stable IDs, claims, provenance, or `first["created"]`. A converter can fabricate 764 records with matching aggregate fields.

### blocking: T5 accepts a fabricated verification and does not prove cleanup preservation

**Location:** [test_project_knowledge_distribution_412.py:271](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/tests/test_project_knowledge_distribution_412.py:271)

The test changes `prepared` to `verified` and supplies only `projects` plus `quarantine_count`; it does not require T2–T4 receipts, heads, digests, or activation evidence. Refusal checks only existence, not bytes or database state, while the successful path passes `vector_db=None` and does not snapshot sessions, quotas, receipts, runtime state, or vector data.

### blocking: T6 checks constants, not actual prompt cleanup or live rollout

**Location:** [test_project_knowledge_distribution_412.py:302](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-data-locality/tests/test_project_knowledge_distribution_412.py:302)

The test inspects `_FORBIDDEN_LEGACY_DIRECTIVES`, not every assembled prompt, and has no assertion for the required recorded real-agent local read/write. Clearing the tuple and adding the new anchor would pass while existing prompt text still says to read `docs/kb/README.md` or append conclusions to `docs/kb/`.

## Verdict

❌ **Not ready for approval.** The dependency chain is serial, but the acceptance layer does not provide sufficient evidence for a destructive persistence migration.

The plan states: “T2 перед apply повторно вычисляет frozen HEAD/counts; drift останавливает проход и обновляет manifest, а не подгоняет эти числа молча.” The current oracle does not verify that behavior.

Otherwise this is an auditor accepting its own manifest as proof—efficient right up until deletion starts.

## Round (2026-08-28T03:22:06Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Раунд два заметно лучше: теперь опасные дырки не в архитектуре, а в местах, где receipt всё ещё сам себе свидетель 😏

## Summary

Большинство раунд-1 замечаний исправлено. Все шесть frozen RED-команд снова завершаются `exit 1`; implementation и live distribution не запускались.

Остаются четыре blocking-находки.

## Findings

### Prior findings

| # | Status | Evidence |
|---:|---|---|
| 1 | **FIXED** | Hard Phase-3 stop добавлен в `plan.md:17-22`. |
| 2 | **FIXED** | T2 содержит frozen `EXPECTED` mapping и сравнивает его с manifest в `test_t2_live_distribution.py:14-33,127-134`. |
| 3 | **FIXED** | Источник читается из pinned Git, bytes и digest пересчитываются независимо в `test_t2_live_distribution.py:60-77,152-156`. |
| 4 | **FIXED** | Выполняется реальный `git clone --no-local --no-checkout`, проверяется отсутствие alternates: `test_t2_live_distribution.py:160-173`. |
| 5 | **STILL BROKEN** | T1 независимо сверяет финальные refs/config, но запрет команд и T2 remote refs остаются self-reported через `git_subcommands` и receipt-поля: `tests/...:222-229`, `test_t2_live_distribution.py:92-114`. |
| 6 | **FIXED** | T1 запускает реальные CLI `--dry-run`, `--apply --commit`, `--verify`: `tests/...:178-196`. |
| 7 | **STILL BROKEN** | Persistence, fresh routers, write и context проверяются, но central fallback вызывается только до activation: `tests/...:261`, без post-activation fallback-проверки. |
| 8 | **STILL BROKEN** | Stable IDs и основные поля проверяются, но provenance не сверяет `task_id`, `evidence_uri` и `git_commit`, хотя они создаются в `scripts/kb_promote_facts.py:394-402`; проверки только `path/anchor/measurement`: `tests/...:346-360`. |
| 9 | **STILL BROKEN** | Bad-digest refusal проверяет лишь наличие файлов, не byte-for-byte state; `owner_state` и fact receipt не входят в protected snapshot: `tests/...:527-558`. |
| 10 | **STILL BROKEN** | Prompt delivery проверяется, но live receipt принимает любой непустой `agent_session_id` и допускает пустые `reads`/`writes`: `tests/...:587-604`. Реальная agent/session привязка не доказана. |

### New blockers

1. **blocking:** T1 dry-run не доказан как mutation-free. Проверяются только отсутствие `docs/kb`, central HEAD и refs; не проверяются central status/bytes, registry, quarantine и их конфигурация (`tests/...:178-187`). Dry-run может оставить untracked-изменения и пройти.

2. **blocking:** T2 не фиксирует именно текущий central owner. `CENTRAL` жёстко задан как `~/.local/state/...`, хотя production runtime поддерживает `STATE_DIRECTORY`, `XDG_STATE_HOME` и другой state root (`test_t2_live_distribution.py:13`, `app/ia/runtime.py:361-373`). Кроме того, проверяется лишь существование `manifest["source_head"]`, а не соответствие текущему/frozen HEAD (`test_t2_live_distribution.py:125`), поэтому reachable stale commit может пройти.

3. **blocking:** T5 использует неполные SQLite fixtures. Реальный RAG содержит `file_chunks`, `vec_files`, `fts_files`, `log_chunks`, `vec_logs`, `fts_logs`, а projection — `current_fts`; тест проверяет только `files`, `logs_indexed` и `current_records` (`app/rag.py:334-399`, `app/ia/projections.py:259-274`, `tests/...:431-446,559-565`). Cleanup, оставляющий foreign chunks или FTS-строки, останется зелёным.

4. **blocking:** Не проверены обязательные отказы по `quarantine mismatch` и `head drift`. План требует их до первой mutation (`plan.md:110-111`), но T5 тестирует только `prepared` и искажённый digest (`tests/...:484-540`). Реализация, игнорирующая drift/quarantine, пройдёт acceptance.

## Verdict

❌ **BLOCKED.** Раунд-1 существенно укреплён, но T2/T5 всё ещё не дают достаточного доказательства для destructive migration; Phase 3 approval выдавать рано.

План утверждает: “T2 перед apply повторно вычисляет frozen HEAD/counts; drift останавливает проход и обновляет manifest, а не подгоняет эти числа молча.” Текущий oracle это полностью не доказывает.

Иначе cleanup получается как нотариус, заверяющий собственное исчезновение: печать есть, контроля нет.
