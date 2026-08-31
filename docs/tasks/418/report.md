# #418 — Phase 3 report

Статус: **implementation complete**. Реализация T1–T4 и подтверждённый post-ceiling P1 fix
закончены. Внешний reviewer не смотрел последнюю одно-строчную правку: verdict APPROVED не заявляется.

Diff from merge-base: **21 files, +3159/-96 lines** — backend schema/service/routes/watchdog/MCP/TG,
dashboard JS/CSS, orchestrator prompt, frozen/focused tests, route snapshot and task/KB/report artifacts.

## Реализовано

- Authoritative `portfolio_projects` с одним root-orchestrator owner, explicit
  sub-orchestrator contributors и optional links к неизменённому technical task namespace.
- Project-owned goals, progress receipts, durable waits и два justified MCP tools:
  `project_goal` и `project_wait`.
- Optional 300-second stall watchdog, shadow by default, с generation-scoped durable outbox,
  retry delivery ID и per-claim token.
- `PROJECTS` button и четырёхколоночная панель внутри существующего `#tasks-panel`; отдельной
  `/project-board` страницы нет.
- Typed durable attention (`legacy|incident|reversal|plan_change`), fail-loud explicit-call
  fallback по #241; wait/watchdog не входят в user-tag path.
- Orchestrator prompt: решения project-bound работы идут через `project_wait`; generic
  `knowledge` не менялся.

## Tool utility gate

- `project_goal`: без tool агенту пришлось бы authenticated-resolve membership/owner policy,
  читать revision, атомарно менять goal + `stall_generation` + activity lease + progress receipt
  и разруливать lost-response replay. Это multi-write transaction/CAS, а не короткая запись в файл
  или поле задачи; tool оставлен.
- `project_wait`: без tool агенту пришлось бы resolve project/member/current goal/optional linked
  task, вычислять duplicate claim и атомарно записывать blocker + watchdog suppression. Tool оставлен.
- Отдельного task-link/list/board tool нет: link встроен в existing `task_update`, чтение живёт в API/UI.

## Проверки к моменту STOP

- Frozen acceptance: `uv run python -m pytest -q docs/tasks/418/acceptance/test_project_portfolio_418.py`
  → `4 passed`; production `sessions 79→79`.
- Focused backend/frontend/TG/schema run → `127 passed`; production `sessions 79→79`.
- Review-fix focused run → `124 passed`; final progress-focused run → `32 passed`.
- Final combined frozen/portfolio/TG/routes/DB/frontend run after the post-ceiling fix →
  `135 passed`; production `sessions 79→79`; `search_memory` decorator count `1`.
- `tests/test_tg_bridge.py::TestNotifyUserMention` → `12 passed` после сохранения #241 fallback.
- Route surface: `18 added / 0 removed`; snapshot green.
- Browser probe: 4 lanes, no page errors; panel width `1049.59px` at 1280 and `1180px` at 1920.
- SQLite backup migration: legacy `sessions 79→79`, `tm_tasks 0→0`; all portfolio tables start
  with 0 rows. Probe used `sqlite3.Connection.backup`, never production writes.
- Full `pytest -x` stopped at unchanged `tests/test_api.py::TestTaskProjectIdentity::test_create_defaults_to_callers_mapped_scope`:
  canonical allocator returned 400; no #418-touched caller appeared in that traceback.

## Review ceiling и post-ceiling fix

Luna Round 3 нашла, что `app/portfolio.py` выбирал same-note progress receipt через
`ORDER BY created_at DESC,id DESC`, хотя решение сравнивает `stall_generation`. Оркестратор
независимо подтвердил P1 и после потолка явно разрешил канонический фикс:
`ORDER BY stall_generation DESC,id DESC`.

Два новых regression cases отдельно покрывают out-of-order и equal timestamps. Оба были RED на
старом order, оба green на generation order. Mutation обратно дала `2 failed`, restore — `2 passed`;
маркеры: fix `1→1`, mutant `1→0`. Остальные три time-ordering места проверены: task cards,
contributors и projects сортируются только для показа человеку, поэтому `created_at` там законен.

Post-ceiling test: frozen acceptance + `TestNotifyUserMention` + integrity regressions →
`21 passed`; production `sessions 79→79`.

Review artifact: `docs/tasks/418/review-implementation-luna.md` — Round 1: 8 blockers; Round 2:
all 8 fixed + one default-progress blocker; Round 3: default fixed + ordering blocker. **Последний
fix сделан после потолка и внешним ревьюером не смотрен; approved verdict отсутствует.**

## Pre-mortem checks

- Existing task lifecycle/delete мог сломаться из-за optional FK → `ON DELETE CASCADE` regression
  удаляет technical task после unlink и получает 0 dangling receipts.
- Stale watchdog callback мог открыть уже accepted delivery → overlapping-lease regression оставляет
  state `accepted` и token второго claim.
- Agent мог обойти membership/list или worker мог создать attention → authenticated list/worker-403
  regressions + frozen ancestry cases.
- TG мог тегать по replayed marker чужого tool → marker принимается только от exact
  `mcp__orchestra__notify_user`; старые #241 tests `12 passed`.
- Dashboard мог скрыть старые panels или разъехаться на desktop → browser oracle + 1280/1920
  computed-width probe, 4 lanes, 0 page errors; agent list/chat DOM не заменялись.

## Post-merge-gate correction

- `tests/test_portfolio_tools_418.py::test_task_update_can_link_without_changing_task_binding`
  больше не сравнивает законную форму пустых `params`; он проверяет behavior: GET task → POST exact
  portfolio link. Оба чистых env-плеча: без `ORCHESTRA_SCOPE` `4 passed`, с
  `ORCHESTRA_SCOPE=/mnt/data/Projects/Python/orchestra` `4 passed`.
- `git merge main` забрал upstream fix `tests/test_mcp_stdio.py` (`message.startswith("do it")`),
  который не относился к #418.
- Final #418 gate без `ORCHESTRA_SCOPE`: frozen acceptance + четыре focused portfolio files +
  `TestNotifyUserMention` + route snapshot → `36 passed`.
- Монолитный полный `pytest -q` без `ORCHESTRA_SCOPE` был убит `RC=137` на 81% без итоговой
  сводки. Полный file-batched прогон тех же `186` test files завершился: 45 failures в 12
  unrelated groups (canonical task allocator, host hooks/pidfd/quota/runtime history/Tailwind и
  другие существующие контуры); ни одного `docs/tasks/418` или `tests/test_portfolio_*` failure.
