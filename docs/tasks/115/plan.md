# #115 — план надёжного merge contract, reconcile и conflict recovery

## Решение

`merge_worker` становится idempotent operation, а не одним длинным HTTP-запросом.
MCP-клиент создаёт idempotency key до первого POST; сервер durable записывает
`PENDING` до первой Git mutation, запускает merge в отдельной tracked task и
сохраняет terminal/partial result. Потеря HTTP response больше не означает
«неизвестно, был ли merge»: повтор с тем же key читает ту же operation, а второй
key не запускает конкурирующую mutation, пока предыдущая operation активна или её
commit-point остаётся `REACHED/UNKNOWN` без evidence-backed reconcile.

Raw merge target-ветки не запрещается этой задачей. Сначала появляются:

1. честный merge operation с непустой диагностикой;
2. CAS-safe reconcile/finalize для уже committed content;
3. один разрешённый conflict workflow, где содержательный конфликт исправляется
   только в worker branch, а target по-прежнему пишет `merge_worker`.

Только после измеренного прохождения этих путей можно отдельной задачей менять
prompt/policy. В #115 никаких prompt-запретов нет.

## Жёсткая граница с #93

#115 **не планирует изменений** в `app/manager.py`, `app/workspace.py` и
`app/routes/sessions.py`. Он работает поверх #93 и не создаёт собственный repo
lock или вторую lifecycle state machine.

Контракт согласован с `audit-worktree`; перед Phase 3 остаётся проверить, что он
реально landed:

- публичный `repo_mutation_lock(repo: str | Path)` по canonical git-common-dir;
  reconcile импортирует contextmanager только для своей отдельной Git-транзакции
  и никогда не оборачивает им `merge_worktree_to_main()` снаружи (nested flock);
- `MergeOutcome` с обязательными `ok`, `state`, `commit_point` и pinned
  `target_branch`, `target_before`, `target_after`, `worker_branch`, `worker_head`,
  включая normal conflict/partial/no-op result; conflict paths сохраняются точно,
  включая пробелы.

Internal #93 mapping принимается без переименования:

- `target_committed` → operation `REACHED`;
- `not_reached|rolled_back` → operation `NOT_REACHED`;
- `unknown` → operation `UNKNOWN`;
- no-op: `state=merged`, `commit_point=not_reached`, `commits_merged=0`,
  `target_after==target_before`.
- pinned entry point #93-T2:
  `execute_merge_session(*, session_id, expected_name, expected_scope,
  expected_branch, expected_head, req)`. Он повторно резолвит exact session ID
  внутри собственного session lock; branch/head сверяются внутри
  `repo_mutation_lock` до Git mutation. Identity mismatch возвращает typed
  `failed/not_reached`. #115 не вызывает name/scope route и не берёт внешний
  nested session/repo lock.

Если одного из контрактов нет, #115 останавливается и координируется через
оркестратора; он не копирует lock и не парсит английский текст ошибок как основной
протокол. Текущие зависимости по #93:

| #93 ticket | Что потребляет #115 | Что #115 не дублирует |
|---|---|---|
| #93-T1 | stable repo lock, rollback/actual Git snapshot | lock, rollback, switch quarantine |
| #93-T2 | success/partial DTO, project-scoped task identity | merge-next validation и task update |
| #93-T4 | обязателен перед destructive reconcile: quarantine блокирует fresh delivery и после restart | delivery serialization |

#116-T3 владеет общим MCP error envelope
`{code,message,status,retryable,request_id,retry_after_seconds,outcome_unknown,details}`
и формой `structuredContent={result,error}`. #115 использует этот контракт, не
создаёт второй transport serializer: `PENDING/RUNNING/SUCCEEDED/PARTIAL` имеют
`isError=false`; `FAILED/UNKNOWN` — `isError=true`, но всё равно сохраняют полный
merge DTO в `result`. У `PARTIAL` typed failed-stage detail остаётся внутри DTO.

#116-T7 владеет `rag_service.schedule_backfill(scope)`, его tests и единственным
route-hunk, который заменяет fire-and-forget backfill после merge. Порядок merge:
**#93-T2 → #116-T7 → #115-T1**. #115 не меняет `rag_service` или sessions route,
а только сохраняет возвращённый `accepted|coalesced|not_ready` в
`MergeOperationResult.rag.status`. Recovery batch в #115-T2 остаётся отдельным
awaited путём и вызывает существующий `backfill_scope()` ровно один раз на scope.

## Operation contract v1

### Идентичность и хранение

- MCP генерирует UUID idempotency key **до** первого request и передаёт его в
  `merge_worker`; optional `operation_id` позволяет caller повторить тот же вызов.
  На HTTP-границе caller — MCP subprocess: он знает key до POST и возвращает его
  LLM после любого пойманного transport failure. Если сам MCP process умер до
  ответа, следующий вызов с новым key получает canonical matching operation id,
  даже если исходная operation уже стала terminal.
- Новый `merge_operations` row коммитится как `PENDING` до `create_task()` и до
  Git. В row лежат operation id/type, session id, scope, worker name, normalized
  request, request hash, accepted worker/session snapshot, terminal session
  snapshot (`branch/head/task_id/needs_switch`), state, stage result JSON,
  timestamps и process owner token.
- Один key + другой request hash → `IDEMPOTENCY_CONFLICT`, без side effects.
- Для одного session одновременно допустима одна `PENDING/RUNNING` operation;
  незавершённые `PARTIAL/UNKNOWN` также держат merge gate. Второй key получает
  canonical operation id, а не вторую очередь.
- Accept fingerprint = immutable `session_id + normalized request + accepted
  worker_branch + worker_head`; он индексируется, но **не unique навсегда**. Тот же
  `operation_id` всегда возвращает старый result. Новый key terminal-dedupe-ится
  только для результата, который мог мутировать state: `commit_point=REACHED`,
  `commit_point=UNKNOWN` или unresolved `PARTIAL/UNKNOWN`. Для доказанного
  `FAILED+NOT_REACHED` и clean no-op новый key разрешён после повторной pinned
  preflight: busy→idle, очищенный target или сдвинувшийся target не должны навечно
  возвращать stale failure. Для mutating terminal retry требуется exact
  equivalence: тот же session/request и текущий `branch/head/task_id/needs_switch`
  равен сохранённому terminal snapshot → вернуть canonical old result.
- `PARTIAL/UNKNOWN` держат session gate независимо от snapshot. `resolved_at`
  может записать **только T2 evidence-backed reconcile** одним из двух typed
  outcomes: `RESOLVED_NOT_REACHED` (journal доказывает, что mutation barrier не
  пересекался, а pinned Git/lifecycle snapshots совпадают) либо
  `RESOLVED_REACHED_FINALIZED` (exact landed target commit доказан и все допустимые
  stages finalized). Нет ручного `clear/force/ack`: недостаточное доказательство
  оставляет `UNKNOWN` и quarantine.
- Runner меняет `PENDING → RUNNING` durable до вызова #93 merge handler. После
  restart orphan `RUNNING` становится `UNKNOWN`; автоматически повторять mutation
  запрещено. Orphan `PENDING` можно запустить только после повторной проверки
  request/session fingerprint, потому что mutation ещё не начиналась.
- Terminal result хранится без TTL в первой версии: при текущих ~205 calls/week
  cleanup не окупает риск удалить единственное доказательство commit outcome.

`app.merge_operations` вызывает только pinned
`execute_merge_session(session_id=..., expected_*=...)` из #93-T2. HTTP route
остаётся adapter над тем же entry point; #115 его не меняет. #93 продолжает
владеть session/lifecycle/repo locks. Strong task registry удерживает runner после
завершения принимающего HTTP request.

SQLite arbitration — явный CAS contract:

- `operation_id TEXT PRIMARY KEY`, обычный index по `dedupe_fingerprint` для
  terminal lookup (не global unique);
- partial unique index по `session_id` для rows без `resolved_at` в states
  `PENDING/RUNNING/PARTIAL/UNKNOWN`;
- accept делает `BEGIN IMMEDIATE`: insert либо после unique conflict читает
  active canonical row и проверяет request hash; terminal lookup применяет правила
  mutating/non-mutating outcome выше;
- owner claim — `UPDATE ... SET state='RUNNING', owner_token=? WHERE
  operation_id=? AND state='PENDING'`; executor стартует только при
  `rowcount == 1`.

### Typed result

```json
{
  "schema_version": 1,
  "operation_id": "uuid",
  "operation_state": "PENDING|RUNNING|SUCCEEDED|PARTIAL|FAILED|UNKNOWN",
  "retryable": false,
  "commit_point": "NOT_REACHED|REACHED|UNKNOWN",
  "git": {
    "status": "NOT_STARTED|SUCCEEDED|CONFLICT|DIRTY|FAILED|UNKNOWN",
    "target_branch": "main",
    "target_before": "sha|null",
    "target_after": "sha|null",
    "worker_branch": "branch",
    "worker_head": "sha|null",
    "conflicts": []
  },
  "task_links": {"status": "NOT_RUN|SUCCEEDED|PARTIAL|FAILED", "items": {}},
  "rag": {"status": "NOT_RUN|ACCEPTED|COALESCED|NOT_READY|SUCCEEDED|FAILED|DISABLED"},
  "lifecycle": {"status": "NOT_RUN|SUCCEEDED|FAILED"},
  "next_task": {"status": "NOT_REQUESTED|SUCCEEDED|FAILED"},
  "error": {
    "code": "CODE", "message": "non-empty", "status": 500,
    "retryable": false, "request_id": "uuid",
    "retry_after_seconds": null, "outcome_unknown": false,
    "details": {"exception_type": "ExceptionClass"}
  },
  "next_action": {"code": "RETRY_SAME_OPERATION", "message": "non-empty"}
}
```

`error=null` допустим только когда ни один stage не требует error detail. Для
любого отказа `code` и `message` непустые; exception class хранится в `details`.
Fallback — конкретный код вроде `UPSTREAM_EMPTY_ERROR`, но никогда пустая строка.
RAG scheduler semantics фиксированы: `ACCEPTED` и `COALESCED` означают принятую
live retained scheduler работу и сами по себе не делают operation partial. Это не
persisted queue: после process restart гарантию восстановления дают #116
stale/watermark и T2 awaited backfill, а не старый scheduler status.
`NOT_READY` означает, что никакая RAG job не принята: result становится
`PARTIAL`, содержит непустой retryable `RAG_NOT_READY`, держит session gate и
указывает `FINALIZE_SAME_OPERATION`. T2 awaited backfill переводит stage в
`SUCCEEDED`, после чего evidence-backed resolution CAS снимает gate. `DISABLED`
является явным terminal policy state, а не скрытым `NOT_READY`.
Основные codes:
`BUSY`, `WAITING`, `TARGET_DIRTY`, `WORKER_DIRTY`, `CONFLICT`,
`ROLLBACK_FAILED`, `TARGET_MISSING`, `POST_COMMIT_PARTIAL`,
`IDEMPOTENCY_CONFLICT`, `TRANSPORT_TIMEOUT`, `TRANSPORT_ERROR`,
`SERVER_ERROR`, `UNKNOWN_OUTCOME`.

`structuredContent` всегда имеет `{result, error}`. `ok=false` больше не отвечает
на вопрос «commit существует?»: источник истины — `commit_point` и per-stage
statuses. `PARTIAL + commit_point=REACHED` остаётся typed success
(`isError=false`), запрещает raw retry и ведёт в finalize. `FAILED/UNKNOWN`
возвращают полный `result` плюс top-level copy `error` с `isError=true`.

### MCP behavior и rolling deploy

- Initial POST только durable принимает operation и возвращает `202`; merge живёт
  независимо от client connection. MCP одним tool call кратко читает status. Если
  operation ещё активна, он возвращает operation id, state и прямое
  `do not merge manually; retry with the same operation_id`.
- Transport timeout после POST сначала вызывает status lookup по известному key.
  Если сервер недоступен, caller получает `UNKNOWN_OUTCOME`, exception class,
  operation id и безопасное next action; пустой FastMCP suffix невозможен.
- `app/mcp_stdio.py` загружается раньше in-memory routes. Если новый endpoint ещё
  не доступен, MCP **не откатывается** на старый unsafe POST, а возвращает
  `MERGE_API_UPGRADE_REQUIRED` с требованием server restart. Рестарт остаётся
  ручным решением пользователя.
- После restart middleware в `app/main.py` запрещает любой HTTP POST в legacy
  `/api/sessions/{name}/merge` и возвращает typed `426 MERGE_OPERATION_REQUIRED`.
  Operation runner вызывает pinned Python entry point, поэтому guard не обходится
  внешним HTTP. Это блокирует и переживший restart старый MCP subprocess.
- Неустранимое окно «новый код уже в Git, старый server ещё в памяти» закрывается
  rollout gate: implementation merge выполняется только при объявленном
  merge-maintenance, после него пользователь сразу делает один controlled restart,
  а до capability probe `operation-v1` никакие merge calls не разрешены. Phase 3
  не рестартит service сам. После restart интеграционный test посылает настоящий
  legacy internal-token request и ожидает 426 без вызова Git.

## Reconcile/finalize contract

Один официальный двухшаговый workflow:

1. `reconcile_merge(...)` — read-only prepare. Создаёт durable manifest,
   проверяет commit/session/task/RAG/ref prerequisites и возвращает
   `reconcile_id` + точный список допустимых/запрещённых действий.
2. `finalize_merge(reconcile_id)` — повторно проверяет тот же manifest под
   session/lifecycle/#93 repo locks и применяет только разрешённые idempotent
   stages.

`validate_reconcile_provenance()` принимает только один из двух authoritative
sources:

- future: immutable `merge_operations` row с pinned session id/scope/repo/request;
- historical: tracked evidence entry, сгенерированный из retained orchestrator
  logs и содержащий source log ids, caller session id/scope, named worker
  worktree/branch, canonical git-common-dir и resulting target SHA.

Caller-supplied `scope` без такого evidence не является provenance и отклоняется.
Это сохраняет корректность cross-repo случая COG→Inscryption: scope берётся из
caller session evidence, repo — из named worktree evidence, а task project —
только через `get_project_by_scope(scope)`. Если retained evidence отсутствует,
автоматическая task attribution fail closed.

Для target commit обязательны: object существует; commit является ancestor
persisted target branch; scope/project совпадает; task ref либо присутствует в
subject и существовал к commit timestamp, либо передан явно и подтверждён в
prepare manifest. Произвольный SHA или молча угаданный task запрещены.

Worker ref можно двигать только когда одновременно истинны все условия:

- worker idle и worktree clean;
- current branch и HEAD точно равны manifest `expected_worker_branch/head` (CAS);
- доказано, что полный expected worker delta представлен в target history;
- перед reset создан и проверен durable
  `refs/orchestra/reconcile/<reconcile_id>/<worker>`;
- write-ahead lifecycle quarantine persisted до ref mutation.

Full-delta proof v1 намеренно строгий: `target_commit` имеет ожидаемого parent
`target_before`, а clean `git merge-tree --write-tree target_before worker_head`
даёт ровно `target_commit^{tree}`. Conflict-resolved/selective/manual merge, который
нельзя воспроизвести этим доказательством, получает `RESET_FORBIDDEN`; metadata и
RAG всё ещё можно восстановить. Семантических эвристик «похоже, всё перенесли» нет.

После проверки worker reset идёт на **текущий** target head, а не на старый
historical commit. CAS mismatch, неоднозначный manual conflict resolution или
новые worker commits запрещают reset, но не мешают независимо восстановить task
links/RAG. Никакой `force` и никакого auto `ours/theirs`.

Per-stage progress сохраняется после каждого шага. Повтор `finalize_merge` не
дублирует `git_commits`, не запускает второй ref reset и повторяет только
`FAILED/NOT_RUN` stages. RAG выполняется через существующий
`rag_service.backfill_scope`; `app/rag.py` не меняется.

Ref reset имеет отдельный crash journal:

1. durable quarantine;
2. create/verify backup ref → persist `BACKUP_READY`;
3. persist `RESETTING(expected_worker_branch, expected_old, intended_target,
   backup_ref)` **до** mutation;
4. CAS symbolic branch + ref/worktree reset и read-back Git snapshot;
5. persist `RESET_DONE` только после exact symbolic branch + head + clean-index
   verification.

При restart из `RESETTING` сначала читается symbolic HEAD. Detached HEAD или
`current_branch != expected_worker_branch` всегда даёт `UNKNOWN`: даже совпавший
OID не позволяет записать lifecycle для другой ветки. Только при точной ветке
`current HEAD = intended target` означает verify+done без второго reset, а
`current HEAD = expected old` разрешает один CAS retry с тем же backup. Любой
третий HEAD или dirty/index mismatch → `UNKNOWN`, quarantine остаётся, backup ref
является recovery authority. Crash между create backup и `BACKUP_READY` проверяет
существующий ref: exact expected OID принимается, другой OID блокирует finalize.

`resolved_at` меняется CAS-запросом `UPDATE ... WHERE state IN
('PARTIAL','UNKNOWN') AND resolved_at IS NULL AND result_hash=?`; rowcount должен
быть 1. Вместе сохраняются immutable `resolution_outcome`, evidence manifest hash,
actor/source и timestamp. Только `RESOLVED_NOT_REACHED` или
`RESOLVED_REACHED_FINALIZED` снимает operation/session gate; arbitrary
acknowledgement endpoint отсутствует.

### Что можно восстановить из нынешних strict 23

- **Task links: да, 23/23.** Все refs распознаются, задачи существовали раньше
  commit timestamps, target SHA известны; `link_commits_to_task` идемпотентен.
- **RAG: да.** Полный backfill по пяти scopes восстанавливает актуальные hashes;
  один batch не должен запускать больше одного backfill на scope.
- **Lifecycle/ref: частично.** Автоматически только для session, где сохранился
  точный expected worker head и CAS/tree verification проходит. Если branch уже
  содержит новую работу или original head/provenance утрачен, ref не двигается.
- **Необратимо без ручного решения:** mapping восьми manual commits без
  распознаваемого task ref и точные conflict decisions/selective-copy provenance,
  которых нет ни в operation record, ни в commit message.
- **Evidence-only, не recovery:** `0244e3d…` имеет `#182`, но named-worker merge
  был no-op, а commit создала отдельная правка `CLAUDE.md`; автоматические
  task/RAG/lifecycle/ref effects для него запрещены.

Phase 3 не применяет recovery к live DB/refs автоматически. Сначала формируется
read-only manifest; live `finalize` — отдельный явный пользовательский gate после
просмотра manifest.

### Pinned evidence SHA input (32: 31 candidates + 1 exclusion)

Ниже frozen SHA seed для T0 `recovery-input.json`; T0 дополняет его exact retained
source log ids и отвергает entry без такого evidence. T3 generator только читает
уже tracked snapshot и не переатрибутирует scope по поздним live данным.

```text
polus | /home/maxim/polus |
  a734c5ab1823001947eba3fc6bf3de3122fd7891
  9a5dcc0540d2d7831174801ff6947c50b022271a
orchestra | /mnt/data/Projects/Python/orchestra |
  ca6b8581f37eb384dfde18f5ab74f478c7b76e07
  ed5b5e3b2d027d1b1b265ecc842cf00b1d0f9e82
  a1a3d3b5283235530d4369d3156f9d635d06e429
  9793a44dee1321f5f2b4638f05f89688db4da02b
  7a8e1b7d7d6fc601aa3bd787a4967a340a856fa1
  aa3d382947e702e9720cd864d55702a6e6914186
  c2776320f547607d990bc894b78e01325e303f87
  6926fea07f19d4c43e0771de70f6ca6d49ea1fcb
COG-second-brain | /mnt/data/Projects/Python/inscryption-ai |
  6f75c4bce3e2deed3078d8d19b2549a8033310d5
  ae8b12789cd798819da4a7d8e938c8e99af716ae
  70c8e70f5db77169673527c1d930500473e952b3
  e2b2d0440b457aad086c606ee16b2c1256f0cca3
  4a250372fa500736bc78c7d592075aad4762db83
  fe75ac046504d6d0f0a9e4130ad3f3af95bf4169
  4ca09774b3e26d05724588e96f6fb331c91fc5e7
  351a248559078ae369d80c70f5d1650a2fe9d1ae
  ef7c67eb2ff9ae24833bcfba72e927f26a288e02
  25fad2515a39a8e8e4a5e1a1c581783f166c3c63
  7c5206b2d7027ba874918c7751d10f3f69d9abe4
seedon | /mnt/data/Projects/Python/seedon |
  f5147cb96cc29617cc7e3b30195f70c521ac6018
  0244e3d64d60fb4682451b3c7742c1abc963bce3
  2e19a830d34a0967db37675db4bafa9a2f669c30
  df720c8688a01b94bd43b5c747d49ab063aca403
seedon | /mnt/data/Projects/Python/seedon/site |
  12306a1c85310e968f8d2785b9835f1ee6bcc5f1
  8cfc8823f0baa6a1bd985a1e7ca9e80a85b6986f
kesha-tg-bot | /mnt/data/Projects/Python/kesha-tg-bot |
  1aba008c5d0e718170ea6ac96c14d907b4512179
  ea73409ebb6661d46354f2f6d41c14f2d3c48751
  7b1850dd8499c987b47e9854d7b2d553bb80f1ea
  d7829daee8a9b4c1b89a636825f13272b59ba208
  36c44f464642070fe60115b994334a55bbce6729
```

## Tickets

### T0 — Freeze retained manual-merge provenance

- Vertical outcome: до ожидания runtime dependencies появляется tracked,
  самодостаточный evidence snapshot, по которому 31 historical integration и один
  явно исключённый non-integration commit можно проверить даже после pruning live
  logs; отдельные backup refs сохраняют все 32 target commit objects при branch
  switch/rewrite и `git gc`.
- Files: `docs/tasks/115/recovery-input.json` (new).
- AC:
  - read-only export на frozen cutoff `logs.id <= 371999` содержит для всех 32 SHA
    source call/result log ids, caller session id/name/scope, named worker
    branch/worktree, canonical git-common-dir, target branch/SHA и минимальные
    exact integration/result excerpts с content hashes;
  - каждый recovery candidate имеет явную связь «named worker integration command
    → resulting target SHA»; простое упоминание SHA в позднем research/log output
    не считается source evidence. Единственный proven no-op хранится с
    `evidence_only_non_integration`, пустым списком разрешённых effects и не входит
    в recovery candidate count;
  - все 32 SHA повторно существуют и являются ancestors указанного target; число
    entries и unique SHA равно 32, COG entries явно сохраняют caller scope
    `COG-second-brain` при repo `inscryption-ai`;
  - export не пишет live DB/worktrees/target branches; он CAS-создаёт только
    `refs/orchestra/recovery/115/<full-sha>` с expected-old zero OID и проверяет
    exact value. Повтор идемпотентен, ref mismatch fail closed, refs остаются до
    отдельного cleanup gate;
  - после commit файл становится authoritative historical input, а T3 fail closed
    на entry вне него; refs делают каждый указанный object reachable для `git gc`.
- Price: **small** — один read-only export и Git verification.
- Risk: неверно выбранный source log закрепит ложную scope/task provenance.
- If implemented wrong: будущий reconcile либо откажется восстанавливать
  доказанный merge, либо свяжет SHA с одноимённой задачей другого project.
- blocked-by: **none**. Это первая Phase 3 action и не ждёт #93/#116.

### T1 — Durable idempotent `merge_worker` с непустым typed result

- Vertical outcome: один MCP call создаёт durable operation, безопасно переживает
  потерю HTTP response и возвращает однозначный commit/stage status; повтор не
  запускает второй merge.
- Files: `app/db.py`, `app/merge_operations.py` (new),
  `app/routes/merge_operations.py` (new), `app/main.py`, `app/mcp_stdio.py`,
  `tests/test_merge_operations.py` (new), `tests/test_mcp_stdio.py`,
  `tests/route_surface_snapshot.json`.
- AC:
  - fresh key durable создаёт `PENDING` до barrier первой mutation; cancellation
    HTTP request не отменяет tracked runner, terminal result затем читается тем же
    key;
  - 20 concurrent requests одного key и 2 разных keys одного session вызывают
    merge executor ровно один раз; payload mismatch того же key возвращает typed
    409 без side effects;
  - тот же arbitration test через два process owners/отдельные SQLite connections
    доказывает partial unique index и `PENDING→RUNNING` CAS; executor получает
    ownership только при `rowcount=1`;
  - response потерян, MCP process умер, operation успела стать `SUCCEEDED+REACHED`,
    `PARTIAL+REACHED` или `UNKNOWN`: retry с новым key при exact current==terminal
    session snapshot возвращает canonical old operation; unresolved
    partial/unknown блокируют merge даже при snapshot drift; `FAILED+NOT_REACHED`
    и clean no-op с новым key проходят новую pinned preflight и не кешируют
    исправленные busy/dirty либо новый target state;
  - retry terminal operation после recreation service/process читает сохранённый
    result; orphan `RUNNING` возвращает `UNKNOWN_OUTCOME` и никогда auto-rerun;
    fingerprint-matching orphan `PENDING` можно выполнить ровно один раз;
  - success, pre-commit failure, conflict, #93 rollback failure, commit success +
    task/link/lifecycle/next-task failure корректно становятся
    `SUCCEEDED/FAILED/PARTIAL` с `commit_point` и stage statuses;
  - ни MCP, ни generic admin endpoint не может выставить `resolved_at` для
    `PARTIAL/UNKNOWN`; это поле меняется только T2 resolution CAS с immutable
    evidence audit;
  - remove+respawn того же `(name, scope)` между accept и runner даёт
    `SESSION_IDENTITY_CHANGED/NOT_REACHED`; pinned #93 entry point не вызывает Git
    для новой session;
  - injected `httpx.ReadTimeout("")`, `ConnectError("")`, HTTP 500 с empty body,
    invalid JSON, empty upstream `error`, unknown DTO и formatter exception дают
    непустые #116 `code/message` + exception type в details + operation id; ни один test result не
    заканчивается голым `Error executing tool merge_worker:`;
  - busy/dirty/conflict result содержит retryability, exact known paths и
    `next_action`; string parsing остаётся только compatibility для rolling old
    #93 DTO и помечается `LEGACY_UPSTREAM_ERROR`;
  - scheduler statuses #116-T7 `accepted/coalesced/not_ready` без потери
    нормализуются в `rag.status=ACCEPTED|COALESCED|NOT_READY`; #115 не создаёт
    второй scheduler и не добавляет второй sessions route hunk; `NOT_READY`
    возвращает `PARTIAL + RAG_NOT_READY + FINALIZE_SAME_OPERATION`, держит gate до
    успешного T2 backfill, тогда как `ACCEPTED/COALESCED` подтверждают live
    retained scheduling и не понижают operation state; restart не трактует их как
    durable completion и идёт через #116 stale/watermark + T2 reconcile;
  - новый MCP против старого live route возвращает
    `MERGE_API_UPGRADE_REQUIRED`, не вызывает legacy merge endpoint;
  - после activation/restart настоящий old-MCP POST в legacy endpoint получает
    typed 426 и не вызывает Git; operation runner использует pinned Python entry
    point, новый MCP — только operation endpoint;
  - rollout test фиксирует hard maintenance sequence: все merge-capable sessions
    paused/no in-flight operation → #115 merge является последним legacy call →
    immediate user-controlled restart → legacy-426 и operation-v1 probes → resume.
- Price: **high** — SQLite operation state + background execution + MCP transport
  в одном shared-runtime slice.
- Risk: потерянная durable запись или ошибочная dedup → повторная mutation;
  неверный `commit_point` → оператор пойдёт raw Git поверх landed commit.
- If implemented wrong: возможны двойной merge, вечный ложный `RUNNING` либо
  ложный `FAILED` после commit — исходная P1 проблема в более убедительной форме.
- blocked-by: **#93-T1, #93-T2, #116-T3, #116-T7**. Не зависит от #93-T3/T4.

### T2 — CAS-safe reconcile/finalize partial или verified batch

- Vertical outcome: по operation id либо evidence-backed batch target commits
  можно безопасно доделать task links, один RAG backfill на scope и допустимую
  lifecycle/ref часть, не затерев новые worker commits.
- Files: `app/merge_operations.py`, `app/merge_reconcile.py` (new),
  `app/routes/merge_operations.py`, `app/mcp_stdio.py`,
  `tests/test_merge_reconcile.py` (new), `tests/test_mcp_stdio.py`.
- AC:
  - prepare полностью read-only; missing/non-ancestor/cross-scope SHA, task created
    after commit и task/project mismatch дают typed refusal;
  - future operation provenance проходит только из immutable operation row;
    historical provenance — только из source log ids + pinned caller
    session/scope/worktree/repo/SHA evidence; caller-supplied scope без evidence и
    same-number task другого project отклоняются;
  - finalize повторно проверяет manifest under session → lifecycle → #93 repo-lock
    order; изменение target/worker/session между prepare и finalize даёт CAS
    refusal до destructive stage;
  - task link использует target commit metadata и существующий idempotent helper;
    второй finalize добавляет 0 duplicates;
  - RAG disabled/failure/success отражаются отдельным stage; retry повторяет только
    failed/not-run RAG, successful stage не запускается снова; batch из N commits
    одного scope вызывает `backfill_scope` ровно один раз;
  - worker ref mutation невозможна без exact branch+HEAD, clean worktree, full
    delta/tree proof и verified backup ref; injected failure после backup оставляет
    backup reachable и durable quarantine;
  - newer worker commit между prepare/finalize сохраняется byte-for-byte, reset не
    вызывается, metadata/RAG result остаётся честным `PARTIAL`;
  - successful reset идёт на current target head, затем Git snapshot и lifecycle
    проверены; backup ref остаётся до отдельной cleanup policy;
  - crash injection до/после backup, `BACKUP_READY`, `RESETTING`, ref reset,
    snapshot verify и `RESET_DONE` следует read-after-crash rules: только exact
    expected symbolic branch + intended HEAD признаётся без повторного reset,
    exact branch + expected old допускает один CAS retry; detached/different branch,
    третий HEAD или dirty state остаётся quarantined `UNKNOWN` с reachable backup;
  - resolution CAS допускает только evidence-backed `RESOLVED_NOT_REACHED` либо
    `RESOLVED_REACHED_FINALIZED`, сохраняет manifest hash/actor/source и снимает
    gate ровно один раз; недостаточный/изменившийся evidence оставляет
    `PARTIAL/UNKNOWN`, а второй resolver получает rowcount 0;
  - после restart в каждом quarantine/resetting state HTTP, TG, bg-job и
    limit-wake fresh delivery через #93-T4 не начинает worker turn; после verified
    finalize gate снимается один раз;
  - restart после каждого persisted stage и повтор finalize сходятся к одному
    результату без повторного ref movement.
- Price: **high** — destructive Git recovery на границе Git/SQLite/RAG.
- Risk: ложноположительный tree proof или неверный CAS target может удалить более
  новую worker work; неверная ancestry/project проверка привяжет чужой commit.
- If implemented wrong: необратимая потеря worker commits либо тихая порча task
  provenance; поэтому fail closed важнее процента автоматически восстановленных
  refs.
- blocked-by: **T1, #93-T1, #93-T2, #93-T4**. Не зависит от #93-T3.

### T3 — Read-only recovery manifest для 31 manual integration + 1 exclusion

- Vertical outcome: оператор получает воспроизводимый план восстановления 23
  доказанных links, RAG по scopes и отдельно безопасную/запрещённую ref часть без
  live mutation.
- Files: `docs/tasks/115/recovery-manifest.json` (generated),
  `docs/tasks/115/recovery-report.md` (generated),
  `scripts/build_merge_recovery_manifest.py` (new),
  `tests/test_merge_recovery_manifest.py` (new).
- Input: immutable `docs/tasks/115/recovery-input.json` из T0.
- AC:
  - input artifact перечисляет 32 pinned full SHA/repo/scope/target и retained
    source log ids; generator fail closed на missing/ambiguous/non-orchestrator
    evidence и никогда не принимает scope только из CLI;
  - manifest содержит все 31 strict manual SHA и один evidence-only exclusion из
    T0, repo/scope/target, commit timestamp, parsed ref, task id, task-created-at и
    текущий link state;
  - ровно 23 entries получают `task_link=READY`, восемь —
    `NEEDS_EXPLICIT_MAPPING`, один — `EXCLUDED_NON_INTEGRATION` без automatic
    effects; ни один ref не выводится только из номера каталога;
  - generator вызывает batch prepare из T2; RAG actions дедуплицированы до одного
    backfill на scope, а gated batch finalize доказывает ровно один
    `backfill_scope` call на scope независимо от числа commits;
  - для каждого worker ref указаны observed current branch/head, expected head
    evidence и `RESET_READY` либо непустая причина отказа; отсутствие evidence
    никогда не превращается в `force`;
  - два запуска read-only prepare на неизменном snapshot дают одинаковый manifest
    hash; live DB, vec DB, refs/worktrees не меняются;
  - report явно отделяет recoverable links/RAG от partial/irrecoverable provenance
    и содержит команду/operation ids для будущего gated finalize.
- Price: **small/medium** — данные уже найдены, стоимость в безопасной верификации
  и manifest review.
- Risk: stale snapshot между manifest и будущим apply.
- If implemented wrong: неверный READY создаст ложную task attribution; поэтому
  final apply всё равно повторяет T2 checks и требует отдельного user gate.
- blocked-by: **T0, T2**. От #93 напрямую не зависит через уже проверенный T2.

### T4 — Единственный разрешённый worker-side conflict workflow

- Vertical outcome: conflict не ведёт оркестратора в target Git; result даёт
  pinned inputs и детерминированную инструкцию разрешить конфликт в worker branch,
  после чего новый merge operation завершает все side effects.
- Files: `app/merge_operations.py`, `app/mcp_stdio.py`,
  `tests/test_merge_operations.py`, `tests/test_mcp_stdio.py`.
- AC:
  - typed `CONFLICT` содержит exact paths, `target_before`, `worker_head`,
    operation id и next action; path с пробелами сохраняется целиком;
  - next action разрешает merge только pinned target SHA **в worker branch**,
    commit разрешения там и новый `merge_worker`; нет `cherry-pick`, checkout/reset
    target, `ours/theirs`, `force` или инструкции менять main;
  - `/tmp` integration: первый conflict оставляет target/ref/index clean; worker
    merge pinned SHA + явный resolution commit; retry с новым key создаёт один
    target commit и возвращает task/RAG/lifecycle stages;
  - если target сдвинулся после worker resolution, retry заново валидирует refs и
    либо безопасно мержит, либо возвращает новый conflict; stale result не форсит
    старый target;
  - `TARGET_DIRTY`/`WORKER_DIRTY` перечисляют exact paths и дают только clean-up
    action в соответствующем checkout; target mutation не запускается;
  - до merge #93-T1/T2 этот workflow недоступен с явным
    `DEPENDENCY_NOT_READY`, а не советует raw fallback;
  - `pipelines/` не меняется; prompt-ban остаётся вне #115.
- Price: **medium** — новый contract/formatter плюс real Git scenario, без нового
  merge engine.
- Risk: неверный pinned SHA или двусмысленная инструкция заставит worker решить не
  тот conflict; stale target без revalidation потеряет более свежие изменения.
- If implemented wrong: конфликт снова вытолкнет оркестратора в raw target merge
  либо worker resolution тихо затрёт одну сторону.
- blocked-by: **T1, #93-T1, #93-T2**. Не зависит от T2/T3 и #93-T3/T4.

## Порядок реализации и gates

1. Сразу выполнить T0 read-only и закоммитить provenance snapshot, не ожидая
   runtime dependencies или pruning retained logs.
2. Дождаться merge #93-T1/T2 и #116-T3/T7; проверить pinned entry point, outcome,
   shared MCP envelope и scheduler status contracts.
3. Реализовать T1; deployment только через hard maintenance sequence из T1 AC.
4. T4 можно делать сразу после T1. T2 дополнительно ждёт #93-T4, затем остаётся
   независимым от T4.
5. T3 запускается только после T0/T2 и остаётся read-only.
6. После Codex implementation review и полного suite показать recovery manifest
   пользователю. Live finalize 23 links/RAG/refs требует отдельного явного «apply».
7. Только после наблюдаемого периода без raw rescue отдельная задача может менять
   prompt/policy. Это не acceptance criterion #115.

## Проверка Phase 3

- Узкие suites после каждого ticket:
  `tests/test_merge_operations.py`, `tests/test_merge_reconcile.py`,
  `tests/test_mcp_stdio.py`; route snapshot обновляется только для новых endpoints.
- Все Git scenarios — только temp repos/SQLite через `tmp_path`; ни один test не
  читает и не меняет live DB/worktrees.
- Full suite под test lock:
  `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.
- Codex review production+tests diff; blocking findings проверяются по коду и
  исправляются в той же session.
- Read-only live compatibility перед rollout: все current session scopes/names,
  operation schema migration на копии live DB, 32-SHA manifest generation.
- Сервер не рестартится автоматически. После merge implementation новый MCP
  fail-closed сообщит `MERGE_API_UPGRADE_REQUIRED`, пока пользователь явно не
  перезапустит Orchestra.

## Что намеренно не входит

- правки `app/manager.py`, `app/workspace.py`, `app/routes/sessions.py` — #93;
- правки `app/tg_bridge.py` — #111/#114;
- правки `app/rag.py` — #113; используется только `rag_service` API;
- любые правки `pipelines/` и запрет raw merge в prompts;
- автоматический `ours/theirs`, raw target cherry-pick или fallback на legacy
  `/api/sessions/{name}/merge`;
- live backfill 23 commits без отдельного gate;
- исправление двойного prefix в `_build_squash_message`: root cause доказан, но
  файл принадлежит #93 territory; вынести в отдельный follow-up после #93.
