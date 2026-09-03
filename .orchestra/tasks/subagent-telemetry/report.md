# Report — полная телеметрия субагентов

**Дата:** 2026-07-01 · **Commit:** 0323651

## Что сделано
Собираем ВСЁ что SDK 0.2.87 даёт по субагентам. Раньше теряли: output_file, полный summary, tool_uses, duration_ms, транскрипт.

### Файлы (+622/-9)
- **db.py** (+76): таблица `subagents` + `subagent_upsert` / `get_subagents` / `get_subagent`.
- **backend_claude.py** (+38): `_task_usage` хелпер, TaskStarted/Progress/Notification → всё в metadata (incl sdk_session_id, tool_use_id, output_file, summary, raw data-dict).
- **session.py** (+23): `_persist_subagent` — upsert телеметрии (fire-and-forget).
- **routes/subagent.py** (new, +72): 3 endpoint.
- **main.py, events.py**: регистрация роутера + доки metadata.

### Endpoints
- `GET /api/subagents/{session_id}` — телеметрия (tokens/summary/output_file/status).
- `GET /api/subagent-transcripts/{session_id}` — список agent_id (list_subagents).
- `GET /api/subagent-transcript/{session_id}/{agent_id}?limit=&offset=` — полный диалог (get_subagent_messages). База для «отдельного чата субагента».

## Ключевые решения
1. **Двойной счёт cost исключён** — per-subagent tokens хранятся в таблице, НЕ прибавляются к session.cost_usd (ResultMessage.total_cost_usd уже включает субагентов).
2. **upsert race-safe** — ON CONFLICT DO UPDATE, текст `COALESCE(NULLIF(excluded,''),x)` (progress не затирает start), числа `max()` (TaskUsage кумулятивен → latest, не суммируем).
3. **Транскрипт декуплен** — agent_id (SDK файл) ≠ task_id (Task message). Транскрипт перечисляется через list_subagents(sdk_session_id), не требует маппинга.
4. **Path-traversal** — agent_id валидируется `^[\w-]+$` (идёт в имя файла).

## Тесты (18, все зелёные)
- test_subagents.py (7): upsert start→progress→end, no-wipe, MAX-not-sum, **10-thread concurrent race → no data loss**, distinct, missing→None.
- test_subagent_routes.py (5): path-traversal 400, missing session 404, no sdk_session, transcript mock read, SDK error graceful.
- test_backend_stream.py (6): _task_usage + subagent tagging (из subagent-visibility).

## Probe (без live-спавна)
Разобрал `claude_agent_sdk/_internal/sessions.py` + проверил на РЕАЛЬНЫХ `~/.claude/projects` транскриптах: `list_subagents` + `get_subagent_messages` работают, вернули 2 субагента + диалог. Путь `<proj>/<sdk_session_id>/subagents/agent-<id>.jsonl`. `directory=None` = fallback по всем проектам.

## Codex
Недоступен: 3 попытки, stdin-hang / timeout (rate-limit + прокси). Вместо — усиленный self-review + **concurrency stress-test** (10 concurrent upserts → MAX tokens=1000 не 5500, description не затёрт). Все 5 flagged-точек оркестратора покрыты.

## Known issues / TODO
- `test_route_surface_snapshot` fails — ПРЕ-ЭКЗИСТИНГ (enterprise routes) + мои 3 новых route. Snapshot обновить при merge (frozen reference, не моя территория).
- `data: dict` не проверен рантаймом (нужен live субагент) — сохраняем в raw_json как есть («ничего не терять»).
- Frontend для endpoints — за frontend-opus (база готова).
- Codex review impl — переспросить когда прокси/rate-limit стабилизируются.
