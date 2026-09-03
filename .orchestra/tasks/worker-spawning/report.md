# Report: worker-spawning R1 + R2

**Task:** research «воркеры спавнят воркеров» → impl R1 (prompt-split) + R2 (orphan-guard).
**Phases:** Research (Codex-reviewed) → Plan → Impl. R3-R5 отложены оркестратором.

## Что сделано

### R1 — промпт-развод spawn_worker vs built-in Agent
Добавлен блок `<parallelism>` в `full-cycle.md` (после `<code-quality>`). Detached decision-tree:
- эфемерный fan-out (поиск/сбор/разведка/verify) → built-in `Agent`;
- долгоживущее видимое по тикетам (worktree/дашборд/resume/переживает compact) → `spawn_worker`;
- default при сомнении → built-in Agent (дешевле);
- «заспавнил → ты владелец, merge/kill до финиша» (связка с R2).

### R2 — orphan-guard
- `app/manager.py`: новый метод `_live_children(parent_name, scope)` — активные (idle/running/waiting) дети по `parent_name`, из in-memory registry + DB, dedup по id. Зеркалит `_live_workers_in_scope`.
- `app/routes/sessions.py`: в `delete_session`, внутри `if not force:`, перед git-проверками — блок с HTTP 400 и именами живых детей. `force=true` переопределяет.

Закрывает асимметрию: `change_orchestrator_scope` блокировал при живых воркерах, kill — нет.

## Файлы (±)
| Файл | Изменение |
|---|---|
| `pipelines/default/prompts/roles/full-cycle.md` | +22 строки (`<parallelism>` блок) |
| `app/manager.py` | +20 строк (`_live_children`) |
| `app/routes/sessions.py` | +5 строк (guard в delete_session) |
| `tests/test_manager.py` | +46 строк (`TestLiveChildren`, 6 тестов) |
| `tests/test_api.py` | +30 строк (`TestDeleteOrphanGuard`, 3 route-теста) |

## Тесты
- `TestLiveChildren` (6): DB-детекция, archived-не-блокирует, only-own-children, scope-isolation, empty-parent, no-children. **6/6 passed.**
- `TestDeleteOrphanGuard` (3): block-with-live-child (400 + имя), force-overrides (200), no-children (200). **3/3 passed.**
- Регрессия: `tests/test_manager.py tests/test_api.py` → **131 passed**, мои 9 в их числе.
- **3 pre-existing fail** (TestInjectSkillsGating x2, TestChangeOrchestratorScope::_persist race) — проверено `git stash`: падают и на базе БЕЗ моих правок. Не связаны с worker-spawning, не трогал.

## AC verification
**R1:** блок присутствует, оба пути с триггерами, default-правило, запрет смешивания, ownership-связка. Prompt резолвится (`ROLE_SYSTEM_PROMPT('default','full-cycle')` → 29541 chars, `<parallelism>` present). ✅
**R2:** kill с idle/running ребёнком без force → 400 + имена ✅; force=true → проходит ✅; без детей / только archived → проходит ✅; ловит unloaded-but-active из DB ✅.

## Adversarial self-review
1. **TOCTOU `starting`-ребёнок:** `_live_children` не ловит статус `starting` (спавн прямо сейчас). Тот же зазор что у `change_scope` (комментарий manager.py про scope-level spawn lock). Принял тот же уровень — не хуже существующего гейта; force = аварийный выход. Записал как known в research R2-a.
2. **Побочное открытие (не баг моих правок):** worker-parent + unrouted child блокируется `validate_spawn` (`allow_unrouted_workers=False`) — всплыло в route-тесте (409 без явного role). Это существующее поведение, подтверждает research F1 (обычный worker не спавнит генериков). В тесте обхожу явным `role="worker"`.
3. **Pyright false-positive** на `_live_children` в sessions.py — `app.deps.manager` типизирован слабо; метод реально на классе (manager.py:721). Не блокер.

## Codex
Пропущен по указанию оркестратора (2 промпт-правки + 1 guard = тривиально). Research-фаза Codex-ревью прошла (`codex-review-research.md`), 4 confidently-wrong правки внесены тогда.

## Breaking / TODO
- Breaking: нет. `force=true` сохраняет старое поведение.
- Отложено (R3-R5, не в scope): depth-limit, merge-target-при-parent-strategy баг, spawn-cost warning. Записаны в research.md.
