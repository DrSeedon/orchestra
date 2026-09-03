# Plan — Codex cache indicator and compact architecture

## Goal

Показать cache status для Codex agents с честной семантикой `≈30m`, не выдавая public API minimum за ChatGPT-auth guarantee, и закрепить архитектурную разницу compact между Claude и Codex.

## Assumptions

- Для Claude сохраняется текущая dashboard policy: `3600s`, точный countdown и `cold` после истечения.
- Для ChatGPT-auth Codex публичного TTL contract нет. `1800s` — reference/observed window для UI, поэтому backend обязан передать признак approximate, а frontend после окна показывает unknown, не гарантированный cold.
- Runtime определяется существующим `backend_type`/`runtime`; model-name heuristics на frontend не добавляются.
- Cache policy — derived response metadata из уже сохранённого `backend_type`. Новая DB column или migration не нужна.
- Изменение не включает native Codex compact, cache-write accounting или preventive compact policy.

## Changes

### Cache policy

- `app/models.py`
  - Добавить единый helper runtime cache metadata.
  - `claude` → `cache_ttl_seconds=3600`, `cache_ttl_approximate=false`.
  - `codex` → `cache_ttl_seconds=1800`, `cache_ttl_approximate=true`.
  - Не менять текущий fallback для других runtimes.
- `app/manager.py::list_sessions`
  - Применять helper к active и DB-loaded non-archived sessions вместо безусловного `CACHE_TTL_SECONDS`.
- `app/routes/system.py::list_orchestrators`
  - Использовать ту же policy для orchestrator tabs, чтобы Codex orchestrator не получил Claude 1h default.

### Dashboard

- `app/static/js/app.js::_cachePill`, `_renderCachePill`
  - Передавать approximate marker через `data-*`.
  - Codex countdown маркировать `≈`; tooltip объясняет, что 30m — reference/observed window без ChatGPT-auth guarantee.
  - После 30m показывать unknown/approximate state, не утверждать definite cold.
  - Вычислять уровни относительно policy window: `hot > 50%`, `warm >= 20%`, `cooling > 0`. Для Claude это сохраняет текущие границы `>30m`/`>=12m`; для Codex даёт `>15m`/`>=6m`.
  - Не подменять явные `0`/unknown через `|| 3600`; fallback допустим только при отсутствующем/невалидном поле.
  - Claude labels и tooltips оставить без изменений.
  - Переиспользовать существующий `.cache-pill`; CSS и `usage.js` не трогать.
- `app/mcp_stdio.py::_cache_pill`
  - Использовать те же runtime metadata и относительные границы.
  - Маркировать Codex countdown как approximate, а после 30m возвращать unknown вместо definite cold, чтобы `list_agents`/`get_worker_info` не противоречили dashboard.

### Documentation

- `docs/tasks/codex-cache-research/research.md`
  - Зафиксировать, что compact invalidates conversation prefix у обоих.
  - Объяснить Claude layered prefix reuse без session UUID против Codex `prompt_cache_key=thread_id`.
  - Отдельно отметить, что new Codex thread теряет reliable matching, но automatic partial hit не исключён.

## Tests

- `tests/test_backend_routing.py`
  - Cache policy returns exact 1h for Claude and approximate 30m for Codex.
- `tests/test_manager.py`
  - `list_sessions()` exposes runtime-specific TTL and approximate marker.
- `tests/test_api.py`
  - `/api/orchestrators` preserves runtime-specific cache metadata.
- `tests/test_frontend.py`
  - Browser evaluation of Codex pill shows approximate marker/tooltip and unknown state after the reference window.
  - Claude pill retains existing exact 1h behavior.
- `tests/test_mcp_stdio.py`
  - Text cache pill follows the same exact/approximate state machine as dashboard.
- Full suite: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q`.

## Not in scope

- Не менять `AgentSession.compact`, native Codex `context/compact`, precompact timer или session lifecycle.
- Не добавлять stable custom `prompt_cache_key`: current app-server API не exposes такой public control.
- Не менять Codex pricing/cache-write accounting.
- Не рестартить Orchestra: Python changes потребуют явной команды пользователя после merge.

## Risks and edge cases

- Active и DB-loaded non-archived sessions проходят разными serialization paths; policy должна применяться к обоим. Archived sessions не входят в текущие `list_sessions()`/`/api/orchestrators` contracts и не добавляются этой задачей.
- `cache_ttl_seconds=0/null` нельзя пропускать через frontend `|| 3600`, иначе unknown снова превратится в Claude 1h.
- Running Codex agent не имеет countdown expiry, но tooltip всё равно не должен обещать гарантированный refresh TTL.
- `last_turn_ts` может отсутствовать или быть malformed; pill остаётся скрытым как сейчас.
- Frontend periodic rerender должен сохранить approximate marker.

## Tickets

### T1 — Codex cache status end-to-end
- Files: `app/models.py`, `app/manager.py`, `app/routes/system.py`, `app/static/js/app.js`, `app/mcp_stdio.py`, `tests/test_backend_routing.py`, `tests/test_manager.py`, `tests/test_api.py`, `tests/test_frontend.py`, `tests/test_mcp_stdio.py`
- AC:
  - Claude session API payload содержит `3600` и `cache_ttl_approximate=false`.
  - Codex session/orchestrator payload содержит `1800` и `cache_ttl_approximate=true`.
  - Idle Codex dashboard/MCP pill показывает countdown с `≈`; после reference window состояние явно unknown/approximate.
  - Claude dashboard/MCP pill сохраняет текущие точные границы `>30m` hot, `12–30m` warm, `1–11m` cooling и `<=0` cold.
  - Active, persisted non-archived и missing-`last_turn_ts` cases покрыты без JS errors.
  - Policy получается из `backend_type` при сериализации; DB schema остаётся без изменений.
- blocked-by: none

### T2 — Compact cache architecture
- Files: `docs/tasks/codex-cache-research/research.md`
- AC:
  - Документ не утверждает, что Claude сохраняет conversation cache после compact.
  - Различие Claude prefix layers и Codex thread-key routing подкреплено official docs/source.
  - Зафиксировано, что fresh Codex thread теряет reliable matching, но не гарантирует zero cache hit.
  - Scope recommendation остаётся: no TTL-driven Codex precompact; native compact — отдельная future task.
- blocked-by: none
