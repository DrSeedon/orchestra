# #115 — Phase 3 progress report

## Выполнено: T0 evidence freeze

T0 завершён отдельно от заблокированных runtime tickets. `recovery-input.json`
schema v2 содержит 33 target commits:

- 32 strict manual integration candidates;
- 23 candidates с однозначным numeric task ref;
- 9 candidates с owner-confirmed решением **не добавлять task link**;
- `0244e3d64d60fb4682451b3c7742c1abc963bce3` сохранён только как
  `evidence_only_non_integration`: worker merge был no-op, commit создала отдельная
  caller-side правка, поэтому automatic task/RAG/lifecycle/ref effects запрещены.

Каждый из 33 target objects закреплён exact custom ref
`refs/orchestra/recovery/115/<full-sha>`, созданным CAS against zero OID. Для
post-cutoff exact-SHA lineage дополнительно закреплён source commit
`35f02293d8d1fca9c83aa66f7a42687bb404de73` под
`refs/orchestra/recovery/115/source/<full-sha>`. Ни один target/worker branch,
worktree или DB row не изменён. Распределение target refs:

- `/home/maxim/polus`: 2;
- `/mnt/data/Projects/Python/orchestra`: 9;
- `/mnt/data/Projects/Python/inscryption-ai`: 11;
- `/mnt/data/Projects/Python/seedon`: 4;
- `/mnt/data/Projects/Python/seedon/site`: 2;
- `/mnt/data/Projects/Python/kesha-tg-bot`: 5.

Refs сохраняют objects при local branch switch/rewrite и `git gc`, но не переживут
удаление самого repository или fresh clone без переноса refs. Удалять их можно
только после отдельного cleanup gate через exact-value CAS against recorded OID.

## Проверка

- JSON SHA-256:
  `4ed7eb452136b79bdd8a4786004b9090436b5b4dbf5c89164cb76537db6b4214`;
- 33 unique entries, 32 candidates, 1 evidence-only exclusion;
- 124 embedded evidence records / 108 unique log IDs: 118 records исходного
  frozen set проверены по cutoff `<=371999`, ещё 5 составляют разрешённую
  post-cutoff lineage, 1 фиксирует owner decision; для каждого проверены
  timestamp, full-content SHA-256 и exact excerpt против SQLite read-only;
- 33/33 target refs и 1/1 source ref resolve в recorded full OID; каждый target
  имеет type `commit` и остаётся ancestor указанного target branch;
- source/target `35f0229… → 9ff4a7f…` имеют одинаковый stable patch-id
  `6332a138486d9e4cbe8495de7a01ab8dddce699d`;
- immutable command excerpt сохраняет создание/checkout fresh branch от `main`;
  target parent и recorded `main_before` оба равны `6926fea…`;
- 0/33 SHA присутствуют в live `tm_tasks.git_commits`;
- strict secret scan и `git diff --check` прошли;
- Codex Round 1 нашёл false-positive Seedon и недостаточную Polus provenance;
  оба finding подтверждены по DB и исправлены. Round 2: `APPROVE`, новых findings
  нет. Первоначальные возражения сохранены в `codex-review-t0.md`;
- Codex extension Round 1 потребовал сделать fresh-branch proof независимым от
  pruneable SQLite. В artifact добавлены полный command excerpt и exact
  `main_before == target parent`; Round 2: `APPROVE`, dissent сохранён в
  `codex-review-t0-extension.md`.

## Координация и оставшаяся работа

Контракт #116 согласован 1:1:
`structuredContent={result,error}` с единым envelope; PARTIAL сохраняет full
domain DTO. `ACCEPTED/COALESCED` означает приём в live retained scheduler, а не
durable queue; после restart восстановление идёт через watermark/reconcile.

T1–T4 не начаты. Они остаются заблокированы принятыми зависимостями #93 и #116;
следующий шаг возможен только после отдельной команды оркестратора.

## Дополнение: восемь commits без numeric task ref

Read-only attribution review завершён в `manual-mapping-review.md`. Для всех
восьми fail-closed решение одинаково: **task link не добавлять**. Ни commit,
branch/worktree, `sessions.task_id`, доступные assignment rows, ни Task Manager не
дают exact `#N`; тематически близкие задачи имеют другой intent.

Три manual prompt-engineer integrations входят в исходный frozen set. Четвёртая,
`9ff4a7f`, добавлена как 33-й entry / 32-й recovery candidate без task link.
Exact lineage доказана цепочкой `[from:prompt-engineer] DONE 35f0229 → exact
cherry-pick → target 9ff4a7f → ff-only main`, равным stable patch-id и двумя
exact refs. Для записей после cutoff действует default reject: исключение возможно
только по такой доказанной lineage и owner decision; временная/тематическая
близость не принимается и branch/head evidence остальных entries не ослабляется.

Codex Round 1 подтвердил `1–8 → skip`, уточнил две source chains и границу
classifier; Round 2 после исправлений: `APPROVE`, новых findings нет.

Breaking changes: none.
