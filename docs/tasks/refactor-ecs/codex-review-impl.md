## Summary

Точечно проверил 4 зоны без запуска тестов и без чтения полного diff.

- `app/manager.py`: `get_by_name()` теперь всегда возвращает `AgentSession`; `_hydrate_row()` ставит `loaded=False` и переносит `description/system_prompt/tg_topic/is_orchestrator`. `update_session_fields()` сохраняет parity со старыми ручками `description/tg_topic/prompt`: live-сессия меняется в памяти + `_persist()`, detached-сессия пишется напрямую в БД.
- `app/tm.py`: `set_main_loop()` вызывается в lifespan до импорта `tm_yougile`; `_schedule()` корректно шлет coroutine из worker thread в main loop через `run_coroutine_threadsafe`. В обычном FastAPI пути sync_log не теряется.
- `app/session_turns.py` + `app/session.py`: `turn_end` делегирован в `TurnManager.handle_turn_end()`, порядок действий совпадает со старым `_handle_turn_end` из `92159f2`: cost/context, refresh, max_turns auto-continue, status persist, compact ack, scope idle, auto-compact, auto-report, pending flush/hibernate.
- `app/tg_bridge.py` + `app/session.py`: module-level annotations для hooks безопасны, `NameError` на `AgentSession` нет; hook-вызовы обернуты в try/except.

## Findings

blocking: `app/tg_bridge.py:1576` — `stop_bridge()` снимает callbacks, но не очищает глобальные `_manager` и `bot`; после stop/start в том же процессе или после старта с отключенным TG (`return` на `1488-1490`) hook wiring может работать со stale manager и закрытым bot, а `manager.tg_topics_remover` заново назначается даже когда bridge фактически disabled → в `stop_bridge()` объявить `global bot, _manager`, после cancel/close выставлять `_manager = None`, `bot = None`, и желательно чистить `_topic_status`; в `start_bridge()` при disabled тоже гарантировать `_manager = None` и `manager.tg_topics_remover = None`.

suggestion: `app/tm.py:732` — `_fire_sync()` и `_fire_journal_sync()` создают `tm_sync_log(status='pending')` до проверки, что coroutine реально удалось запланировать; в FastAPI это ок из-за `set_main_loop()`, но в CLI/no-loop путь `_fire_async()` закрывает coroutine и только пишет debug, оставляя pending-запись без фактического fire → либо в no-loop помечать запись `error/skipped`, либо возвращать bool из `_fire_async()` и писать pending только после успешного schedule.

## Verdict

требует фиксов

## Round 2 — 2026-06-11T09:07:12+02:00

### Re-review

FIXED: `app/tg_bridge.py:1576` — blocking по stale globals закрыт. `stop_bridge()` теперь объявляет `global bot, _manager`, снимает hooks, очищает `manager.tg_topics_remover`, отменяет `_tasks`, закрывает `bot.session`, затем выставляет `bot = None` и `_manager = None`. После stop/start в том же процессе callbacks больше не должны работать через закрытый bot или старый manager.

Аргумент принят: disabled-путь `start_bridge()` оставляет `manager.tg_topics_remover = remove_topics_for_orchs`, но `_manager` не назначает. Для удаления топиков это совпадает с legacy-семантикой прямого вызова bridge-функции: `remove_topics_for_orchs()` сам guarded на `not bot or not config.get("group_id")` и возвращает skipped/error `bridge inactive`. Session hooks при `_manager is None` фактически no-op, так что отдельного blocking здесь больше не вижу.

Аргумент принят: pending `sync_log` в no-loop CLI оставлен как behavior-preserving legacy. Это остаётся техническим долгом, но не блокирует refactor-ecs при заявленной цели сохранить поведение.

### Вердикт раунда

APPROVED
