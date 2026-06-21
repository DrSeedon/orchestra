## Summary

Ключ broker должен быть `self.id`. `manager.get_session_id()` возвращает `AgentSession.id`, `add_log()` пишет в `logs.session_id` тоже `self.id`; Claude SDK `session_id` здесь не подходит.

План в целом держит v1-scope: только Claude main-agent text partials, без DB persistence, TG/codex/opencode не должны ломаться. Главная реальная проблема плана: ordering в SSE. Предложенный порядок `DB logs -> live partials` может отдать финальный `text` раньше уже накопленных partials, а frontend-fix из §6 это не полностью лечит.

## Findings

[suggestion] `docs/tasks/83/plan.md:186`, `docs/tasks/83/plan.md:213`, `app/static/js/app.js:2135`, `app/static/js/app.js:2153` — SSE generator сначала отдаёт DB logs, потом drain live queue. Если за один sleep в broker накопились partials и уже закоммитился финальный `text`, клиент получит финал, затем старые `stream` events. §6 заменит body финалом, но последующие `stream` после `text` создадут новую висящую stream bubble. → Фикс: после initial history в steady-state сначала drain broker queue, потом читать/отдавать DB logs; либо перед отдачей финального `text` вычищать live queue. Минимальный вариант: `drain live -> get_logs -> yield logs`, сохранив initial history first.

[suggestion] `docs/tasks/83/plan.md:139`, `docs/tasks/83/plan.md:150`, `app/manager.py:1078`, `app/session.py:874`, `app/db.py:633` — в плане оставлен copy-paste блок с `self.session_id`, а ниже он исправлен на `self.id`. Это опасно: `self.session_id` это Claude resume token и на первом turn часто ещё `None`; SSE подписывается на `manager.get_session_id()` == `session.id`, DB тоже по `self.id`. → Фикс: удалить неправильный блок целиком, оставить только `broker.publish(self.id, ...)`.

[suggestion] `docs/tasks/83/plan.md:116`, `docs/tasks/83/plan.md:130` — broker корректен только при single-process/single-event-loop. Для текущей архитектуры это нормальное MVP-допущение, но `copy-free iterate` по set хрупкий, если позже появится другой loop/thread/worker. → Фикс: заменить на `for q in tuple(self._subs.get(session_id, ())):` и явно написать, что uvicorn multi-worker не поддерживается, как и остальной in-memory manager.

[suggestion] `docs/tasks/83/plan.md:189`, `app/static/js/app.js:188` — partial events без `id`, а общий SSE handler обновляет `lastId/firstId` без проверки `l.id`. Обычно до stream уже есть DB `user_message`, но в edge case первый live event может выставить `firstId = undefined`. → Фикс: в план добавить frontend guard: обновлять `chatLogs.*Id` только если `Number.isFinite(l.id)`.

[nit] `docs/tasks/83/plan.md:271`, `app/backend_claude.py:241` — test plan покрывает broker, но не покрывает самый рискованный фильтр scope: `StreamEvent` main text проходит, `parent_tool_use_id`, `thinking_delta`, `input_json_delta` не проходят. → Фикс: добавить маленькие unit-тесты на `_convert(StreamEvent(...))`.

## Verdict

План можно брать в работу после правки ordering и удаления `self.session_id` snippet. Без этого есть высокий риск, что dashboard будет показывать финал, а затем допечатывать устаревшие partials в отдельный пузырь. Остальное укладывается в MVP и не должно ломать DB finals, TG, codex/opencode flow.