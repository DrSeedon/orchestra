# project-portfolio

## Установлено

- `scope` — одна техническая process/session string (`ORCHESTRA_SCOPE`), а не portfolio identity; session хранит один scope, task resolution и visibility выводят project из него · `app/manager.py:417-430`; `app/mcp_stdio.py:40,957`; `app/tm.py:605-634` · 2026-08-30, #418
- Human/task project уже существует как `tm_projects`: `tm_tasks.project_id` обязателен, но owner relation отсутствует; live snapshot содержит 19 project rows / 13 non-null distinct scopes / 6 rows без scope и 732 tasks во всех 19 project ids · `app/db.py:375-411`; read-only SQLite query in `docs/tasks/418/research.md` §3.3 · 2026-08-30, #418
- Cross-repo `spawn_worker(repo_path=...)` у живого parent сохраняет parent `SCOPE`, поэтому Git worktree может быть в другом repository, а task/number остаются в parent project · `app/mcp_stdio.py:920-928,932-967` · 2026-08-30, #418
- Project owner isolation сейчас не принуждается: DB и spawn lock уникальны по `(name, scope)`, поэтому разные orchestrator names в одном scope проходят; enforcement seam — atomic project-owner assignment после определения `is_orch` и до side effects · `app/db.py:53-77`; `app/manager.py:608-611,652-700` · 2026-08-30, #418
- Seedon duplicate — migration debt: `seedon-orchestrator` не имеет parent и создан 09.05, `dev-lead` создан 31.05 с `parent_name=seedon-orchestrator` и завершённой task #35; у `dev-lead` шесть live idle children, unfinished bound child tasks нет · live SQLite joins, exact output in `docs/tasks/418/research.md` §5 · 2026-08-30, #418
- Task board не может доверять текущему `in_progress`: frozen 2026-08-30T06:28:16.825Z snapshot дал 79 tasks/8 projects, из них 26 bound к archived sessions, 18 без binding, 31 к idle, 3 к running и 1 к waiting · full read-only SQL/output in `docs/tasks/418/research.md` §6 · 2026-08-30, #418
- Archive lifecycle с 24.08 requeues orphan `in_progress → new` или elects a live heir atomically, но старый debt не backfilled и idle/wait ambiguity остаётся · `app/tm.py:906-938`; `app/db.py:1588-1599`; commit `6f874ace` · 2026-08-30, #418
- Threshold alone does not prevent watchdog spam: corrected synthetic dirty-state replay (exactly one owner, bounded `start<=ts<=end`, no post-cutoff gift tick) gave 176 edge episodes / 33,885 repeated 5-minute triggers at 30m and still 20 / 19,613 at 24h; missing historical task transitions/bg intervals mean it is neither a frequency nor an upper bound, only a sensitivity counterexample · `docs/tasks/418/watchdog_replay.py`; definition/output in research §8 · 2026-08-30, #418
- Codex goal exists as stable `/goal`: a persistent active-chat objective with view/edit/pause/resume/clear and verifiable stopping condition; it is thread-local and does not supply project ownership or a shared board · https://learn.chatgpt.com/use-cases/follow-goals ; `codex features list` → `goals stable true` · 2026-08-30, #418
- Only proposed new agent tool is `project_wait(project, question, task_ref="")`: explicit project is mandatory because one owner may own several and task numbers are project-scoped; without the tool the agent must perform authenticated owner/project/task resolution, durable wait write and duplicate/suppression CAS · `docs/tasks/418/research.md` §9 · 2026-08-30, #418

## Отвергнуто

- «Чистый frontend поверх scope выполняет заказанные invariants» · one session has one scope, cross-repo task remains in parent project, owner uniqueness and durable question have no storage · `docs/tasks/418/research.md` §§3–4 · 2026-08-30, #418
- «Нужна новая таблица human projects рядом с `tm_projects`» · existing task FK/project namespace already owns all 732 tasks; a second registry would add reconciliation without a new property · `app/db.py:375-411`; live counts · 2026-08-30, #418
- «Большой threshold исправит ложные watchdog pings» · corrected synthetic sensitivity replay at 24h still emitted 20 edge episodes and 19,613 repeated ticks under the stated dirty-state model; task truth, not timer length, is the load-bearing dependency · `docs/tasks/418/research.md` §8 · 2026-08-30, #418
- «Codex goal не существует» · official OpenAI docs and local CLI 0.150.1 both expose it · https://learn.chatgpt.com/docs/developer-commands?surface=cli ; local feature registry · 2026-08-30, #418

## Пробелы

- Worker target identity: `sessions.project_id` versus stable task id · architecture choice deliberately deferred for user discussion before Phase 2 · 2026-08-30, #418
- Optimal stall threshold · 30m is the proposed six-check initial value; exact historical task-state timeline is incomplete, so 14-day post-reconciliation shadow telemetry is required · 2026-08-30, #418
- Visual column order and whether idle owner counts as active work · user decision not yet recorded · 2026-08-30, #418

## Источники

- docs/tasks/418/research.md — code trace, live DB measurements, two variants, watchdog replay, board/wait/goal verdict and Seedon migration proposal.
