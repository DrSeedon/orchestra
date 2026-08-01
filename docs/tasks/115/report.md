# #115 — Phase 3 progress report

## Выполнено: T0 evidence freeze

T0 завершён отдельно от заблокированных runtime tickets. Зафиксирован
`recovery-input.json` с 32 historical target commits:

- 31 strict manual integration candidates;
- 23 candidates с однозначным numeric task ref;
- 8 candidates требуют explicit human mapping;
- `0244e3d64d60fb4682451b3c7742c1abc963bce3` сохранён только как
  `evidence_only_non_integration`: worker merge был no-op, commit создала отдельная
  caller-side правка, поэтому automatic task/RAG/lifecycle/ref effects запрещены.

Каждый из 32 объектов закреплён exact custom ref
`refs/orchestra/recovery/115/<full-sha>`, созданным CAS against zero OID. Ни один
target/worker branch, worktree или DB row не изменён. Распределение refs:

- `/home/maxim/polus`: 2;
- `/mnt/data/Projects/Python/orchestra`: 8;
- `/mnt/data/Projects/Python/inscryption-ai`: 11;
- `/mnt/data/Projects/Python/seedon`: 4;
- `/mnt/data/Projects/Python/seedon/site`: 2;
- `/mnt/data/Projects/Python/kesha-tg-bot`: 5.

Refs сохраняют objects при local branch switch/rewrite и `git gc`, но не переживут
удаление самого repository или fresh clone без переноса refs. Удалять их можно
только после отдельного cleanup gate через exact-value CAS against recorded OID.

## Проверка

- JSON SHA-256:
  `6e551db4e68f223db194e0c3fc30ecfa8b3d2dc748f544e6faebcad4a96aa679`;
- 32 unique entries, 31 candidates, 1 evidence-only exclusion;
- 118 embedded source records / 102 unique log IDs; для каждого повторно
  проверены cutoff `<=371999`, timestamp, full-content SHA-256 и exact excerpt
  против SQLite в read-only mode;
- 32/32 refs resolve в recorded full OID; каждый object имеет type `commit` и
  остаётся ancestor указанного `main`;
- 0/32 SHA присутствуют в live `tm_tasks.git_commits`;
- strict secret scan и `git diff --check` прошли;
- Codex Round 1 нашёл false-positive Seedon и недостаточную Polus provenance;
  оба finding подтверждены по DB и исправлены. Round 2: `APPROVE`, новых findings
  нет. Первоначальные возражения сохранены в `codex-review-t0.md`.

## Координация и оставшаяся работа

Контракт #116 согласован 1:1:
`structuredContent={result,error}` с единым envelope; PARTIAL сохраняет full
domain DTO. `ACCEPTED/COALESCED` означает приём в live retained scheduler, а не
durable queue; после restart восстановление идёт через watermark/reconcile.

T1–T4 не начаты. Они остаются заблокированы принятыми зависимостями #93 и #116;
следующий шаг возможен только после отдельной команды оркестратора.

Breaking changes: none.
