# Task #88 — финальный отчёт

## Результат

Исходный диагноз «`spawn_worker` игнорирует `repo_path` для незарегистрированного проекта» опровергнут production logs и Git metadata:

- Inscryption worktree принадлежал `inscryption-ai/.git`; COG был только logical scope slug.
- `batch4-food-services` принадлежал Orchestra, потому что caller передал `repo_path=/mnt/data/Projects/Python/orchestra`.
- Незарегистрированные repository roots уже поддерживались и остались поддержаны.

Исправлены два подтверждённых дефекта:

1. `repo_path` теперь проходит точный fail-loud preflight до spawn side effects.
2. `spawn_worker` теперь показывает фактические worktree/repository/common-dir/branch и не скрывает failure доставки initial task.

## Tickets

### T1 — Fail-loud primary repository preflight: DONE

- `app/workspace.py:121` — `validate_repo_root()` принимает только exact ordinary primary checkout.
- Отклоняются с ясными ошибками:
  - missing;
  - standalone non-Git;
  - nested path, для которого Git нашёл parent root;
  - bare repository;
  - linked worktree;
  - gitfile / `--separate-git-dir`;
  - symlinked/external `.git`.
- `app/manager.py:414-419` — missing/invalid `repo_path` отклоняется до `delete_archived_session`, persistence, task mutation, auto-commit и worker start.
- `app/session.py:200-201`, `app/manager.py:540-541` — canonical repository/common-dir сохраняются как transient spawn metadata до lifecycle commit point; DB migration не нужна.
- `create_worktree()` повторяет validation для прямых call-sites.
- `scope != repo_path` и незарегистрированные ordinary roots продолжают работать.

### T2 — Прозрачный spawn result и честная incident history: DONE

- `app/routes/sessions.py:134-136` — API возвращает retained server-side metadata без fallible Git discovery после worker start.
- `app/mcp_stdio.py:156-195`:
  - требует четыре non-empty string metadata fields;
  - печатает API `worktree_path`, `repo_path`, `git_common_dir`, `branch` verbatim;
  - malformed create response сообщает, что worker мог быть создан, и не отправляет initial task;
  - send failure сообщает «worker создан, task не доставлен», сохраняет mapping и не печатает `Task sent`.
- `BUGS.md` — обе исторические записи сохранены, но диагноз помечен `REFUTED/CORRECTED`; записаны фактические tool inputs, common dirs и исправления #88.

## TDD и тесты

RED evidence:

- initial T1 run: `9 failed` — helper отсутствовал, nested path принимался, standalone non-Git падал поздним `RuntimeError`, manager preflight отсутствовал;
- initial T2 run: `3 failed, 1 passed` — mapping отсутствовал, malformed success отправлял task;
- Codex Round 1 fixes: `10 failed, 3 passed` — empty-path bypass, post-create metadata discovery, wrong metadata types и ignored send failure;
- Codex Round 2 fixes: `3 failed` — metadata не retained, route выполнял Git после start, strict external-layout contract не был закреплён;
- final guard: symlinked `.git` regression сначала `1 failed`.

GREEN evidence:

- T1 focused: `10 passed in 2.37s`;
- workspace + manager: `147 passed in 4.40s`;
- T2 MCP: `21 passed in 2.32s`;
- first combined targeted: `168 passed in 5.18s`;
- after Round 1: `228 passed in 46.52s`;
- affected runtime after Round 2: `318 passed in 54.63s`;
- final validator class: `8 passed in 2.69s`;
- final full suite: `941 passed, 20 skipped in 92.12s`.

Final full-suite artifact: `/tmp/pytest-88-final.log`.

## Проверка живой конфигурации после merge main

Read-only запрос к `/mnt/data/Projects/Python/orchestra/data/orchestra.db` вернул 17 distinct scopes с non-archived sessions. Тот же `validate_repo_root()` прогнан по каждому:

- 16 реальных project scopes прошли, включая Orchestra, Seedon, Sensar, Polus и COG-second-brain;
- актуальный Polus scope — `/home/maxim/polus`, а не `/mnt/data/Projects/Python/polus`;
- актуальный COG scope — `/home/maxim/Рабочий стол/Cursor/COG-second-brain`; после `Path.resolve()` это `/mnt/data/Рабочий стол/Cursor/COG-second-brain`, exact primary root с локальной `.git`;
- единственный FAIL — синтетическая stale session `worker-1` со scope `/test/scope`, cwd `/tmp`, созданная 2026-07-18; путь не существует и project orchestrator отсутствует.

Итог: ни один живой project scope не ломается новым strict contract.

После разрешения merge conflict полный suite на объединённой ветке: `942 passed, 20 skipped in 91.36s`; artifact `/tmp/pytest-88-post-merge.log`.

## Codex adversarial review

Artifacts:

- `docs/tasks/88/codex-review-plan.md`;
- `docs/tasks/88/codex-review-impl.md`.

Plan review: 0 blockers; четыре suggestions приняты.

Implementation:

- Round 1: два blockers — empty `repo_path` bypass и ложный `Task sent` при delivery failure; исправлены.
- Round 2: два blockers — lifecycle для временно принятого separate-git-dir layout и Git lookup после worker start.
- Round 3: separate/external Git-dir layouts явно выведены из product contract; metadata перенесена в manager preflight. Verdict: **APPROVED**, новых blocking crash/wrong-repo/security/orphan-lifecycle defects нет.

## Adversarial self-review

- Возможный orphan session при `repo_path=""|None` закрыт manager-ordering tests.
- Возможный «worker создан, но caller увидел success без task» закрыт send-result validation.
- Возможный post-start API error из-за повторного Git lookup закрыт retained metadata и тестом, который перемещает repository сразу после fake manager return.
- Возможный неверный `_resolve_repo()` для external common dir закрыт узким accepted-layout contract и tests для linked, gitfile и symlinked `.git`.

## Breaking / migration / operations

- **Intentional breaking validation:** `repo_path` обязан быть ordinary primary working-tree root с собственной реальной `.git` directory. Linked, gitfile, bare, nested и external-Git-dir layouts отклоняются.
- Success response расширен диагностическими строками; прежняя первая строка сохранена.
- DB schema/migrations: none.
- Server restart/deploy: не выполнялись.
- TODO: none.

## Commits

- `b65159b` — research;
- `e727cf6` — plan;
- `d9419b6` — exact root preflight;
- `9982706` — visible spawn mapping;
- `a78f93e` — corrected BUGS diagnoses;
- `16b5c0e` — Round 1 lifecycle fixes;
- `1f37eb0` — retained preflight metadata;
- `9ca64b2` — strict external Git-dir guard.

## Reusable lesson

Каталог `worktrees/<scope-slug>/<worker>` доказывает только logical scope, не physical Git source. Для расследования и пользовательского ответа источником истины являются server-validated repository root и `git-common-dir`; успешный lifecycle tool должен показывать их сразу.
