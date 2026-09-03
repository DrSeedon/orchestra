<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

«Просто переименуем каталоги» внезапно оказалось миграцией состояния на 18 репозиториев 🤨

## Summary

Исследование правильно выявляет cross-project blast radius, различает historical `source_path` и current manifest path и отвергает backend-connect mutation. Но rollout и acceptance пока небезопасны: есть риск потери памяти в старых worktree, неполное evidence-доказательство и некорректный pytest baseline. Файлы не редактировал; `codex_review` недоступен, выполнено статическое ревью текущего кода.

## Findings

1. blocking: `docs/tasks/430/research.md:269-274` — commit в project main не мигрирует существующие worker worktrees. Текущий код читает memory из `repository_path or scope` и для worker передаёт именно `wt_path` (`app/prompting.py:59-73`, `app/manager.py:750-753`). Старый worktree после переключения prompt не содержит `.orchestra/workers`, поэтому `load_worker_memory()` тихо вернёт пустую строку. Нужен per-worktree rollout/rebase/recreate gate для всех живых и recovery-сессий.

2. blocking: `docs/tasks/430/research.md:266-277` — live canary не имеет механически определённого project scope. Существующий prompt receipt проверяет только `(runtime, role)` и вызывает assembler без scope (`app/ia/cutover.py:296-320`), а worker prompt сейчас тоже собирается без scope (`app/manager.py:745`, `1773-1775`). Один успешный агент не доказывает безопасность остальных 18 репозиториев; нужен receipt на каждый scope либо запрет global switch до прохождения всего fleet.

3. blocking: `docs/tasks/430/research.md:197-231` — не учтён validator новых evidence paths. `KnowledgeService._cold_source_path()` принимает `docs/tasks`, `docs/kb` и `docs/archive`, но отвергает `.orchestra/...` (`app/ia/knowledge.py:676-689`). После миграции импорт нового evidence будет падать, если не определить двухпоколенный allowlist: старые пути для pinned commits плюс новые пути для текущих источников.

4. blocking: `docs/tasks/430/research.md:214-226,269-274` — проверка трёх pinned records не подтверждает сохранение 12 503 исторических ссылок. Byte/count parity проверяет перемещённые файлы и manifest, но не все `git_commit:path → git_blob → SHA` bindings. Acceptance должен делать полный детерминированный проход по всем records, а не только три случайных образца.

5. blocking: `docs/tasks/430/research.md:351-368` — заявленный failed-node baseline не является результатом одной полной pytest-команды: full run завершился `RC=137` на 82%, затем добавлен отдельный overlapping shard. Union из 50 node ids неполон и не сопоставим с будущим полным запуском. Нужен фиксированный набор одинаковых shards/collection manifest для before и after с отдельным исходом `incomplete`.

6. suggestion: `docs/tasks/430/research.md:91-99` — число `comfy 1 747` расходится с supplied fleet snapshot, где указано 1 745. Перед Phase 2 стоит зафиксировать определение счётчика, дату и воспроизводимую команду, иначе parity-проверки будут стартовать с неоднозначной population.

7. suggestion: `docs/tasks/430/research.md:101-119` — inventory назван exhaustive, но для AST/path-component pass приведены только три примера, без команды, exclusions и машиночитаемого полного списка. Сохраните inventory с referrer-классом и строками; иначе Phase 2 не сможет механически доказать отсутствие пропущенных split/dynamic call sites.

8. question: `docs/tasks/430/research.md:259-262,384-387` — Dockerfile и TODO признаны вне владения, но не определён обязательный coordination receipt, без которого запрещается считать cutover завершённым. Кто и каким артефактом подтверждает их обновление или явное вынесение в dependent ticket?

## Verdict

Исследование полезно и основные load-bearing выводы подтверждаются текущим кодом, но в текущем виде **не готово передавать работу в Phase 2**. Сначала нужно закрыть worktree/scope rollout, полный evidence gate и воспроизводимый pytest protocol.

Иначе получится prompt уже новый, а память всё ещё живёт в старом worktree — цифровой переезд с чемоданами, оставленными на вокзале.

## Round (2026-09-01T17:11:45Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, inventory тоже решил стать частью inventory — самоотчётность уровня бюрократии 🤨

## Summary

Round 1 statuses:

| Item | Status | Evidence |
|---|---|---|
| B1 | FIXED | `research.md:287-297` — live/resumable worktree gate |
| B2 | FIXED | `research.md:294-296` — receipt per scope/worktree, global switch only after fleet |
| B3 | FIXED | `research.md:245-249` — transitional `.orchestra` validator |
| B4 | FIXED | `research.md:229-233` — полный проход 12 759 path/blob/SHA |
| B5 | FIXED | `research.md:380-405` — incomplete baseline + collection + six shards |
| S6 | FIXED | `research.md:423-425,487-488` — stale/fresh count conflict explicitly recorded |
| S7 | STILL BROKEN | inventory generator self-includes future tracked artifacts |
| Q8 | FIXED | `research.md:426-429` — mandatory dependent-ticket receipt |

## Findings

1. blocking: `docs/tasks/430/reference_inventory.py:16-18,128-154` — generator scans every tracked file but excludes nothing. Сейчас весь `docs/tasks/430/` untracked, однако после коммита он начнёт сканировать собственные `research.md`, `reference_inventory.py` и особенно `reference-inventory.tsv`, где старые literals повторяются в каждой строке. Поэтому заявленные 26 202 rows, 13 827 files и SHA изменятся при обычном повторном запуске, а S7 нельзя считать исправленным. Нужно исключить output/generator/research из входа либо зафиксировать неизменяемый allowlisted input tree и commit.

## Verdict

**НЕ APPROVED.** Все прежние blocking findings B1–B5 закрыты, S6 и Q8 закрыты, но S7 остаётся блокирующим для заявленной воспроизводимости inventory из-за self-inclusion. `codex_review` недоступен; проверка выполнена статически по артефактам и текущему генератору.

Иначе реестр referrer’ов превращается в зеркало, которое заносит в список само себя — и ещё по строке на каждый чих.
